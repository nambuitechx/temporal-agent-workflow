# POC: Dynamic Agent Loop + Multi-Agent + HITL (rút gọn từ Xora Resolve)

Tài liệu này thiết kế một **POC nhỏ, chạy được trong vài ngày**, nhằm trả lời một câu hỏi kiến trúc duy nhất:

> *"Pattern `While-Loop + Orchestrator Agent` (mô tả trong [Dynamic Agent Loop Orchestration.md](../agent-workflow/Dynamic%20Agent%20Loop%20Orchestration.md)) có thực sự điều phối được multi-agent + HITL một cách bền vững (durable), audit được, và không tốn tài nguyên khi chờ người duyệt hay không?"*

POC **không** implement lại [Xora Resolve Backend Architecture.md](../architecture/Xora%20Resolve%20Backend%20Architecture.md) hay sơ đồ `xora_architecture.png` — chỉ mượn **ý tưởng nghiệp vụ** (Incident Investigation Runtime: Evidence → RCA → HITL) làm kịch bản demo, dựng trên một lát cắt kiến trúc mỏng nhất có thể.

---

## 1. Phạm vi rút gọn — cái gì giữ, cái gì bỏ

So với 11 capability trong kiến trúc đầy đủ, POC chỉ giữ lại phần lõi của **Dynamic Agent Loop**: Execution Engine (while-loop) + Agent + HITL.

| Capability (kiến trúc đầy đủ) | Trong POC |
| --- | --- |
| Admission (auth/tenant/quota) | ❌ Bỏ — hardcode 1 user, không multi-tenant |
| **Execution Engine (workflow/state/HITL)** | ✅ Giữ — chính là đối tượng cần test, dựng bằng Temporal |
| **Agent (Orchestrator)** | ✅ Giữ — 1 LLM đóng vai orchestrator, quyết định action mỗi vòng lặp |
| **Specialized Agents** | ✅ Giữ **2 agent**: `Log Investigator Agent`, `Metrics Investigator Agent` |
| Model Gateway (routing/guardrails đa model) | ❌ Bỏ — gọi thẳng 1 model (Claude qua Anthropic API) |
| Tool Gateway (PEP, capability registry thật) | ⚠️ Rút gọn — 2 "tool" là **hàm Python trả dữ liệu giả lập** (fake logs/metrics), không có auth/rate-limit/audit thật, nhưng vẫn giữ nguyên **hình dạng lời gọi** (`capability + arguments` qua 1 lớp trung gian) để sau này thay bằng Tool Gateway thật mà không đổi Orchestrator |
| Evidence Service (DB, provenance, lifecycle) | ⚠️ Rút gọn — evidence là list object trong `self.history` của Workflow, không có Postgres/S3 riêng |
| RCA Proposal | ✅ Giữ — Orchestrator tự tổng hợp bằng LLM, không có model riêng |
| **HITL** | ✅ Giữ — đúng như thiết kế gốc: `workflow.signal` + `workflow.wait_condition` |
| Case / Audit / Trace / Evaluation | ❌ Bỏ — chỉ log ra console + Temporal Event History (đã tự có sẵn, không build thêm) |
| AWS (Bedrock AgentCore, ECS, RDS...) | ❌ Bỏ — chạy 100% local (Temporal dev server local + Postgres local nếu cần, hoặc SQLite) |

→ Nguyên tắc: **giữ đúng hình dạng ranh giới module** (Orchestrator không biết logic gọi tool, tool không biết logic reasoning, workflow không gọi LLM trực tiếp) dù bên trong mỗi module còn rất đơn giản — để nếu POC thành công, việc "lắp" Tool Gateway/Evidence Service thật vào sau này không cần đổi kiến trúc, chỉ đổi implementation.

---

## 2. Kịch bản demo

