"""Temporal Activities — generic, dùng chung cho mọi usecase (mục 5 của
`docs/2026-09-08-generic-agent-loop-design.md`).

Mọi phần "non-deterministic" (query Postgres, gọi LLM/AgentCore) nằm ở đây,
tách biệt hoàn toàn khỏi Workflow code. Activity KHÔNG còn tự cầm system
prompt/tool function — nó tra `shared/db/registry.py` theo
`usecase_version_id` để biết gọi agent nào, bằng cách nào (`local_tool_ref`
mô phỏng, hoặc `agentcore_agent_arn` khi AgentCore integration xong — mục 0).
"""
from __future__ import annotations

import importlib
import json
import uuid

from temporalio import activity
from temporalio.exceptions import ApplicationError

from .db.registry import RegistryError, ResolvedAgent, get_agent, get_orchestrator, get_usecase_limits as _get_usecase_limits, list_allowed_agents
from .models import ALLOWED_ACTIONS

# --------------------------------------------------------------------------
# Invoke agent theo ResolvedAgent — đích cuối là AgentCore Runtime (mục 0),
# hiện tại chỉ có nhánh local_tool_ref (mô phỏng cục bộ) được implement.
# --------------------------------------------------------------------------


def _invoke_local_tool(local_tool_ref: str, args: dict, case_context: dict) -> dict:
    module_name, _, func_name = local_tool_ref.partition(":")
    if not module_name or not func_name:
        raise ApplicationError(
            f"local_tool_ref không đúng format 'module:function': {local_tool_ref!r}",
            type="RegistryError",
            non_retryable=True,
        )
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    return func(args, case_context)


def _invoke_agent(resolved: ResolvedAgent, args: dict, case_context: dict) -> dict:
    if resolved.agentcore_agent_arn:
        # Đích cuối (mục 0 design doc) — chưa implement, phụ thuộc protocol
        # AgentCore Runtime chưa xác nhận (xem mục 10 "việc chưa chốt").
        raise ApplicationError(
            f"Gọi AgentCore Runtime thật (ARN={resolved.agentcore_agent_arn!r}) chưa được implement",
            type="NotImplemented",
            non_retryable=True,
        )
    if not resolved.local_tool_ref:
        raise ApplicationError(
            f"Agent {resolved.agent_name!r} không có cả agentcore_agent_arn lẫn local_tool_ref",
            type="RegistryError",
            non_retryable=True,
        )
    return _invoke_local_tool(resolved.local_tool_ref, args, case_context)


# --------------------------------------------------------------------------
# ask_orchestrator
# --------------------------------------------------------------------------


@activity.defn
async def ask_orchestrator(
    usecase_version_id: str, description: str, case_context: dict, history: list[dict]
) -> dict:
    """Tra registry lấy orchestrator của `usecase_version_id` này, gọi nó,
    validate quyết định trả về theo allowlist (ALLOWED_ACTIONS platform-wide +
    allowed_agents theo DB — mục 5). Vi phạm allowlist -> raise
    ApplicationError non_retryable, Workflow phải escalate ngay, KHÔNG BAO GIỜ
    được execute action nằm ngoài allowlist (Scenario E)."""
    scenario_id = case_context.get("scenario_id")
    if scenario_id == "scenario_e_allowlist_violation" and not _already_has_human_turn(history):
        # Test hook có chủ đích: mô phỏng 1 lần LLM trả decision sai allowlist,
        # KHÔNG gọi model thật — để bài test guardrail deterministic, không phụ
        # thuộc việc "prompt injection" có ăn hay không trên 1 model cụ thể.
        decision = {
            "action": "CALL_AGENT",
            "agent_name": "shell_agent",
            "args": {"cmd": "rm -rf /"},
            "reason": "(simulated bad LLM output — dùng để test guardrail, xem Scenario E)",
        }
        allowed_agents: set[str] = set()
    else:
        try:
            usecase_version_uuid = uuid.UUID(usecase_version_id)
            orchestrator = await get_orchestrator(usecase_version_uuid)
            allowed_agents = await list_allowed_agents(usecase_version_uuid)
        except RegistryError as exc:
            raise ApplicationError(str(exc), type="RegistryError", non_retryable=True) from exc

        orchestrator_context = {**case_context, "description": description, "allowed_agents": sorted(allowed_agents)}
        decision = _invoke_agent(orchestrator, {"history": history}, orchestrator_context)

    _validate_decision(decision, allowed_agents)
    return decision


