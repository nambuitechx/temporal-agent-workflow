"""Temporal Activities — mọi phần "non-deterministic" (gọi LLM, đọc fake tool
data) đều nằm ở đây, tách biệt hoàn toàn khỏi Workflow code (xem nguyên tắc
mục 1 của ../agent-workflow/Dynamic Agent Loop Orchestration.md).
"""
from __future__ import annotations

import json
import os
import re

from temporalio import activity
from temporalio.exceptions import ApplicationError

from .agents.log_agent_prompt import LOG_AGENT_SYSTEM_PROMPT
from .agents.metrics_agent_prompt import METRICS_AGENT_SYSTEM_PROMPT
from .agents.orchestrator_prompt import ORCHESTRATOR_SYSTEM_PROMPT
from .models import ALLOWED_AGENTS, ALLOWED_ACTIONS
from .tools.incident_logs import get_incident_logs
from .tools.incident_metrics import get_incident_metrics

# Model host qua AWS Bedrock — gọi TRỰC TIẾP bằng AWS SDK (boto3), KHÔNG qua
# SDK `anthropic`/`AnthropicBedrock` (KHÔNG phải Bedrock AgentCore — đây chỉ
# là model provider, tương đương "Model Gateway" rút gọn, xem mục 1/5 của POC
# design). Dùng Bedrock Runtime "Converse API" — interface thống nhất cho mọi
# model trên Bedrock (không riêng Anthropic), tách biệt hoàn toàn khỏi format
# request/response của Anthropic Messages API.
#
# Model ID mặc định = Claude 3.5 Sonnet. Chỉnh BEDROCK_MODEL_ID nếu account/
# region của bạn cần "Cross-region inference profile" (tiền tố vùng, vd
# "us.anthropic.claude-3-5-sonnet-20241022-v2:0") — lấy đúng ID từ `aws
# bedrock list-foundation-models` hoặc AWS Console → Bedrock → Model access.
MODEL = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
MAX_TOKENS = 1024

_client = None  # lazy-init, client không nên tạo ở import-time


def _bedrock():
    """Trả về boto3 `bedrock-runtime` client — xác thực qua AWS credential
    chain chuẩn (env vars / ~/.aws/credentials mount từ host / instance
    profile), KHÔNG dùng ANTHROPIC_API_KEY. Xem docker-compose.yml (mount
    ~/.aws) và README.md để biết cách set up AWS profile cho POC."""
    global _client
    if _client is None:
        import boto3  # import trễ để activities.py import nhanh trong test

        session = boto3.Session(
            profile_name=os.environ.get("AWS_PROFILE"),  # None → boto3 dùng profile mặc định
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        _client = session.client("bedrock-runtime")
    return _client


# --------------------------------------------------------------------------
# ask_orchestrator
# --------------------------------------------------------------------------


@activity.defn
async def ask_orchestrator(incident_description: str, scenario_id: str, history: list[dict]) -> dict:
    """Gọi LLM đóng vai Orchestrator — quyết định bước tiếp theo dựa trên history.

    Trả về JSON đã được validate theo allowlist (ALLOWED_ACTIONS/ALLOWED_AGENTS).
    Nếu decision vi phạm allowlist, activity raise ApplicationError
    (non_retryable) — Workflow phải bắt lỗi này và escalate ngay, KHÔNG BAO
    GIỜ được execute action nằm ngoài allowlist (Scenario E).
    """
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
    else:
        decision = await _call_orchestrator_llm(incident_description, history)

    _validate_decision(decision)
    return decision


def _already_has_human_turn(history: list[dict]) -> bool:
    return any(h.get("role") == "human" for h in history)


def _validate_decision(decision: dict) -> None:
    action = decision.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ApplicationError(
            f"Orchestrator trả về action ngoài allowlist: {action!r}",
            type="GuardrailViolation",
            non_retryable=True,
        )
    if action == "CALL_AGENT":
        agent_name = decision.get("agent_name")
        if agent_name not in ALLOWED_AGENTS:
            raise ApplicationError(
                f"Orchestrator trả về agent_name ngoài allowlist: {agent_name!r}",
                type="GuardrailViolation",
                non_retryable=True,
            )


async def _call_orchestrator_llm(incident_description: str, history: list[dict]) -> dict:
    messages = _history_to_messages(incident_description, history)
    response = _bedrock().converse(
        modelId=MODEL,
        system=[{"text": ORCHESTRATOR_SYSTEM_PROMPT}],
        messages=messages,
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    return _parse_json_response(response)


# --------------------------------------------------------------------------
# run_agent
# --------------------------------------------------------------------------


@activity.defn
async def run_agent(agent_name: str, args: dict, scenario_id: str) -> dict:
    """Chạy 1 Specialized Agent cụ thể (log_agent | metrics_agent).

    Guardrail thứ 2 (defense-in-depth): dù ask_orchestrator đã validate,
    run_agent tự kiểm tra lại agent_name trước khi thực thi — Workflow không
    bao giờ nên "tin" hoàn toàn 1 lớp validate duy nhất.
    """
    if agent_name not in ALLOWED_AGENTS:
        raise ApplicationError(
            f"run_agent nhận agent_name ngoài allowlist: {agent_name!r}",
            type="GuardrailViolation",
            non_retryable=True,
        )

    if agent_name == "log_agent":
        system_prompt = LOG_AGENT_SYSTEM_PROMPT
        raw_data = get_incident_logs(scenario_id)
    else:
        system_prompt = METRICS_AGENT_SYSTEM_PROMPT
        raw_data = get_incident_metrics(scenario_id)

    user_content = (
        f"Yêu cầu điều tra (args từ Orchestrator): {json.dumps(args, ensure_ascii=False)}\n\n"
        f"Dữ liệu thô đã thu thập được:\n{json.dumps(raw_data, ensure_ascii=False, indent=2)}"
    )
    response = _bedrock().converse(
        modelId=MODEL,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_content}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    result = _parse_json_response(response)
    result.setdefault("agent_name", agent_name)
    result.setdefault("evidence", [])
    return result


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


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_ROLE_MAP = {"user": "user", "orchestrator": "assistant", "tool": "user", "human": "user"}


def _history_to_messages(incident_description: str, history: list[dict]) -> list[dict]:
    """Chuyển self.history (list role/content) của Workflow thành messages[] hợp
    lệ cho Bedrock Converse API (`{"role": ..., "content": [{"text": ...}]}`)
    — gộp các entry liên tiếp cùng role vì Converse chỉ chấp nhận 2 role
    "user"/"assistant" xen kẽ, không có role "system" trong messages[]."""
    texts: list[tuple[str, str]] = []
    for h in history:
        role = _ROLE_MAP.get(h.get("role"), "user")
        content = h.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if texts and texts[-1][0] == role:
            texts[-1] = (role, texts[-1][1] + "\n\n" + text)
        else:
            texts.append((role, text))

    if not texts:
        texts.append(("user", incident_description))
    return [{"role": role, "content": [{"text": text}]} for role, text in texts]


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_response(response: dict) -> dict:
    blocks = response["output"]["message"]["content"]
    text = "".join(block["text"] for block in blocks if "text" in block).strip()
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise ApplicationError(
            f"Không parse được JSON từ response của model: {text[:500]!r}",
            type="ModelOutputParseError",
            non_retryable=True,
        )
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ApplicationError(
            f"JSON không hợp lệ từ model: {exc}",
            type="ModelOutputParseError",
            non_retryable=True,
        ) from exc
