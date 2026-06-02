import os
import json
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY 환경변수가 설정되지 않았습니다.")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/research-agent",
            "X-Title": "Research Automation Agent",
        }

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        caller: str = "unknown",
        enable_thinking: bool = False,
    ) -> str:
        # thinking 모델은 temperature=1 고정 권장
        if "thinking" in model.lower():
            temperature = 1

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # thinking 지원 모델은 include_reasoning: true로 사고 과정 수신
        if enable_thinking or os.environ.get("ENABLE_THINKING", "").lower() == "true":
            payload["include_reasoning"] = True

        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        # OpenRouter: 사고 과정은 reasoning 필드로 반환됨
        reasoning = msg.get("reasoning") or ""
        usage = data.get("usage", {})
        self._log_tokens(caller, model, usage)
        self._log_thought(caller, model, messages, content, usage, reasoning)
        return content

    def _log_tokens(self, caller: str, model: str, usage: dict):
        if not os.environ.get("TOKEN_TRACKING_ENABLED", "true").lower() == "true":
            return
        token_log = os.environ.get("TOKEN_LOG_PATH", "./workspace/default/experiment/logs/token_usage.jsonl")
        try:
            os.makedirs(os.path.dirname(token_log), exist_ok=True)
            entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "caller": caller,
                "model": model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
            with open(token_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _log_thought(self, caller: str, model: str, messages: list, response: str, usage: dict, reasoning: str = ""):
        thoughts_path = os.environ.get("LLM_THOUGHTS_PATH", "")
        if not thoughts_path:
            return
        try:
            os.makedirs(os.path.dirname(thoughts_path), exist_ok=True)
            last_user = next(
                (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            with open(thoughts_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {caller} | {model}\n")
                f.write(
                    f"tokens: {usage.get('prompt_tokens',0)} in / "
                    f"{usage.get('completion_tokens',0)} out\n\n"
                )
                preview = last_user[:600] + "..." if len(last_user) > 600 else last_user
                f.write(f"[INPUT]\n{preview}\n\n")
                if reasoning:
                    f.write(f"[THINKING]\n{reasoning}\n\n")
                f.write(f"[OUTPUT]\n{response}\n")
        except Exception:
            pass
