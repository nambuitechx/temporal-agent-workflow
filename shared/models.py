"""Các hằng số/kiểu dữ liệu dùng chung giữa Workflow, Activity và Backend.

Đây là "allowlist" bắt buộc theo guardrail của Dynamic Agent Loop (xem
../agent-workflow/Dynamic Agent Loop Orchestration.md, mục 2). Orchestrator
(LLM, không tin cậy tuyệt đối) chỉ được chọn action/agent nằm trong các set
này — validate ngay trong Activity trước khi trả quyết định về Workflow.
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
# không.
ALLOWED_ACTIONS = {"CALL_AGENT", "NEEDS_HUMAN"}
ALLOWED_AGENTS = {"log_agent", "metrics_agent"}

DEFAULT_MAX_ITERATIONS = 15

TASK_QUEUE = "incident-investigation"
