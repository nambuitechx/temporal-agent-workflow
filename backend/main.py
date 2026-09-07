"""Backend Server — CHỈ là 1 Temporal Client mỏng expose REST cho Web UI.

Không chứa business logic, không gọi LLM, không đăng ký Worker (Worker là
container/process riêng, xem worker/main.py). Đây là điểm HTTP duy nhất mà
UI cần biết — tách để UI không phải nhúng Temporal SDK.
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from temporalio.client import Client
from temporalio.service import RPCError

from shared.models import TASK_QUEUE
from shared.workflows import IncidentInvestigationWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI(title="Xora POC — Dynamic Agent Loop Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_client: Client | None = None

SCENARIOS = [
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


async def get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    return _client


class SubmitIncidentRequest(BaseModel):
    description: str
    scenario_id: str
    max_iterations: int = Field(default=15, ge=1, le=100)


class ApprovalRequest(BaseModel):
    note: str = ""


@app.get("/scenarios")
async def list_scenarios():
    return {"scenarios": SCENARIOS}


@app.post("/incidents")
async def submit_incident(req: SubmitIncidentRequest):
    client = await get_client()
    incident_id = f"incident-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        IncidentInvestigationWorkflow.run,
        {
            "incident_id": incident_id,
            "description": req.description,
            "scenario_id": req.scenario_id,
            "max_iterations": req.max_iterations,
        },
        id=incident_id,
        task_queue=TASK_QUEUE,
    )
    logger.info("Started workflow %s (scenario=%s)", incident_id, req.scenario_id)
    return {"incident_id": incident_id}


@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    client = await get_client()
    handle = client.get_workflow_handle(incident_id)
    try:
        state = await handle.query(IncidentInvestigationWorkflow.get_state)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy incident {incident_id!r}: {exc}") from exc
    return state


@app.post("/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, req: ApprovalRequest):
    client = await get_client()
    handle = client.get_workflow_handle(incident_id)
    try:
        await handle.signal(IncidentInvestigationWorkflow.approve, req.note)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "signaled", "action": "approve"}


@app.post("/incidents/{incident_id}/reject")
async def reject_incident(incident_id: str, req: ApprovalRequest):
    client = await get_client()
    handle = client.get_workflow_handle(incident_id)
    try:
        await handle.signal(IncidentInvestigationWorkflow.reject, req.note)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "signaled", "action": "reject"}


@app.get("/health")
async def health():
    return {"status": "ok"}
