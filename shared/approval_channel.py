"""
Human-in-the-loop 승인 채널 추상화.
- LocalApprovalChannel : Streamlit UI와 threading.Queue로 통신 (로컬 모드)
- 서버 모드의 ntfy 통신은 orchestrator/main_agent.py가 직접 처리한다.

pending_q 아이템 형식:
  {
    'type':    'stage' | 'direction' | 'paper_upload',
    'title':   str,
    'summary': str,          # stage / direction 전용
    'papers':  list[dict],   # paper_upload 전용
  }

response_q 아이템 형식:
  {'decision': str, 'note': str}              # stage / direction
  {'decision': 'papers', 'papers': dict}      # paper_upload: {title: full_text}
"""
import queue

from shared.events import notify as _notify


class LocalApprovalChannel:
    def __init__(self):
        self.pending_q: queue.Queue = queue.Queue()   # 대기 중인 질문
        self.response_q: queue.Queue = queue.Queue()  # 사용자 응답
        self.log_q: queue.Queue = queue.Queue()       # 로그 문자열
        # Dashboard SSE reads this directly (persists until answered)
        self.current_request: dict | None = None

    # ── 에이전트 → UI ───────────────────────────────────────────────

    def request_approval(self, stage_name: str, summary: str) -> str:
        """단계 완료 승인 요청. 'approve' | 'reject' | 'modify' 반환."""
        item = {'type': 'stage', 'title': stage_name, 'summary': summary}
        self.current_request = item
        _notify()
        self.pending_q.put(item)
        resp = self.response_q.get(block=True)
        self.current_request = None
        _notify()
        return resp['decision']

    def ask_direction(self, question: str, summary: str) -> tuple[str, str]:
        """
        실행 중 방향 질문. (decision, note) 반환.
        - decision: 'continue' | 'stop' | 'modify'
        - note: 사용자가 입력한 수정 지시사항 (없으면 '')
        """
        item = {'type': 'direction', 'title': question, 'summary': summary}
        self.current_request = item
        _notify()
        self.pending_q.put(item)
        resp = self.response_q.get(block=True)
        self.current_request = None
        _notify()
        return resp['decision'], resp.get('note', '')

    def request_papers(self, papers: list) -> dict:
        """
        원문을 구하지 못한 논문 목록을 UI에 전달하고
        사용자가 업로드한 텍스트 dict {title: full_text} 를 반환.
        사용자가 건너뛰면 빈 dict 반환.
        """
        item = {
            'type': 'paper_upload',
            'title': f'논문 원문 요청 ({len(papers)}편)',
            'papers': papers,
        }
        self.current_request = item
        _notify()
        self.pending_q.put(item)
        resp = self.response_q.get(block=True)
        self.current_request = None
        _notify()
        return resp.get('papers', {})

    def submit_papers(self, papers_text: dict):
        """Streamlit에서 PDF 추출 완료 후 호출."""
        self.response_q.put({'decision': 'papers', 'papers': papers_text})

    def log(self, message: str):
        if message.strip():
            self.log_q.put(message.strip())

    # ── UI → 에이전트 ───────────────────────────────────────────────

    def submit(self, decision: str, note: str = ''):
        """Streamlit UI에서 사용자가 버튼을 눌렀을 때 호출."""
        self.response_q.put({'decision': decision, 'note': note})

    # ── Streamlit polling ───────────────────────────────────────────

    def drain_logs(self) -> list[str]:
        msgs = []
        while True:
            try:
                msgs.append(self.log_q.get_nowait())
            except queue.Empty:
                break
        return msgs

    def poll_pending(self) -> dict | None:
        """대기 중인 질문이 있으면 반환, 없으면 None."""
        try:
            return self.pending_q.get_nowait()
        except queue.Empty:
            return None