Mượn đúng tinh thần Incident Investigation của Xora Resolve, thu nhỏ về các incident giả lập, dữ liệu hardcode. Một scenario duy nhất (happy-path → HITL-approve) không đủ để chứng minh pattern chịu được thực tế — mỗi nhánh quyết định của Orchestrator (`CALL_AGENT` lặp lại, `NEEDS_HUMAN` approve/reject, guardrail chặn, vượt `MAX_ITERATIONS`) cần **ít nhất 1 kịch bản demo/test riêng**, dữ liệu fake input khác nhau để ép đúng nhánh đó chạy.

> ⚠️ **Quyết định thiết kế quan trọng (rút ra từ 1 lần chạy thật với Bedrock)**:
> Bản thiết kế ban đầu có 1 action thứ 3 tên `FINISH` — cho phép Orchestrator
> tự kết luận thẳng, bỏ qua HITL, khi nó tự chấm `confidence >= 0.8`. Khi chạy
> thật với Claude 3.5 Sonnet, model tự chấm `0.9` cho 1 chuỗi suy luận chỉ dựa
> trên correlate log/metrics giữa 2 service (không có bằng chứng trực tiếp
> nội bộ service bị nghi ngờ) và bỏ qua HITL hoàn toàn hợp lệ theo code cũ.
> Vấn đề gốc: **`confidence` chỉ là 1 con số LLM tự báo cáo, chưa từng được
> validate/enforce ở đâu trong code** — để 1 thành phần không tin cậy (LLM)
> tự quyết định có cần bị giám sát hay không là sai nguyên tắc guardrail cơ
> bản (không bao giờ để đối tượng cần giám sát tự cấp quyền miễn giám sát cho
> chính nó).
>
> → **Đã bỏ hẳn action `FINISH` khỏi allowlist.** Orchestrator giờ chỉ còn 2
> lựa chọn: `CALL_AGENT` hoặc `NEEDS_HUMAN`. **Mọi RCA, bất kể confidence bao
> nhiêu, đều bắt buộc phải có 1 signal `approve`/`reject` từ con người** mới
> được coi là `FINISHED`. `confidence` vẫn được yêu cầu tính toán và hiển thị
> trên UI, nhưng giờ chỉ mang tính **tham khảo cho người duyệt** (ưu tiên
> incident nào cần xem kỹ hơn), không còn vai trò điều khiển luồng nào cả.
> Xem chi tiết + rationale đầy đủ trong `shared/models.py`.

### Scenario A — Happy-path đầy đủ, kết thúc bằng HITL-approve (kịch bản chính, demo trực tiếp cho stakeholder)

> **Incident**: `checkout-api trả lỗi 500 tăng đột biến lúc 10:30`

```text
1. Orchestrator nhận incident → quyết định: cần xem logs trước
2. → Log Investigator Agent: đọc "logs" giả lập → phát hiện lỗi
   "connection timeout to payment-adapter"
3. Orchestrator: log gợi ý payment-adapter, cần xem thêm metrics
   → Metrics Investigator Agent: đọc "metrics" giả lập → phát hiện
   payment-adapter latency tăng từ 10:28
4. Orchestrator: đủ evidence → tổng hợp RCA hypothesis:
   "payment-adapter là nguyên nhân gây lỗi 500 ở checkout-api"
   (action luôn là NEEDS_HUMAN — không có nhánh nào khác để kết luận)
5. NEEDS_HUMAN → Workflow đóng băng, chờ Signal
6. Analyst xem RCA trên Web UI, bấm "Approve" (+ ghi chú)
7. Workflow nhận Signal approve → status = FINISHED → trả kết quả cuối,
   in toàn bộ Execution Trace (đã được Temporal ghi Event History)
```

Fake data dùng riêng cho scenario này (`incident_checkout_payment_timeout.json`) mô tả 1 chuỗi correlate log/metrics giữa 2 service — dù đủ thuyết phục để model tự tin cao (đã quan sát thực tế: Claude 3.5 Sonnet tự chấm 0.9), vẫn luôn phải qua HITL vì action `FINISH` không còn tồn tại.

