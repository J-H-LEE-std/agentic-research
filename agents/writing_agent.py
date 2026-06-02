import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent
from shared.prompts import WRITING

class WritingAgent(BaseAgent):
    def run(self, context: dict) -> dict:
        papers_path = os.path.abspath(os.environ.get("PAPERS_OUTPUT_PATH", "./workspace/default/papers"))
        topic = context.get("topic", "")
        literature = context.get("literature", {})
        design = context.get("design", {})
        implement = context.get("implement", {})
        analysis = context.get("analysis", {})

        ko_draft = self._write_korean_draft(topic, literature, design, implement, analysis)
        en_draft = self._translate_to_english(ko_draft)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(papers_path, exist_ok=True)

        ko_path = os.path.join(papers_path, f"paper_ko_{timestamp}.md")
        en_path = os.path.join(papers_path, f"paper_en_{timestamp}.md")

        with open(ko_path, "w", encoding="utf-8") as f:
            f.write(ko_draft)
        with open(en_path, "w", encoding="utf-8") as f:
            f.write(en_draft)

        return {
            "korean_draft_path": ko_path,
            "english_draft_path": en_path,
            "korean_draft": ko_draft,
            "english_draft": en_draft,
        }

    def _write_korean_draft(self, topic, literature, design, implement, analysis) -> str:
        papers = literature.get("papers", [])
        gap = literature.get("research_gap", "")
        idea = design.get("idea", "")
        pseudocode = design.get("pseudocode", "")
        analysis_text = analysis.get("analysis_text", "")
        graph_path = analysis.get("graph_path", "")

        related_works = "\n".join(
            [f"- **{p.get('title', '')}**: {p.get('contribution', p.get('abstract', ''))[:150]}"
             for p in papers[:8] if p.get("title")]
        )

        messages = [
            {"role": "system", "content": WRITING},
            {
                "role": "user",
                "content": (
                    f"**연구 주제:** {topic}\n\n"
                    f"**연구 공백:** {gap}\n\n"
                    f"**핵심 아이디어:**\n{idea[:1000]}\n\n"
                    f"**알고리즘 (Pseudocode):**\n{pseudocode[:1000]}\n\n"
                    f"**실험 결과 분석:**\n{analysis_text[:1000]}\n\n"
                    f"**관련 연구:**\n{related_works}\n\n"
                    "위 내용을 바탕으로 한국어 논문 초안을 작성하세요.\n"
                    "구조: # Abstract → # 1. Introduction → # 2. Related Work → "
                    "# 3. Method → # 4. Experiments → # 5. Conclusion → # References"
                ),
            },
        ]
        return self.client.chat(
            model=self.model,
            messages=messages,
            temperature=0.4,
            max_tokens=6000,
            caller="writing_agent_korean",
        )

    def _translate_to_english(self, korean_draft: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional academic translator specializing in AI and machine learning research. "
                    "Translate the following Korean academic paper into fluent, publication-quality English. "
                    "Preserve all technical terms, Markdown formatting, section structure, and mathematical notation."
                ),
            },
            {
                "role": "user",
                "content": f"Translate this Korean academic paper to English:\n\n{korean_draft}",
            },
        ]
        return self.client.chat(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=6000,
            caller="writing_agent_english",
        )
