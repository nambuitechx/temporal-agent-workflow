"""Test IncidentInvestigationWorkflow bằng Temporal test framework
(time-skipping WorkflowEnvironment) — KHÔNG gọi Anthropic API thật.

3 Activity thật (ask_orchestrator/run_agent/notify_human) được thay bằng bản
fake cùng tên/chữ ký cho mỗi test, để test đúng LOGIC của while-loop (mục 7 của
POC design — Scenario A/B/C/D/E) một cách deterministic, tách biệt khỏi việc
gọi LLM thật (phần đó verify thủ công qua Web UI, xem README.md).

Có thêm 1 test regression (`test_legacy_finish_action_no_longer_completes_workflow`)
khoá lại quyết định thiết kế: action "FINISH" đã bị loại khỏi allowlist — mọi
RCA đều bắt buộc qua NEEDS_HUMAN, không còn đường nào để Orchestrator (hay 1
Activity lỗi/rogue) tự kết luận mà bỏ qua người duyệt (xem shared/models.py).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from shared.models import TASK_QUEUE
from shared.workflows import IncidentInvestigationWorkflow


@pytest_asyncio.fixture(scope="session")
async def env():
    # 1 test-server time-skipping dùng chung cho cả session — mỗi test tự mở
    # Worker riêng (task queue giống nhau nhưng không chạy đồng thời).
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment


def _base_request(scenario_id: str = "scenario_a_checkout_payment_timeout", max_iterations: int = 15) -> dict:
    return {
        "incident_id": f"test-{uuid.uuid4().hex[:8]}",
        "description": "checkout-api trả lỗi 500",
        "scenario_id": scenario_id,
        "max_iterations": max_iterations,
    }


async def _wait_for_status(handle, status: str, attempts: int = 30) -> None:
    for _ in range(attempts):
        state = await handle.query(IncidentInvestigationWorkflow.get_state)
        if state["status"] == status:
            return
    raise AssertionError(f"Workflow không đạt trạng thái {status!r} sau {attempts} lần query")


# ---------------------------------------------------------------------------
# Scenario C — dù confidence rất cao (0.95), VẪN phải qua HITL. Không còn
# đường "tự kết luận" (FINISH) nào để LLM tự bỏ qua bước duyệt — xem
# shared/models.py để biết lý do đổi thiết kế (confidence tự chấm không được
# tin cậy để quyết định có cần giám sát hay không).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_c_high_confidence_still_requires_hitl(env: WorkflowEnvironment):
    @activity.defn(name="ask_orchestrator")
    async def fake_ask_orchestrator(description: str, scenario_id: str, history: list[dict]) -> dict:
        return {
            "action": "NEEDS_HUMAN",
            "rca_proposal": {"hypothesis": "config lỗi", "confidence": 0.95, "supporting_evidence_refs": []},
        }

    @activity.defn(name="run_agent")
    async def fake_run_agent(agent_name: str, args: dict, scenario_id: str) -> dict:  # pragma: no cover
        raise AssertionError("Không cần gọi run_agent trong test này")

    notified = []

    @activity.defn(name="notify_human")
    async def fake_notify_human(payload: dict) -> str:
        notified.append(payload)
        return "notified"

    request = _base_request("scenario_c_auto_finish_clear_stacktrace")
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentInvestigationWorkflow],
        activities=[fake_ask_orchestrator, fake_run_agent, fake_notify_human],
    ):
        handle = await env.client.start_workflow(
            IncidentInvestigationWorkflow.run, request, id=request["incident_id"], task_queue=TASK_QUEUE
        )
        # Dù confidence = 0.95, workflow phải dừng ở WAITING_HUMAN — KHÔNG
        # được tự FINISHED trước khi có signal approve/reject.
        await _wait_for_status(handle, "WAITING_HUMAN")
        state = await handle.query(IncidentInvestigationWorkflow.get_state)
        assert state["status"] == "WAITING_HUMAN"
        assert state["rca_proposal"]["confidence"] == 0.95

        await handle.signal(IncidentInvestigationWorkflow.approve, "Đồng ý, evidence rõ ràng.")
        result = await handle.result()

    assert result["status"] == "FINISHED"
    assert "config lỗi" in result["rca_proposal"]["hypothesis"]
    assert notified and notified[0]["event"] == "RCA_APPROVED"


# ---------------------------------------------------------------------------
# Regression: nếu 1 Activity (lỗi/rogue/code cũ) trả về action="FINISH" — dù
# action này không còn tồn tại trong allowlist — Workflow tuyệt đối không
# được coi đó là hoàn thành hợp lệ. Phải rơi vào escalate an toàn, giống hệt
# xử lý 1 action lạ bất kỳ (defense-in-depth, không chỉ dựa vào 1 lớp check).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_finish_action_no_longer_completes_workflow(env: WorkflowEnvironment):
    @activity.defn(name="ask_orchestrator")
    async def fake_ask_orchestrator(description: str, scenario_id: str, history: list[dict]) -> dict:
        return {"action": "FINISH", "final_answer": "should never be trusted anymore"}

    @activity.defn(name="run_agent")
    async def fake_run_agent(agent_name: str, args: dict, scenario_id: str) -> dict:  # pragma: no cover
        raise AssertionError("Không nên gọi run_agent trong test này")

    escalations = []

    @activity.defn(name="notify_human")
    async def fake_notify_human(payload: dict) -> str:
        escalations.append(payload)
        return "notified"

    request = _base_request()
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentInvestigationWorkflow],
        activities=[fake_ask_orchestrator, fake_run_agent, fake_notify_human],
    ):
        handle = await env.client.start_workflow(
            IncidentInvestigationWorkflow.run, request, id=request["incident_id"], task_queue=TASK_QUEUE
        )
        result = await handle.result()

    assert result["status"] == "ESCALATED"
    assert result["final_answer"] != "should never be trusted anymore"
    assert escalations and "Unknown action" in escalations[0]["reason"]


# ---------------------------------------------------------------------------
# Scenario A — NEEDS_HUMAN -> approve -> finished
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_a_hitl_approve(env: WorkflowEnvironment):
    @activity.defn(name="ask_orchestrator")
    async def fake_ask_orchestrator(description: str, scenario_id: str, history: list[dict]) -> dict:
        return {
            "action": "NEEDS_HUMAN",
            "rca_proposal": {
                "hypothesis": "payment-adapter gây lỗi checkout-api",
                "confidence": 0.72,
                "supporting_evidence_refs": [],
            },
        }

    @activity.defn(name="run_agent")
    async def fake_run_agent(agent_name: str, args: dict, scenario_id: str) -> dict:  # pragma: no cover
        raise AssertionError("Không cần gọi run_agent trong test này")

    notified = []

    @activity.defn(name="notify_human")
    async def fake_notify_human(payload: dict) -> str:
        notified.append(payload)
        return "notified"

    request = _base_request()
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentInvestigationWorkflow],
        activities=[fake_ask_orchestrator, fake_run_agent, fake_notify_human],
    ):
        handle = await env.client.start_workflow(
            IncidentInvestigationWorkflow.run, request, id=request["incident_id"], task_queue=TASK_QUEUE
        )
        await _wait_for_status(handle, "WAITING_HUMAN")
        await handle.signal(IncidentInvestigationWorkflow.approve, "Đủ căn cứ, đồng ý.")
        result = await handle.result()

    assert result["status"] == "FINISHED"
    assert notified and notified[0]["event"] == "RCA_APPROVED"


# ---------------------------------------------------------------------------
# Scenario B — NEEDS_HUMAN -> reject -> quay lại loop -> lần 2 NEEDS_HUMAN
# (hypothesis mới) -> approve -> FINISHED. Không còn nhánh FINISH trực tiếp
# nào — lần đề xuất RCA thứ 2 vẫn phải qua đúng 1 vòng duyệt nữa.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_b_hitl_reject_then_continue(env: WorkflowEnvironment):
    call_count = {"n": 0}

    @activity.defn(name="ask_orchestrator")
    async def fake_ask_orchestrator(description: str, scenario_id: str, history: list[dict]) -> dict:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "action": "NEEDS_HUMAN",
                "rca_proposal": {"hypothesis": "giả thuyết 1 (sẽ bị reject)", "confidence": 0.6},
            }
        # Sau khi bị reject, Orchestrator đọc note và đưa ra hypothesis khác —
        # vẫn phải qua NEEDS_HUMAN lần nữa, không được tự kết luận.
        assert any(h.get("role") == "human" for h in history), "history phải có note reject"
        return {
            "action": "NEEDS_HUMAN",
            "rca_proposal": {"hypothesis": "giả thuyết 2", "confidence": 0.9},
        }

    @activity.defn(name="run_agent")
    async def fake_run_agent(agent_name: str, args: dict, scenario_id: str) -> dict:  # pragma: no cover
        raise AssertionError("Không cần gọi run_agent trong test này")

    @activity.defn(name="notify_human")
    async def fake_notify_human(payload: dict) -> str:
        return "notified"

    request = _base_request()
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentInvestigationWorkflow],
        activities=[fake_ask_orchestrator, fake_run_agent, fake_notify_human],
    ):
        handle = await env.client.start_workflow(
            IncidentInvestigationWorkflow.run, request, id=request["incident_id"], task_queue=TASK_QUEUE
        )
        await _wait_for_status(handle, "WAITING_HUMAN")
        await handle.signal(IncidentInvestigationWorkflow.reject, "Chưa đủ bằng chứng, kiểm tra thêm.")

        # Sau reject, workflow quay lại RUNNING rồi tới WAITING_HUMAN lần 2
        # (với hypothesis mới) — chờ đúng trạng thái đó trước khi approve.
        for _ in range(30):
            state = await handle.query(IncidentInvestigationWorkflow.get_state)
            if state["status"] == "WAITING_HUMAN" and state["rca_proposal"]["hypothesis"] == "giả thuyết 2":
                break
        else:
            raise AssertionError("Không thấy WAITING_HUMAN lần 2 với hypothesis mới")

        await handle.signal(IncidentInvestigationWorkflow.approve, "Đồng ý với giả thuyết 2.")
        result = await handle.result()

    assert result["status"] == "FINISHED"
    assert result["rca_proposal"]["hypothesis"] == "giả thuyết 2"
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Scenario D — circuit breaker: vượt MAX_ITERATIONS -> ESCALATED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_d_circuit_breaker_max_iterations(env: WorkflowEnvironment):
    @activity.defn(name="ask_orchestrator")
    async def fake_ask_orchestrator(description: str, scenario_id: str, history: list[dict]) -> dict:
        # Orchestrator "không biết dừng" — luôn xin thêm evidence.
        return {"action": "CALL_AGENT", "agent_name": "log_agent", "args": {}}

    @activity.defn(name="run_agent")
    async def fake_run_agent(agent_name: str, args: dict, scenario_id: str) -> dict:
        return {"agent_name": agent_name, "summary": "vẫn chưa rõ", "evidence": []}

    escalations = []

    @activity.defn(name="notify_human")
    async def fake_notify_human(payload: dict) -> str:
        escalations.append(payload)
        return "notified"

    request = _base_request("scenario_d_max_iterations", max_iterations=2)
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentInvestigationWorkflow],
        activities=[fake_ask_orchestrator, fake_run_agent, fake_notify_human],
    ):
        handle = await env.client.start_workflow(
            IncidentInvestigationWorkflow.run, request, id=request["incident_id"], task_queue=TASK_QUEUE
        )
        result = await handle.result()

    assert result["status"] == "ESCALATED"
    assert escalations and escalations[0]["event"] == "ESCALATED"
    assert "MAX_ITERATIONS" in escalations[0]["reason"]


# ---------------------------------------------------------------------------
# Scenario E — guardrail: agent_name ngoài allowlist -> escalate ngay, KHÔNG
# execute action đó.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_e_allowlist_violation_is_blocked(env: WorkflowEnvironment):
    @activity.defn(name="ask_orchestrator")
    async def fake_ask_orchestrator(description: str, scenario_id: str, history: list[dict]) -> dict:
        # Mô phỏng đúng hành vi guardrail thật của activities.ask_orchestrator:
        # validate và raise non_retryable nếu ngoài allowlist.
        raise ApplicationError(
            "Orchestrator trả về agent_name ngoài allowlist: 'shell_agent'",
            type="GuardrailViolation",
            non_retryable=True,
        )

    @activity.defn(name="run_agent")
    async def fake_run_agent(agent_name: str, args: dict, scenario_id: str) -> dict:  # pragma: no cover
        raise AssertionError("KHÔNG được thực thi run_agent với agent_name ngoài allowlist")

    escalations = []

    @activity.defn(name="notify_human")
    async def fake_notify_human(payload: dict) -> str:
        escalations.append(payload)
        return "notified"

    request = _base_request("scenario_e_allowlist_violation")
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentInvestigationWorkflow],
        activities=[fake_ask_orchestrator, fake_run_agent, fake_notify_human],
    ):
        handle = await env.client.start_workflow(
            IncidentInvestigationWorkflow.run, request, id=request["incident_id"], task_queue=TASK_QUEUE
        )
        result = await handle.result()

    assert result["status"] == "ESCALATED"
    assert escalations and "GuardrailViolation" in escalations[0]["reason"]