### Scenario B — HITL-reject: analyst từ chối RCA, workflow phải xử lý đúng, không tự ý FINISH

```text
1-5. Giống Scenario A, tới bước NEEDS_HUMAN.
6. Analyst bấm "Reject" trên Web UI kèm ghi chú
   "Chưa đủ bằng chứng, cần kiểm tra thêm topology"
7. Workflow nhận Signal reject → append note vào history →
   quay lại vòng lặp (iteration += 1, KHÔNG return ngay) →
   Orchestrator đọc note, quyết định action tiếp theo
   (vd gọi thêm agent khác, hoặc NEEDS_HUMAN lần 2 với RCA mới)
```

Verify: reject **không được** làm Workflow crash hay tự FINISH với kết quả cũ — phải quay lại vòng lặp với context đã cập nhật ghi chú từ chối.

### Scenario C — Evidence rất rõ ràng (confidence cao) — VẪN bắt buộc qua HITL

> **Incident**: `checkout-api trả lỗi 500, log có stacktrace rõ ràng trỏ thẳng tới lỗi cấu hình DB connection string`

```text
1. Orchestrator → Log Investigator Agent: log rất rõ ràng, chỉ ra
   đúng 1 nguyên nhân duy nhất, không mơ hồ (exception nội bộ, không
   cần correlate qua service khác).
2. Orchestrator: đủ evidence, RCA hypothesis confidence rất cao
   (model có thể tự chấm 0.9+) — NHƯNG action vẫn PHẢI là NEEDS_HUMAN,
   vì "FINISH" không tồn tại trong allowlist.
3. Workflow đóng băng ở WAITING_HUMAN y hệt Scenario A — không có
   đường tắt nào cho evidence "quá rõ ràng".
```

Verify: đây là scenario **quan trọng nhất để khoá lại quyết định thiết kế** — kể cả khi evidence rõ ràng tới mức lẽ ra một con người cũng sẽ kết luận ngay lập tức, hệ thống vẫn không được phép tự động kết thúc mà không có signal approve/reject. Test `test_scenario_c_high_confidence_still_requires_hitl` (mock confidence = 0.95) và `test_legacy_finish_action_no_longer_completes_workflow` (mock action = "FINISH" trực tiếp, giả lập 1 Activity lỗi/rogue) đều phải fail nếu ai đó vô tình thêm lại đường tắt này.

### Scenario D — Circuit breaker: vượt `MAX_ITERATIONS`

> Set `MAX_ITERATIONS = 2` (thấp hơn bình thường), dùng incident cần ≥ 3 bước để có đủ evidence (log mơ hồ, cần gọi thêm agent thứ 3 giả lập hoặc gọi lặp lại log_agent/metrics_agent nhiều lần).

```text
1-2. Orchestrator gọi agent 2 lần liên tiếp, vẫn chưa đủ evidence
     để tự tin đưa ra RCA (confidence không đạt, cần thêm bước).
3. iteration == MAX_ITERATIONS → thoát while loop bằng nhánh
   escalate_to_human (không phải NEEDS_HUMAN bình thường) →
   trả về "escalated", không loop vô hạn.
```

Verify: workflow không bị treo/loop vô hạn khi Orchestrator "không biết dừng" — đúng như rủi ro nêu ở tài liệu gốc.

### Scenario E — Guardrail chặn hành vi sai (allowlist violation)

> Cố tình chỉnh prompt/response giả lập để Orchestrator trả về `agent_name` ngoài allowlist (vd `"shell_agent"` hoặc action lạ `"CALL_TOOL_DIRECTLY"`).

```text
1. Activity `ask_orchestrator` nhận response từ LLM có agent_name
   không nằm trong {"log_agent", "metrics_agent"}.
2. Validate ngay trong Activity → reject, KHÔNG trả quyết định đó
   về Workflow → retry với prompt nhắc lại allowlist, hoặc nếu
   retry vẫn sai → coi như lỗi Activity, để Workflow xử lý theo
   retry_policy/escalate, tuyệt đối không execute action ngoài
   allowlist.
```

