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

        # 서버 모드: ntfy 알림만 전송하고 계속 진행 (non-blocking fallback)
        import asyncio
        import httpx
        from shared.models import get_ntfy_config
        cfg = get_ntfy_config()
        url = f"{cfg['server_url']}/{cfg['topic']}"
        auth = None
        if cfg.get("username") and cfg.get("password"):
            auth = httpx.BasicAuth(cfg["username"], cfg["password"])

        async def _notify():
            headers = {
                "Title": f"[방향 확인] {question[:50]}",
                "Priority": "high",
                "Content-Type": "text/plain; charset=utf-8",
            }
            async with httpx.AsyncClient(timeout=10, auth=auth) as client:
                try:
                    await client.post(url, content=summary.encode("utf-8"), headers=headers)
                except Exception:
                    pass

        asyncio.run(_notify())
        print(f"  → ntfy 알림 전송 (서버 모드, 자동으로 계속 진행)")
        return "continue", ""
