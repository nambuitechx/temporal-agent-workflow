"""Backend Server — Temporal Client mỏng (start/query/signal case) + CRUD
admin cho registry Postgres (mục 6 của
`docs/2026-09-08-generic-agent-loop-design.md`).

Không chứa business logic của agent loop (đó là Workflow/Activity), không gọi
LLM trực tiếp — chỉ CRUD metadata (usecases/usecase_versions/usecase_agents/
agentcore_agents) và cầm Temporal Client để start/query/signal case.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client
from temporalio.service import RPCError

from shared.db.models import (
    AgentcoreAgent,
    AgentKind,
    Usecase,
    UsecaseAgent,
    UsecaseStatus,
    UsecaseVersion,
    UsecaseVersionStatus,
)
from shared.db.session import async_session_maker
from shared.models import TASK_QUEUE
from shared.workflows import AgentLoopWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI(title="Xora POC — Generic Agent Loop Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_client: Client | None = None

# Danh sách "demo scenario" (bộ fake log/metrics data cố định trong
# shared/data/scenarios/*, xem docs/2026-09-07-poc-design-dynamic-agent-loop.md
# mục 2) — đây là tiện ích riêng cho UI demo của usecase
# `incident_investigation`, KHÔNG phải 1 phần của registry generic (mục 4-6
# design doc mới). Cố tình giữ static ở đây thay vì đưa vào Postgres — nó là
# fixture data của 1 usecase cụ thể, không phải metadata usecase/agent dùng
# chung platform-wide.
DEMO_SCENARIOS = [
    {
        "id": "scenario_a_checkout_payment_timeout",
        "label": "A — Happy-path (kỳ vọng dừng ở HITL, bấm Approve)",
        "description": "checkout-api trả lỗi 500 tăng đột biến lúc 10:30",
    },
    {
        "id": "scenario_a_checkout_payment_timeout",
        "label": "B — Giống A nhưng dùng để test HITL-Reject",
        "description": "checkout-api trả lỗi 500 tăng đột biến lúc 10:30",
    },
    {
        "id": "scenario_c_auto_finish_clear_stacktrace",
        "label": "C — Evidence rất rõ ràng, nhưng vẫn bắt buộc qua HITL",
        "description": "checkout-api trả lỗi 500 ngay sau deploy v2.14.0, log có stacktrace rõ ràng",
    },
    {
        "id": "scenario_d_max_iterations",
        "label": "D — Circuit breaker (nên đặt max_iterations = 2 khi submit)",
        "description": "checkout-api có độ trễ tăng nhẹ, log/metrics mơ hồ, không rõ nguyên nhân",
    },
    {
        "id": "scenario_e_allowlist_violation",
        "label": "E — Guardrail: Orchestrator trả agent_name ngoài allowlist (simulated)",
        "description": "checkout-api báo lỗi lạ (dùng để kích hoạt test hook mô phỏng guardrail violation)",
    },
]


@app.get("/demo-scenarios")
async def list_demo_scenarios():
    return {"scenarios": DEMO_SCENARIOS}


async def get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    return _client


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


# ==========================================================================
# Cases — start/query/signal qua Temporal (không đổi logic so với trước,
# chỉ đổi tên field theo mục 3 design doc: incident_id -> case_id,
# rca_proposal -> proposal, evidence -> artifacts)
# ==========================================================================


class CaseCreateRequest(BaseModel):
    usecase_key: str
    case_context: dict[str, Any] = Field(default_factory=dict)
    max_iterations: int | None = Field(default=None, ge=1, le=100)


class ApprovalRequest(BaseModel):
    note: str = ""


@app.get("/usecases")
async def list_usecases(db: AsyncSession = Depends(get_db)):
    """Chỉ trả usecase active + version READY **mới nhất theo version_number**
    — KHÔNG bắt buộc phải trùng với `is_latest` (sửa lỗi thực tế: tạo 1 draft
    version mới, hợp lệ về nghiệp vụ, không được phép khoá luôn việc submit
    case đang dùng version ready trước đó chỉ vì draft mới đã "cướp" cờ
    is_latest — `is_latest` chỉ có nghĩa "bản mới nhất để admin sửa tiếp",
    không phải "bản duy nhất được phép chạy case"). Xem cùng logic ở
    `_resolve_ready_version`."""
    usecases = (await db.execute(select(Usecase).where(Usecase.status == UsecaseStatus.ACTIVE))).scalars().all()
    out = []
    for uc in usecases:
        version = (
            await db.execute(
                select(UsecaseVersion)
                .where(UsecaseVersion.usecase_id == uc.id, UsecaseVersion.status == UsecaseVersionStatus.READY)
                .order_by(UsecaseVersion.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if version is None:
            continue
        out.append(
            {
                "usecase_key": uc.usecase_key,
                "label": uc.label,
                "description": uc.description,
                "default_max_iterations": uc.default_max_iterations,
                "max_iterations_cap": uc.max_iterations_cap,
                "usecase_version_id": str(version.id),
                "version_number": version.version_number,
            }
        )
    return {"usecases": out}


async def _resolve_ready_version(db: AsyncSession, usecase_key: str) -> tuple[Usecase, UsecaseVersion]:
    """Resolve version READY **mới nhất theo version_number** cho case mới —
    KHÔNG bắt buộc `is_latest=true`. Lý do (sự cố thực tế đã gặp): 1 admin tạo
    version draft mới (v2) trong lúc v1 vẫn đang ready — is_latest chuyển
    sang v2 ngay lập tức dù v2 chưa publish được. Nếu bắt buộc
    `is_latest AND ready`, hành động quản trị hoàn toàn hợp lệ này (tạo
    version mới để chỉnh sửa dần) sẽ khoá đứt việc submit case cho tới khi v2
    publish xong — sai, vì v1 vẫn là 1 config hoàn toàn dùng được. Case mới
    phải tiếp tục dùng v1 cho tới khi v2 thật sự publish (ready)."""
    usecase = (
        await db.execute(select(Usecase).where(Usecase.usecase_key == usecase_key, Usecase.status == UsecaseStatus.ACTIVE))
    ).scalar_one_or_none()
    if usecase is None:
        raise HTTPException(status_code=404, detail=f"usecase_key={usecase_key!r} không tồn tại hoặc bị disable")
    version = (
        await db.execute(
            select(UsecaseVersion)
            .where(UsecaseVersion.usecase_id == usecase.id, UsecaseVersion.status == UsecaseVersionStatus.READY)
            .order_by(UsecaseVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=409,
            detail=f"usecase_key={usecase_key!r} chưa có usecase_version nào ở trạng thái ready",
        )
    return usecase, version


@app.post("/cases")
async def submit_case(req: CaseCreateRequest, db: AsyncSession = Depends(get_db)):
    usecase, version = await _resolve_ready_version(db, req.usecase_key)

    client = await get_client()
    case_id = f"case-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        AgentLoopWorkflow.run,
        {
            "case_id": case_id,
            "usecase_id": usecase.usecase_key,
            "usecase_version_id": str(version.id),
            "case_context": req.case_context,
            "max_iterations": req.max_iterations,
        },
        id=case_id,
        task_queue=TASK_QUEUE,
    )
    logger.info("Started workflow %s (usecase=%s, version=%s)", case_id, req.usecase_key, version.id)
    return {"case_id": case_id, "usecase_version_id": str(version.id)}


@app.get("/cases/{case_id}")
async def get_case(case_id: str):
    client = await get_client()
    handle = client.get_workflow_handle(case_id)
    try:
        state = await handle.query(AgentLoopWorkflow.get_state)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy case {case_id!r}: {exc}") from exc
    return state


@app.post("/cases/{case_id}/approve")
async def approve_case(case_id: str, req: ApprovalRequest):
    client = await get_client()
    handle = client.get_workflow_handle(case_id)
    try:
        await handle.signal(AgentLoopWorkflow.approve, req.note)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "signaled", "action": "approve"}


@app.post("/cases/{case_id}/reject")
async def reject_case(case_id: str, req: ApprovalRequest):
    client = await get_client()
    handle = client.get_workflow_handle(case_id)
    try:
        await handle.signal(AgentLoopWorkflow.reject, req.note)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "signaled", "action": "reject"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ==========================================================================
# Admin CRUD — usecases / usecase_versions / usecase_agents (mục 6)
# ==========================================================================


class UsecaseCreateRequest(BaseModel):
    usecase_key: str
    label: str
    description: str = ""
    default_max_iterations: int = 15
    max_iterations_cap: int = 30


def _usecase_out(uc: Usecase) -> dict:
    return {
        "id": str(uc.id),
        "usecase_key": uc.usecase_key,
        "label": uc.label,
        "description": uc.description,
        "status": uc.status.value,
        "default_max_iterations": uc.default_max_iterations,
        "max_iterations_cap": uc.max_iterations_cap,
    }


@app.get("/admin/usecases")
async def admin_list_usecases(db: AsyncSession = Depends(get_db)):
    """Khác `GET /usecases` (public, chỉ active + version ready) — trả TẤT
    CẢ usecase bất kể status, dùng cho màn hình quản trị."""
    usecases = (await db.execute(select(Usecase))).scalars().all()
    return {"usecases": [_usecase_out(u) for u in usecases]}


@app.get("/admin/usecases/{usecase_id}")
async def admin_get_usecase(usecase_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    usecase = (await db.execute(select(Usecase).where(Usecase.id == usecase_id))).scalar_one_or_none()
    if usecase is None:
        raise HTTPException(status_code=404, detail=f"usecase {usecase_id} không tồn tại")
    return _usecase_out(usecase)


@app.get("/admin/usecases/{usecase_id}/versions")
async def admin_list_versions(usecase_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    usecase = (await db.execute(select(Usecase).where(Usecase.id == usecase_id))).scalar_one_or_none()
    if usecase is None:
        raise HTTPException(status_code=404, detail=f"usecase {usecase_id} không tồn tại")
    versions = (
        await db.execute(
            select(UsecaseVersion)
            .where(UsecaseVersion.usecase_id == usecase_id)
            .order_by(UsecaseVersion.version_number.desc())
        )
    ).scalars().all()
    return {"versions": [_version_out(v) for v in versions]}


@app.post("/admin/usecases", status_code=201)
async def admin_create_usecase(req: UsecaseCreateRequest, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(Usecase).where(Usecase.usecase_key == req.usecase_key))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"usecase_key={req.usecase_key!r} đã tồn tại")
    usecase = Usecase(
        id=uuid.uuid4(),
        usecase_key=req.usecase_key,
        label=req.label,
        description=req.description,
        default_max_iterations=req.default_max_iterations,
        max_iterations_cap=req.max_iterations_cap,
    )
    db.add(usecase)
    await db.commit()
    return _usecase_out(usecase)


class UsecaseUpdateRequest(BaseModel):
    label: str | None = None
    description: str | None = None
    default_max_iterations: int | None = None
    max_iterations_cap: int | None = None
    status: str | None = None  # "active" | "disabled"


@app.patch("/admin/usecases/{usecase_id}")
async def admin_update_usecase(usecase_id: uuid.UUID, req: UsecaseUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Dùng để disable/enable usecase (`status`) hay sửa label/description/
    giới hạn iteration. KHÔNG chặn disable khi còn case sống — case đang chạy
    đã resolve xong `usecase_version_id` lúc start, Workflow không đọc lại
    `usecases.status` giữa chừng; disable chỉ chặn TẠO case mới
    (`POST /cases`, xem `_resolve_ready_version`)."""
    usecase = (await db.execute(select(Usecase).where(Usecase.id == usecase_id))).scalar_one_or_none()
    if usecase is None:
        raise HTTPException(status_code=404, detail=f"usecase {usecase_id} không tồn tại")

    updates = req.model_dump(exclude_unset=True)
    if "status" in updates:
        raw_status = updates.pop("status")
        try:
            usecase.status = UsecaseStatus(raw_status)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"status phải là 'active' hoặc 'disabled': {raw_status!r}"
            ) from exc
    for field, value in updates.items():
        setattr(usecase, field, value)

    await db.commit()
    return _usecase_out(usecase)


