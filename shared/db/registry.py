"""Registry lookup dùng bởi `shared/activities.py` — thay hardcode
`if agent_name == "log_agent": ...` bằng query Postgres theo
`usecase_version_id` (mục 5 design doc).

Mỗi hàm tự mở session (Activity không có DI như FastAPI route) và query lại
mỗi lần gọi — không cache lúc worker start, vì đây là dữ liệu vận hành có thể
sửa qua admin API bất cứ lúc nào (mục 5, cân nhắc cache TTL để ở mục 10, chưa
làm sớm).
"""
from __future__ import annotations

import dataclasses
import uuid

from sqlalchemy import select

from .models import AgentcoreAgent, AgentKind, Usecase, UsecaseAgent, UsecaseVersion
from .session import async_session_maker


class RegistryError(Exception):
    """Không tra được dữ liệu cần thiết trong registry (usecase/agent không
    tồn tại, hoặc cấu hình thiếu — vd version chưa gán orchestrator). Activity
    bắt lỗi này và raise `ApplicationError(type="RegistryError", non_retryable=True)`
    — cùng tinh thần "không đoán/không tự chạy" như GuardrailViolation."""


@dataclasses.dataclass(frozen=True)
class ResolvedAgent:
    """Kết quả join `usecase_agents` (tên logic, kind, override) với
    `agentcore_agents` (identity/ARN/local_tool_ref/mặc định) — Activity chỉ
    thấy 1 object phẳng, không tự join hay biết về 2 bảng (mục 5)."""

    agent_name: str
    kind: AgentKind
    agentcore_agent_arn: str | None
    local_tool_ref: str | None
    read_only: bool
    secrets: list[str]
    timeout_seconds: int
    retry_policy: dict


@dataclasses.dataclass(frozen=True)
class UsecaseLimits:
    default_max_iterations: int
    max_iterations_cap: int


def _resolve(usecase_agent: UsecaseAgent, agent: AgentcoreAgent) -> ResolvedAgent:
    return ResolvedAgent(
        agent_name=usecase_agent.agent_name,
        kind=usecase_agent.kind,
        agentcore_agent_arn=agent.agentcore_agent_arn,
        local_tool_ref=agent.local_tool_ref,
        read_only=agent.read_only,
        secrets=list(agent.secrets or []),
        timeout_seconds=usecase_agent.timeout_seconds or agent.default_timeout_seconds,
        retry_policy=usecase_agent.retry_policy or agent.default_retry_policy or {},
    )


async def get_orchestrator(usecase_version_id: uuid.UUID) -> ResolvedAgent:
    async with async_session_maker() as session:
        stmt = (
            select(UsecaseAgent, AgentcoreAgent)
            .join(AgentcoreAgent, UsecaseAgent.agent_id == AgentcoreAgent.id)
            .where(
                UsecaseAgent.usecase_version_id == usecase_version_id,
                UsecaseAgent.kind == AgentKind.ORCHESTRATOR,
            )
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            raise RegistryError(
                f"usecase_version_id={usecase_version_id} không có agent nào kind=orchestrator "
                "— version chưa được cấu hình đúng (lẽ ra phải bị chặn lúc publish, mục 4 design doc)"
            )
        usecase_agent, agent = row
        return _resolve(usecase_agent, agent)


async def get_agent(usecase_version_id: uuid.UUID, agent_name: str) -> ResolvedAgent | None:
    async with async_session_maker() as session:
        stmt = (
            select(UsecaseAgent, AgentcoreAgent)
            .join(AgentcoreAgent, UsecaseAgent.agent_id == AgentcoreAgent.id)
            .where(
                UsecaseAgent.usecase_version_id == usecase_version_id,
                UsecaseAgent.agent_name == agent_name,
            )
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            return None
        usecase_agent, agent = row
        return _resolve(usecase_agent, agent)


async def list_allowed_agents(usecase_version_id: uuid.UUID) -> set[str]:
    """`allowed_agents` = tập `agent_name` có kind='subagent' của version này
    (mục 4) — dùng làm allowlist thay `ALLOWED_AGENTS` hardcode cũ."""
    async with async_session_maker() as session:
        stmt = select(UsecaseAgent.agent_name).where(
            UsecaseAgent.usecase_version_id == usecase_version_id,
            UsecaseAgent.kind == AgentKind.SUBAGENT,
        )
        return set((await session.execute(stmt)).scalars().all())


async def get_usecase_limits(usecase_version_id: uuid.UUID) -> UsecaseLimits:
    async with async_session_maker() as session:
        stmt = (
            select(Usecase.default_max_iterations, Usecase.max_iterations_cap)
            .join(UsecaseVersion, UsecaseVersion.usecase_id == Usecase.id)
            .where(UsecaseVersion.id == usecase_version_id)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            raise RegistryError(f"usecase_version_id={usecase_version_id} không tồn tại")
        default_max_iterations, max_iterations_cap = row
        return UsecaseLimits(default_max_iterations=default_max_iterations, max_iterations_cap=max_iterations_cap)
