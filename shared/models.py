"""Hằng số RUNTIME dùng chung giữa Workflow, Activity và Backend — generic
cho mọi usecase (mục 2/3 của
`docs/2026-09-08-generic-agent-loop-design.md`).

Đây là "allowlist" bắt buộc theo guardrail của Dynamic Agent Loop (xem
../agent-workflow/Dynamic Agent Loop Orchestration.md, mục 2). Orchestrator
(LLM, không tin cậy tuyệt đối) chỉ được chọn action nằm trong set này —
validate ngay trong Activity trước khi trả quyết định về Workflow.

`ALLOWED_AGENTS` cũ (hardcode `{"log_agent", "metrics_agent"}`) đã bị xoá
khỏi đây — allowlist agent giờ là DỮ LIỆU theo từng `usecase_version_id`
(bảng `usecase_agents`, tra qua `shared/db/registry.list_allowed_agents`),
KHÔNG còn là Python constant platform-wide. `ALLOWED_ACTIONS` thì vẫn ở lại
đây, cố định, KHÔNG nằm trong DB — đây chính là ranh giới "runtime không bao
giờ để usecase override" (mục 2 design doc).
"""

# Lưu ý: KHÔNG có action "FINISH" — đã bỏ khỏi allowlist có chủ đích.
#
# Thiết kế ban đầu từng cho Orchestrator tự chọn FINISH (kết luận thẳng,
# không qua người duyệt) khi nó tự chấm "confidence >= 0.8". Vấn đề: ngưỡng
# đó chỉ là 1 câu dặn trong prompt — KHÔNG có chỗ nào trong code thực sự
# validate/enforce con số confidence LLM tự báo cáo. Nghĩa là việc "có cần
# con người duyệt hay không" hoàn toàn phụ thuộc vào 1 thành phần không tin
# cậy (LLM) tự đánh giá chính mình — sai nguyên tắc cơ bản của guardrail
# (không bao giờ để thành phần cần bị giám sát tự quyết định có bị giám sát
# hay không). Model thật (Claude 3.5 Sonnet) từng tự chấm 0.9 cho 1 evidence
# chain chỉ là suy luận correlate giữa 2 service, bỏ qua HITL hoàn toàn hợp lệ
# theo code cũ dù đúng ra nên cần người duyệt.
#
# → Sửa lại: Orchestrator chỉ còn 2 lựa chọn — CALL_AGENT (thu thập thêm
# evidence) hoặc NEEDS_HUMAN (đề xuất RCA, LUÔN LUÔN phải chờ người duyệt).
# "confidence" trong rca_proposal giờ chỉ mang tính THAM KHẢO cho người duyệt
# đọc trên UI, không còn giữ vai trò điều khiển luồng (control flow) nào cả —
# loại bỏ hoàn toàn khả năng 1 con số LLM tự chấm quyết định có bị audit hay
# không. Bất biến này không nằm trong config của usecase nào cả, mọi usecase
# dùng chung 1 set này (mục 2 design doc).
ALLOWED_ACTIONS = {"CALL_AGENT", "NEEDS_HUMAN"}

# Fallback tuyệt đối khi request không truyền max_iterations VÀ registry
# lookup (usecases.default_max_iterations) vì lý do nào đó thất bại — không
# nên xảy ra trong vận hành bình thường, chỉ là lưới an toàn cuối.
DEFAULT_MAX_ITERATIONS = 15

TASK_QUEUE = "agent-loop"
