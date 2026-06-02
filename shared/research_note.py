"""Research note parser — structured Markdown → context dict."""
import re

SECTION_KEYS = {
    "연구 제목": "topic",
    "연구 배경": "background",
    "연구 가설": "hypothesis",
    "핵심 연구 질문": "research_questions",
    "제약 사항": "constraints",
    "기대 결과": "expected_outcome",
    "관련 키워드": "keywords",
}

TEMPLATE = """\
# 연구 노트

## 연구 제목
(연구 주제를 한 줄로 입력하세요)

## 연구 배경 및 동기
(이 연구를 하게 된 배경과 해결하고 싶은 문제를 설명하세요)

## 연구 가설
(핵심 가설을 구체적으로 작성하세요)

## 핵심 연구 질문
-
-

## 제약 사항 및 조건
(실험 환경, 사용 가능한 리소스 등)

## 기대 결과
(어떤 수치적/질적 결과를 기대하는지 작성하세요)

## 관련 키워드
(논문 검색에 활용할 키워드를 쉼표로 구분하여 입력하세요)
"""


def parse(text: str) -> dict:
    """Parse a structured Markdown research note into a context dict.

    Returns a dict with keys: topic, background, hypothesis,
    research_questions, constraints, expected_outcome, keywords.
    Only keys whose sections are present and non-empty are included.
    """
    result: dict = {}

    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)
    for section in sections[1:]:
        lines = section.split("\n")
        header = lines[0].strip()
        content = "\n".join(lines[1:]).strip()

        if not content:
            continue

        for pattern, key in SECTION_KEYS.items():
            if pattern in header:
                # Skip unfilled template placeholders
                if content.startswith("(") and content.endswith(")"):
                    break
                result[key] = content
                break

    # Fallback: derive topic from first H1 or first non-blank line
    if "topic" not in result:
        for line in text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line and line not in ("연구 노트",):
                result["topic"] = line
                break

    return result


def extract_topic(text: str) -> str:
    """Return just the topic string for pipeline use."""
    return parse(text).get("topic", text.strip().splitlines()[0])


def to_context_extras(parsed: dict) -> dict:
    """Return the non-topic fields as a flat dict for context injection."""
    return {k: v for k, v in parsed.items() if k != "topic"}
