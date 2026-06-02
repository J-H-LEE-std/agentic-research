import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.openrouter_client import OpenRouterClient
from shared.models import get_model
from shared.state import read_progress, log_approval


class BaseAgent:
    def __init__(self, role: str = "sub_agents"):
        self.client = OpenRouterClient()
        self.model = get_model(role)
        self.role = role

    def run(self, context: dict) -> dict:
        raise NotImplementedError

    def _build_context_str(self, context: dict) -> str:
        progress = read_progress()
        parts = [f"[연구 진행 상황]\n{progress}"]
        for k, v in context.items():
            if k not in ("progress", "_channel"):
                parts.append(f"[{k}]\n{v}")
        return "\n\n".join(parts)

    def ask_direction(
        self,
        context: dict,
        question: str,
        summary: str,
    ) -> tuple[str, str]:
        """
        실행 중 방향 질문. (decision, note) 반환.
        - 로컬 모드: Streamlit UI가 블로킹 응답
        - 서버 모드: ntfy SSE 폴링 (orchestrator의 ntfy 헬퍼 재사용)
        - 채널 없음: 기본값 'continue' 반환 (자동 진행)
        """
        print(f"\n[방향 질문] {question}")
        log_approval(f"방향 질문: {question}")

        channel = context.get("_channel")
        if channel is not None:
            # 로컬 Streamlit 모드
            return channel.ask_direction(question, summary)

        # 서버 모드: ntfy 알림 전송 후 SSE 폴링으로 응답 대기
        import asyncio
        import time
        import httpx
        from shared.models import get_ntfy_config
        cfg = get_ntfy_config()
        topic_url = f"{cfg['server_url']}/{cfg['topic']}"
        timeout = cfg.get("timeout_seconds", 300)
        default = cfg.get("default_on_timeout", "continue")
        auth = None
        if cfg.get("username") and cfg.get("password"):
            auth = httpx.BasicAuth(cfg["username"], cfg["password"])

        async def _ask() -> tuple[str, str]:
            full_summary = (
                f"[방향 확인] {question}\n\n{summary}\n\n"
                f"응답: 'continue'(계속) / 'stop'(중단) / 'modify: 지시사항'(재시도)\n"
                f"(미응답 시 {timeout}초 후 자동으로 '{default}' 처리)"
            )
            headers = {
                "Title": f"[방향 확인] {question[:50]}",
                "Priority": "high",
                "Content-Type": "text/plain; charset=utf-8",
            }
            async with httpx.AsyncClient(timeout=10, auth=auth) as client:
                try:
                    await client.post(topic_url, content=full_summary.encode("utf-8"), headers=headers)
                    print(f"  → ntfy 알림 전송 완료, 응답 대기 중... ({timeout}초)")
                except Exception as e:
                    print(f"  → ntfy 알림 실패 (기본값 '{default}' 적용): {e}")
                    return default, ""

            keywords = {
                "continue": ("continue", ""), "계속": ("continue", ""),
                "stop": ("stop", ""),       "중단": ("stop", ""),
            }
            sse_url = f"{topic_url}/sse"
            deadline = time.time() + timeout
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=10, read=timeout + 5, write=10, pool=10),
                    auth=auth,
                ) as client:
                    async with client.stream("GET", sse_url) as stream:
                        async for line in stream.aiter_lines():
                            if time.time() > deadline:
                                break
                            if not line.startswith("data:"):
                                continue
                            try:
                                import json as _json
                                msg = _json.loads(line[5:].strip()).get("message", "").strip()
                                msg_lower = msg.lower()
                                for kw, result in keywords.items():
                                    if kw in msg_lower:
                                        return result
                                if "modify" in msg_lower or "수정" in msg_lower:
                                    note = msg.split(":", 1)[1].strip() if ":" in msg else msg
                                    return "modify", note
                            except Exception:
                                continue
            except Exception:
                pass

            print(f"  → 타임아웃 — 기본값 '{default}' 적용")
            return default, ""

        return asyncio.run(_ask())