Verify: đây là bài test bảo mật/guardrail quan trọng nhất của toàn bộ pattern — Orchestrator (LLM, không tin cậy tuyệt đối) không bao giờ được phép trực tiếp điều khiển Workflow gọi Activity tuỳ ý.

→ 5 scenario trên (A–E) là **bộ tối thiểu bắt buộc** phải chạy được trước khi kết luận POC pass — không dừng ở scenario A. Mapping trực tiếp với tiêu chí thành công ở mục 7 (mỗi tiêu chí ở mục 7 nên trỏ về đúng 1 scenario ở đây để test).

---

## 3. Kiến trúc POC

```text
┌─────────────────────┐
│   Web UI (browser)   │   (submit incident, xem trace realtime, approve/reject)
└──────────┬───────────┘
           │ REST/HTTP
           ▼
┌─────────────────────┐
│   Backend Server     │   (FastAPI — wrap Temporal Client, không chứa business logic)
│   (Temporal Client)  │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│         Temporal Workflow (durable)          │
│         IncidentInvestigationWorkflow        │
│                                               │
│   while iteration < MAX_ITERATIONS:          │
│     decision = ask_orchestrator(history)     │
│     if NEEDS_HUMAN    → wait_condition(sig)  │  ← LUÔN bắt buộc,
│                          approve→FINISHED /     không có FINISH
│                          reject→continue        trực tiếp nào cả
│     if CALL_AGENT      → run_agent(name,args)│
└──────────┬───────────────────┬───────────────┘
           │ (Activity)        │ (Activity)
           ▼                   ▼
 ┌─────────────────┐   ┌─────────────────────────┐
 │ ask_orchestrator │   │ run_agent(agent_name)   │
 │  (gọi LLM,        │   │  ├── log_agent          │
 │   role=Orchestrator)  │  └── metrics_agent       │
 └─────────────────┘   └──────────┬──────────────┘
                                  ▼
                        ┌─────────────────────┐
                        │  Fake Tool Layer     │
                        │  get_incident_logs() │
                        │  get_incident_metrics()│
                        │  (data hardcode/JSON) │
                        └─────────────────────┘
```

**3 Activity duy nhất** (đúng nguyên tắc "mọi phần non-deterministic nằm trong Activity"):

- `ask_orchestrator(history) -> Decision` — gọi LLM đóng vai Orchestrator, trả JSON `{action, agent_name?, args?, rca_proposal?}`. **Không có `final_answer` ở đây** — Orchestrator không được phép tự viết kết luận cuối cùng, chỉ được *đề xuất* RCA (`rca_proposal`) để người duyệt xem.
- `run_agent(agent_name, args) -> AgentResult` — gọi LLM đóng vai 1 trong 2 Specialized Agent (system prompt khác nhau), agent này *tự chọn* gọi fake-tool tương ứng, trả evidence có cấu trúc.
- `notify_human(payload)` — giả lập gửi thông báo cho analyst (POC: chỉ log ra console/ghi file).

**Allowlist bắt buộc** (đúng guardrail đã nêu trong tài liệu gốc): Orchestrator chỉ được chọn `agent_name ∈ {"log_agent", "metrics_agent"}`, action ∈ `{CALL_AGENT, NEEDS_HUMAN}` — **không có `FINISH`** (xem cảnh báo ở mục 2) — validate ngay trong `ask_orchestrator` trước khi trả về Workflow, reject/retry nếu LLM trả giá trị ngoài allowlist.

**Backend Server tách riêng khỏi Worker** — 2 process khác nhau dù cùng codebase, đúng nguyên tắc "Workflow code phải deterministic, mọi phần gọi ra ngoài nằm trong Activity/Worker":

