"""
연구별 격리 workspace 디렉토리를 생성하고 관련 환경변수를 설정한다.

workspace/
  {task_id:04d}_{slug}/
    progress.md              ← PROGRESS_PATH
    llm_thoughts.log         ← LLM_THOUGHTS_PATH
    experiment/              ← EXECUTOR_OUTPUT_PATH
      logs/
        token_usage.jsonl    ← TOKEN_LOG_PATH
        experiment_*.json
      experiment_*.py
    papers/                  ← PAPERS_OUTPUT_PATH (논문 초안, 피어리뷰 리포트)
    graphs/                  ← GRAPHS_OUTPUT_PATH
    uploaded_papers/         ← UPLOADED_PAPERS_PATH
"""
import os
import re
from pathlib import Path

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "./workspace")


def init_workspace(task_id, topic: str) -> Path:
    slug = re.sub(r"[^\w가-힣]", "_", topic.strip())[:40].strip("_")
    id_str = f"{task_id:04d}" if isinstance(task_id, int) else str(task_id)
    name = f"{id_str}_{slug}"
    ws = Path(WORKSPACE_ROOT) / name
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "experiment").mkdir(exist_ok=True)
    (ws / "experiment" / "logs").mkdir(exist_ok=True)
    (ws / "papers").mkdir(exist_ok=True)
    (ws / "graphs").mkdir(exist_ok=True)
    (ws / "uploaded_papers").mkdir(exist_ok=True)

    ws_abs = str(ws.resolve())
    os.environ["RESEARCH_WORKSPACE"] = ws_abs
    os.environ["PROGRESS_PATH"] = str((ws / "progress.md").resolve())
    os.environ["EXECUTOR_OUTPUT_PATH"] = str((ws / "experiment").resolve())
    os.environ["TOKEN_LOG_PATH"] = str((ws / "experiment" / "logs" / "token_usage.jsonl").resolve())
    os.environ["LLM_THOUGHTS_PATH"] = str((ws / "llm_thoughts.log").resolve())
    os.environ["PAPERS_OUTPUT_PATH"] = str((ws / "papers").resolve())
    os.environ["GRAPHS_OUTPUT_PATH"] = str((ws / "graphs").resolve())
    os.environ["UPLOADED_PAPERS_PATH"] = str((ws / "uploaded_papers").resolve())
    return ws


def get_workspace() -> "Path | None":
    ws = os.environ.get("RESEARCH_WORKSPACE")
    return Path(ws) if ws else None
