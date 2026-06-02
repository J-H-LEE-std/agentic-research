"""
Main Orchestrator: 전체 6단계 연구 파이프라인을 총괄하고,
각 단계별 Sub-agent에 위임하며, 중요 시점마다 ntfy로 인간 승인을 요청한다.

사용 모델은 config.yaml의 models / peer_review.reviewers 참조.
"""
import sys
import os
import asyncio
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.openrouter_client import OpenRouterClient
from shared.models import get_model, get_ntfy_config
from shared.prompts import ORCHESTRATOR
from shared import state

from agents.literature_agent import LiteratureAgent
from agents.design_agent import DesignAgent
from agents.implement_agent import ImplementAgent
from agents.analysis_agent import AnalysisAgent
from agents.writing_agent import WritingAgent
from agents.peer_review_agent import PeerReviewAgent

import httpx


class MainOrchestrator:
    def __init__(self, topic: str, approval_channel=None, note_extras: dict = None):
        self.topic = topic
        self.client = OpenRouterClient()
        self.model = get_model("orchestrator")
        self.ntfy_cfg = get_ntfy_config()
        self.context: dict = {"topic": topic}
        if note_extras:
            self.context["note"] = note_extras
        self._local_channel = approval_channel

    def run(self):
        # 에이전트들이 channel에 접근할 수 있도록 context에 주입
        self.context["_channel"] = self._local_channel
        print(f"\n{'='*60}")
        print(f"Research Orchestrator 시작")
        print(f"주제: {self.topic}")
        print(f"모델: {self.model}")
        print(f"{'='*60}\n")

        try:
            self._run_stage_1_literature()
            self._human_checkpoint("문헌 조사 완료", self._summarize_literature())

            self._run_stage_2_design()
            self._human_checkpoint("알고리즘 설계 완료 (가장 중요)", self._summarize_design())

            self._run_stage_3_implement()

            self._run_stage_4_analysis()
            self._human_checkpoint("실험 결과 분석 완료", self._summarize_analysis())

            self._run_stage_5_writing()

            self._run_stage_6_peer_review()
            self._human_checkpoint(
                "피어리뷰 + 논문 초안 완료 — 최종 검토 요청",
                self._summarize_final(),
            )

            state.mark_completed(self.topic)
            print("\n연구 파이프라인 완료!")
            self._print_summary()

        except KeyboardInterrupt:
            print("\n사용자에 의해 중단되었습니다.")
        except Exception as e:
            print(f"\n오류 발생: {e}")
            raise

        return self.context

    # ── Stage Runners ──────────────────────────────────────────────────

    def _run_stage_1_literature(self):
        print("[Stage 1] 문헌 수집 및 분석 시작...")
        state.update_stage(1, "Literature Review", "in_progress")
        result = LiteratureAgent().run(self.context)
        self.context["literature"] = result
        n_papers = len(result.get("raw_papers", []))
        gap = result.get("research_gap", "")
        state.update_stage(
            1, "Literature Review", "completed",
            f"Papers found: {n_papers}\nKey gap identified: {gap[:100]}"
        )
        print(f"  → 논문 {n_papers}편 수집, 연구 공백 도출 완료")

    def _run_stage_2_design(self):
        print("[Stage 2] 알고리즘 설계 시작 (Recursive Verifier 포함)...")
        state.update_stage(2, "Algorithm Design", "in_progress")
        result = DesignAgent().run(self.context)
        self.context["design"] = result
        passed = result.get("passed_verification", False)
        rounds = result.get("verification_rounds", 0)
        state.update_stage(
            2, "Algorithm Design", "completed",
            f"Verification passed: {passed}\nVerification rounds: {rounds}"
        )
        print(f"  → 알고리즘 설계 완료 (검증 {'통과' if passed else '미통과'}, {rounds}라운드)")

    def _run_stage_3_implement(self):
        print(f"[Stage 3] 코드 구현 및 실험 실행 시작 ({get_model('implement')})...")
        state.update_stage(3, "Implementation & Experiments", "in_progress")
        result = ImplementAgent().run(self.context)
        self.context["implement"] = result
        code_path = result.get("code_path", "")
        rc = result.get("exec_result", {}).get("return_code", -1)
        state.update_stage(
            3, "Implementation & Experiments", "completed",
            f"Code: {os.path.basename(code_path)}\nReturn code: {rc}"
        )
        print(f"  → 실험 완료 (return_code={rc})")

    def _run_stage_4_analysis(self):
        print("[Stage 4] 결과 분석 및 시각화 시작 (Recursive Verifier 포함)...")
        state.update_stage(4, "Result Analysis", "in_progress")
        result = AnalysisAgent().run(self.context)
        self.context["analysis"] = result
        graph = result.get("graph_path", "")
        state.update_stage(
            4, "Result Analysis", "completed",
            f"Graph: {os.path.basename(str(graph))}"
        )
        print(f"  → 분석 완료, 그래프: {graph}")

    def _run_stage_5_writing(self):
        print("[Stage 5] 논문 초안 작성 시작...")
        state.update_stage(5, "Paper Writing", "in_progress")
        result = WritingAgent().run(self.context)
        self.context["writing"] = result
        ko = result.get("korean_draft_path", "")
        en = result.get("english_draft_path", "")
        state.update_stage(
            5, "Paper Writing", "completed",
            f"Korean: {os.path.basename(ko)}\nEnglish: {os.path.basename(en)}"
        )
        print(f"  → 논문 초안 저장: {en}")

    def _run_stage_6_peer_review(self):
        from shared.models import get_peer_review_models
        reviewers = get_peer_review_models()
        print(f"[Stage 6] 피어리뷰 시작 ({len(reviewers)}개 모델, 다각도 평가)...")
        for r in reviewers:
            print(f"  · {r['perspective_kr']}  → {r['model']}")
        state.update_stage(6, "Peer Review", "in_progress")
        result = PeerReviewAgent().run(self.context)
        self.context["peer_review"] = result
        aggregate = result.get("aggregate", {})
        verdict = aggregate.get("final_verdict", "N/A")
        score = aggregate.get("average_score", "N/A")
        report = result.get("report_path", "")
        state.update_stage(
            6, "Peer Review", "completed",
            f"Final verdict: {verdict}\nAverage score: {score}/10\nReport: {os.path.basename(report)}"
        )
        print(f"  → 피어리뷰 완료: {verdict} (평균 {score}/10)")

    # ── Human-in-the-Loop ──────────────────────────────────────────────

    def _human_checkpoint(self, stage_name: str, summary: str):
        print(f"\n[인간 승인 요청] {stage_name}")
        state.log_approval(f"{stage_name} 승인 요청 전송...")

        if self._local_channel is not None:
            # 로컬 Streamlit 모드: Queue로 직접 통신
            decision = self._local_channel.request_approval(stage_name, summary)
        else:
            # 서버 모드: ntfy SSE
            decision = asyncio.run(self._send_approval_request(stage_name, summary))

        if decision == "approve":
            state.log_approval(f"{stage_name} 승인됨")
            print(f"  → 승인됨, 다음 단계로 진행합니다.")
        elif decision == "reject":
            state.log_approval(f"{stage_name} 거부됨 — 파이프라인 중단")
            raise RuntimeError(f"인간이 '{stage_name}' 단계를 거부했습니다.")
        else:
            state.log_approval(f"{stage_name} 수정 요청 — 계속 진행 (수동 확인 필요)")
            print(f"  → 수정 요청됨. progress.md를 확인하세요.")

    def _ask_direction_ntfy(self, question: str, summary: str) -> tuple[str, str]:
        """서버 모드: ntfy로 방향 질문 전송 후 SSE 응답 대기."""
        full_summary = (
            f"[방향 확인 필요]\n{question}\n\n{summary}\n\n"
            "응답: 'continue'(계속) / 'stop'(중단) / 'modify: 지시사항'(수정)"
        )
        decision = asyncio.run(self._send_approval_request(question, full_summary))
        # ntfy에서 'modify: 내용' 형식으로 올 경우 파싱
        if decision.startswith("modify:"):
            note = decision[7:].strip()
            return "modify", note
        return decision, ""

    def _ntfy_auth(self) -> "httpx.BasicAuth | None":
        u = self.ntfy_cfg.get("username", "")
        p = self.ntfy_cfg.get("password", "")
        if u and p:
            return httpx.BasicAuth(u, p)
        return None

    async def _send_approval_request(self, stage_name: str, summary: str) -> str:
        topic_url = f"{self.ntfy_cfg['server_url']}/{self.ntfy_cfg['topic']}"
        timeout = self.ntfy_cfg["timeout_seconds"]
        default = self.ntfy_cfg.get("default_on_timeout", "approve")

        message = (
            f"[{stage_name}]\n\n{summary}\n\n"
            f"응답: 'approve' / 'reject' / 'modify'\n"
            f"(미응답 시 {timeout}초 후 자동으로 '{default}' 처리)"
        )
        headers = {
            "Title": f"[연구 Agent] {stage_name} 승인 요청",
            "Priority": "high",
            "Content-Type": "text/plain; charset=utf-8",
        }
        async with httpx.AsyncClient(timeout=10, auth=self._ntfy_auth()) as client:
            try:
                await client.post(topic_url, content=message.encode("utf-8"), headers=headers)
                print(f"  → ntfy 알림 전송 완료: {topic_url}")
            except Exception as e:
                print(f"  → ntfy 알림 실패 (계속 진행): {e}")
                return default

        return await self._poll_ntfy_response(timeout, default)

    async def _poll_ntfy_response(self, timeout_seconds: int, default: str) -> str:
        import time
        sse_url = f"{self.ntfy_cfg['server_url']}/{self.ntfy_cfg['topic']}/sse"
        keywords = {
            "approve": "approve", "reject": "reject", "modify": "modify",
            "승인": "approve", "거부": "reject", "수정": "modify",
        }
        deadline = time.time() + timeout_seconds
        print(f"  → 응답 대기 중... ({timeout_seconds}초)")

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=timeout_seconds + 5, write=10, pool=10),
                auth=self._ntfy_auth(),
            ) as client:
                async with client.stream("GET", sse_url) as stream:
                    async for line in stream.aiter_lines():
                        if time.time() > deadline:
                            break
                        if not line.startswith("data:"):
                            continue
                        try:
                            data = json.loads(line[5:].strip())
                            msg = data.get("message", "").strip().lower()
                            for kw, decision in keywords.items():
                                if kw in msg:
                                    return decision
                        except (json.JSONDecodeError, KeyError):
                            continue
        except Exception:
            pass

        print(f"  → 타임아웃 — 기본값 '{default}' 적용")
        return default

    # ── Summaries ──────────────────────────────────────────────────────

    def _summarize_literature(self) -> str:
        lit = self.context.get("literature", {})
        n = len(lit.get("raw_papers", []))
        gap = lit.get("research_gap", "")
        direction = lit.get("recommended_direction", "")
        return f"수집 논문: {n}편\n\n연구 공백:\n{gap}\n\n추천 방향:\n{direction}"

    def _summarize_design(self) -> str:
        des = self.context.get("design", {})
        idea = des.get("idea", "")[:500]
        passed = des.get("passed_verification", False)
        rounds = des.get("verification_rounds", 0)
        return f"검증: {'통과' if passed else '미통과'} ({rounds}라운드)\n\n핵심 아이디어:\n{idea}"

    def _summarize_analysis(self) -> str:
        ana = self.context.get("analysis", {})
        text = ana.get("analysis_text", "")[:500]
        graph = ana.get("graph_path", "")
        return f"그래프: {graph}\n\n분석 결과:\n{text}"

    def _summarize_final(self) -> str:
        wr = self.context.get("writing", {})
        pr = self.context.get("peer_review", {})
        aggregate = pr.get("aggregate", {})
        report = pr.get("report_path", "")
        verdict = aggregate.get("final_verdict", "N/A")
        score = aggregate.get("average_score", "N/A")
        en_path = wr.get("english_draft_path", "")
        weaknesses = aggregate.get("common_weaknesses", [])
        changes = aggregate.get("required_changes", [])

        summary = (
            f"논문: {en_path}\n"
            f"피어리뷰 결과: {verdict} (평균 {score}/10)\n"
            f"리포트: {report}\n\n"
        )
        if weaknesses:
            summary += "주요 약점:\n" + "\n".join(f"- {w}" for w in weaknesses[:3]) + "\n\n"
        if changes:
            summary += "필수 수정:\n" + "\n".join(f"- {c}" for c in changes[:3])
        return summary

    def _print_summary(self):
        print("\n" + "="*60)
        print("최종 결과물 요약")
        print("="*60)
        impl = self.context.get("implement", {})
        ana = self.context.get("analysis", {})
        wr = self.context.get("writing", {})
        pr = self.context.get("peer_review", {})
        aggregate = pr.get("aggregate", {})
        print(f"  코드:        {impl.get('code_path', 'N/A')}")
        print(f"  실험 로그:   {impl.get('log_path', 'N/A')}")
        print(f"  그래프:      {ana.get('graph_path', 'N/A')}")
        print(f"  논문(KO):   {wr.get('korean_draft_path', 'N/A')}")
        print(f"  논문(EN):   {wr.get('english_draft_path', 'N/A')}")
        print(f"  피어리뷰:    {pr.get('report_path', 'N/A')}")
        print(f"  최종 판정:   {aggregate.get('final_verdict', 'N/A')} "
              f"(평균 {aggregate.get('average_score', 'N/A')}/10)")
        print(f"  진행 상황:   progress.md")
        print("="*60)
