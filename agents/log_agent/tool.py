"""`log_agent` — Specialized Agent đọc log ứng dụng liên quan tới 1 case.

Chữ ký `run(args, case_context) -> dict` là "hình dạng" `local_tool_ref` mà
`shared/db/registry.py` mong đợi (xem mục 0.1 của design doc) — khi
`agentcore_agents.agentcore_agent_arn` có giá trị, Activity gọi thẳng
AgentCore Runtime thay vì import module này; `run()` ở đây chỉ là bản mô
phỏng cục bộ.
"""
from __future__ import annotations

import json
from pathlib import Path

from agents._common.llm import call_llm_json

PROMPT_PATH = Path(__file__).resolve().parent / "prompt.md"
# shared/data/scenarios/* là fake data mô phỏng "Evidence access" (Tool plane
# thật) — cố tình VẪN nằm trong shared/, không move vào agents/ (mục 8 bước 1
# của design doc chỉ move *tool code*, không move fixture data).
DATA_DIR = Path(__file__).resolve().parents[2] / "shared" / "data" / "scenarios"


def _get_incident_logs(scenario_id: str) -> dict:
    path = DATA_DIR / scenario_id / "logs.json"
    if not path.exists():
        return {
            "service": "unknown",
            "time_range": "unknown",
            "entries": [],
            "note": f"Không có fake logs cho scenario_id={scenario_id!r}",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def run(args: dict, case_context: dict) -> dict:
    scenario_id = case_context.get("scenario_id", "unknown")
    raw_data = _get_incident_logs(scenario_id)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    user_content = (
        f"Yêu cầu điều tra (args từ Orchestrator): {json.dumps(args, ensure_ascii=False)}\n\n"
        f"Dữ liệu thô đã thu thập được:\n{json.dumps(raw_data, ensure_ascii=False, indent=2)}"
    )
    result = call_llm_json(prompt, [{"role": "user", "content": [{"text": user_content}]}])
    result.setdefault("agent_name", "log_agent")
    result.setdefault("evidence", [])
    return result
