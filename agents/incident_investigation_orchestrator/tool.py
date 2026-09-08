"""`incident_investigation_orchestrator` — Orchestrator Agent của usecase
`incident_investigation`. Vẫn là 1 "agent" bình thường theo mục 0.1 của design
doc (chữ ký `run(args, case_context) -> dict` giống mọi agent khác) — điểm
khác biệt duy nhất là input/output của nó là *quyết định điều phối*
(`CALL_AGENT`/`NEEDS_HUMAN`), không phải evidence.

Validate quyết định trả về theo `ALLOWED_ACTIONS`/`allowed_agents` là việc
của `shared/activities.ask_orchestrator` (guardrail, mục 5 design doc) —
KHÔNG làm ở đây, để giữ đúng ranh giới "agent code không tự validate guardrail
platform-wide".
"""
from __future__ import annotations

from pathlib import Path

from agents._common.llm import call_llm_json, history_to_messages

PROMPT_PATH = Path(__file__).resolve().parent / "prompt.md"


def run(args: dict, case_context: dict) -> dict:
    history = args.get("history", [])
    description = case_context.get("description", "")
    allowed_agents: list[str] = case_context.get("allowed_agents", [])

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    if allowed_agents:
        prompt += "\n\nDanh sách agent_name hợp lệ cho usecase này: " + ", ".join(
            f'"{name}"' for name in allowed_agents
        )

    messages = history_to_messages(description, history)
    return call_llm_json(prompt, messages)
