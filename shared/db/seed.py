"""Seed dữ liệu cho usecase `incident_investigation` (mục 8 bước 3 design
doc) — script idempotent, chạy qua `make seed` (xem README/Makefile). KHÔNG
phải Alembic data migration có chủ đích — dữ liệu demo, không phải schema.
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from shared.db.models import AgentcoreAgent, AgentKind, Usecase, UsecaseAgent, UsecaseVersion, UsecaseVersionStatus
from shared.db.session import async_session_maker

USECASE_KEY = "incident_investigation"

AGENTS = [
    {
        "agent_key": "incident_investigation_orchestrator",
        "label": "Incident Investigation Orchestrator",
        "local_tool_ref": "agents.incident_investigation_orchestrator.tool:run",
        "read_only": True,
        "kind": AgentKind.ORCHESTRATOR,
    },
    {
        "agent_key": "log_agent",
        "label": "Log Investigator Agent",
        "local_tool_ref": "agents.log_agent.tool:run",
        "read_only": True,
        "kind": AgentKind.SUBAGENT,
    },
    {
        "agent_key": "metrics_agent",
        "label": "Metrics Investigator Agent",
        "local_tool_ref": "agents.metrics_agent.tool:run",
        "read_only": True,
        "kind": AgentKind.SUBAGENT,
    },
]


async def seed() -> None:
    async with async_session_maker() as session:
        usecase = (
            await session.execute(select(Usecase).where(Usecase.usecase_key == USECASE_KEY))
        ).scalar_one_or_none()
        if usecase is None:
            usecase = Usecase(
                id=uuid.uuid4(),
                usecase_key=USECASE_KEY,
                label="Incident Investigation",
                description="Điều tra sự cố qua log_agent/metrics_agent, đề xuất RCA, chờ HITL duyệt.",
                default_max_iterations=15,
                max_iterations_cap=30,
            )
            session.add(usecase)
            await session.flush()
            print(f"created usecase {USECASE_KEY} id={usecase.id}")
        else:
            print(f"usecase {USECASE_KEY} đã tồn tại, id={usecase.id}")

        version = (
            await session.execute(
                select(UsecaseVersion).where(
                    UsecaseVersion.usecase_id == usecase.id, UsecaseVersion.version_number == 1
                )
            )
        ).scalar_one_or_none()
        if version is None:
            version = UsecaseVersion(
                id=uuid.uuid4(),
                usecase_id=usecase.id,
                version_number=1,
                is_latest=True,
                # Seed thẳng thành ready — dữ liệu demo đã biết hợp lệ, không
                # đi qua endpoint publish (mục 8 bước 3 design doc).
                status=UsecaseVersionStatus.READY,
            )
            session.add(version)
            await session.flush()
            print(f"created usecase_versions v1 id={version.id}")
        else:
            print(f"usecase_versions v1 đã tồn tại, id={version.id}")

        agent_ids: dict[str, uuid.UUID] = {}
        for spec in AGENTS:
            agent = (
                await session.execute(select(AgentcoreAgent).where(AgentcoreAgent.agent_key == spec["agent_key"]))
            ).scalar_one_or_none()
            if agent is None:
                agent = AgentcoreAgent(
                    id=uuid.uuid4(),
                    agent_key=spec["agent_key"],
                    label=spec["label"],
                    agentcore_agent_arn=None,
                    local_tool_ref=spec["local_tool_ref"],
                    read_only=spec["read_only"],
                    secrets=[],
                    default_timeout_seconds=120 if spec["kind"] == AgentKind.ORCHESTRATOR else 300,
                    default_retry_policy={},
                    agent_metadata={},
                )
                session.add(agent)
                await session.flush()
                print(f"created agentcore_agents {spec['agent_key']} id={agent.id}")
            else:
                print(f"agentcore_agents {spec['agent_key']} đã tồn tại, id={agent.id}")
            agent_ids[spec["agent_key"]] = agent.id

        for spec in AGENTS:
            agent_name = f"{USECASE_KEY}__{spec['agent_key']}"
            existing = (
                await session.execute(
                    select(UsecaseAgent).where(
                        UsecaseAgent.usecase_version_id == version.id,
                        UsecaseAgent.agent_name == agent_name,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(f"usecase_agents {agent_name} đã tồn tại")
                continue
            session.add(
                UsecaseAgent(
                    id=uuid.uuid4(),
                    usecase_version_id=version.id,
                    agent_id=agent_ids[spec["agent_key"]],
                    agent_name=agent_name,
                    kind=spec["kind"],
                    timeout_seconds=None,
                    retry_policy=None,
                )
            )
            print(f"linked {agent_name} (kind={spec['kind'].value})")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
