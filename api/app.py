"""
FastAPI dashboard backend.

Routes:
  GET  /                          → dashboard HTML
  POST /api/tasks                 → submit research topic
  GET  /api/tasks                 → list all tasks (with stages)
  GET  /api/tasks/{id}            → single task detail + stages + logs
  DELETE /api/tasks/{id}          → cancel (running or pending)
  POST /api/tasks/{id}/respond    → answer an approval/direction request
  GET  /api/stream                → SSE: real-time task/stage/log updates
"""
import asyncio
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared import db, events
from api.runner import runner

app = FastAPI(title="Research Agent Dashboard")


@app.on_event("startup")
def _startup():
    db.init_db()
    for task in db.get_tasks():
        if task["status"] == "running":
            db.update_task_status(task["id"], "failed")
    next_task = db.get_next_pending()
    if next_task:
        note_extras = _parse_note_extras(next_task.get("note_md", ""))
        runner.start(next_task["id"], next_task["topic"], note_extras)


def _parse_note_extras(note_md: str) -> dict:
    if not note_md.strip():
        return {}
    from shared.research_note import parse as parse_note, to_context_extras
    return to_context_extras(parse_note(note_md))


# ── Models ─────────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    topic: str = ""
    note_md: str = ""   # 선택: 연구 노트 Markdown 전문


class ApprovalResponse(BaseModel):
    decision: str          # approve | reject | modify | continue | stop
    note: str = ""


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/tasks", status_code=201)
def create_task(body: TaskCreate):
    from shared.research_note import parse as parse_note, to_context_extras

    note_md = body.note_md.strip()
    if note_md:
        parsed = parse_note(note_md)
        topic = parsed.get("topic", "").strip() or body.topic.strip()
        note_extras = to_context_extras(parsed)
    else:
        topic = body.topic.strip()
        note_extras = {}

    if not topic:
        raise HTTPException(400, "topic must not be empty")

    task_id = db.create_task(topic, note_md=note_md)
    if not runner.is_running:
        runner.start(task_id, topic, note_extras)
    return {"id": task_id}


@app.get("/api/tasks")
def list_tasks():
    tasks = db.get_tasks()
    for t in tasks:
        t["stages"] = db.get_stage_logs(t["id"])
    return tasks


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404)
    task["stages"] = db.get_stage_logs(task_id)
    task["logs"] = db.get_logs(task_id)
    return task