def _already_has_human_turn(history: list[dict]) -> bool:
    return any(h.get("role") == "human" for h in history)


def _validate_decision(decision: dict, allowed_agents: set[str]) -> None:
    action = decision.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ApplicationError(
            f"Orchestrator trả về action ngoài allowlist: {action!r}",
            type="GuardrailViolation",
            non_retryable=True,
        )
    if action == "CALL_AGENT":
        agent_name = decision.get("agent_name")
        if agent_name not in allowed_agents:
            raise ApplicationError(
                f"Orchestrator trả về agent_name ngoài allowlist: {agent_name!r}",
                type="GuardrailViolation",
                non_retryable=True,
            )


# --------------------------------------------------------------------------
# run_agent
# --------------------------------------------------------------------------


@activity.defn
async def run_agent(usecase_version_id: str, agent_name: str, args: dict, case_context: dict) -> dict:
    """Chạy 1 Specialized Agent cụ thể theo tên logic (`agent_name`, dạng
    `{usecase_key}__{agent_key}`, mục 4 design doc).

    Guardrail thứ 2 (defense-in-depth): dù ask_orchestrator đã validate,
    run_agent tự tra lại `list_allowed_agents` độc lập trước khi thực thi —
    Workflow không bao giờ nên "tin" hoàn toàn 1 lớp validate duy nhất.
    """
    try:
        usecase_version_uuid = uuid.UUID(usecase_version_id)
        allowed_agents = await list_allowed_agents(usecase_version_uuid)
        if agent_name not in allowed_agents:
            raise ApplicationError(
                f"run_agent nhận agent_name ngoài allowlist: {agent_name!r}",
                type="GuardrailViolation",
                non_retryable=True,
            )
        resolved = await get_agent(usecase_version_uuid, agent_name)
    except RegistryError as exc:
        raise ApplicationError(str(exc), type="RegistryError", non_retryable=True) from exc

    if resolved is None:
        raise ApplicationError(
            f"run_agent không tra được agent_name={agent_name!r} trong registry",
            type="RegistryError",
            non_retryable=True,
        )

    result = _invoke_agent(resolved, args, case_context)
    result.setdefault("agent_name", agent_name)
    result.setdefault("evidence", [])
    return result


# --------------------------------------------------------------------------
# get_usecase_limits — defense-in-depth cho circuit breaker (mục 3 design doc)
# --------------------------------------------------------------------------


@activity.defn
async def get_usecase_limits(usecase_version_id: str) -> dict:
    try:
        limits = await _get_usecase_limits(uuid.UUID(usecase_version_id))
    except RegistryError as exc:
        raise ApplicationError(str(exc), type="RegistryError", non_retryable=True) from exc
    return {"default_max_iterations": limits.default_max_iterations, "max_iterations_cap": limits.max_iterations_cap}


# --------------------------------------------------------------------------
# notify_human
# --------------------------------------------------------------------------


@activity.defn
async def notify_human(payload: dict) -> str:
    """Giả lập gửi thông báo cho analyst (POC: chỉ log ra console/Worker log).

    Trong Xora Resolve thật đây sẽ là 1 lời gọi ra ngoài (Slack/email/ChatOps).
    """
    activity.logger.info("[HITL] Cần con người xử lý: %s", json.dumps(payload, ensure_ascii=False))
    return "notified"
