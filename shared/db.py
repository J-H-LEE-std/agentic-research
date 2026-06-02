"""
SQLite-backed task queue for the dashboard API.
Provides task CRUD, stage tracking, and per-task log storage.
"""
import sqlite3
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from shared.events import notify as _notify

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent.parent / "research.db"))

# Set by runner when a task starts; state.py reads this to sync stage updates.
current_task_id: int | None = None

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT    NOT NULL,
            note_md     TEXT    NOT NULL DEFAULT '',
            pop_csv_path TEXT   NOT NULL DEFAULT '',
            status      TEXT    NOT NULL DEFAULT 'pending',
            current_stage INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
            started_at  TEXT,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS stage_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL,
            stage_num   INTEGER NOT NULL,
            stage_name  TEXT    NOT NULL,
            status      TEXT    NOT NULL,
            detail      TEXT    NOT NULL DEFAULT '',
            updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
            UNIQUE (task_id, stage_num)
        );
        CREATE TABLE IF NOT EXISTS task_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL,
            message     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
        );
    """)
    _conn().commit()
    # Migrate: add note_md column if absent (for databases created before this change)
    cols = [r[1] for r in _conn().execute("PRAGMA table_info(tasks)").fetchall()]
    if "note_md" not in cols:
        _conn().execute("ALTER TABLE tasks ADD COLUMN note_md TEXT NOT NULL DEFAULT ''")
        _conn().commit()
    if "pop_csv_path" not in cols:
        _conn().execute("ALTER TABLE tasks ADD COLUMN pop_csv_path TEXT NOT NULL DEFAULT ''")
        _conn().commit()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Task CRUD ──────────────────────────────────────────────────────────────────

def create_task(topic: str, note_md: str = "") -> int:
    cur = _conn().execute(
        "INSERT INTO tasks (topic, note_md) VALUES (?, ?)", (topic, note_md)
    )
    _conn().commit()
    _notify()
    return cur.lastrowid


def get_task(task_id: int) -> dict | None:
    row = _conn().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_tasks() -> list[dict]:
    rows = _conn().execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_next_pending() -> dict | None:
    row = _conn().execute(
        "SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def set_pop_csv_path(task_id: int, path: str):
    _conn().execute("UPDATE tasks SET pop_csv_path = ? WHERE id = ?", (path, task_id))
    _conn().commit()


def update_task_status(task_id: int, status: str, started_at: str = None, completed_at: str = None):
    fields, values = ["status = ?"], [status]
    if started_at:
        fields.append("started_at = ?")
        values.append(started_at)
    if completed_at:
        fields.append("completed_at = ?")
        values.append(completed_at)
    values.append(task_id)
    _conn().execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)
    _conn().commit()
    _notify()


# ── Stage tracking ─────────────────────────────────────────────────────────────

def update_task_stage(task_id: int, stage_num: int, stage_name: str, status: str, detail: str = ""):
    _conn().execute("""
        INSERT INTO stage_logs (task_id, stage_num, stage_name, status, detail, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id, stage_num) DO UPDATE SET
            status = excluded.status,
            detail = excluded.detail,
            updated_at = excluded.updated_at
    """, (task_id, stage_num, stage_name, status, detail, _now()))
    _conn().execute(
        "UPDATE tasks SET current_stage = ? WHERE id = ?", (stage_num, task_id)
    )
    _conn().commit()
    _notify()


def get_stage_logs(task_id: int) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM stage_logs WHERE task_id = ? ORDER BY stage_num", (task_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Per-task logs ──────────────────────────────────────────────────────────────

def add_log(task_id: int, message: str):
    _conn().execute(
        "INSERT INTO task_logs (task_id, message) VALUES (?, ?)", (task_id, message)
    )
    _conn().commit()


def get_logs(task_id: int, after_id: int = 0) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM task_logs WHERE task_id = ? AND id > ? ORDER BY id",
        (task_id, after_id),
    ).fetchall()
    return [dict(r) for r in rows]
