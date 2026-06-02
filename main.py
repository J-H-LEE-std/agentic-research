"""
진입점:
  python main.py --topic "연구 주제"
  python main.py --note research_note_template.md
"""
import argparse
import os
import sys

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(description="Research Automation Agent")
    parser.add_argument(
        "--topic",
        type=str,
        default="",
        help="연구 주제 (예: 'Efficient Transformer Attention for Long Sequences')",
    )
    parser.add_argument(
        "--note",
        type=str,
        default="",
        help="연구 노트 Markdown 파일 경로 (research_note_template.md 형식)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="기존 workspace가 있으면 이어서 실행",
    )
    args = parser.parse_args()

    note_extras: dict = {}

    if args.note:
        with open(args.note, encoding="utf-8") as f:
            note_text = f.read()
        from shared.research_note import parse as parse_note, to_context_extras
        parsed = parse_note(note_text)
        topic = parsed.get("topic", "").strip()
        note_extras = to_context_extras(parsed)
        if not topic:
            parser.error("연구 노트 파일에 '## 연구 제목' 섹션이 없거나 비어 있습니다.")
    elif args.topic:
        topic = args.topic.strip()
    else:
        parser.error("--topic 또는 --note 중 하나를 지정하세요.")

    # workspace 초기화 (에이전트 import 전에 실행해야 환경변수가 적용됨)
    from shared.workspace import init_workspace
    task_id = os.getpid()  # CLI 모드: PID를 task_id 대용으로 사용
    ws = init_workspace(task_id, topic)
    print(f"Workspace: {ws}")

    from shared.state import init_progress
    from orchestrator.main_agent import MainOrchestrator

    if not args.resume:
        init_progress(topic)

    orchestrator = MainOrchestrator(topic=topic, note_extras=note_extras)
    orchestrator.run()


if __name__ == "__main__":
    main()
