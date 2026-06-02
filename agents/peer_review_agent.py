"""
Peer Review Agent: 복수의 모델이 각자 다른 관점으로 연구를 평가한다.
사용 모델 및 관점은 config.yaml의 peer_review.reviewers 참조.
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent
from shared.models import get_peer_review_models
from shared.openrouter_client import OpenRouterClient



class PeerReviewAgent:
    def __init__(self):
        self.client = OpenRouterClient()
        self.reviewers = get_peer_review_models()

    def run(self, context: dict) -> dict:
        topic = context.get("topic", "")
        writing = context.get("writing", {})
        analysis = context.get("analysis", {})
        design = context.get("design", {})
        literature = context.get("literature", {})

        research_summary = self._build_research_summary(
            topic, literature, design, analysis, writing
        )

        reviews = []
        for reviewer in self.reviewers:
            print(f"  → [{reviewer['perspective_kr']}] 검토 중... ({reviewer['model']})")
            review = self._run_single_review(reviewer, research_summary, topic)
            reviews.append(review)

        aggregate = self._aggregate_reviews(reviews, topic)
        report_path = self._save_report(reviews, aggregate, topic)

        return {
            "reviews": reviews,
            "aggregate": aggregate,
            "report_path": report_path,
        }

    def _build_research_summary(
        self, topic, literature, design, analysis, writing
    ) -> str:
        gap = literature.get("research_gap", "")
        idea = design.get("idea", "")[:800]
        pseudocode = design.get("pseudocode", "")[:600]
        analysis_text = analysis.get("analysis_text", "")[:800]
        en_draft = writing.get("english_draft", "")[:2000]
        passed_verification = design.get("passed_verification", False)
        verification_rounds = design.get("verification_rounds", 0)

        return (
            f"# Research Summary\n\n"
            f"**Topic:** {topic}\n\n"
            f"**Research Gap:**\n{gap}\n\n"
            f"**Core Idea:**\n{idea}\n\n"
            f"**Algorithm (Pseudocode):**\n{pseudocode}\n\n"
            f"**Experimental Analysis:**\n{analysis_text}\n\n"
            f"**Internal Verification:** {'Passed' if passed_verification else 'Not passed'} "
            f"({verification_rounds} rounds)\n\n"
            f"**Paper Draft (excerpt):**\n{en_draft}"
        )

    def _run_single_review(self, reviewer: dict, research_summary: str, topic: str) -> dict:
        messages = [
            {"role": "system", "content": reviewer["system_prompt"]},
            {
                "role": "user",
                "content": (
                    f"다음 연구를 '{reviewer['perspective_kr']}' 관점에서 평가하세요.\n\n"
                    f"{research_summary}\n\n"
                    "반드시 JSON 형식으로만 출력하세요."
                ),
            },
        ]

        response = self.client.chat(
            model=reviewer["model"],
            messages=messages,
            temperature=0.4,
            max_tokens=2048,
            caller=f"peer_review_{reviewer['perspective']}",
        )

        # JSON 파싱
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            parsed = json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            parsed = {"raw_response": response, "score": None, "verdict": "Parse Error"}

        return {
            "reviewer_name": reviewer["reviewer_name"],
            "perspective": reviewer["perspective"],
            "perspective_kr": reviewer["perspective_kr"],
            "model": reviewer["model"],
            "result": parsed,
        }

    def _aggregate_reviews(self, reviews: list, topic: str) -> dict:
        scores = []
        verdicts = []
        all_strengths = []
        all_weaknesses = []
        all_required_changes = []

        verdict_weight = {
            "Accept": 4,
            "Minor Revision": 3,
            "Major Revision": 2,
            "Borderline": 2,
            "Reject": 1,
            "Parse Error": 0,
        }

        for r in reviews:
            result = r.get("result", {})
            score = result.get("score")
            if isinstance(score, (int, float)):
                scores.append(float(score))
            verdict = result.get("verdict", "")
            if verdict:
                verdicts.append(verdict)
            all_strengths.extend(result.get("strengths", []))
            all_weaknesses.extend(result.get("weaknesses", []))
            all_required_changes.extend(result.get("required_changes", []))

        avg_score = round(sum(scores) / len(scores), 2) if scores else None

        # 가중 다수결로 최종 판정
        verdict_counts: dict = {}
        for v in verdicts:
            for key in verdict_weight:
                if key.lower() in v.lower():
                    verdict_counts[key] = verdict_counts.get(key, 0) + 1
                    break

        if verdict_counts:
            final_verdict = max(verdict_counts, key=lambda k: (verdict_counts[k], verdict_weight.get(k, 0)))
        else:
            final_verdict = "Undetermined"

        return {
            "average_score": avg_score,
            "final_verdict": final_verdict,
            "verdict_breakdown": verdict_counts,
            "common_strengths": list(dict.fromkeys(all_strengths))[:5],
            "common_weaknesses": list(dict.fromkeys(all_weaknesses))[:5],
            "required_changes": list(dict.fromkeys(all_required_changes))[:5],
        }

    def _save_report(self, reviews: list, aggregate: dict, topic: str) -> str:
        papers_path = os.path.abspath(os.environ.get("PAPERS_OUTPUT_PATH", "./workspace/default/papers"))
        os.makedirs(papers_path, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(papers_path, f"peer_review_{timestamp}.md")

        lines = [
            f"# Peer Review Report",
            f"",
            f"**Topic:** {topic}",
            f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}",
            f"",
            f"## Aggregate Result",
            f"",
            f"| 항목 | 결과 |",
            f"|---|---|",
            f"| 평균 점수 | {aggregate.get('average_score', 'N/A')} / 10 |",
            f"| 최종 판정 | **{aggregate.get('final_verdict', 'N/A')}** |",
            f"",
            f"### 공통 강점",
        ]
        for s in aggregate.get("common_strengths", []):
            lines.append(f"- {s}")

        lines += ["", "### 공통 약점"]
        for w in aggregate.get("common_weaknesses", []):
            lines.append(f"- {w}")

        lines += ["", "### 필수 수정 사항"]
        for c in aggregate.get("required_changes", []):
            lines.append(f"- {c}")

        lines += ["", "---", "", "## 개별 리뷰"]
        for r in reviews:
            result = r.get("result", {})
            lines += [
                f"",
                f"### {r['perspective_kr']} — {r['reviewer_name']}",
                f"*Model: `{r['model']}`*",
                f"",
                f"- **점수:** {result.get('score', 'N/A')} / 10",
                f"- **판정:** {result.get('verdict', 'N/A')}",
                f"- **요약:** {result.get('summary', '')}",
                f"",
                f"**강점:**",
            ]
            for s in result.get("strengths", []):
                lines.append(f"- {s}")
            lines.append("")
            lines.append("**약점:**")
            for w in result.get("weaknesses", []):
                lines.append(f"- {w}")
            lines.append("")
            lines.append("**필수 수정:**")
            for c in result.get("required_changes", []):
                lines.append(f"- {c}")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return report_path