- **Worker**: đăng ký `IncidentInvestigationWorkflow` + 3 Activity, chạy `worker.run()` — không expose HTTP, chỉ poll task queue của Temporal.
- **Backend Server** (FastAPI): *chỉ* là Temporal Client mỏng, expose REST cho Web UI — `POST /incidents` (start workflow), `GET /incidents/{id}` (query state), `POST /incidents/{id}/approve|reject` (signal). Backend không chứa business logic, không gọi LLM — tách để UI có 1 điểm gọi HTTP quen thuộc thay vì phải nhúng Temporal SDK vào frontend.

---

## 4. State rút gọn của Workflow

```python
class IncidentInvestigationWorkflow:
    incident_id: str
    history: list[dict]          # {role, content} tích lũy — chính là "evidence log"
    evidence: list[dict]         # {source, fact, confidence} — tách riêng khỏi history để dễ đọc
    rca_proposal: dict | None    # {hypothesis, confidence, supporting_evidence_refs}
    approved: bool | None
    approval_note: str | None
    iteration: int
```

- `evidence` đóng vai trò **Evidence Service rút gọn**: mỗi lần Specialized Agent trả evidence mới, Workflow append vào đây (thay vì gọi 1 Evidence Service thật). Đây chính là chỗ dễ tách ra thành service riêng sau này (đúng nguyên tắc "module boundary = future service boundary").
- `rca_proposal` đóng vai trò RCA Proposal — **luôn luôn** dẫn tới nhánh `NEEDS_HUMAN`, bất kể `confidence` là bao nhiêu (không còn ngưỡng nào quyết định bỏ qua HITL — xem cảnh báo thiết kế ở mục 2). `confidence` chỉ là field hiển thị tham khảo cho người duyệt.

Query handler để đọc state khi đang chạy (không cần đợi workflow xong):

```python
@workflow.query
def get_state(self) -> dict:
    return {
        "iteration": self.iteration,
        "evidence": self.evidence,
        "rca_proposal": self.rca_proposal,
        "status": "WAITING_HUMAN" if self.rca_proposal and self.approved is None else "RUNNING",
    }
```

---

## 5. Tech stack đề xuất — tối giản tối đa

| Thành phần | Chọn | Vì sao |
| --- | --- | --- |
| Workflow engine | **Temporal**, self-hosted qua Docker (`temporalio/temporal` — Temporal CLI `server start-dev`, SQLite embedded — không cần Postgres riêng cho POC) | Chạy 100% local qua `docker compose up`, có sẵn Temporal Web UI xem Event History/replay — test đúng thứ cần test (durability + signal) mà không cần AWS cho phần workflow engine |
| LLM | **Claude 3.5 Sonnet qua AWS Bedrock**, gọi **trực tiếp bằng AWS SDK (`boto3`)** — Bedrock Runtime "Converse API" (`bedrock-runtime.converse(...)`), **không** qua thư viện `anthropic`/`AnthropicBedrock`. Xác thực bằng AWS credentials mount read-only từ `~/.aws` trên host — **không dùng API key riêng** | Khớp với việc team đã có sẵn AWS account/Bedrock Model Access; dùng đúng AWS SDK chuẩn (không phụ thuộc SDK bên thứ 3 có thể lỗi thời/khác version so với AWS SDK), interface Converse thống nhất cho mọi model trên Bedrock chứ không riêng Anthropic. Đây **không phải** Bedrock AgentCore (agent runtime) — chỉ đổi model provider, tương đương "Model Gateway" rút gọn |
| Ngôn ngữ backend | Python (`temporalio` SDK + `boto3` + FastAPI) | Khớp code mẫu đã có trong tài liệu gốc |
| Quản lý dependency Python | **uv** (`pyproject.toml` + `uv.lock`) cho cả Backend lẫn Worker | uv nhanh, lockfile reproducible, đồng nhất cách quản lý dependency giữa 2 service Python thay vì trộn pip + uv |
| Backend API | **FastAPI**, container riêng, chỉ đóng vai Temporal Client mỏng (không chứa Worker) | Tách để restart/scale độc lập với Worker; là điểm HTTP duy nhất mà UI cần biết |
| DB / state lâu dài | **Không cần** — Temporal tự giữ state qua Event History cho phạm vi POC | Giảm tối đa setup |
| Giao diện HITL | **Vite + React + TypeScript**, build tĩnh serve qua nginx — cùng convention với `xbrain-workspace/apps/web` (alias `@/*`, `tsconfig` app/node tách riêng, nginx proxy `/api` same-origin) | Trực quan hơn CLI để demo cho stakeholder không quen dòng lệnh; khớp stack frontend đã dùng trong workspace thay vì tự chế 1 convention khác cho riêng POC |
| Fake tools | JSON hardcode theo từng scenario (`shared/data/scenarios/*/logs.json`, `metrics.json`) | Không cần tích hợp Datadog/ITSM thật |
| Đóng gói & chạy local | **Docker Compose** — 4 service: `temporal` (server), `worker`, `backend`, `ui` | 1 lệnh `docker compose up` dựng toàn bộ POC, đúng tinh thần "chạy được trong vài ngày", không ai phải tự cài Temporal/Python/Node trên máy |

