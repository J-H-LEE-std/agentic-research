"""
Research Agent — Streamlit 로컬 UI
실행: streamlit run ui/streamlit_app.py
"""
import sys
import os
import threading
import time
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from shared.approval_channel import LocalApprovalChannel
from shared.state import init_progress, read_progress
from shared.research_note import parse as parse_note, extract_topic, to_context_extras, TEMPLATE

# ── 페이지 설정 ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Research Agent",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

STAGE_LABELS = {
    1: "문헌 수집",
    2: "알고리즘 설계",
    3: "코드 구현",
    4: "결과 분석",
    5: "논문 작성",
    6: "피어리뷰",
}
STATUS_ICON = {
    "pending":          "⏳",
    "in_progress":      "🔄",
    "waiting_approval": "⏸",
    "completed":        "✅",
    "failed":           "❌",
}

# ── 세션 상태 초기화 ────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "channel":          None,
        "thread":           None,
        "logs":             [],
        "pending_item":     None,   # pending_q에서 꺼낸 dict | None
        "running":          False,
        "finished":         False,
        "topic":            "",
        "stage_status":     {i: "pending" for i in range(1, 7)},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── stdout 리디렉터 ─────────────────────────────────────────────────────
class _ChannelWriter(io.TextIOBase):
    def __init__(self, channel: LocalApprovalChannel, original):
        self._ch = channel
        self._orig = original

    def write(self, text: str) -> int:
        if text.strip():
            self._ch.log(text)
        self._orig.write(text)
        return len(text)

    def flush(self):
        self._orig.flush()


# ── 오케스트레이터 실행 스레드 ───────────────────────────────────────────
def _run_orchestrator(topic: str, channel: LocalApprovalChannel, note_extras: dict = None):
    orig_stdout = sys.stdout
    sys.stdout = _ChannelWriter(channel, orig_stdout)
    try:
        from orchestrator.main_agent import MainOrchestrator
        orch = MainOrchestrator(topic=topic, approval_channel=channel, note_extras=note_extras or {})
        orch.run()
    except Exception as e:
        channel.log(f"[오류] {e}")
    finally:
        sys.stdout = orig_stdout
        channel.log("__FINISHED__")


# ── 사이드바 ────────────────────────────────────────────────────────────
def _render_sidebar():
    with st.sidebar:
        st.title("🔬 Research Agent")
        st.caption("로컬 모드 — Streamlit UI")
        st.divider()

        if not st.session_state.running and not st.session_state.finished:
            _render_input_panel()
        else:
            st.markdown(f"**주제**\n\n{st.session_state.topic}")
            if st.session_state.finished:
                st.success("완료!")
                if st.button("새 연구 시작", use_container_width=True):
                    for k in list(st.session_state.keys()):
                        del st.session_state[k]
                    st.rerun()

        st.divider()
        st.subheader("파이프라인 진행")
        for i, label in STAGE_LABELS.items():
            status = st.session_state.stage_status.get(i, "pending")
            icon = STATUS_ICON.get(status, "⏳")
            color = {
                "completed":        "#22c55e",
                "in_progress":      "#3b82f6",
                "waiting_approval": "#f59e0b",
                "failed":           "#ef4444",
            }.get(status, "#6b7280")
            st.markdown(
                f"<div style='padding:4px 0; color:{color}'>"
                f"{icon} Stage {i}: {label}</div>",
                unsafe_allow_html=True,
            )


def _render_input_panel():
    """Sidebar input: simple topic text or structured research note."""
    mode = st.radio(
        "입력 방식",
        ["간단 입력", "연구 노트 (Markdown)"],
        horizontal=True,
        key="input_mode",
    )

    if mode == "간단 입력":
        topic_input = st.text_area(
            "연구 주제",
            placeholder="예: Efficient Transformer Attention for Long Sequences",
            height=100,
            key="topic_input",
        )
        if st.button("▶ 파이프라인 시작", use_container_width=True, type="primary"):
            topic = topic_input.strip()
            if not topic:
                st.error("연구 주제를 입력하세요.")
            else:
                _start_pipeline(topic, {})
                st.rerun()

    else:  # 연구 노트 모드
        uploaded = st.file_uploader(
            ".md 파일 업로드 (선택)",
            type=["md", "txt"],
            key="note_upload",
        )
        if uploaded is not None:
            default_text = uploaded.read().decode("utf-8")
        else:
            default_text = TEMPLATE

        note_text = st.text_area(
            "연구 노트 (Markdown)",
            value=default_text,
            height=320,
            key="note_input",
        )

        # 실시간 파싱 미리보기
        if note_text.strip():
            parsed = parse_note(note_text)
            topic_preview = parsed.get("topic", "")
            if topic_preview and not topic_preview.startswith("("):
                st.caption(f"📌 주제: **{topic_preview}**")
                extras = to_context_extras(parsed)
                if extras:
                    with st.expander("인식된 필드", expanded=False):
                        for k, v in extras.items():
                            label = {
                                "background": "배경",
                                "hypothesis": "가설",
                                "research_questions": "연구 질문",
                                "constraints": "제약 사항",
                                "expected_outcome": "기대 결과",
                                "keywords": "키워드",
                            }.get(k, k)
                            st.markdown(f"**{label}**\n\n{v[:200]}")
            else:
                st.warning("'## 연구 제목' 섹션에 주제를 입력하세요.")

        if st.button("▶ 파이프라인 시작", use_container_width=True, type="primary", key="note_start"):
            parsed = parse_note(note_text)
            topic = parsed.get("topic", "").strip()
            if not topic or topic.startswith("("):
                st.error("연구 노트에 '## 연구 제목'을 작성하세요.")
            else:
                extras = to_context_extras(parsed)
                _start_pipeline(topic, extras)
                st.rerun()


