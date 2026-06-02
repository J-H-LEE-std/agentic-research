import sys
import os
import json
import subprocess
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent
from shared.models import get_model
from shared.prompts import IMPLEMENT

MAX_RETRIES = 3


class ImplementAgent(BaseAgent):
    def __init__(self):
        # 코딩 특화 모델 사용
        super().__init__(role="implement")

    def run(self, context: dict) -> dict:
        topic = context.get("topic", "")
        design = context.get("design", {})
        pseudocode = design.get("pseudocode", "")
        idea = design.get("idea", "")

        code = self._generate_code(topic, pseudocode, idea)
        code_path, log_path, exec_result = self._run_with_retry(code, topic, context)

        return {
            "code_path": code_path,
            "log_path": log_path,
            "exec_result": exec_result,
            "final_code": code,
        }

    def _generate_code(self, topic: str, pseudocode: str, idea: str) -> str:
        messages = [
            {"role": "system", "content": IMPLEMENT},
            {
                "role": "user",
                "content": (
                    f"연구 주제: {topic}\n\n"
                    f"알고리즘 아이디어:\n{idea}\n\n"
                    f"Pseudocode:\n{pseudocode}\n\n"
                    "위 내용을 Python 코드로 구현하고, 실험 결과를 outputs/ 디렉토리에 JSON으로 저장하세요."
                ),
            },
        ]
        code = self.client.chat(
            model=self.model,
            messages=messages,
            temperature=0.2,
            max_tokens=4096,
            caller="implement_agent_codegen",
        )
        return self._strip_markdown(code)

    def _run_with_retry(self, code: str, topic: str, context: dict = None) -> tuple:
        output_path = os.path.abspath(os.environ.get("EXECUTOR_OUTPUT_PATH", "./workspace/default/experiment"))
        os.makedirs(output_path, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        code_filename = f"experiment_{timestamp}.py"
        log_filename = f"experiment_{timestamp}_log.json"
        code_path = os.path.join(output_path, code_filename)
        log_path = os.path.join(output_path, "logs", log_filename)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        current_code = code
        exec_result = {}

        for attempt in range(1, MAX_RETRIES + 1):
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(current_code)

            result = self._execute_python(current_code, output_path)
            exec_result = {
                "attempt": attempt,
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "return_code": result["return_code"],
            }

            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(exec_result, f, ensure_ascii=False, indent=2)

            if result["return_code"] == 0:
                break

            if attempt < MAX_RETRIES:
                current_code = self._debug_code(current_code, result["stderr"], attempt)
            else:
                # 모든 재시도 실패 → 방향 질문
                decision, note = self.ask_direction(
                    context or {},
                    question=f"코드 실행이 {MAX_RETRIES}회 모두 실패했습니다 — 어떻게 할까요?",
                    summary=(
                        f"마지막 오류:\n```\n{result['stderr'][:500]}\n```\n\n"
                        "**계속 진행**: 실패한 결과로 분석 단계 진행\n"
                        "**방향 수정**: 지시사항을 입력하면 코드 재생성을 시도합니다\n"
                        "**중단**: 파이프라인 종료"
                    ),
                )
                if decision == "stop":
                    raise RuntimeError("사용자가 구현 단계에서 파이프라인을 중단했습니다.")
                if decision == "modify" and note:
                    print(f"  → 수정 지시로 코드 재생성 시도: {note}")
                    current_code = self._generate_code(topic, "", note)
                    retry_result = self._execute_python(current_code)
                    if retry_result["return_code"] == 0:
                        exec_result = {"attempt": MAX_RETRIES + 1, **retry_result}
                        with open(log_path, "w", encoding="utf-8") as f:
                            json.dump(exec_result, f, ensure_ascii=False, indent=2)

        return code_path, log_path, exec_result

    def _execute_python(self, code: str, output_path: str = None) -> dict:
        if output_path is None:
            output_path = os.path.abspath(os.environ.get("EXECUTOR_OUTPUT_PATH", "./workspace/default/experiment"))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        try:
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=output_path,
            )
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "return_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "TimeoutError: 30초 초과", "return_code": -1}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "return_code": -1}
        finally:
            os.unlink(tmp_path)

    def _debug_code(self, code: str, error: str, attempt: int) -> str:
        messages = [
            {
                "role": "system",
                "content": IMPLEMENT + "\n\n디버깅 모드: 오류를 분석하고 코드를 수정하세요.",
            },
            {
                "role": "user",
                "content": (
                    f"[시도 {attempt}/{MAX_RETRIES}] 다음 코드에서 오류가 발생했습니다.\n\n"
                    f"[오류]\n{error}\n\n"
                    f"[코드]\n{code}\n\n"
                    "수정된 코드만 출력하세요."
                ),
            },
        ]
        fixed = self.client.chat(
            model=self.model,
            messages=messages,
            temperature=0.2,
            max_tokens=4096,
            caller=f"implement_agent_debug_a{attempt}",
        )
        return self._strip_markdown(fixed)

    @staticmethod
    def _strip_markdown(code: str) -> str:
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0]
        elif "```" in code:
            code = code.split("```")[1].split("```")[0]
        return code.strip()
