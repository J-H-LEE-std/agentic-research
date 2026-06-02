import os
import time
from pathlib import Path


def _progress_path() -> str:
    return os.environ.get("PROGRESS_PATH", "./progress.md")


def init_progress(topic: str):
    now = time.strftime("%Y-%m-%d %H:%M")
    content = f"""# Research Progress

**Topic:** {topic}
**Started:** {now}
**Status:** in_progress

## Stage 1: Literature Review
- Status: ⏳ pending

## Stage 2: Algorithm Design
- Status: ⏳ pending

## Stage 3: Implementation & Experiments
- Status: ⏳ pending

## Stage 4: Result Analysis
- Status: ⏳ pending

## Stage 5: Paper Writing
- Status: ⏳ pending

## Stage 6: Peer Review
- Status: ⏳ pending

## Human Approval Log
"""
    path = _progress_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read_progress() -> str:
    try:
        with open(_progress_path(), "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def update_stage(stage_num: int, stage_name: str, status: str, details: str = ""):
    try:
        from shared import db as _db
        if _db.current_task_id is not None:
            _db.update_task_stage(_db.current_task_id, stage_num, stage_name, status, details)
    except Exception:
        pass

    content = read_progress()
    path = _progress_path()
    stage_header = f"## Stage {stage_num}: {stage_name}"

    status_icons = {
        "pending": "⏳ pending",
        "in_progress": "🔄 in_progress",
        "waiting_approval": "⏸ waiting_approval",
        "completed": "✅ completed",
        "failed": "❌ failed",
    }
    status_text = status_icons.get(status, status)

    lines = content.split("\n")
    new_lines = []
    in_section = False
    replaced = False

    for i, line in enumerate(lines):
        if line.strip() == stage_header:
            in_section = True
            new_lines.append(line)
            new_lines.append(f"- Status: {status_text}")
            if details:
                for detail_line in details.strip().split("\n"):
                    new_lines.append(f"- {detail_line}")
            replaced = True
            continue
        if in_section:
            if line.startswith("## ") and line.strip() != stage_header:
                in_section = False
                new_lines.append(line)
            elif line.startswith("- "):
                continue
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not replaced:
        new_lines.append(f"\n{stage_header}")
        new_lines.append(f"- Status: {status_text}")
        if details:
            for detail_line in details.strip().split("\n"):
                new_lines.append(f"- {detail_line}")

    # Update global status
    new_content = "\n".join(new_lines)
    if status == "waiting_approval":
        new_content = new_content.replace(
            "**Status:** in_progress", "**Status:** waiting_approval"
        )
    elif status in ("in_progress",):
        new_content = new_content.replace(
            "**Status:** waiting_approval", "**Status:** in_progress"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)


def log_approval(message: str):
    content = read_progress()
    timestamp = time.strftime("%H:%M")
    entry = f"- [{timestamp}] {message}"
    if "## Human Approval Log" in content:
        content = content + "\n" + entry
    else:
        content += f"\n\n## Human Approval Log\n{entry}"
    with open(_progress_path(), "w", encoding="utf-8") as f:
        f.write(content)


def mark_completed(topic: str):
    content = read_progress()
    content = content.replace("**Status:** in_progress", "**Status:** completed")
    content = content.replace("**Status:** waiting_approval", "**Status:** completed")
    with open(_progress_path(), "w", encoding="utf-8") as f:
        f.write(content)