def _start_pipeline(topic: str, note_extras: dict):
    init_progress(topic)
    channel = LocalApprovalChannel()
    st.session_state.channel = channel
    st.session_state.topic = topic
    st.session_state.running = True
    st.session_state.logs = []
    st.session_state.stage_status = {i: "pending" for i in range(1, 7)}
    st.session_state.pending_item = None

    thread = threading.Thread(
        target=_run_orchestrator,
        args=(topic, channel, note_extras),
        daemon=True,
    )
    thread.start()
    st.session_state.thread = thread


# ── 메인 영역 ────────────────────────────────────────────────────────────
def _render_main():
    st.header("Research Agent", divider="gray")

    if not st.session_state.running and not st.session_state.finished:
        st.info("왼쪽 사이드바에서 연구 주제를 입력하고 파이프라인을 시작하세요.")
        return

    channel: LocalApprovalChannel = st.session_state.channel

    # ── 새 로그 수집 ──────────────────────────────────────────────────
    for msg in channel.drain_logs() if channel else []:
        if msg == "__FINISHED__":
            st.session_state.running = False
            st.session_state.finished = True
        else:
            st.session_state.logs.append(msg)
            _update_stage_status(msg)

    # ── 대기 중인 질문 수집 ───────────────────────────────────────────
    if st.session_state.pending_item is None and channel:
        item = channel.poll_pending()
        if item:
            st.session_state.pending_item = item

    # ── 인터랙션 카드 (최상단 고정) ──────────────────────────────────
    if st.session_state.pending_item:
        item = st.session_state.pending_item
        if item['type'] == 'stage':
            _render_stage_approval(item, channel)
        elif item['type'] == 'paper_upload':
            _render_paper_upload(item, channel)
        else:
            _render_direction_question(item, channel)

    # ── 채팅 로그 ─────────────────────────────────────────────────────
    st.subheader("Agent 로그")
    with st.container(height=420, border=True):
        for msg in st.session_state.logs:
            _render_log_message(msg)

    # ── 자동 새로고침 ─────────────────────────────────────────────────
    if st.session_state.running and st.session_state.pending_item is None:
        time.sleep(0.8)
        st.rerun()


# ── Stage 완료 승인 카드 ─────────────────────────────────────────────────
def _render_stage_approval(item: dict, channel: LocalApprovalChannel):
    st.warning(f"### ⏸ 단계 완료 — 승인 필요: {item['title']}", icon="🔔")
    with st.expander("상세 내용", expanded=True):
        st.markdown(item['summary'])

    col1, col2, col3 = st.columns(3)
    note = st.text_input(
        "수정 지시사항 (선택 — 승인/거부 시에도 메모 가능)",
        key="stage_note",
        placeholder="예: 참고 논문에 2024년 이후 논문만 포함해주세요",
    )

    with col1:
        if st.button("✅ 승인", use_container_width=True, type="primary", key="stage_approve"):
            _submit(channel, "approve", note)
    with col2:
        if st.button("❌ 거부", use_container_width=True, key="stage_reject"):
            _submit(channel, "reject", note)
    with col3:
        if st.button("✏ 수정 후 진행", use_container_width=True, key="stage_modify"):
            _submit(channel, "modify", note)

    st.divider()


# ── 중간 방향 질문 카드 ──────────────────────────────────────────────────
def _render_direction_question(item: dict, channel: LocalApprovalChannel):
    st.info(f"### 🤔 방향 확인 필요: {item['title']}", icon="❓")
    with st.expander("상황 설명", expanded=True):
        st.markdown(item['summary'])

    st.markdown("**어떻게 진행할까요?**")
    col1, col2, col3 = st.columns(3)

    note = st.text_input(
        "지시사항 입력 (수정 시 필수, 계속/중단 시 선택)",
        key="dir_note",
        placeholder="예: 논문이 적더라도 일단 진행하세요 / 주제를 좁혀서 다시 검색하세요",
    )

    with col1:
        if st.button("▶ 계속 진행", use_container_width=True, type="primary", key="dir_continue"):
            _submit(channel, "continue", note)
    with col2:
        if st.button("⏹ 파이프라인 중단", use_container_width=True, key="dir_stop"):
            _submit(channel, "stop", note)
    with col3:
        if st.button("🔄 방향 수정", use_container_width=True, key="dir_modify"):
            if not note.strip():
                st.error("수정 시에는 지시사항을 입력해주세요.")
            else:
                _submit(channel, "modify", note)

    st.divider()