@app.delete("/api/tasks/{task_id}")
def cancel_task(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if task["status"] == "running":
        # DB를 즉시 cancelled로 — SSE가 바로 반영하도록
        db.update_task_status(task_id, "cancelled", completed_at=now)
        runner.cancel()
    elif task["status"] == "pending":
        db.update_task_status(task_id, "cancelled")
    else:
        raise HTTPException(400, f"Cannot cancel task with status '{task['status']}'")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/respond")
def respond_to_approval(task_id: int, body: ApprovalResponse):
    task = db.get_task(task_id)
    if not task or task["status"] != "running":
        raise HTTPException(400, "Task is not running")
    ch = runner.channel
    if ch is None or ch.current_request is None:
        raise HTTPException(400, "No approval request is pending")
    ch.submit(body.decision, body.note)
    return {"ok": True}


@app.post("/api/tasks/{task_id}/pop")
async def upload_pop_csv(task_id: int, file: UploadFile = File(...)):
    """PoP(Publish or Perish) CSV 내보내기 파일을 업로드한다."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404)
    if task["status"] not in ("pending", "running"):
        raise HTTPException(400, f"Task status is '{task['status']}' — only pending/running tasks accept PoP CSV")

    data_root = os.path.dirname(os.path.abspath(
        os.environ.get("EXECUTOR_OUTPUT_PATH", "./data/outputs")
    ))
    pop_dir = os.path.join(data_root, "pop")
    os.makedirs(pop_dir, exist_ok=True)

    content = await file.read()
    csv_path = os.path.join(pop_dir, f"task_{task_id}_pop.csv")
    with open(csv_path, "wb") as f:
        f.write(content)

    db.set_pop_csv_path(task_id, csv_path)

    from shared.pop_parser import parse_pop_file
    try:
        papers = parse_pop_file(csv_path)
        return {"ok": True, "papers_found": len(papers)}
    except Exception as e:
        raise HTTPException(400, f"CSV 파싱 실패: {e}")


@app.post("/api/tasks/{task_id}/papers")
async def upload_papers(task_id: int, files: List[UploadFile] = File(default=[])):
    """원문 PDF 업로드 — paper_upload 타입 approval request에 응답한다."""
    from shared.pdf_extractor import extract_text

    task = db.get_task(task_id)
    if not task or task["status"] != "running":
        raise HTTPException(400, "Task is not running")
    ch = runner.channel
    if ch is None or ch.current_request is None or ch.current_request.get("type") != "paper_upload":
        raise HTTPException(400, "No paper upload request is pending")

    papers = ch.current_request.get("papers", [])
    papers_text: dict = {}
    for f in files:
        content = await f.read()
        text = extract_text(content)
        if text:
            papers_text[f.filename] = text

    # 파일명과 논문 제목을 매칭
    matched: dict = {}
    for paper in papers:
        title = paper.get("title", "")
        for fname, text in papers_text.items():
            fname_lower = fname.lower().replace(".pdf", "").replace("_", " ")
            title_words = [w for w in title.split()[:4] if len(w) > 3]
            if title_words and any(w.lower() in fname_lower for w in title_words):
                matched[title] = text
                break

    # 매칭되지 않은 텍스트를 남은 논문에 순서대로 할당
    unmatched_texts = [t for fn, t in papers_text.items()
                       if fn not in {fn for fn in papers_text if fn}]
    for paper in papers:
        if paper.get("title", "") not in matched and unmatched_texts:
            matched[paper["title"]] = unmatched_texts.pop(0)

    # 업로드된 파일을 workspace에 저장
    ws = os.environ.get("RESEARCH_WORKSPACE", "")
    if ws:
        upload_dir = os.path.join(ws, "uploaded_papers")
        os.makedirs(upload_dir, exist_ok=True)

    ch.submit_papers(matched)
    return {"ok": True, "matched": len(matched), "total_uploaded": len(papers_text)}


# ── Workspace file helpers ────────────────────────────────────────────────────

def _find_workspace(task_id: int) -> "Path | None":
    root = Path(os.environ.get("WORKSPACE_ROOT", "./workspace"))
    prefix = f"{task_id:04d}_"
    if root.exists():
        for d in root.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                return d
    return None


FILE_ICONS = {
    ".md":   "📄",
    ".pdf":  "📕",
    ".png":  "📊",
    ".jpg":  "📊",
    ".py":   "💻",
    ".json": "📋",
    ".log":  "📝",
    ".zip":  "📦",
    ".csv":  "📊",
    ".tex":  "📄",
}


@app.get("/api/tasks/{task_id}/files")
def list_task_files(task_id: int):
    if not db.get_task(task_id):
        raise HTTPException(404)
    ws = _find_workspace(task_id)
    if not ws:
        return {"files": [], "workspace": None}
    files = []
    for f in sorted(ws.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(ws)).replace("\\", "/")
            files.append({
                "path": rel,
                "name": f.name,
                "size": f.stat().st_size,
                "icon": FILE_ICONS.get(f.suffix.lower(), "📎"),
            })
    return {"files": files, "workspace": ws.name}


@app.get("/api/tasks/{task_id}/files/{filepath:path}")
def download_file(task_id: int, filepath: str):
    if not db.get_task(task_id):
        raise HTTPException(404)
    ws = _find_workspace(task_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    target = (ws / filepath).resolve()
    try:
        target.relative_to(ws.resolve())
    except ValueError:
        raise HTTPException(403)
    if not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, filename=target.name)


@app.get("/api/tasks/{task_id}/archive")
def download_archive(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404)
    ws = _find_workspace(task_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(ws.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(ws))
    buf.seek(0)

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{ws.name}.zip"'},
    )


# ── SSE stream ─────────────────────────────────────────────────────────────────

@app.get("/api/stream")
async def event_stream():
    async def generate():
        last_log_ids: dict[int, int] = {}

        while True:
            tasks = db.get_tasks()
            payload: list[dict] = []

            for t in tasks:
                entry = dict(t)
                entry["stages"] = db.get_stage_logs(t["id"])

                if t["status"] == "running":
                    after = last_log_ids.get(t["id"], 0)
                    new_logs = db.get_logs(t["id"], after_id=after)
                    if new_logs:
                        last_log_ids[t["id"]] = new_logs[-1]["id"]
                    entry["new_logs"] = new_logs

                    ch = runner.channel
                    entry["approval_request"] = ch.current_request if ch else None

                payload.append(entry)

            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            # 상태 변경(notify) 즉시 push, 없으면 1초 후 log 업데이트용으로 wake-up
            await events.wait_for_change(1.0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

@app.get("/")
def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, encoding="utf-8") as f:
        return HTMLResponse(f.read())