def _version_out(v: UsecaseVersion) -> dict:
    return {
        "id": str(v.id),
        "usecase_id": str(v.usecase_id),
        "version_number": v.version_number,
        "is_latest": v.is_latest,
        "status": v.status.value,
    }


@app.post("/admin/usecases/{usecase_id}/versions", status_code=201)
async def admin_create_version(usecase_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Tạo version mới (`draft`, `is_latest=true`), hạ cờ version cũ xuống
    false — mục 4: version là snapshot bất biến, sửa gì cũng tạo version mới."""
    usecase = (await db.execute(select(Usecase).where(Usecase.id == usecase_id))).scalar_one_or_none()
    if usecase is None:
        raise HTTPException(status_code=404, detail=f"usecase {usecase_id} không tồn tại")

    prev_latest = (
        await db.execute(
            select(UsecaseVersion).where(UsecaseVersion.usecase_id == usecase_id, UsecaseVersion.is_latest.is_(True))
        )
    ).scalar_one_or_none()
    next_number = (prev_latest.version_number + 1) if prev_latest else 1
    if prev_latest is not None:
        prev_latest.is_latest = False

    version = UsecaseVersion(
        id=uuid.uuid4(),
        usecase_id=usecase_id,
        version_number=next_number,
        is_latest=True,
        status=UsecaseVersionStatus.DRAFT,
    )
    db.add(version)
    await db.commit()
    return _version_out(version)


class UsecaseAgentCreateRequest(BaseModel):
    agent_id: uuid.UUID
    kind: str  # "orchestrator" | "subagent"
    timeout_seconds: int | None = None
    retry_policy: dict[str, Any] | None = None


@app.post("/admin/usecase-versions/{version_id}/agents", status_code=201)
async def admin_link_agent(version_id: uuid.UUID, req: UsecaseAgentCreateRequest, db: AsyncSession = Depends(get_db)):
    """agent_name KHÔNG nhận free-text — backend tự sinh
    `{usecase_key}__{agent_key}` (mục 4 design doc)."""
    version = (await db.execute(select(UsecaseVersion).where(UsecaseVersion.id == version_id))).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail=f"usecase_version {version_id} không tồn tại")
    if version.status != UsecaseVersionStatus.DRAFT:
        raise HTTPException(status_code=409, detail="version đã publish (status=ready), không sửa usecase_agents được nữa")

    usecase = (await db.execute(select(Usecase).where(Usecase.id == version.usecase_id))).scalar_one()
    agent = (await db.execute(select(AgentcoreAgent).where(AgentcoreAgent.id == req.agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agentcore_agents {req.agent_id} không tồn tại")

    try:
        kind = AgentKind(req.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"kind phải là 'orchestrator' hoặc 'subagent': {req.kind!r}") from exc

    agent_name = f"{usecase.usecase_key}__{agent.agent_key}"

    if kind == AgentKind.ORCHESTRATOR:
        existing_orch = (
            await db.execute(
                select(UsecaseAgent).where(
                    UsecaseAgent.usecase_version_id == version_id, UsecaseAgent.kind == AgentKind.ORCHESTRATOR
                )
            )
        ).scalar_one_or_none()
        if existing_orch is not None:
            raise HTTPException(status_code=409, detail="version này đã có 1 orchestrator, không gán thêm được")

    link = UsecaseAgent(
        id=uuid.uuid4(),
        usecase_version_id=version_id,
        agent_id=agent.id,
        agent_name=agent_name,
        kind=kind,
        timeout_seconds=req.timeout_seconds,
        retry_policy=req.retry_policy,
    )
    db.add(link)
    await db.commit()
    return {
        "id": str(link.id),
        "agent_name": agent_name,
        "kind": kind.value,
        "usecase_version_id": str(version_id),
        "agent_id": str(agent.id),
    }


@app.delete("/admin/usecase-versions/{version_id}/agents/{link_id}", status_code=204)
async def admin_unlink_agent(version_id: uuid.UUID, link_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Gỡ 1 agent khỏi version — chỉ khi version còn `draft` (cùng khoá như
    `admin_link_agent`: version đã publish là snapshot bất biến, mục 4 design
    doc). Gỡ orchestrator hợp lệ ở tầng DB (không có ràng buộc "phải luôn có
    orchestrator" khi còn draft) — chỉ bị chặn lúc publish nếu chưa gán lại."""
    version = (await db.execute(select(UsecaseVersion).where(UsecaseVersion.id == version_id))).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail=f"usecase_version {version_id} không tồn tại")
    if version.status != UsecaseVersionStatus.DRAFT:
        raise HTTPException(status_code=409, detail="version đã publish (status=ready), không gỡ agent được nữa")

    link = (
        await db.execute(
            select(UsecaseAgent).where(UsecaseAgent.id == link_id, UsecaseAgent.usecase_version_id == version_id)
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail=f"usecase_agents {link_id} không tồn tại trong version này")

    await db.delete(link)
    await db.commit()
    return None


@app.post("/admin/usecase-versions/{version_id}/publish")
async def admin_publish_version(version_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """draft -> ready, chỉ khi đúng 1 orchestrator đã gán (mục 4 design doc).
    Sau publish, /admin/usecase-versions/{id}/agents bị khoá (status != draft)."""
    version = (await db.execute(select(UsecaseVersion).where(UsecaseVersion.id == version_id))).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail=f"usecase_version {version_id} không tồn tại")
    if version.status == UsecaseVersionStatus.READY:
        return _version_out(version)

    orchestrators = (
        await db.execute(
            select(UsecaseAgent).where(
                UsecaseAgent.usecase_version_id == version_id, UsecaseAgent.kind == AgentKind.ORCHESTRATOR
            )
        )
    ).scalars().all()
    if len(orchestrators) != 1:
        raise HTTPException(
            status_code=400,
            detail=f"chưa gán orchestrator cho version này (hiện có {len(orchestrators)}, cần đúng 1)",
        )

    version.status = UsecaseVersionStatus.READY
    await db.commit()
    return _version_out(version)


@app.get("/admin/usecase-versions/{version_id}")
async def admin_get_version(version_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    version = (await db.execute(select(UsecaseVersion).where(UsecaseVersion.id == version_id))).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail=f"usecase_version {version_id} không tồn tại")
    links = (
        await db.execute(select(UsecaseAgent).where(UsecaseAgent.usecase_version_id == version_id))
    ).scalars().all()
    return {
        **_version_out(version),
        "agents": [
            {"id": str(link.id), "agent_name": link.agent_name, "kind": link.kind.value, "agent_id": str(link.agent_id)}
            for link in links
        ],
    }


# ==========================================================================
# Admin CRUD — agentcore_agents (mục 6, vòng đời tách khỏi CRUD usecase)
# ==========================================================================


class AgentcoreAgentCreateRequest(BaseModel):
    agent_key: str
    label: str
    agentcore_agent_arn: str | None = None
    local_tool_ref: str | None = None
    read_only: bool
    secrets: list[str] = Field(default_factory=list)
    default_timeout_seconds: int = 120
    default_retry_policy: dict[str, Any] = Field(default_factory=dict)
    agent_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentcoreAgentUpdateRequest(BaseModel):
    label: str | None = None
    agentcore_agent_arn: str | None = None
    local_tool_ref: str | None = None
    read_only: bool | None = None
    secrets: list[str] | None = None
    default_timeout_seconds: int | None = None
    default_retry_policy: dict[str, Any] | None = None
    agent_metadata: dict[str, Any] | None = None


def _agent_out(a: AgentcoreAgent) -> dict:
    return {
        "id": str(a.id),
        "agent_key": a.agent_key,
        "label": a.label,
        "agentcore_agent_arn": a.agentcore_agent_arn,
        "local_tool_ref": a.local_tool_ref,
        "read_only": a.read_only,
        "secrets": a.secrets,
        "default_timeout_seconds": a.default_timeout_seconds,
        "default_retry_policy": a.default_retry_policy,
        "agent_metadata": a.agent_metadata,
    }


@app.get("/admin/agentcore-agents")
async def admin_list_agents(db: AsyncSession = Depends(get_db)):
    agents = (await db.execute(select(AgentcoreAgent))).scalars().all()
    return {"agents": [_agent_out(a) for a in agents]}


@app.post("/admin/agentcore-agents", status_code=201)
async def admin_create_agent(req: AgentcoreAgentCreateRequest, db: AsyncSession = Depends(get_db)):
    if bool(req.agentcore_agent_arn) == bool(req.local_tool_ref):
        raise HTTPException(status_code=422, detail="phải có đúng 1 trong 2: agentcore_agent_arn hoặc local_tool_ref")
    existing = (
        await db.execute(select(AgentcoreAgent).where(AgentcoreAgent.agent_key == req.agent_key))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"agent_key={req.agent_key!r} đã tồn tại")

    agent = AgentcoreAgent(
        id=uuid.uuid4(),
        agent_key=req.agent_key,
        label=req.label,
        agentcore_agent_arn=req.agentcore_agent_arn,
        local_tool_ref=req.local_tool_ref,
        read_only=req.read_only,
        secrets=req.secrets,
        default_timeout_seconds=req.default_timeout_seconds,
        default_retry_policy=req.default_retry_policy,
        agent_metadata=req.agent_metadata,
    )
    db.add(agent)
    await db.commit()
    return _agent_out(agent)


async def _live_case_count_for_agent(db: AsyncSession, agent_id: uuid.UUID) -> dict:
    """Trả về usecase_version nào đang tham chiếu agent này + số case
    RUNNING/WAITING_HUMAN của từng version — dùng cho cả check chặn update
    (mục 4) lẫn endpoint đọc /usage (mục 6). Query Temporal, không phải
    Postgres, vì Postgres không biết case nào còn sống."""
    version_ids = set(
        (
            await db.execute(select(UsecaseAgent.usecase_version_id).where(UsecaseAgent.agent_id == agent_id))
        ).scalars().all()
    )
    if not version_ids:
        return {"referenced_versions": [], "live_case_count": 0}

    client = await get_client()
    live_by_version: dict[str, int] = {str(v): 0 for v in version_ids}
    async for wf in client.list_workflows(query="ExecutionStatus = 'Running'"):
        handle = client.get_workflow_handle(wf.id)
        try:
            state = await handle.query(AgentLoopWorkflow.get_state)
        except RPCError:
            continue
        version_id = state.get("usecase_version_id")
        if version_id in live_by_version and state.get("status") in ("RUNNING", "WAITING_HUMAN"):
            live_by_version[version_id] += 1

    return {
        "referenced_versions": [{"usecase_version_id": v, "live_case_count": c} for v, c in live_by_version.items()],
        "live_case_count": sum(live_by_version.values()),
    }


@app.get("/admin/agentcore-agents/{agent_id}/usage")
async def admin_agent_usage(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = (await db.execute(select(AgentcoreAgent).where(AgentcoreAgent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agentcore_agents {agent_id} không tồn tại")
    return await _live_case_count_for_agent(db, agent_id)


@app.patch("/admin/agentcore-agents/{agent_id}")
async def admin_update_agent(agent_id: uuid.UUID, req: AgentcoreAgentUpdateRequest, db: AsyncSession = Depends(get_db)):
    """mục 4: agentcore_agents mutable, nhưng chặn update ở tầng ứng dụng khi
    còn case RUNNING/WAITING_HUMAN tham chiếu tới nó. Race condition giữa lúc
    check và lúc UPDATE thật CHƯA được khoá (mục 10 — chưa chốt), chấp nhận
    cho POC này."""
    agent = (await db.execute(select(AgentcoreAgent).where(AgentcoreAgent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agentcore_agents {agent_id} không tồn tại")

    usage = await _live_case_count_for_agent(db, agent_id)
    if usage["live_case_count"] > 0:
        raise HTTPException(
            status_code=409,
            detail=f"còn {usage['live_case_count']} case RUNNING/WAITING_HUMAN đang dùng agent này, không cho sửa. "
            "Xem GET /admin/agentcore-agents/{id}/usage để biết chi tiết.",
        )

    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(agent, field, value)

    new_arn = agent.agentcore_agent_arn
    new_ref = agent.local_tool_ref
    if bool(new_arn) == bool(new_ref):
        raise HTTPException(status_code=422, detail="phải có đúng 1 trong 2: agentcore_agent_arn hoặc local_tool_ref")

    await db.commit()
    return _agent_out(agent)
