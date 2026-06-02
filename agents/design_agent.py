import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent
from verifier.recursive_verifier import RecursiveVerifier
from shared.prompts import DESIGN


class DesignAgent(BaseAgent):
    def run(self, context: dict) -> dict:
        topic = context.get("topic", "")
        literature = context.get("literature", {})
        note = context.get("note", {})

        gap = literature.get("research_gap", "")
        direction = literature.get("recommended_direction", "")
        papers_summary = json.dumps(literature.get("papers", [])[:5], ensure_ascii=False)

        note_context = ""
        if note.get("hypothesis"):
            note_context += f"\n\n연구자 가설: {note['hypothesis']}"
        if note.get("expected_outcome"):
            note_context += f"\n\n기대 결과: {note['expected_outcome']}"
        if note.get("constraints"):
            note_context += f"\n\n제약 사항: {note['constraints']}"

        messages = [
            {"role": "system", "content": DESIGN},
            {
                "role": "user",
                "content": (
                    f"연구 주제: {topic}\n\n"
                    f"연구 공백: {gap}\n\n"
                    f"추천 방향: {direction}{note_context}\n\n"
                    f"관련 논문 요약:\n{papers_summary}\n\n"
                    "새로운 알고리즘 아이디어와 핵심 혁신 포인트를 상세히 설명하세요."
                ),
            },
        ]
        idea = self.client.chat(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=3000,
            caller="design_agent_idea",
        )

        verifier = RecursiveVerifier()
        verification = asyncio.run(
            verifier.verify_with_human_fallback(
                claim=idea,
                context=f"연구 주제: {topic}\n연구 공백: {gap}",
                caller="design_agent",
                pipeline_context=context,
            )
        )

        final_idea = verification["final_claim"]
        pseudo_messages = [
            {"role": "system", "content": DESIGN},
            {
                "role": "user",
                "content": (
                    f"다음 검증된 알고리즘 아이디어를 Pseudocode로 구체화하세요.\n"
                    f"입력/출력, 시간/공간 복잡도, 핵심 연산을 명시하세요.\n\n{final_idea}"
                ),
            },
        ]
        pseudocode = self.client.chat(
            model=self.model,
            messages=pseudo_messages,
            temperature=0.3,
            max_tokens=3000,
            caller="design_agent_pseudo",
        )

        return {
            "idea": idea,
            "verification": verification,
            "pseudocode": pseudocode,
            "passed_verification": verification["passed"],
            "verification_rounds": len(verification["rounds"]),
        }
