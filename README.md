# Xora POC — Dynamic Agent Loop + Multi-Agent + HITL

Implementation của [POC Design - Dynamic Agent Loop.md](POC%20Design%20-%20Dynamic%20Agent%20Loop.md).
Đây là bản chạy được của pattern **While-Loop + Orchestrator Agent** (xem
[../agent-workflow/Dynamic Agent Loop Orchestration.md](../agent-workflow/Dynamic%20Agent%20Loop%20Orchestration.md)),
thu nhỏ từ ý tưởng "Incident Investigation Runtime" của Xora Resolve.

Stack: **uv** (backend + worker, Python) + **Vite/React/TypeScript** (UI) +
**AWS Bedrock** (Claude 3.5 Sonnet, gọi trực tiếp bằng AWS SDK/boto3 — không
qua SDK `anthropic`, xác thực qua AWS credentials mount từ host, không API
key riêng). Đã verify build + chạy thật qua Docker (xem
[Kết quả đã verify](#kết-quả-đã-verify)).

## Chạy thử

1. Cần Docker + Docker Compose, và AWS credentials đã cấu hình trên host
   (`~/.aws/credentials`, vd qua `aws configure`) với Claude 3.5 Sonnet đã
   được enable trong **Bedrock Model Access** ở region bạn dùng.
2. Copy `.env.example` thành `.env`, chỉnh `AWS_PROFILE`/`AWS_REGION`/
   `BEDROCK_MODEL_ID` cho khớp.
3. `docker compose up --build`
4. Mở:
   - **Web UI**: http://localhost:3000 — submit incident, xem trace realtime, approve/reject.
   - **Backend API** (FastAPI docs): http://localhost:8000/docs
   - **Temporal Web UI** (Event History, replay): http://localhost:8233

Trong Web UI: chọn 1 trong 5 scenario ở dropdown (mô tả incident tự điền theo
scenario, xem [mục 2 của design doc](POC%20Design%20-%20Dynamic%20Agent%20Loop.md#2-kịch-bản-demo)),
bấm **Submit incident**, theo dõi timeline cập nhật mỗi 1.5s. Khi status
chuyển `WAITING_HUMAN`, panel Approve/Reject hiện ra.

> Lưu ý: Scenario B dùng chung `scenario_id` với A (data giống nhau) — để test
> nhánh reject, cứ submit rồi bấm **Reject** thay vì **Approve** khi tới bước
> HITL. Scenario E có "test hook" mô phỏng LLM trả kết quả sai allowlist —
> không phụ thuộc việc prompt-injection có "ăn" trên model thật hay không, và
> không gọi Bedrock (xem `shared/activities.py::ask_orchestrator`) — chạy
> được ngay cả khi chưa cấu hình AWS credentials.

## Hướng dẫn test Scenario A/B/C/D end-to-end với Claude 3.5 Sonnet thật

Khác với Scenario E (có test hook, không gọi Bedrock), 4 scenario này gọi
**model thật** — sẽ phát sinh chi phí Bedrock (nhỏ, vài request/scenario) và
cần AWS credentials + Model Access hợp lệ. Làm theo thứ tự dưới đây, kiểm tra
lại kết quả với đúng phần "Verify" tương ứng ở [mục 2 của design doc](POC%20Design%20-%20Dynamic%20Agent%20Loop.md#2-kịch-bản-demo)
trước khi kết luận scenario đó pass.

### 0. Chuẩn bị

```bash
cp .env.example .env
# chỉnh AWS_PROFILE/AWS_REGION/BEDROCK_MODEL_ID cho khớp account của bạn
docker compose up --build -d
docker compose ps        # cả 4 service phải "healthy"/"running", không restart-loop
```

Mở sẵn 2 tab: **Web UI** (http://localhost:3000) và **Temporal Web UI**
(http://localhost:8233 → chọn workflow theo `incident_id` để xem Event
History/Timeline) — dùng để đối chiếu khi cần audit lại quyết định của model.

### Cách xác nhận workflow đang thực sự "pending" ở bước HITL

Áp dụng cho mọi scenario có bước `WAITING_HUMAN` (A, B, C) — dùng để verify
tiêu chí #2 ở mục 7 design doc ("HITL không tốn tài nguyên khi chờ"), không
chỉ tin vào status hiển thị trên Web UI của POC.

**1. Trên Temporal Web UI (trực quan nhất)**

1. Mở http://localhost:8233 → namespace `default` → tab **Workflows**.
2. Tìm theo `Workflow ID` = `incident-xxxxxxxx` (copy từ Web UI của POC hoặc
   từ response `POST /incidents`) — hoặc filter `Status: Running` để lọc ra
   các workflow chưa kết thúc.
3. Click vào workflow đó → tab **Summary**:
   - `Status` = **Running** (chưa `Completed`).
   - Mục **Pending Activities** phải **rỗng** — đây chính là bằng chứng
     "0 CPU/RAM": không có Activity nào đang chạy/chờ retry cho workflow
     này, nó chỉ đang "ngủ" chờ Signal.
4. Tab **History** (Event History) → cuộn xuống cuối: sự kiện cuối cùng phải
   là `WorkflowTaskCompleted` ngay sau khi `ask_orchestrator` trả về
   `NEEDS_HUMAN` — **không có** `ActivityTaskScheduled` nào mới sau đó. Nếu
   có thêm activity đang chạy, đó là dấu hiệu code có bug (không thực sự dừng).

**2. Query trực tiếp `get_state` từ Web UI (không cần gọi API riêng)**

Trong trang chi tiết workflow, tìm tab/nút **Query Workflow** → chọn
`get_state` → Run. Kết quả JSON trả về phải có `"status": "WAITING_HUMAN"` —
đây chính là query handler `@workflow.query` trong `shared/workflows.py`,
đọc trực tiếp state mà không cần chờ workflow chạy xong.

**3. Xác nhận bằng CLI (chắc chắn nhất — đúng tinh thần "audit từ Event History")**

```bash
# Mô tả workflow — xem status + pending activities
docker compose exec temporal temporal workflow describe --workflow-id <incident-id>

# Query trực tiếp get_state qua CLI (tương đương gọi query từ Web UI)
docker compose exec temporal temporal workflow query \
  --workflow-id <incident-id> \
  --type get_state

# Xác nhận KHÔNG có Activity nào đang chạy cho workflow này
docker compose exec temporal temporal workflow show \
  --workflow-id <incident-id> \
  --output json | grep -i "ActivityTaskScheduled\|ActivityTaskStarted" | tail -5
# → dòng cuối cùng phải dừng ở lần gọi ask_orchestrator TRƯỚC KHI vào
#   NEEDS_HUMAN, không có activity nào mới xuất hiện cho tới khi approve/reject.
```

**Bằng chứng thuyết phục nhất**: sau khi thấy `Status: Running` + `Pending
Activities` rỗng, thử đợi vài phút (không làm gì cả) rồi mới bấm
Approve/Reject — nếu context/evidence của Agent 1, Agent 2 vẫn còn nguyên
trong `get_state()`, đó là bằng chứng Temporal thực sự "đóng băng" workflow
(0 compute) chứ không phải polling ngầm.

### A — Happy-path, dừng ở HITL rồi Approve

1. Web UI → chọn scenario **"A — Happy-path..."** → **Submit incident**.
2. Theo dõi timeline: kỳ vọng thấy `orchestrator` gọi `log_agent` trước, rồi
   `metrics_agent`, rồi 1 lần `orchestrator` nữa với `action: NEEDS_HUMAN` và
   `rca_proposal.confidence` (mô hình tự chấm — con số này giờ **chỉ mang
   tính tham khảo**, không còn quyết định có cần HITL hay không, vì action
   `FINISH` đã bị loại khỏi allowlist — xem [mục 2 của design doc](POC%20Design%20-%20Dynamic%20Agent%20Loop.md#2-kịch-bản-demo)).
3. Khi status chuyển `WAITING_HUMAN`, panel Approve/Reject hiện ra → bấm
   **Approve** kèm ghi chú bất kỳ.
4. **Verify pass**: status cuối = `FINISHED` (chỉ sau khi bạn bấm Approve —
   **không bao giờ** tự chuyển FINISHED trước đó dù confidence cao thế nào),
   `final_answer` nhắc tới `payment-adapter` (hoặc nguyên nhân tương đương
   model tự suy ra từ log/metrics giả lập).

### B — Giống A nhưng Reject thay vì Approve

1. Submit **cùng scenario A** (hoặc chọn mục "B — ...HITL-Reject" trong dropdown).
2. Tới bước `WAITING_HUMAN`, bấm **Reject** kèm ghi chú cụ thể, vd
   *"Chưa đủ bằng chứng, kiểm tra thêm topology trước khi kết luận"*.
3. **Verify pass**: workflow **không** kết thúc ngay — quay lại `RUNNING`,
   `iteration` tăng thêm, và lần gọi `ask_orchestrator` kế tiếp phải phản ánh
   đã đọc ghi chú reject (xem trong Temporal Web UI → input của activity call
   tiếp theo có chứa `role: human, content: {approved: false, note: "..."}`).
   Cuối cùng vẫn nên đi tới `FINISHED` hoặc `WAITING_HUMAN` lần 2 — miễn
   **không lặp lại y hệt** RCA vừa bị reject.

### C — Evidence rất rõ ràng — vẫn PHẢI qua HITL (không có auto-finish)

Đây là scenario quan trọng nhất để verify quyết định thiết kế: **không có
đường tắt nào** cho phép bỏ qua người duyệt, kể cả khi evidence rõ ràng tới
mức 1 con người cũng sẽ kết luận ngay lập tức.

1. Submit scenario **"C — Evidence rất rõ ràng..."** — log giả lập cố tình
   có stacktrace rất rõ ràng (`psycopg2.OperationalError`, config sai sau
   deploy) — đủ để model tự tin rất cao (0.9+).
2. **Verify pass**: dù confidence cao, workflow **vẫn dừng ở
   `WAITING_HUMAN`**, panel Approve/Reject vẫn hiện ra bình thường — giống
   hệt Scenario A, không có nhánh nào tự động `FINISHED` mà thiếu signal.
   Bấm Approve để hoàn tất.
3. Nếu bạn thấy workflow **tự chuyển `FINISHED` mà không có bước duyệt nào**
   — đó **là bug thật**, cần báo lại ngay (kiểm tra `shared/models.py` xem
   `ALLOWED_ACTIONS` có bị thêm nhầm `"FINISH"` trở lại không).

### D — Circuit breaker (vượt MAX_ITERATIONS)

1. Submit scenario **"D — Circuit breaker..."**, **quan trọng: đặt Max
   iterations = 2** trong form trước khi Submit (data cố tình mơ hồ để cần
   ≥ 3 bước mới đủ evidence).
2. **Verify pass**: status cuối = `ESCALATED` sau đúng 2 vòng gọi
   `ask_orchestrator`, không treo/loop vô hạn. Kiểm tra Temporal Web UI: đúng
   2 lần `AgentInvoked`/activity `ask_orchestrator`, không có lần thứ 3.

### Troubleshooting lỗi Bedrock thường gặp

| Lỗi thấy trong `docker compose logs worker` | Nguyên nhân | Cách sửa |
| --- | --- | --- |
| `AccessDeniedException: ... don't have access to the model` | Model chưa được enable trong **Bedrock Model Access** ở đúng region | Vào AWS Console → Bedrock → Model access → enable Claude 3.5 Sonnet cho `AWS_REGION` trong `.env` |
| `ValidationException: ... model identifier is invalid` hoặc `on-demand throughput isn't supported` | Model ID sai, hoặc region này chỉ hỗ trợ model qua **inference profile** (không hỗ trợ on-demand trực tiếp) | Đổi `BEDROCK_MODEL_ID` sang dạng có tiền tố vùng, vd `apac.anthropic.claude-3-5-sonnet-20241022-v2:0` cho `ap-southeast-1` — xem comment trong `.env.example` |
| `UnrecognizedClientException` / `InvalidSignatureException` | AWS credentials không hợp lệ hoặc mount sai | Kiểm tra `docker compose exec worker ls -la /root/.aws`, xác nhận `AWS_PROFILE` trong `.env` khớp đúng tên profile trong `~/.aws/credentials` |
| `ThrottlingException` | Vượt rate limit Bedrock (hiếm với tần suất test POC) | Temporal tự retry activity theo default retry policy — đợi vài giây, hoặc giảm số incident submit song song |
| Không có lỗi nhưng workflow luôn escalate ngay iteration 0 | LLM trả JSON không parse được (`ModelOutputParseError`) — model chèn text ngoài JSON dù đã dặn trong prompt | Xem field `reason` trong response `GET /incidents/{id}` hoặc log worker để đọc raw text model trả về, cân nhắc strict hơn trong `ORCHESTRATOR_SYSTEM_PROMPT` |

### Chạy UI ở chế độ dev (không qua Docker)

```bash
cd ui
npm install
npm run dev      # http://localhost:3000, proxy /api -> API_URL (mặc định :8000)
```

Cần backend chạy sẵn (`cd backend && uv sync && uv run uvicorn backend.main:app --reload --port 8000`)
và worker chạy riêng (`cd worker && uv sync && uv run python main.py`).

## Chạy test (mock activities, không gọi Bedrock)

```bash
docker run --rm -v "$PWD":/app -w /app python:3.12-slim bash -c "
  pip install temporalio==1.9.0 boto3==1.35.99 pytest==8.3.4 pytest-asyncio==0.24.0 &&
  PYTHONPATH=/app python -m pytest tests/ -v
"
```

6 test: 5 test tương ứng 5 scenario ở mục 2 của design doc + 1 test regression
(`test_legacy_finish_action_no_longer_completes_workflow`) khoá lại việc action
`FINISH` đã bị loại khỏi allowlist — mock cả 3 Activity
(`ask_orchestrator`/`run_agent`/`notify_human`) để test đúng LOGIC của
while-loop bằng Temporal time-skipping test framework — không gọi model thật.

## Kiến trúc thư mục

```text
docker-compose.yml      # temporal + worker + backend + ui
shared/                 # code dùng chung giữa worker & backend
  models.py              # allowlist/hằng số dùng chung (guardrail)
  workflows.py           # IncidentInvestigationWorkflow (while-loop + HITL signal)
  activities.py          # ask_orchestrator / run_agent / notify_human (gọi Bedrock qua boto3)
  agents/                # system prompt của Orchestrator + 2 Specialized Agent
  tools/                 # Fake Tool Layer — đọc fake data thay vì gọi API thật
  data/scenarios/        # fake log/metrics data, 1 bộ riêng cho mỗi scenario
worker/                 # container Worker — đăng ký Workflow+Activities, uv (pyproject.toml + uv.lock)
backend/                # container Backend — FastAPI, Temporal Client mỏng, uv (pyproject.toml + uv.lock)
ui/                     # container UI — Vite + React + TypeScript, build tĩnh, serve qua nginx (proxy /api)
tests/                  # test workflow logic (time-skipping, mock activities)
```

Xem giải thích đầy đủ (vì sao tách như vậy, cái gì rút gọn so với kiến trúc
thật) ở [POC Design - Dynamic Agent Loop.md](POC%20Design%20-%20Dynamic%20Agent%20Loop.md).

## Vì sao AWS Bedrock (gọi trực tiếp bằng boto3) thay vì Anthropic API

Worker gọi model bằng **AWS SDK (`boto3`) trực tiếp** tới Bedrock Runtime
"Converse API" (`bedrock-runtime.converse(...)`) — **không** dùng thư viện
`anthropic`/`AnthropicBedrock` (interface riêng của Anthropic), mà dùng đúng
API chuẩn của AWS cho mọi model trên Bedrock. Xác thực qua AWS credential
chain chuẩn (env vars → `~/.aws/credentials`/`~/.aws/config` → instance
profile), **không có API key nào trong code hay biến môi trường**.
`docker-compose.yml` mount `~/.aws:/root/.aws:ro` từ host vào container
`worker` (read-only, không bao giờ copy secrets vào image). Model mặc định:
**Claude 3.5 Sonnet** — mặc định qua **cross-region inference profile**
(`apac.anthropic.claude-3-5-sonnet-20241022-v2:0`, khớp region mặc định
`ap-southeast-1`), vì phần lớn region ngoài `us-east-1`/`us-west-2` không hỗ
trợ gọi model on-demand trực tiếp (xem bảng troubleshooting bên dưới nếu gặp
`ValidationException`). Chỉnh `BEDROCK_MODEL_ID` cho khớp region/account của
bạn. Đây **không phải** Bedrock AgentCore (agent runtime) — chỉ là đổi model
provider, tương đương "Model Gateway" rút gọn ở mục 1/5 của design doc.

## Kết quả đã verify

Đã build + chạy thật qua `docker compose up` trong quá trình implement (không
chỉ viết code suông), bao gồm cả sau khi đổi worker sang uv + boto3 trực tiếp:

- ✅ Cả 3 image (`worker`, `backend` — build bằng `uv sync --frozen`,
  `ui` — build Vite rồi serve tĩnh qua nginx) build thành công.
- ✅ `temporal` container start healthy (Temporal CLI dev server, SQLite
  persistence tại `/home/temporal/temporal.db` — image chạy user non-root
  `temporal`, `/data` không ghi được nên dùng `/home/temporal`).
- ✅ `backend` có healthcheck riêng (`GET /health`), `ui` phụ thuộc
  `backend: condition: service_healthy` trước khi start.
- ✅ `worker` (build bằng uv) import đúng `boto3`/`temporalio`/`shared.*` —
  verify bằng chạy `python -c "..."` trực tiếp trong image vừa build.
- ✅ `worker` mount `~/.aws` từ host thành công (`/root/.aws`, read-only,
  verify bằng `docker compose exec worker ls -la /root/.aws`).
- ✅ UI (Vite build) → nginx → `location /api/` proxy sang `backend:8000`
  (biến `API_UPSTREAM` được nginx tự envsubst từ template lúc container
  start) — verify bằng `curl http://localhost:3000/api/scenarios` và submit
  thật 1 incident qua đúng đường proxy này.
- ✅ Submit thật 1 incident Scenario E qua UI proxy → Workflow chạy trong
  Worker container thật (uv + boto3) → guardrail chặn `agent_name="shell_agent"`
  → escalate đúng như thiết kế (`"status": "ESCALATED"`, thấy rõ trong cả
  worker log lẫn response API) — **không cần gọi Bedrock thật** vì Scenario E
  có test hook short-circuit trước khi tạo `bedrock-runtime` client.
- ✅ `pytest tests/` — cả 5 scenario (A–E, xem mục 2 design doc) + 1 test
  regression khoá lại việc bỏ action `FINISH` pass bằng Temporal
  time-skipping test framework, mock activities (không cần AWS credentials
  thật).

Trong lúc verify đã sửa 5 vấn đề thực tế (không chỉ lý thuyết):

1. `docker-compose.yml`: `temporalio/temporal` image chạy với user non-root
   `temporal` (uid 1000) — thư mục `/data` không tồn tại/không ghi được, phải
   dùng `/home/temporal` (home dir sẵn có, ghi được) làm nơi mount volume.
2. `shared/workflows.py`: `ActivityError.__str__()` mặc định chỉ in ra
   `"Activity task failed"` (generic), không lộ được message/type của lỗi gốc
   (vd `GuardrailViolation`) nằm trong `ActivityError.cause` — đã thêm helper
   `_describe()` để lấy đúng thông tin lỗi gốc.
3. `ui/tsconfig.app.json`: option `baseUrl` bị deprecate ở TypeScript 6 khi
   dùng `moduleResolution: "bundler"` — bỏ `baseUrl`, chỉ giữ `paths`. Thiếu
   `src/vite-env.d.ts` (`/// <reference types="vite/client" />`) cũng khiến
   `tsc` không resolve được side-effect import `import "@/styles.css"`.
4. `.dockerignore`: pattern `.venv` chỉ khớp thư mục `.venv` ở gốc build
   context, không khớp `worker/.venv`/`backend/.venv` — 1 lần chạy `uv sync`
   cục bộ (ngoài Docker) từng làm build context phình lên ~59MB vì venv của
   `worker` bị gửi kèm. Đã thêm pattern `**/.venv` để loại trừ mọi cấp.
5. **`shared/models.py` — lỗ hổng thiết kế thật, phát hiện qua 1 lần chạy
   thật với Bedrock** (xem [Nhật ký chạy thật với Bedrock](#nhật-ký-chạy-thật-với-bedrock-do-bạn-tự-chạy)):
   action `FINISH` cho phép Orchestrator (LLM, không tin cậy tuyệt đối) tự
   kết luận và bỏ qua HITL dựa trên `confidence` **tự nó báo cáo**, mà
   `confidence` đó chưa từng được validate/enforce ở đâu trong code. Đã bỏ
   hẳn action `FINISH` khỏi allowlist — mọi RCA giờ bắt buộc qua `NEEDS_HUMAN`,
   không có ngoại lệ nào dựa trên confidence.

## Chưa verify (cần chạy tay với model Bedrock thật)

- Tiêu chí #1 (determinism khi `docker compose restart worker` giữa chừng) —
  cần chạy tay, xem mục 7 của design doc.
- Tiêu chí #2 (HITL không tốn tài nguyên khi chờ) — xem hướng dẫn chi tiết ở
  [Cách xác nhận workflow đang thực sự "pending" ở bước HITL](#cách-xác-nhận-workflow-đang-thực-sự-pending-ở-bước-hitl).

## Nhật ký chạy thật với Bedrock (do bạn tự chạy)

**Scenario A, lần chạy #1** (`apac.anthropic.claude-3-5-sonnet-20241022-v2:0`,
`ap-southeast-1`): model điều tra đúng trình tự (`metrics_agent` →
`log_agent` → `metrics_agent(payment-adapter)` → `log_agent(payment-adapter)`),
nhưng **không dừng ở `NEEDS_HUMAN`** — model tự chấm `confidence: 0.9` (≥ 0.8)
và `FINISH` thẳng, vì log của `checkout-api` có 1 dòng nói thẳng
`"connection timeout to payment-adapter"`, nên model coi đây là bằng chứng
trực tiếp đủ chắc chắn.

→ Tại thời điểm đó, `< 0.8`/`>= 0.8` chỉ là 1 câu dặn trong prompt —
**KHÔNG có chỗ nào trong code thực sự validate/enforce con số `confidence`
LLM tự báo cáo**. Nghĩa là việc "có cần người duyệt hay không" phụ thuộc
100% vào 1 thành phần không tin cậy (LLM) tự đánh giá chính mình — sai
nguyên tắc guardrail cơ bản. Đây **là 1 lỗ hổng thiết kế thật**, không chỉ
là "model chưa được tune kỹ".

**Đã sửa tận gốc kiến trúc** (không chỉ tinh chỉnh prompt): bỏ hẳn action
`FINISH` khỏi allowlist (`shared/models.py`). Orchestrator giờ chỉ còn 2 lựa
chọn — `CALL_AGENT` hoặc `NEEDS_HUMAN`. **Mọi RCA, bất kể confidence bao
nhiêu, đều bắt buộc phải có signal approve/reject từ con người** mới được
coi là `FINISHED` — không còn phụ thuộc vào việc LLM tự chấm điểm đúng hay
sai nữa, vì con số đó không còn quyền quyết định control flow nào cả (chỉ
còn là thông tin tham khảo hiển thị cho người duyệt). Đã thêm test regression
`test_legacy_finish_action_no_longer_completes_workflow` khoá lại việc này —
nếu ai vô tình thêm lại `"FINISH"` vào allowlist, test sẽ fail ngay.

Scenario C (trước đây tên "Auto-finish, confidence cao") đã được định nghĩa
lại thành **"Evidence rất rõ ràng — vẫn PHẢI qua HITL"** — verify đúng invariant
mới: dù confidence cao cỡ nào, hệ thống không bao giờ tự động kết thúc mà
không có signal. Xem đầy đủ rationale + cảnh báo thiết kế ở
[mục 2 của design doc](POC%20Design%20-%20Dynamic%20Agent%20Loop.md#2-kịch-bản-demo).
