import sys
import os
import json
import asyncio
import subprocess
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent
from verifier.recursive_verifier import RecursiveVerifier
from shared.prompts import ANALYSIS

class AnalysisAgent(BaseAgent):
    def run(self, context: dict) -> dict:
        topic = context.get("topic", "")
        implement = context.get("implement", {})
        log_path = implement.get("log_path", "")
        exec_result = implement.get("exec_result", {})

        experiment_data = self._load_experiment_data(log_path, exec_result)
        note = context.get("note", {})
        analysis_text = self._analyze_results(topic, experiment_data, note)

        verifier = RecursiveVerifier()
        verification = asyncio.run(
            verifier.verify_with_human_fallback(
                claim=analysis_text,
                context=f"연구 주제: {topic}\n실험 데이터: {json.dumps(experiment_data, ensure_ascii=False)[:500]}",
                caller="analysis_agent",
                pipeline_context=context,
            )
        )

        graph_path = self._generate_graphs(topic, experiment_data, exec_result)

        return {
            "analysis_text": verification["final_claim"],
            "graph_path": graph_path,
            "verification": verification,
            "experiment_summary": experiment_data,
        }

    def _load_experiment_data(self, log_path: str, exec_result: dict) -> dict:
        data = {"exec_result": exec_result, "parsed_output": {}}
        if log_path and os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    data["log"] = json.load(f)
            except Exception:
                pass

        stdout = exec_result.get("stdout", "")
        if stdout:
            try:
                start = stdout.find("{")
                end = stdout.rfind("}") + 1
                if start >= 0 and end > start:
                    data["parsed_output"] = json.loads(stdout[start:end])
            except (json.JSONDecodeError, ValueError):
                data["stdout_raw"] = stdout

        return data

    def _analyze_results(self, topic: str, experiment_data: dict, note: dict = None) -> str:
        data_str = json.dumps(experiment_data, ensure_ascii=False, indent=2)
        note_context = ""
        if note and note.get("hypothesis"):
            note_context += f"\n연구 가설: {note['hypothesis']}"
        if note and note.get("expected_outcome"):
            note_context += f"\n기대 결과: {note['expected_outcome']}"
        messages = [
            {"role": "system", "content": ANALYSIS},
            {
                "role": "user",
                "content": (
                    f"연구 주제: {topic}{note_context}\n\n"
                    f"실험 데이터:\n{data_str[:3000]}\n\n"
                    "다음 항목을 분석하세요:\n"
                    "1. 핵심 성능 지표 및 수치 결과\n"
                    "2. 기존 방법 대비 개선 효과 (정량적)\n"
                    "3. 통계적 유의성 평가\n"
                    "4. 결과의 한계점 및 신뢰도\n"
                    "5. 연구 기여도 종합 평가"
                ),
            },
        ]
        return self.client.chat(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=3000,
            caller="analysis_agent_analyze",
        )

    def _generate_graphs(self, topic: str, experiment_data: dict, exec_result: dict) -> str:
        graphs_path = os.path.abspath(os.environ.get("GRAPHS_OUTPUT_PATH", "./workspace/default/graphs"))
        os.makedirs(graphs_path, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        graph_path = os.path.join(graphs_path, f"results_{timestamp}.png")

        plot_code = f"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import json

output_path = {repr(graph_path)}
data = {repr(experiment_data)}

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle({repr(f'Research Results: {topic[:50]}')}, fontsize=12)

parsed = data.get('parsed_output', {{}})
if parsed and isinstance(parsed, dict):
    keys = list(parsed.keys())[:6]
    vals = []
    for k in keys:
        v = parsed[k]
        if isinstance(v, (int, float)):
            vals.append(v)
        elif isinstance(v, list) and v and isinstance(v[0], (int, float)):
            vals.append(float(np.mean(v)))
        else:
            vals.append(0)
    if keys and vals:
        axes[0].bar(range(len(keys)), vals, color='steelblue')
        axes[0].set_xticks(range(len(keys)))
        axes[0].set_xticklabels(keys, rotation=45, ha='right', fontsize=8)
        axes[0].set_title('Experiment Metrics')
        axes[0].set_ylabel('Value')
else:
    axes[0].text(0.5, 0.5, 'No structured data\\navailable', ha='center', va='center', transform=axes[0].transAxes)
    axes[0].set_title('Experiment Metrics')

stdout = data.get('exec_result', {{}}).get('stdout', '')
lines = [l for l in stdout.split('\\n') if l.strip()]
axes[1].axis('off')
display_text = '\\n'.join(lines[:20]) if lines else 'No output captured'
axes[1].text(0.05, 0.95, display_text, va='top', ha='left', transform=axes[1].transAxes,
             fontsize=7, family='monospace', wrap=True)
axes[1].set_title('Experiment Output')

plt.tight_layout()
plt.savefig(output_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Graph saved to {{output_path}}")
"""
        try:
            proc = subprocess.run(
                [sys.executable, "-c", plot_code],
                capture_output=True, text=True, timeout=30
            )
            return graph_path if proc.returncode == 0 else f"Graph generation failed: {proc.stderr[:200]}"
        except Exception as e:
            return f"Graph generation error: {str(e)}"
