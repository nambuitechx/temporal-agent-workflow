"""AgentLoopWorkflow — Execution Engine generic, dùng chung cho mọi usecase
(mục 3 của `docs/2026-09-08-generic-agent-loop-design.md`; tên cũ
`IncidentInvestigationWorkflow`).

Đúng nguyên tắc "Workflow code phải deterministic": vòng lặp chỉ if/else dựa
trên kết quả trả về từ Activity, KHÔNG gọi LLM/HTTP/random/datetime.now()
trực tiếp trong file này. Mọi phần không xác định trước (bao gồm query
Postgres theo `usecase_version_id`) nằm trong activities.py — xem mục 7 design
doc.
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError

# Import các Activity + hằng số qua "imports_passed_through" vì activities.py
# import các thư viện non-deterministic (boto3, sqlalchemy) — Workflow
# sandbox không cần (và không nên) validate determinism của module đó, chỉ
# cần biết chữ ký hàm để gọi execute_activity.
with workflow.unsafe.imports_passed_through():
    from .activities import ask_orchestrator, get_usecase_limits, notify_human, run_agent
    from .models import DEFAULT_MAX_ITERATIONS


def _describe(exc: ActivityError) -> str:
    """ActivityError.__str__ chỉ in ra generic 'Activity task failed' — lấy
    đúng type/message của exception gốc (vd ApplicationError GuardrailViolation
    hoặc RegistryError) từ `.cause` để lý do escalate hữu ích, audit được."""
    cause = exc.cause
    if cause is None:
        return str(exc)
    cause_type = getattr(cause, "type", None) or type(cause).__name__
    cause_message = getattr(cause, "message", None) or str(cause)
    return f"{cause_type}: {cause_message}"


@workflow.defn
class AgentLoopWorkflow:
    def __init__(self) -> None:
        self.case_id: str = ""
        self.usecase_id: str = ""
        self.usecase_version_id: str = ""
        self.history: list[dict] = []
        self.artifacts: list[dict] = []
        self.proposal: dict | None = None
        self.approved: bool | None = None
        self.approval_note: str | None = None
        self.iteration: int = 0
        self.status: str = "RUNNING"
        self.final_answer: str | None = None

    # ------------------------------------------------------------------
    # Signals — cách HITL đưa dữ liệu từ bên ngoài vào workflow đang chờ,
    # không polling, 0 CPU/RAM trong lúc chờ (workflow.wait_condition).
    # ------------------------------------------------------------------

    @workflow.signal
    def approve(self, note: str = "") -> None:
        self.approved = True
        self.approval_note = note

    @workflow.signal
    def reject(self, note: str = "") -> None:
        self.approved = False
        self.approval_note = note

    # ------------------------------------------------------------------
    # Query — đọc state hiện tại mà không cần đợi workflow chạy xong,
    # không làm thay đổi Event History.
    # ------------------------------------------------------------------

    @workflow.query
    def get_state(self) -> dict:
        return {
            "case_id": self.case_id,
            "usecase_id": self.usecase_id,
            "usecase_version_id": self.usecase_version_id,
            "status": self.status,
            "iteration": self.iteration,
            "history": self.history,
            "artifacts": self.artifacts,
            "proposal": self.proposal,
            "final_answer": self.final_answer,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    @workflow.run
    async def run(self, request: dict) -> dict:
        self.case_id = request["case_id"]
        self.usecase_id = request["usecase_id"]
        self.usecase_version_id = request["usecase_version_id"]
        case_context = request.get("case_context", {})
        description = case_context.get("description", "")

        self.history.append({"role": "user", "content": description})

        # Circuit breaker defense-in-depth (mục 3 design doc): backend đã
        # clamp max_iterations theo usecases.max_iterations_cap lúc tạo case,
        # nhưng Workflow tự tra lại cap, không tin thẳng giá trị từ request —
        # cùng nguyên tắc 2-lớp validate đã áp dụng cho agent_name.
        try:
            limits = await workflow.execute_activity(
                get_usecase_limits,
                args=[self.usecase_version_id],
                start_to_close_timeout=timedelta(seconds=30),
            )
        except ActivityError as exc:
            return await self._escalate(f"get_usecase_limits activity error: {_describe(exc)}")

        requested_max = request.get("max_iterations") or limits["default_max_iterations"] or DEFAULT_MAX_ITERATIONS
        effective_max_iterations = min(requested_max, limits["max_iterations_cap"])

        while self.iteration < effective_max_iterations:
            try:
                decision = await workflow.execute_activity(
                    ask_orchestrator,
                    args=[self.usecase_version_id, description, case_context, self.history],
                    start_to_close_timeout=timedelta(minutes=2),
                )
            except ActivityError as exc:
                # Guardrail violation (Scenario E) hoặc lỗi parse output của
                # model — Activity đã đánh dấu non_retryable, tuyệt đối không
                # được cố "đoán" hay tự chạy action bị chặn. Escalate an toàn.
                return await self._escalate(f"ask_orchestrator activity error: {_describe(exc)}")

            self.history.append({"role": "orchestrator", "content": decision})
            action = decision["action"]

            # Không có nhánh "tự kết luận" (FINISH) nào cả — mọi RCA đều bắt
            # buộc đi qua NEEDS_HUMAN, bất kể confidence Orchestrator tự chấm
            # là bao nhiêu. Xem giải thích trong shared/models.py.
            if action == "NEEDS_HUMAN":
                self.proposal = decision.get("rca_proposal")
                self.status = "WAITING_HUMAN"

                # Đóng băng workflow — 0 CPU/RAM cho tới khi Signal approve/reject
                # tới, có thể chờ hàng giờ/hàng ngày mà không tốn tài nguyên compute.
                await workflow.wait_condition(lambda: self.approved is not None)

                self.history.append(
                    {"role": "human", "content": {"approved": self.approved, "note": self.approval_note}}
                )

                if self.approved:
                    await workflow.execute_activity(
                        notify_human,
                        args=[{"event": "PROPOSAL_APPROVED", "proposal": self.proposal}],
                        start_to_close_timeout=timedelta(minutes=1),
                    )
                    self.status = "FINISHED"
                    self.final_answer = (
                        f"Đề xuất được duyệt: {self.proposal.get('hypothesis')}"
                        if self.proposal
                        else "Đã được con người duyệt."
                    )
                    return self._result()

                # Reject: KHÔNG được tự FINISH với kết quả cũ — quay lại vòng
                # lặp, giữ nguyên artifacts đã thu thập, để Orchestrator đọc
                # note và điều chỉnh hướng điều tra (Scenario B).
                self.status = "RUNNING"
                self.approved = None
                self.iteration += 1
                continue

            if action == "CALL_AGENT":
                agent_name = decision["agent_name"]
                args = decision.get("args", {})
                try:
                    result = await workflow.execute_activity(
                        run_agent,
                        args=[self.usecase_version_id, agent_name, args, case_context],
                        start_to_close_timeout=timedelta(minutes=5),
                    )
                except ActivityError as exc:
                    return await self._escalate(f"run_agent activity error: {_describe(exc)}")

                self.history.append({"role": "tool", "content": result})
                self.artifacts.extend(result.get("evidence", []))
                self.iteration += 1
                continue

            # Không nên tới được đây — ask_orchestrator đã validate allowlist,
            # đây chỉ là 1 guard cuối cùng để Workflow không crash khó hiểu.
            return await self._escalate(f"Unknown action từ Orchestrator: {action!r}")

        # Vượt effective_max_iterations — circuit breaker bắt buộc (Scenario
        # D), tránh loop vô hạn khi Orchestrator "không biết dừng".
        return await self._escalate("MAX_ITERATIONS exceeded")

    # ------------------------------------------------------------------

    async def _escalate(self, reason: str) -> dict:
        self.status = "ESCALATED"
        await workflow.execute_activity(
            notify_human,
            args=[{"event": "ESCALATED", "reason": reason, "artifacts": self.artifacts}],
            start_to_close_timeout=timedelta(minutes=1),
        )
        return self._result()

    def _result(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "final_answer": self.final_answer,
            "proposal": self.proposal,
            "artifacts": self.artifacts,
        }
