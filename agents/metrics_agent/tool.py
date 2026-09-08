"""`metrics_agent` — Specialized Agent đọc metrics liên quan tới 1 case.
Xem `agents/log_agent/tool.py` để biết lý do thiết kế chữ ký `run()`."""
from __future__ import annotations

import json
from pathlib import Path

from agents._common.llm import call_llm_json

PROMPT_PATH = Path(__file__).resolve().parent / "prompt.md"
DATA_DIR = Path(__file__).resolve().parents[2] / "shared" / "data" / "scenarios"


def _get_incident_metrics(scenario_id: str) -> dict:
    path = DATA_DIR / scenario_id / "metrics.json"
    if not path.exists():
        return {
            "service": "unknown",
            "time_range": "unknown",
            "series": [],
            "note": f"Không có fake metrics cho scenario_id={scenario_id!r}",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def run(args: dict, case_context: dict) -> dict:
    scenario_id = case_context.get("scenario_id", "unknown")
    raw_data = _get_incident_metrics(scenario_id)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    user_content = (
        f"Yêu cầu điều tra (args từ Orchestrator): {json.dumps(args, ensure_ascii=False)}\n\n"
        f"Dữ liệu thô đã thu thập được:\n{json.dumps(raw_data, ensure_ascii=False, indent=2)}"
    )
    result = call_llm_json(prompt, [{"role": "user", "content": [{"text": user_content}]}])
    result.setdefault("agent_name", "metrics_agent")
    result.setdefault("evidence", [])
    return result