**Không dùng** trong POC: Tool Gateway service riêng, Model Gateway thật (đa
model/routing), Postgres schema theo domain, S3, AWS ECS/EventBridge/SQS,
multi-tenant, Audit/Case/Evaluation module, Bedrock AgentCore (agent
runtime — khác với việc chỉ dùng Bedrock làm model provider ở trên).

---

## 6. Cấu trúc thư mục đề xuất

```text
temporal-agent-workflow/
│
├── README.md
├── docker-compose.yml          # temporal + worker + backend + ui, 1 lệnh chạy toàn bộ
│
├── shared/                     # code dùng chung giữa worker & backend (cùng build context)
│   ├── data/                    # mỗi scenario (mục 2) có 1 bộ fake data riêng để ép đúng nhánh
│   │   ├── scenario_a_checkout_payment_timeout/
│   │   │   ├── logs.json
│   │   │   └── metrics.json
│   │   ├── scenario_b_hitl_reject/
│   │   ├── scenario_c_auto_finish_clear_stacktrace/
│   │   ├── scenario_d_max_iterations/
│   │   └── scenario_e_allowlist_violation/       # không cần data thật, chỉ cần fake LLM response
│   │   └── ...
│   ├── workflows.py            # IncidentInvestigationWorkflow (while-loop + signal)
│   ├── activities.py           # ask_orchestrator, run_agent, notify_human
│   ├── agents/
│   │   ├── orchestrator_prompt.py
│   │   ├── log_agent_prompt.py
│   │   └── metrics_agent_prompt.py
│   └── tools/
│       ├── incident_logs.py     # get_incident_logs(service, time_range)
│       └── incident_metrics.py  # get_incident_metrics(service, time_range)
│
├── worker/
│   ├── Dockerfile               # build bằng uv (uv sync --frozen)
│   ├── pyproject.toml           # uv — temporalio + boto3
│   ├── uv.lock
│   └── main.py                  # đăng ký Workflow + Activities (từ shared/), start Temporal worker
│
├── backend/
│   ├── Dockerfile               # build bằng uv (uv sync --frozen)
│   ├── pyproject.toml
│   ├── uv.lock
│   └── main.py                  # FastAPI: POST /incidents, GET /incidents/{id}, POST /incidents/{id}/approve|reject
│
├── ui/                           # Vite + React + TypeScript, cùng convention với xbrain-workspace/apps/web
│   ├── Dockerfile                # 2 giai đoạn: node build (Vite) → nginx serve tĩnh + proxy /api
│   ├── nginx.conf                # template — envsubst ${API_UPSTREAM} lúc container start
│   ├── package.json
│   ├── vite.config.ts            # alias @/* , dev/preview proxy /api -> API_URL
│   ├── tsconfig.json / tsconfig.app.json / tsconfig.node.json
│   └── src/
│       ├── main.tsx / App.tsx
│       ├── types.ts
│       ├── lib/api.ts             # fetch wrapper, luôn gọi qua "/api" (cùng-origin ở mọi môi trường)
│       └── components/
│           ├── IncidentForm.tsx
│           ├── ExecutionTrace.tsx  # timeline realtime (poll GET /incidents/{id})
│           └── ApprovalPanel.tsx   # RCA proposal + nút Approve/Reject + ô ghi chú
│
└── tests/
    └── test_workflow.py          # dùng Temporal test framework (time-skipping) để test happy-path + HITL
```

