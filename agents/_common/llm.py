"""Helper gọi AWS Bedrock Converse API — dùng chung bởi mọi `agents/*/tool.py`.

Đây là phần "stand-in" cho việc AgentCore Runtime suy luận/gọi tool thật (xem
mục 0/0.1 của `docs/2026-09-08-generic-agent-loop-design.md`). Đặt trong
`agents/_common/`, KHÔNG trong `shared/` — `agents/` phải tự đứng độc lập để
lift-and-shift nguyên khối sang đóng gói AgentCore sau này mà không kéo theo
code của Temporal runtime (`shared/`/`worker/`/`backend/`).

Khi chuyển sang gọi AgentCore Runtime thật, mọi `agents/*/tool.py` không còn
gọi hàm này nữa — `shared/activities.py` sẽ gọi thẳng AgentCore bằng ARN thay
vì import `local_tool_ref` (xem mục 0 của design doc).
"""
from __future__ import annotations

import json
import os
import re

MODEL = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
MAX_TOKENS = 1024

_client = None  # lazy-init, client không nên tạo ở import-time


def _bedrock():
    global _client
    if _client is None:
        import boto3  # import trễ để module import nhanh trong test

        session = boto3.Session(
            profile_name=os.environ.get("AWS_PROFILE"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        _client = session.client("bedrock-runtime")
    return _client


class LLMOutputError(Exception):
    """Model trả về output không parse được thành JSON — caller (tool.py) tự
    quyết định cách xử lý (thường là để lỗi nổi lên cho Activity)."""


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def call_llm_json(system_prompt: str, messages: list[dict]) -> dict:
    """Gọi Bedrock Converse API với 1 system prompt + messages[], parse JSON
    object đầu tiên tìm thấy trong response text. `messages` đã đúng format
    Converse API (`[{"role": "user"|"assistant", "content": [{"text": ...}]}]`)."""
    response = _bedrock().converse(
        modelId=MODEL,
        system=[{"text": system_prompt}],
        messages=messages,
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    blocks = response["output"]["message"]["content"]
    text = "".join(block["text"] for block in blocks if "text" in block).strip()
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise LLMOutputError(f"Không parse được JSON từ response của model: {text[:500]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"JSON không hợp lệ từ model: {exc}") from exc


_ROLE_MAP = {"user": "user", "orchestrator": "assistant", "tool": "user", "human": "user"}


def history_to_messages(description: str, history: list[dict]) -> list[dict]:
    """Chuyển `history` (list role/content kiểu Workflow) thành messages[] hợp
    lệ cho Converse API — gộp entry liên tiếp cùng role vì Converse chỉ chấp
    nhận user/assistant xen kẽ, không có role "system" trong messages[]."""
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
        texts.append(("user", description))
    return [{"role": role, "content": [{"text": text}]} for role, text in texts]