def _render_paper_upload(item: dict, channel: LocalApprovalChannel):
    from shared.pdf_extractor import extract_text as _extract_text

    papers = item.get('papers', [])
    st.info(f"### 📄 논문 원문 요청 — {len(papers)}편", icon="📎")
    st.markdown(
        "자동으로 원문을 받지 못한 논문입니다. "
        "학교 네트워크에서 PDF를 다운받아 업로드해 주세요. "
        "건너뛰면 초록(abstract)만으로 분석을 계속합니다."
    )

    with st.expander("원문이 필요한 논문 목록", expanded=True):
        for p in papers:
            title = p.get('title', '(제목 없음)')
            url = p.get('url', '')
            if url:
                st.markdown(f"- [{title}]({url})")
            else:
                st.markdown(f"- {title}")

    uploaded_files = st.file_uploader(
        "PDF 업로드 (여러 파일 선택 가능)",
        type=["pdf"],
        accept_multiple_files=True,
        key="paper_pdfs",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📤 제출", use_container_width=True, type="primary", key="paper_submit"):
            papers_text: dict = {}
            for f in (uploaded_files or []):
                text = _extract_text(f.read())
                if text:
                    # 파일명에서 공백 제거한 키로 저장; 에이전트에서 title과 매칭
                    papers_text[f.name] = text
            # title-based 매칭 시도
            matched: dict = {}
            for paper in papers:
                title = paper.get('title', '')
                # 파일명에 논문 제목 일부가 포함되면 매칭
                for fname, text in papers_text.items():
                    if any(word.lower() in fname.lower() for word in title.split()[:3] if len(word) > 3):
                        matched[title] = text
                        break
            # 매칭 실패한 것도 순서대로 채움
            unmatched_texts = [t for fn, t in papers_text.items()
                               if fn not in {fn for fn, _ in papers_text.items() if fn}]
            for paper in papers:
                if paper.get('title', '') not in matched and unmatched_texts:
                    matched[paper['title']] = unmatched_texts.pop(0)

            count = len(matched)
            st.session_state.logs.append(f"[논문 업로드] {count}편 원문 제출")
            channel.submit_papers(matched)
            st.session_state.pending_item = None
            st.rerun()

    with col2:
        if st.button("⏭ 건너뛰기 (초록으로 진행)", use_container_width=True, key="paper_skip"):
            st.session_state.logs.append("[논문 업로드] 건너뜀 — 초록으로 계속 진행")
            channel.submit_papers({})
            st.session_state.pending_item = None
            st.rerun()

    st.divider()


def _submit(channel: LocalApprovalChannel, decision: str, note: str):
    label_map = {
        "approve": "승인", "reject": "거부", "modify": "수정 요청",
        "continue": "계속 진행", "stop": "중단",
    }
    label = label_map.get(decision, decision)
    log_msg = f"[{label}]"
    if note.strip():
        log_msg += f" — {note.strip()}"
    st.session_state.logs.append(log_msg)
    channel.submit(decision, note.strip())
    st.session_state.pending_item = None
    st.rerun()


# ── 로그 메시지 렌더링 ────────────────────────────────────────────────────
def _render_log_message(msg: str):
    if any(msg.startswith(p) for p in ("[승인]", "[거부]", "[계속 진행]", "[중단]", "[수정")):
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg)
    elif msg.startswith("[오류]"):
        with st.chat_message("assistant", avatar="❌"):
            st.error(msg)
    elif msg.startswith("[인간 승인") or msg.startswith("[방향 질문]"):
        with st.chat_message("assistant", avatar="🔔"):
            st.markdown(f"**{msg}**")
    elif msg.startswith("[Stage"):
        with st.chat_message("assistant", avatar="🔬"):
            st.markdown(msg)
    else:
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(msg)


# ── 사이드바 Stage 상태 업데이트 ─────────────────────────────────────────
def _update_stage_status(msg: str):
    for i in range(1, 7):
        if f"[Stage {i}]" in msg:
            if "완료" in msg or "completed" in msg.lower():
                st.session_state.stage_status[i] = "completed"
            elif "시작" in msg or "in_progress" in msg.lower():
                st.session_state.stage_status[i] = "in_progress"
        if "[인간 승인 요청]" in msg and STAGE_LABELS.get(i, "") in msg:
            st.session_state.stage_status[i] = "waiting_approval"
        if "[방향 질문]" in msg and STAGE_LABELS.get(i, "") in msg:
            st.session_state.stage_status[i] = "waiting_approval"


# ── 레이아웃 ─────────────────────────────────────────────────────────────
_render_sidebar()

tab_chat, tab_progress = st.tabs(["💬 Agent 대화", "📋 progress.md"])

with tab_chat:
    _render_main()

with tab_progress:
    progress_text = read_progress()
    if progress_text:
        st.markdown(progress_text)
    else:
        st.info("아직 진행 상황이 없습니다.")
    if st.button("🔄 새로고침", key="refresh_progress"):
        st.rerun()