`docker-compose.yml` (sơ lược 4 service — **đã implement và verify chạy được
thật**, xem [README.md](README.md) mục "Kết quả đã verify" để biết chi tiết
và các điểm phải sửa so với bản phác thảo ban đầu):

```yaml
services:
  temporal:
    image: temporalio/temporal:latest   # Temporal CLI `server start-dev`, SQLite persistence, kèm Web UI
    entrypoint: ["temporal", "server", "start-dev"]
    command:
      - --ip=0.0.0.0
      - --port=7233
      - --ui-ip=0.0.0.0
      - --ui-port=8233               # Web UI mặc định = port gRPC + 1000, không phải 8080
      - --db-filename=/home/temporal/temporal.db  # image chạy user non-root "temporal", /data không ghi được
    ports: ["7233:7233", "8233:8233"]
    volumes: ["temporal-data:/home/temporal"]

  worker:
    build: {context: ., dockerfile: worker/Dockerfile}
    depends_on: {temporal: {condition: service_healthy}}
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
      # AWS Bedrock — KHÔNG có ANTHROPIC_API_KEY nào ở đây.
      - AWS_PROFILE=${AWS_PROFILE:-default}
      - AWS_REGION=${AWS_REGION:-us-east-1}
      - BEDROCK_MODEL_ID=${BEDROCK_MODEL_ID:-apac.anthropic.claude-3-5-sonnet-20241022-v2:0}  # inference profile — nhiều region không hỗ trợ on-demand trực tiếp
    volumes:
      - ${HOME}/.aws:/root/.aws:ro   # đọc AWS credentials từ host, không copy secrets vào image

  backend:
    build: {context: ., dockerfile: backend/Dockerfile}   # Dockerfile dùng uv sync --frozen
    depends_on: {temporal: {condition: service_healthy}}
    ports: ["8000:8000"]
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
    healthcheck: {test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]}

  ui:
    build: ./ui   # 2-stage: npm run build (Vite) rồi COPY dist/ vào nginx
    depends_on: {backend: {condition: service_healthy}}
    ports: ["3000:80"]
```

→ `docker compose up` là đủ để có: Temporal server + Web UI (audit trace,
port 8233), Worker (chạy Workflow/Activity), Backend API (port 8000), và Web
UI demo (port 3000) — không ai cần cài Python/Node/Temporal CLI trực tiếp
trên máy.

---

## 7. Câu hỏi POC cần trả lời (tiêu chí thành công)

POC coi là **thành công** nếu chứng minh được cả 5 điều dưới đây bằng cách chạy thật (không phải suy luận trên giấy). Mỗi tiêu chí trỏ về đúng 1 scenario cụ thể ở mục 2 để test, không kiểm tra chung chung:

