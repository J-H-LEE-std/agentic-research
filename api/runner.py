"""
Runs the MainOrchestrator in a background thread.
- stdout is captured and forwarded to DB logs + approval channel log_q.
- Cancellation: sets cancel_event + unblocks any pending approval.
- Auto-starts next pending task on completion.
"""
import sys
import threading
from datetime import datetime, timezone

from shared import db
from shared.approval_channel import LocalApprovalChannel


class _StdoutCapture:
    """Redirects print() output to the approval channel log queue and DB."""

    def __init__(self, channel: LocalApprovalChannel, task_id: int):
        self._channel = channel
        self._task_id = task_id
        self._buf = ""
        self._real = sys.__stdout__

    def write(self, text: str):
        self._real.write(text)
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._channel.log(line)
                db.add_log(self._task_id, line)

    def flush(self):
        self._real.flush()

    def fileno(self):
        return self._real.fileno()


class TaskRunner:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._channel: LocalApprovalChannel | None = None
        self.current_task_id: int | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def channel(self) -> LocalApprovalChannel | None:
        return self._channel

    def start(self, task_id: int, topic: str, note_extras: dict = None) -> bool:
        with self._lock:
            if self.is_running:
                return False
            self._cancel_event.clear()
            self.current_task_id = task_id
            db.current_task_id = task_id
            self._channel = LocalApprovalChannel()

            extras = dict(note_extras or {})
            task = db.get_task(task_id)
            if task and task.get("pop_csv_path"):
                try:
                    from shared.pop_parser import parse_pop_file
                    pop_papers = parse_pop_file(task["pop_csv_path"])
                    if pop_papers:
                        extras["pop_papers"] = pop_papers
                except Exception as e:
                    print(f"[runner] PoP CSV 파싱 실패: {e}")

            self._thread = threading.Thread(
                target=self._run, args=(task_id, topic, extras),
                daemon=True, name=f"task-{task_id}"
            )
            self._thread.start()
            return True

    def cancel(self):
        self._cancel_event.set()
        ch = self._channel
        if ch:
            # Unblock any waiting approval/direction
            ch.response_q.put({"decision": "reject", "note": "cancelled"})

    def _run(self, task_id: int, topic: str, note_extras: dict = {}):
        # workspace 초기화는 에이전트 모듈 import 전에 해야 환경변수가 정확히 적용됨
        from shared.workspace import init_workspace
        init_workspace(task_id, topic)

        from shared.state import init_progress
        from orchestrator.main_agent import MainOrchestrator

        db.update_task_status(task_id, "running", started_at=_now())
        init_progress(topic)

        old_stdout = sys.stdout
        sys.stdout = _StdoutCapture(self._channel, task_id)

        final_status = "failed"
        try:
            orchestrator = MainOrchestrator(
                topic=topic, approval_channel=self._channel, note_extras=note_extras
            )
            orchestrator.run()
            final_status = "cancelled" if self._cancel_event.is_set() else "completed"
        except (RuntimeError, KeyboardInterrupt):
            final_status = "cancelled" if self._cancel_event.is_set() else "failed"
        except Exception as exc:
            db.add_log(task_id, f"[ERROR] {exc}")
            final_status = "cancelled" if self._cancel_event.is_set() else "failed"
        finally:
            sys.stdout = old_stdout
            # API endpoint가 이미 cancelled를 기록했을 수 있으므로 확인 후 기록
            current = db.get_task(task_id)
            if not current or current["status"] != "cancelled":
                db.update_task_status(task_id, final_status, completed_at=_now())
            self.current_task_id = None
            db.current_task_id = None
            self._channel = None

            if not self._cancel_event.is_set():
                next_task = db.get_next_pending()
                if next_task:
                    from shared.research_note import parse as _parse_note, to_context_extras as _to_extras
                    note_md = next_task.get("note_md", "")
                    next_extras = _to_extras(_parse_note(note_md)) if note_md.strip() else {}
                    self.start(next_task["id"], next_task["topic"], next_extras)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Singleton used by the FastAPI app
runner = TaskRunner()
