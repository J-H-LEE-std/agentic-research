"""
Recursive Verifier: 같은 계열의 작은 모델(20B)이 큰 모델(120B)의 주장을 반복적으로 반박·검증한다.
합의 도달 시 통과, N회 후에도 미달 시 ntfy로 인간 판단 요청.
"""
import os
import sys
import asyncio
import httpx
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.openrouter_client import OpenRouterClient
from shared.models import get_model, get_verifier_config, get_ntfy_config
from shared.prompts import VERIFIER_MAIN, VERIFIER_CRITIC


CONSENSUS_PHRASES = [
    "no significant objection",
    "i agree",
    "the argument is sound",
    "i cannot find a meaningful flaw",
    "this is valid",
    "no further objection",
    "consensus reached",
    "argument holds",
    "충분히 타당",
    "더 이상 반박",
    "동의합니다",
    "유의미한 반박 없음",
]


def _has_consensus(verifier_reply: str) -> bool:
    lower = verifier_reply.lower()
    return any(phrase in lower for phrase in CONSENSUS_PHRASES)


class RecursiveVerifier:
    def __init__(self):
        self.client = OpenRouterClient()
        self.main_model = get_model("sub_agents")    # 120B: 재반론 담당
        self.verifier_model = get_model("verifier")  # 20B: 반박 담당 (같은 계열 하위 모델)
        cfg = get_verifier_config()
        self.max_rounds = cfg["max_rounds"]

    def verify(self, claim: str, context: str = "", caller: str = "verifier") -> dict:
        """
        claim: 검증할 주장/아이디어
        context: 배경 컨텍스트
        returns: {"passed": bool, "final_claim": str, "rounds": list, "reason": str}
        """
        rounds = []
        current_claim = claim

        for round_num in range(1, self.max_rounds + 1):
            # 20B 모델이 반박 시도
            verifier_messages = [
                {"role": "system", "content": VERIFIER_CRITIC},
                {
                    "role": "user",
                    "content": (
                        f"[컨텍스트]\n{context}\n\n"
                        f"[검증할 주장 — Round {round_num}/{self.max_rounds}]\n{current_claim}\n\n"
                        "이 주장의 결함을 찾아 비판적으로 분석하세요."
                    ),
                },
            ]
            verifier_reply = self.client.chat(
                model=self.verifier_model,
                messages=verifier_messages,
                temperature=0.3,
                max_tokens=1024,
                caller=f"{caller}_critic_r{round_num}",
            )

            rounds.append({
                "round": round_num,
                "objection": verifier_reply,
                "rebuttal": None,
            })

            if _has_consensus(verifier_reply):
                return {
                    "passed": True,
                    "final_claim": current_claim,
                    "rounds": rounds,
                    "reason": f"Round {round_num}에서 합의 도달",
                }

            # 120B 모델이 재반론
            rebuttal_messages = [
                {"role": "system", "content": VERIFIER_MAIN},
                {
                    "role": "user",
                    "content": (
                        f"[원래 주장]\n{current_claim}\n\n"
                        f"[비평가의 반박]\n{verifier_reply}\n\n"
                        "반박에 응답하고 주장을 개선하세요."
                    ),
                },
            ]
            rebuttal = self.client.chat(
                model=self.main_model,
                messages=rebuttal_messages,
                temperature=0.5,
                max_tokens=2048,
                caller=f"{caller}_main_r{round_num}",
            )
            rounds[-1]["rebuttal"] = rebuttal
            current_claim = rebuttal

        return {
            "passed": False,
            "final_claim": current_claim,
            "rounds": rounds,
            "reason": f"{self.max_rounds}회 반복 후 합의 미달 — 인간 판단 필요",
        }

    async def verify_with_human_fallback(
        self,
        claim: str,
        context: str = "",
        caller: str = "verifier",
        pipeline_context: dict = None,
    ) -> dict:
        result = self.verify(claim, context, caller)
        if not result["passed"]:
            last_objection = result["rounds"][-1]["objection"] if result["rounds"] else ""
            question = f"Recursive Verifier 합의 실패 ({self.max_rounds}라운드) — 이 주장을 통과시킬까요?"
            summary = (
                f"**최종 주장 (요약):**\n{result['final_claim'][:400]}\n\n"
                f"**마지막 반박:**\n{last_objection[:400]}\n\n"
                "**계속 진행**: 현재 주장으로 다음 단계 진행\n"
                "**방향 수정**: 주장을 어떻게 바꿀지 지시하면 재생성합니다\n"
                "**중단**: 파이프라인 종료"
            )

            channel = (pipeline_context or {}).get("_channel")
            if channel is not None:
                # 로컬 모드: Streamlit UI에서 블로킹 응답
                decision, note = channel.ask_direction(question, summary)
            else:
                # 서버 모드: ntfy 알림 후 기본값 통과
                await _request_human_decision(prompt=f"{question}\n\n{summary}")
                decision, note = "continue", ""

            if decision == "stop":
                raise RuntimeError("사용자가 Recursive Verifier 단계에서 파이프라인을 중단했습니다.")
            if decision == "modify" and note:
                result["final_claim"] = result["final_claim"] + f"\n\n[수정 지시 반영: {note}]"

        return result


async def _request_human_decision(prompt: str):
    cfg = get_ntfy_config()
    url = f"{cfg['server_url']}/{cfg['topic']}"
    headers = {
        "Title": "[검증 실패] 인간 판단 요청",
        "Priority": "urgent",
        "Content-Type": "text/plain; charset=utf-8",
    }
    auth = None
    if cfg.get("username") and cfg.get("password"):
        import base64
        creds = base64.b64encode(f"{cfg['username']}:{cfg['password']}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, content=prompt.encode("utf-8"), headers=headers)
        except Exception:
            pass