1. **Determinism** (verify trên Scenario A hoặc B): Workflow **replay lại đúng y hệt** sau khi kill/restart Worker giữa chừng vòng lặp (test bằng cách `docker compose restart worker` lúc đang ở iteration 2, xem Temporal tự phục hồi đúng state, UI vẫn hiển thị đúng timeline sau khi worker sống lại).
2. **HITL không tốn tài nguyên khi chờ** (verify trên Scenario A + B): Workflow ở trạng thái `NEEDS_HUMAN` không có Activity/Worker nào đang chạy (kiểm tra bằng Temporal Web UI — không thấy Activity pending), có thể "approve" hoặc "reject" sau một khoảng chờ tuỳ ý (test thử chờ vài phút) mà không mất context Agent 1/Agent 2 đã thu thập; Scenario B còn phải verify thêm reject không làm mất/ghi đè context cũ.
3. **HITL là bắt buộc tuyệt đối, không có đường tắt dựa trên confidence tự chấm** (verify trên Scenario C): kể cả khi Orchestrator tự chấm confidence rất cao (0.9+), Workflow vẫn phải dừng ở `NEEDS_HUMAN`, không có action nào để tự kết luận (`FINISH` đã bị loại khỏi allowlist — xem cảnh báo thiết kế ở mục 2). Test `test_legacy_finish_action_no_longer_completes_workflow` khoá lại: nếu 1 Activity (bug/rogue) trả về `action="FINISH"`, Workflow phải escalate an toàn thay vì coi đó là hoàn thành hợp lệ.
4. **Circuit breaker hoạt động** (verify trên Scenario D): Set `MAX_ITERATIONS` cố tình thấp (vd = 2) với 1 incident cần ≥3 bước → Workflow phải rơi vào nhánh `escalate_to_human`/kết thúc an toàn, không loop vô hạn.
5. **Allowlist chặn được hành vi sai** (verify trên Scenario E): Cố tình prompt-inject để LLM trả về `agent_name` không nằm trong allowlist (vd `"shell_agent"`) → Activity `ask_orchestrator` phải reject/retry, Workflow không được phép gọi Activity ngoài danh sách.
6. **Audit được** (verify trên tất cả scenario A–E): Từ Temporal Web UI, dựng lại được toàn bộ trình tự quyết định (Orchestrator gọi agent nào, evidence gì được tạo, ai duyệt/từ chối lúc nào) chỉ từ Event History — không cần hệ thống log riêng.

Nếu cả 5 điều trên pass → kết luận: pattern While-Loop + Orchestrator Agent của [Dynamic Agent Loop Orchestration.md](../agent-workflow/Dynamic%20Agent%20Loop%20Orchestration.md) khả thi để làm nền cho Execution Engine thật của Xora Resolve.

---

## 8. Rủi ro & giới hạn đã biết của POC (không cần fix ở giai đoạn này)

- Fake tools trả dữ liệu tĩnh → không test được lỗi mạng/timeout thật của tool call (chấp nhận được, đó là việc của Tool Gateway thật, không phải của Execution Engine).
- Không có multi-tenant/auth → không test được nhánh Admission/Policy.
- 1 model duy nhất, không test được model routing/fallback (việc của Model Gateway).
- Evidence lưu trong Workflow state (Event History) — POC **cố tình chưa** tách ra external store, chỉ note lại rủi ro phình Event History (mục 3 + mục 5 của tài liệu gốc) để chứng minh bằng thực nghiệm nếu chạy nhiều vòng lặp hơn `continue_as_new` threshold.
- Không benchmark chi phí token/latency — POC là bài test kiến trúc, không phải bài test hiệu năng.

---

## 9. Các bước tiếp theo sau POC (không làm ngay)

- Nếu pass: thử thay 1 trong 2 fake tool bằng 1 API thật (vd gọi thật 1 log aggregator) để test ranh giới Tool Gateway rút gọn có "lắp" API thật vào dễ không.
- Thử `continue_as_new` bằng cách ép incident chạy > 50 vòng lặp giả lập, đo Event History size trước/sau.
- Thử thay Anthropic API trực tiếp bằng Bedrock AgentCore Runtime (đổi implementation của `AgentRuntime` Protocol) để đo thêm chi phí/độ trễ tích hợp AWS thật — **chỉ làm khi đã có ngân sách AWS**, không phải điều kiện để đánh giá POC này.
