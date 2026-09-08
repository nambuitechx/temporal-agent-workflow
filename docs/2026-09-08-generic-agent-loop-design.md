# Generic Agent Loop — Design Doc

Đề xuất tách phần **runtime** (Temporal workflow điều khiển vòng lặp
Orchestrator + HITL) ra khỏi phần **domain config** (agent nào tồn tại, ai là
orchestrator/subagent của usecase nào) — để thêm 1 usecase/domain mới không
cần định nghĩa lại Workflow hay viết Workflow riêng cho từng usecase.

Bối cảnh: implementation hiện tại (`shared/workflows.py`,
`shared/activities.py`, `shared/models.py`) đang hardcode cho đúng 1 usecase
— xem [2026-09-07-poc-design-dynamic-agent-loop.md](2026-09-07-poc-design-dynamic-agent-loop.md)
và [CLAUDE.md](../CLAUDE.md) để hiểu luồng gốc trước khi đọc doc này.

**Cập nhật quan trọng so với bản thảo đầu:** revision này thay hoàn toàn
phương án "registry theo filesystem" (`usecases/<id>/v<n>/manifest.yaml`)
bằng **Postgres + Alembic + asyncpg**, theo đúng convention của
[synaptix-platform/apps/backend](../../../synaptix-platform/apps/backend)
(`BaseTableModel`, async engine, alembic versions đánh số tuần tự) — vì lý do
nêu ở mục 0. Revision sau đó bổ sung thêm: source code agent (prompt + tool
mô phỏng) vẫn ở trong repo, nhưng chuyển sang thư mục top-level `agents/`,
tách khỏi `shared/` — xem mục 0.1. Revision sau đó tách bảng metadata agent
thành 2 bảng (`agentcore_agents` + `usecase_agents`, mục 4) vì 1 agent
AgentCore có thể được nhiều usecase khác nhau tái sử dụng, không thuộc về
đúng 1 usecase — xem mục 0. Revision sau đó chốt cách xử lý mâu thuẫn
immutability vs reuse phát sinh từ đó: `agentcore_agents` mutable, chặn update
ở tầng ứng dụng khi còn case sống tham chiếu — xem mục 4. Revision sau đó chốt
quy ước đặt tên `usecase_agents.agent_name`: backend tự sinh
`{usecase_key}__{agent_key}`, không nhận free-text — xem mục 4. Revision gần
nhất, sau review, chốt thêm 4 điểm: (1) tên bảng SQLAlchemy phải override
tường minh `__tablename__` snake_case số nhiều, không dựa vào default của
`BaseTableModel` — xem mục 4; (2) giữ nguyên `created_by`/`updated_by` kế thừa
từ `BaseTableModel` trên mọi bảng — xem mục 4; (3) circuit breaker
`max_iterations_cap` phải được Workflow tự kiểm tra lại (defense-in-depth),
không chỉ dựa vào backend clamp lúc tạo case — xem mục 3 và mục 5; (4)
`usecase_versions` cần cột trạng thái "sẵn sàng dùng" tách khỏi `is_latest`,
và bắt buộc có đúng 1 orchestrator trước khi chuyển sang trạng thái đó — xem
mục 4.

---

## 0. Phạm vi thật của repo này — và vì sao không nên định nghĩa prompt/tool ở đây

Repo `temporal-agent-workflow` chỉ nên chịu trách nhiệm cho phần **Temporal
workflow runtime**: state bền, thứ tự bước, HITL, retry, circuit breaker —
đúng ô đầu tiên trong sơ đồ của
[Connector Spec](../../connector/Connector%20Spec%20for%20Xora%20Platform.md#1-connector-nằm-ở-đâu-trong-hệ-thống):

```text
Temporal Workflow        cầm lái tiến trình điều tra: state bền, thứ tự bước,
                         budget tổng, HITL, retry, escalate
        │ invoke agent theo ARN
        ▼
AgentCore Runtime        agent suy luận, chọn capability, gọi tool
        │ MCP call
        ▼
Tool plane (3 MCP)       Catalog · Router (PEP) · Evidence access
```

Nói cách khác: **repo này không nên *vận hành* agent** (Router/Catalog/Tool
plane, tool-calling thật) — đó là việc của AWS Bedrock AgentCore (đã/sẽ được
deploy riêng) và của Tool plane mô tả trong Connector Spec. Nhưng repo này
**vẫn tạm thời giữ *source code* của agent** (prompt + tool implementation
mô phỏng) — chỉ là không nên trộn nó vào `shared/` (chỗ chứa code Temporal
runtime), vì 2 lý do khác hẳn nhau về vòng đời: `shared/` đóng gói cùng
worker/backend image, còn code agent về sau cần **tách ra được nguyên khối**
để đóng gói/deploy lên AgentCore mà không phải viết lại.

Hệ quả cho thiết kế:

- Activity `ask_orchestrator`/`run_agent` **đích cuối** = "invoke agent theo
  ARN" — gọi AgentCore Runtime bằng định danh agent (ARN hoặc tương đương),
  không tự cầm system prompt/tool function trong tay như hiện tại.
- Cái mà `shared/db` cần **biết** để làm được việc đó không phải là "nội dung
  prompt" hay "code của tool", mà là **metadata định danh**: usecase này có
  orchestrator agent nào, subagent nào, định danh AgentCore của từng agent là
  gì, và các thông số vận hành (timeout, retry) khi Workflow gọi nó qua
  Activity. Đây chính là "AgentCore metadata" quản lý bằng database (mục 4).
- Việc chọn Postgres/Alembic cho **metadata** (không phải cho source code
  agent) phản ánh đúng bản chất: agent nào ứng với usecase nào, ARN nào, là
  **dữ liệu vận hành**, cùng loại với "Registry — bảng dữ liệu, không phải
  code" ở mục 5 của Connector Spec, nên sống cùng 1 kiểu hạ tầng (Postgres
  control-plane) với phần còn lại của nền tảng Xora
  (`synaptix-platform/apps/backend`). Ngược lại **source code** agent (prompt
  text, hàm tool) vẫn nên là file trong git — nó là code, review qua PR, không
  phải config vận hành sửa qua admin UI.
- Trong lúc AgentCore integration chưa xong, `local_tool_ref` (một cột trong
  bảng `agentcore_agents`, xem mục 4) trỏ tới hàm Python mô phỏng nằm trong
  thư mục `agents/` mới (mục 0.1) — đúng vai trò "stand-in", không phải giá
  trị sản xuất. Khi chuyển sang gọi AgentCore thật, chỉ Activity
  implementation đổi (đọc `agentcore_agent_arn` thay vì `local_tool_ref`),
  schema DB và Workflow không đổi; thư mục `agents/` thì được lift-and-shift
  sang đóng gói AgentCore, không cần viết lại từ đầu vì nó chưa từng bị trộn
  với `shared/`/`worker/`.
- **Một agent AgentCore không thuộc về đúng 1 usecase.** Nhiều usecase khác
  nhau hoàn toàn có thể cùng gọi chung 1 agent đã deploy (vd 2 usecase khác
  nhau đều cần "tra log qua Loki" — dùng chung 1 `log_agent`, không mỗi
  usecase tự deploy 1 bản ARN riêng chỉ khác tên). Vì vậy phải tách rời 2 loại
  metadata: "agent này là gì" (ARN, tool mô phỏng, có read-only không) —
  thuộc về **agent**, độc lập usecase; và "usecase này dùng agent nào, gọi nó
  bằng tên gì, đóng vai orchestrator hay subagent trong luồng này" — thuộc về
  **quan hệ usecase↔agent**. Bản thảo trước gộp 2 loại này vào 1 bảng
  `usecase_agents`, buộc phải tạo lại y hệt 1 dòng (và về sau, y hệt 1 agent)
  cho mỗi usecase muốn dùng — mục 4 tách lại thành 2 bảng.

### 0.1. `agents/` — thư mục riêng, tách khỏi `shared/`, tổ chức theo agent chứ không theo usecase

```text
agents/                              # top-level, ngang hàng shared/worker/backend/ui
  log_agent/                         # = agentcore_agents.agent_key (mục 4) — KHÔNG nesting theo usecase
    prompt.md
    tool.py                          # def run(args, case_context) -> dict
  metrics_agent/
    prompt.md
    tool.py
  incident_investigation_orchestrator/   # orchestrator thường vẫn gắn 1 usecase, nhưng vẫn là 1 "agent"
    prompt.md                            # bình thường như mọi agent khác, không có thư mục cha riêng
  <agent_khac>/
    prompt.md
    tool.py
```

Không nesting `agents/<usecase_key>/<agent_name>/` như bản thảo trước —
đúng hệ quả của mục 0 (agent không thuộc về 1 usecase): thư mục đặt tên theo
`agent_key`, phẳng, ngang hàng nhau. Một agent (vd `log_agent`) có 1 thư mục
duy nhất dù được bao nhiêu usecase tham chiếu tới; usecase nào cần dùng agent
này thì chỉ cần thêm 1 dòng trong bảng liên kết `usecase_agents` (mục 4) trỏ
tới `agentcore_agents` tương ứng, không cần copy thư mục.

Đây là source code hiện tại của `shared/agents/*_prompt.py` +
`shared/tools/*.py`, chỉ **chuyển vị trí** (top-level, không nằm dưới
`shared/`) và tách mỗi agent thành 1 thư mục riêng. Lý do tách theo từng agent
một thư mục: gần với cách AgentCore thường đóng gói 1 agent (instructions +
action group/tool code đi cùng nhau) — sau này lấy nguyên `agents/log_agent/`
làm base cho 1 AgentCore agent deployment sẽ là lift-and-shift, không phải
tái cấu trúc.

`agentcore_agents.local_tool_ref` (mục 4) format đổi từ
`shared/tools/log_agent.py:run` thành `agents/log_agent/tool.py:run` — vẫn
cùng dạng `module:function`, chỉ đổi đường dẫn gốc.

Tên thư mục chỉ để người đọc dễ tra cứu — **nguồn sự thật vẫn là cột
`agent_key`/`local_tool_ref` trong Postgres**, không phải cấu trúc thư mục;
đổi tên thư mục không tự động đổi hành vi, phải update lại giá trị cột
tương ứng.

## 1. Vấn đề

Những thứ đang bị trộn giữa "runtime" và "domain" trong code hiện tại:

| Thuộc runtime (nên giữ generic) | Thuộc domain (đang bị hardcode) |
|---|---|
| While-loop, `NEEDS_HUMAN` → `wait_condition`, circuit breaker, escalate | `ALLOWED_AGENTS = {"log_agent", "metrics_agent"}` |
| `ALLOWED_ACTIONS = {CALL_AGENT, NEEDS_HUMAN}` (không có `FINISH`) | System prompt của Orchestrator + từng Specialized Agent (tạm thời còn trong repo, xem mục 0) |
| Signal `approve`/`reject`, query `get_state` | `if agent_name == "log_agent": ... else: ...` trong `run_agent` |
| `_escalate`, `_describe` (đọc lỗi activity) | `agents/*/tool.py` (mục 0.1), `shared/data/scenarios/*` (fake data mô phỏng AgentCore) |
| | Field tên miền cụ thể: `incident_id`, `rca_proposal`, `evidence` |

Mục tiêu: Workflow/Activity code (runtime) viết 1 lần, dùng chung cho mọi
usecase. Mỗi usecase mới chỉ thêm **1 dòng metadata trong Postgres** (usecase
+ danh sách agent của nó), không sửa `shared/workflows.py` hay
`shared/activities.py`.

## 2. Nguyên tắc tách lớp

Runtime (control-flow, guardrail an toàn platform-wide) không bao giờ để
usecase override — usecase chỉ được **thu hẹp thêm**, không được nới rộng.
Cụ thể `ALLOWED_ACTIONS` vẫn cố định `{CALL_AGENT, NEEDS_HUMAN}` toàn hệ
thống, không nằm trong config của usecase nào cả — đây chính là bài học rút
ra từ việc bỏ action `FINISH` (xem `shared/models.py`): một invariant an toàn
không nên là thứ có thể bị 1 usecase config vô tình/cố ý mở lại.

Domain (usecase nào tồn tại, orchestrator/subagent nào thuộc usecase đó) là
**dữ liệu trong Postgres**, nạp theo `usecase_id` lúc chạy — không phải
Python constant biên dịch cứng, cũng không phải file YAML.

## 3. Generic hoá Workflow

Đổi tên `IncidentInvestigationWorkflow` → `AgentLoopWorkflow`. State đổi từ
tên miền cụ thể sang tên trung tính:

| Cũ | Mới |
|---|---|
| `incident_id` | `case_id` |
| `rca_proposal` | `proposal` |
| `evidence` | `artifacts` |
| *(không có)* | `usecase_id`, `usecase_version_id` (mới) |

Toàn bộ logic bên trong `run()` (while-loop, nhánh `NEEDS_HUMAN`/`CALL_AGENT`,
`_escalate`, circuit breaker) **giữ nguyên không đổi** — chỉ đổi tên field và
truyền thêm `usecase_id`/`usecase_version_id` xuống Activity cùng các tham số
hiện có (`args=[..., usecase_id, usecase_version_id]`), giống hệt cách
`max_iterations` đang được truyền qua `request` dict ngày nay. `usecase_id`
ở đây là `usecases.usecase_key` (slug, không phải UUID) — `usecase_version_id`
mới là UUID trỏ đúng 1 dòng `usecase_versions` (mục 4).

**Circuit breaker phải tự kiểm tra lại `max_iterations_cap`, không chỉ tin
backend.** Backend (`POST /cases`, mục 6) đã clamp `max_iterations` request
theo `usecases.max_iterations_cap` lúc tạo case, nhưng đây là guardrail
platform-wide (giống lý do `ALLOWED_ACTIONS` không nằm trong config usecase,
mục 2) — không nên chỉ dựa vào đúng 1 lớp validate ở biên API, cùng nguyên
tắc defense-in-depth đã áp dụng cho `agent_name` (`ask_orchestrator` +
`run_agent` validate độc lập, mục 5). Cách làm: bước đầu `run()` gọi 1
Activity registry mới (`get_usecase_limits`, mục 5) lấy `max_iterations_cap`
theo `usecase_version_id`, rồi tính
`effective_max_iterations = min(request.get("max_iterations", default), cap)`
— dùng giá trị này thay `max_iterations` trong điều kiện while-loop, không
dùng thẳng giá trị từ `request`. 1 lần gọi thêm mỗi case (không phải mỗi
iteration), chi phí không đáng kể so với vòng lặp `ask_orchestrator`/
`run_agent` vốn đã gọi Activity mỗi bước.

## 4. Lưu trữ: Postgres + Alembic + asyncpg (theo convention synaptix-platform)

Thay vì `usecases/<id>/v<n>/manifest.yaml` trên filesystem, dùng 1 Postgres
control-plane riêng cho repo này (service `postgres` mới trong
`docker-compose.yml`, tách biệt với SQLite nội bộ của `temporal` container).
Kiến trúc mã nguồn theo đúng khuôn của
[`synaptix-platform/apps/backend`](../../../synaptix-platform/apps/backend):

```text
shared/
  db/
    session.py     # async_engine (asyncpg) + async_sessionmaker — giống app/core/db.py
    models.py       # SQLAlchemy declarative: BaseTableModel-style (uuid pk, created_at/updated_at)
    registry.py     # hàm async: get_orchestrator(), get_agent(), list_allowed_agents() — xem mục 5
  alembic/
    env.py
    versions/
      0001_usecases.py
```

`BaseTableModel` copy nguyên tinh thần từ `app/models/base.py` bên
synaptix-platform: `id: UUID` PK mặc định `uuid4()`, `created_at`/`updated_at`
tự động, **`created_by`/`updated_by: UUID | None`** (giữ nguyên, không lược
bớt — Activity chạy trong Worker không có identity người dùng nên các dòng
Activity tự ghi (nếu có) sẽ luôn null; 2 cột này có giá trị thật khi ghi qua
đường admin CRUD ở mục 6, nơi có identity người gọi API), cùng
`naming_convention` cho index/constraint. Không liệt kê lại `created_by`/
`updated_by` trong từng bảng ở dưới — mọi bảng kế thừa `BaseTableModel` đều có.

**Lưu ý bắt buộc khi định nghĩa model:** `BaseTableModel.__tablename__` mặc
định là `cls.__name__.lower()` (vd class `UsecaseVersion` → bảng
`usecaseversion`), **không tự chèn `_`** cho tên nhiều từ. Mọi bảng dưới đây
phải override `__tablename__` tường minh đúng tên snake_case số nhiều đã ghi
(`usecases`, `usecase_versions`, `agentcore_agents`, `usecase_agents`) —
không dựa vào default, nếu không migration Alembic sẽ sinh sai tên so với
mô tả trong doc này. Dependencies thêm vào
**cả** `worker/pyproject.toml` và `backend/pyproject.toml` (cả 2 process đều
cần đọc DB — worker để activities tra registry, backend để CRUD usecase):
`sqlalchemy`, `asyncpg`, `alembic`.

### Schema

**`usecases`** — 1 dòng / domain, tương đương thư mục `usecases/<id>/` cũ:

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | uuid PK | |
| `usecase_key` | str, unique | slug ổn định, vd `incident_investigation` — cái Workflow/API dùng để tham chiếu |
| `label` | str | hiển thị UI |
| `description` | str | |
| `status` | enum(`active`,`disabled`) | usecase bị disable thì backend từ chối tạo case mới |
| `default_max_iterations` | int | |
| `max_iterations_cap` | int | trần cứng platform-wide, usecase không vượt được |
| `created_at`/`updated_at` | timestamptz | |

**`usecase_versions`** — tương đương thư mục `v<n>/` cũ, **append-only**:

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | uuid PK | đây là giá trị thực sự lưu vào `usecase_version_id` của Workflow input, không phải số `n` |
| `usecase_id` | FK → `usecases.id` | |
| `version_number` | int | tăng dần, unique theo `(usecase_id, version_number)`, chỉ để hiển thị/audit |
| `is_latest` | bool | đúng 1 dòng `is_latest=true` / usecase, enforce bằng partial unique index |
| `status` | enum(`draft`,`ready`) | mới — tách khỏi `is_latest`. `draft` = đang gán agent, chưa dùng được cho case mới; `ready` = đã qua validate (ít nhất 1 orchestrator, xem dưới), backend cho phép resolve khi tạo case. `is_latest=true` không tự nghĩa là dùng được — 1 version mới tạo mặc định `draft`, admin phải chuyển sang `ready` tường minh (mục 6) |
| `created_at` | timestamptz | |

Sau khi 1 `usecase_versions` row **chuyển sang `status='ready'`**, không được
update các `usecase_agents` thuộc nó nữa — sửa gì cũng tạo version mới
(`version_number + 1`, trạng thái `draft` ban đầu, set `is_latest=true`, hạ cờ
version cũ xuống `false`). Trong lúc còn `draft`, admin được sửa
`usecase_agents` của version đó thoải mái (đang cấu hình, chưa có case nào
tham chiếu tới). Đây là nguyên tắc "version là snapshot bất biến" thay cho
"version là thư mục vật lý" ở bản thảo filesystem trước, cùng lý do: case
đang `WAITING_HUMAN` phải luôn audit lại đúng config đã dùng lúc start, không
bị đổi giữa chừng.

**Ràng buộc "phải có orchestrator" khi gán nhiều agent.** Partial unique
index ở bảng `usecase_agents` (dưới) chỉ chặn **nhiều hơn 1** dòng
`kind='orchestrator'` cho cùng 1 version, không chặn **0** dòng — 1 version
gán toàn `subagent`, không có orchestrator, vẫn hợp lệ ở tầng DB, và
`get_orchestrator()` (mục 5) sẽ không tra được gì lúc chạy, lỗi runtime khó
hiểu thay vì lỗi rõ ràng lúc cấu hình. Quy tắc chốt: 1 version có thể được
gán 1 hoặc nhiều agent; nếu tổng số agent gán vào version đó từ 2 trở lên,
bắt buộc phải có ít nhất 1 dòng `kind='orchestrator'` trong số đó (trường
hợp version chỉ gán đúng 1 agent, chính agent đó phải là orchestrator — ứng
với 1 usecase tối giản không có subagent, Orchestrator tự đề xuất RCA không
cần `CALL_AGENT`). Ràng buộc này **enforce ở tầng ứng dụng, không phải DB
constraint** (giống lý do chọn tầng ứng dụng cho việc chặn update
`agentcore_agents` ở trên — Postgres không tự biết "đủ" hay chưa theo nghĩa
nghiệp vụ), tại đúng thời điểm admin chuyển `status` từ `draft` sang `ready`
(mục 6): backend từ chối chuyển trạng thái nếu chưa thoả điều kiện trên. Đây
cũng là lý do tách `status` khỏi `is_latest` — `is_latest` chỉ nói "version
mới nhất", không nói "đã cấu hình xong, dùng được".

**Quyết định:** bất biến "pin theo version" ở trên chỉ đứng vững nếu
`agentcore_agents` (bảng identity, mục dưới) cũng không bị sửa tại chỗ khi
đang có case sống phụ thuộc vào nó. Đã chốt chọn phương án **cho phép
`agentcore_agents` mutable, nhưng chặn update ở tầng ứng dụng** (không phải
DB constraint — Temporal mới biết case nào còn sống, Postgres không biết):

- Trước khi backend thực hiện `UPDATE agentcore_agents ... WHERE id = ...`
  (vd đổi `agentcore_agent_arn` khi redeploy agent), backend phải tra cứu
  toàn bộ `usecase_version_id` đang tham chiếu tới `agent_id` này (qua
  `usecase_agents`), rồi hỏi Temporal xem có case nào `RUNNING`/
  `WAITING_HUMAN` thuộc các version đó không.
- Còn ít nhất 1 case sống → **từ chối update** (409/`ApplicationError` tương
  đương), không cho sửa. Không còn case sống nào → cho update bình thường,
  hành vi ngầm nêu trên không xảy ra vì không còn workflow nào để bị ảnh
  hưởng.
- Cùng logic tra cứu này được expose qua endpoint đọc riêng
  `GET /agentcore-agents/{id}/usage` (mục 6) để UI admin hiển thị **trước**
  khi cho sửa, không phải để admin bấm Save rồi mới biết bị chặn.

Đánh đổi đã chấp nhận: nếu cần sửa gấp 1 agent đang có case sống tham chiếu
(vd agent lỗi cần vá khẩn cấp), thao tác này sẽ bị chặn — chưa có quy trình
"buộc sửa" (force override) cho tình huống đó, xem mục 10.

**`agentcore_agents`** — đây là bảng "AgentCore metadata" bạn yêu cầu: định
danh 1 agent **độc lập với usecase nào dùng nó** — 1 agent (1 ARN, hoặc 1
`local_tool_ref` mô phỏng) có thể được nhiều usecase khác nhau tham chiếu tới
qua bảng liên kết `usecase_agents` bên dưới:

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | uuid PK | |
| `agent_key` | str, unique | slug ổn định cho chính agent này (vd `log_agent`), độc lập usecase — khớp tên thư mục trong `agents/` (mục 0.1) |
| `label` | str | hiển thị UI/admin |
| `agentcore_agent_arn` | str, nullable | định danh AgentCore Runtime — đích cuối (mục 0). Null nghĩa là chưa deploy AgentCore cho agent này |
| `local_tool_ref` | str, nullable | `module:function` trỏ vào thư mục `agents/` (mục 0.1) — CHỈ dùng khi `agentcore_agent_arn` null, tức đang ở chế độ mô phỏng cục bộ |
| `read_only` | bool, NOT NULL | bắt buộc khai tường minh (DB constraint `NOT NULL`, không có default) — cùng lý do đã nêu ở bản thảo trước: tool/agent gọi ra ngoài (kể cả qua AgentCore) không nên vô tình mutate |
| `secrets` | jsonb (`list[str]`) | chỉ tên biến env, không chứa giá trị |
| `default_timeout_seconds` | int | → `start_to_close_timeout` mặc định của `execute_activity`, usecase có thể override (xem `usecase_agents`) |
| `default_retry_policy` | jsonb | mặc định, usecase có thể override |
| `agent_metadata` | jsonb | chỗ chứa thêm field không cần cột riêng. Đặt tên `agent_metadata`, KHÔNG được đặt `metadata` — `Base.metadata` (`BaseTableModel`) là thuộc tính SQLAlchemy Declarative dành riêng cho `MetaData` object, khai `metadata: Mapped[...]` đè lên nó sẽ lỗi ngay lúc import model |
| `created_at`/`updated_at` | timestamptz | |

Ràng buộc: mỗi `agentcore_agents` row phải có **đúng 1 trong 2** của
`agentcore_agent_arn`/`local_tool_ref` khác null (check constraint) — một
agent hoặc trỏ AgentCore thật, hoặc dùng mô phỏng cục bộ, không có cả hai
cũng không được thiếu cả hai.

**`usecase_agents`** — bảng liên kết (many-to-many): usecase version nào dùng
agent nào, gọi bằng tên logic gì, đóng vai trò gì trong luồng của usecase đó:

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | uuid PK | |
| `usecase_version_id` | FK → `usecase_versions.id` | |
| `agent_id` | FK → `agentcore_agents.id` | cùng 1 `agent_id` có thể xuất hiện ở nhiều `usecase_version_id` khác nhau — đây chính là điểm cho phép tái sử dụng agent |
| `agent_name` | str | tên logic Orchestrator **của usecase này** dùng khi chọn `CALL_AGENT` — **backend tự sinh**, KHÔNG nhận free-text từ admin UI: `f"{usecase_key}__{agent_key}"` (vd usecase `incident_investigation` + agent `log_agent` → `incident_investigation__log_agent`), tính lúc tạo dòng liên kết. Unique theo `(usecase_version_id, agent_name)` — tự động thoả mãn vì `(usecase_version_id, agent_id)` vốn đã xác định usecase_key/agent_key duy nhất |
| `kind` | enum(`orchestrator`,`subagent`) | vai trò của agent này **trong usecase version này** — đúng 1 dòng `kind=orchestrator` / version, enforce bằng partial unique index. Cùng 1 agent về lý thuyết có thể là orchestrator ở usecase này và subagent ở usecase khác, nên `kind` thuộc về quan hệ, không thuộc về `agentcore_agents` |
| `timeout_seconds` | int, nullable | override `agentcore_agents.default_timeout_seconds` cho riêng usecase này; null = dùng default của agent |
| `retry_policy` | jsonb, nullable | override tương tự |
| `created_at`/`updated_at` | timestamptz | |

`allowed_agents` cho 1 usecase version = tập `agent_name` có
`kind='subagent'` của version đó (join `usecase_agents` → `agentcore_agents`
để lấy ARN/`local_tool_ref`). `allowed_actions` vẫn không nằm trong DB — lý
do như mục 2.

Hệ quả của việc `agent_name` auto-generate (`{usecase_key}__{agent_key}`):
prompt của Orchestrator cho usecase này (mục 0.1) phải liệt kê đúng các tên
`agent_name` này khi mô tả agent nào nó được phép `CALL_AGENT` — vì luôn
mang tiền tố `usecase_key`, không cần lo trùng tên với agent cùng key ở
usecase khác dù bảng `agentcore_agents` chỉ có 1 dòng `log_agent` dùng
chung. Admin UI nên hiển thị sẵn `agent_name` vừa sinh ra ngay sau khi liên
kết, để người viết prompt copy đúng chuỗi, không tự gõ lại.

Hệ quả khác: vì `agent_name` là hàm xác định của `(usecase_key, agent_key)`,
**không thể liên kết cùng 1 agent 2 lần vào cùng 1 usecase version** dưới 2
vai trò/tên gọi khác nhau (vd cần `log_agent` đóng 2 vai trò khác nhau trong
cùng 1 luồng) — nếu về sau cần ca này, phải nới lại quy tắc sinh tên (thêm
hậu tố phân biệt), chưa xử lý ở doc này vì chưa có nhu cầu thực tế.

## 5. Registry lookup trong Activities

`shared/activities.py` hiện hardcode `if agent_name == "log_agent": ...`.
Thay bằng `shared/db/registry.py` — các hàm async, mỗi Activity tự mở
session (giống cách `app/api/routes/*` bên synaptix mở session qua
dependency, ở đây Activity không có DI nên tự gọi
`async_session_maker()` trực tiếp):

```python
async def get_orchestrator(usecase_version_id: uuid.UUID) -> ResolvedAgent: ...
async def get_agent(usecase_version_id: uuid.UUID, agent_name: str) -> ResolvedAgent | None: ...
async def list_allowed_agents(usecase_version_id: uuid.UUID) -> set[str]: ...
async def get_usecase_limits(usecase_version_id: uuid.UUID) -> UsecaseLimits: ...
```

`UsecaseLimits` (mới) chỉ mang `max_iterations_cap` (join `usecase_versions`
→ `usecases`) — dùng cho check defense-in-depth ở mục 3. Gọi 1 lần lúc
`run()` bắt đầu qua 1 Activity riêng (không gộp vào `get_orchestrator` vì
2 việc khác mục đích: 1 cái resolve identity agent, 1 cái resolve giới hạn
platform-wide).

`ResolvedAgent` là kết quả join `usecase_agents` (tên logic, `kind`, override
timeout/retry nếu có) với `agentcore_agents` (ARN/`local_tool_ref`,
`read_only`, `secrets`, default timeout/retry) — Activity chỉ thấy 1 object
phẳng, không cần tự join hay biết về 2 bảng.

- `run_agent(usecase_version_id, agent_name, args, case_context)` →
  `get_agent(...)`, nếu `agentcore_agent_arn` có giá trị → gọi AgentCore
  Runtime bằng ARN đó (đích cuối); nếu null → import `local_tool_ref` và gọi
  như hàm Python thường (mô phỏng, path hiện tại của repo). Activity code
  **không rẽ nhánh theo tên agent cụ thể** ở cả 2 trường hợp.
- `ask_orchestrator(usecase_version_id, ...)` → `get_orchestrator(...)` rồi
  làm tương tự.

Guardrail 2 lớp hiện có (`ask_orchestrator` validate, `run_agent` validate
lại độc lập — defense-in-depth) giữ nguyên, chỉ đổi nguồn tra cứu từ hằng số
Python sang query Postgres.

Mỗi lần Activity chạy đều query DB (không cache lúc worker start như bản
filesystem trước) — vì đây giờ là dữ liệu vận hành có thể sửa qua API/admin
UI bất cứ lúc nào, không phải file đọc 1 lần lúc container khởi động. Cân
nhắc thêm cache ngắn hạn (TTL vài giây) nếu tần suất gọi Activity cao, nhưng
để mục 10 — chưa cần tối ưu sớm.

## 6. Backend/API

- `GET /scenarios` → `GET /usecases`: list `usecases` (status=active) +
  `usecase_versions` **READY có `version_number` lớn nhất** (không phải
  `is_latest`, xem sửa lỗi dưới), để UI tự build dropdown thay vì hardcode
  `SCENARIOS` như `backend/main.py` hiện tại.
- `POST /incidents` → `POST /cases`: nhận `usecase_key` (backend tự resolve
  `usecase_versions` READY có `version_number` lớn nhất → lấy `id` làm
  `usecase_version_id` nhúng vào workflow input; không có version nào ready
  → 409), `case_context` thay `scenario_id`.

  **[Sửa lỗi phát hiện lúc vận hành]** Bản thảo đầu yêu cầu **đồng thời**
  `is_latest=true` VÀ `status='ready'` để resolve version cho case mới — sai:
  tạo 1 version draft mới (v2) — thao tác quản trị hoàn toàn hợp lệ trong lúc
  v1 vẫn `ready` — khiến `is_latest` chuyển ngay sang v2 (chưa publish), và
  vì không còn version nào thoả *cả hai* điều kiện, `POST /cases` trả 409
  ngay lập tức dù v1 (ready) vẫn là 1 config hoàn toàn dùng được. `is_latest`
  chỉ nên mang nghĩa "bản mới nhất để admin sửa tiếp" (dùng ở
  `UsecaseDetailScreen` để mặc định chọn version nào hiển thị), KHÔNG phải
  "bản duy nhất được phép chạy case". Đã sửa: resolve version READY có
  `version_number` lớn nhất, độc lập với `is_latest` — case mới tiếp tục
  dùng v1 cho tới khi v2 thật sự publish thành `ready` (lúc đó v2 mới có
  `version_number` lớn nhất trong tập READY, tự động thay thế v1 mà không
  cần thao tác gì thêm).
- `GET/POST /incidents/{id}/...` → `.../cases/{id}/...`, không đổi logic.
- Thêm nhóm endpoint admin CRUD cho `usecases`/`usecase_versions`/
  `usecase_agents` (tạo usecase mới, tạo version mới, gán agent nào cho
  version nào — request chỉ cần `agent_id` + `kind`, KHÔNG nhận `agent_name`:
  backend tự sinh theo quy tắc `{usecase_key}__{agent_key}` ở mục 4, trả về
  trong response để admin UI hiển thị/copy vào prompt Orchestrator) — thay
  thế việc "thêm file YAML" bằng "gọi API/thao tác trên UI quản trị". Riêng
  version có thêm `POST /usecase-versions/{id}/publish` — chuyển
  `status: draft → ready`; backend validate đúng 1 `kind='orchestrator'` đã
  gán (mục 4) trước khi cho publish, trả 400 kèm lý do nếu chưa thoả (vd
  "chưa gán orchestrator"). Publish rồi thì `usecase_agents` của version đó
  bị khoá sửa như mô tả ở mục 4.
- Thêm nhóm endpoint admin CRUD **riêng** cho `agentcore_agents` (đăng ký 1
  agent mới, gán/đổi ARN AgentCore của nó) — tách khỏi CRUD usecase phía trên
  vì đây là vòng đời khác nhau: đăng ký 1 agent làm 1 lần, gán nó vào N
  usecase là việc khác (qua `usecase_agents`). Kèm theo 1 endpoint đọc riêng
  `GET /agentcore-agents/{id}/usage` — trả danh sách `usecase_version` đang
  tham chiếu tới agent này + số case `RUNNING`/`WAITING_HUMAN` hiện tại của
  từng version (query Temporal, không phải Postgres) — để admin UI hiển thị
  trước khi cho sửa/xoá 1 agent, thay vì chỉ chặn lúc submit (xem mục 10).
  Chưa thiết kế chi tiết ở doc này (mục 10).

## 7. Vì sao không phá tính deterministic của Temporal

Việc query Postgres theo `usecase_version_id` chỉ xảy ra **trong Activity**
(được phép I/O, non-deterministic) — Workflow chỉ truyền `usecase_id` +
`usecase_version_id` xuống như string/uuid, y hệt cách `max_iterations` đang
chảy qua hôm nay. Không vi phạm nguyên tắc "Workflow code phải deterministic"
ghi trong docstring `shared/workflows.py`.

## 8. Lộ trình migrate

1. Tạo thư mục `agents/` (mục 0.1) ở top-level, di chuyển
   `shared/agents/*_prompt.py` → `agents/{incident_investigation_orchestrator,
   log_agent,metrics_agent}/prompt.md` và `shared/tools/*.py` →
   `agents/{log_agent,metrics_agent}/tool.py` (đổi chữ ký hàm tool sang
   `run(args, case_context)`) — thuần di chuyển + đổi chữ ký, không đổi logic
   bên trong. Layout phẳng theo `agent_key`, không nesting theo usecase (mục
   0.1).
2. Thêm service `postgres` vào `docker-compose.yml` (control-plane DB, tách
   biệt SQLite của Temporal), thêm `shared/db/`, `shared/alembic/`, migration
   `0001` tạo 4 bảng ở mục 4 (`usecases`, `usecase_versions`,
   `agentcore_agents`, `usecase_agents`).
3. Seed dữ liệu hiện tại bằng 1 migration data hoặc script seed: 3 dòng
   `agentcore_agents` (`incident_investigation_orchestrator`, `log_agent`,
   `metrics_agent`, mỗi dòng `local_tool_ref` trỏ đường dẫn mới ở bước 1,
   `agentcore_agent_arn=null`), 1 dòng `usecases`
   (`usecase_key=incident_investigation`), 1 dòng `usecase_versions`
   (`version_number=1`, `is_latest=true`, `status=ready` — seed thẳng thành
   ready vì đây là dữ liệu đã biết hợp lệ, không đi qua endpoint publish),
   và 3 dòng `usecase_agents` nối version đó với 3 agent ở trên
   (`kind=orchestrator`/`subagent` tương ứng, đúng 1 dòng `orchestrator`).
4. Refactor `shared/workflows.py`: đổi tên field, thêm `usecase_id`/
   `usecase_version_id` vào request, gọi thêm activity resolve
   `UsecaseLimits` lúc bắt đầu `run()` để tính `effective_max_iterations`
   (mục 3) — phần còn lại của logic control-flow không đổi.
5. Refactor `shared/activities.py`: thay hardcode bằng
   `shared/db/registry.py` lookup, thêm activity mới cho
   `get_usecase_limits` (mục 5).
6. Refactor `backend/main.py`: đổi endpoint, thêm CRUD admin, đọc usecase
   list từ Postgres thay vì `SCENARIOS` hardcode.
7. `tests/test_workflow.py` giữ nguyên cách mock activity (fake theo tên) —
   thêm `usecase_id`/`usecase_version_id` vào `_base_request()`; test nào
   cần dữ liệu registry thật thì seed trực tiếp vào DB test (giống pattern
   test DB bên `synaptix-platform/apps/backend`), không cần mock lớp DB.
8. (Sau, ngoài phạm vi doc này) UI đọc `/usecases` để tự build form; tích
   hợp gọi AgentCore Runtime thật (thay `local_tool_ref` bằng
   `agentcore_agent_arn` trong `agentcore_agents` cho từng agent, không đổi
   schema DB, và `agents/log_agent/` được lift sang gói deploy AgentCore mà
   không cần viết lại — xem mục 0.1).

## 9. Liên hệ với Connector Spec (`xora-brainstorm/connector`)

Đây không còn là 2 nguyên tắc tương tự áp dụng độc lập ở 2 tầng — sau khi
tính luôn mục 0, đây là **cùng 1 kiến trúc nối tiếp nhau**: repo này
("Temporal Workflow" — ô đầu sơ đồ Connector Spec) gọi AgentCore Runtime
theo ARN lưu trong `agentcore_agents.agentcore_agent_arn`; AgentCore Runtime
mới là nơi gọi vào Tool plane (Catalog/Router/Evidence access) mà Connector
Spec mô tả.

Sau khi tách `agentcore_agents`/`usecase_agents` thành 2 bảng (mục 4), phép
tương tự còn chặt hơn bản thảo trước: registry `capability → connector` của
Connector Spec (mục 5 spec đó) là quan hệ **nhiều-nhiều** — nhiều capability
có thể cùng back bởi 1 connector, và ngược lại 1 connector back nhiều
capability. Registry `usecase_agents` ở đây cũng vậy: nhiều usecase có thể
cùng dùng 1 `agentcore_agents` row. Hai registry vẫn độc lập, khác tầng
(`capability → connector` so với `usecase → agent`), nhưng cùng chung 1 lý do
tồn tại: tách "định danh nguồn lực dùng chung" (connector; agent) ra khỏi
"ai được phép dùng nó theo cách nào" (capability binding; usecase binding),
để nguồn lực dùng chung không phải nhân bản mỗi lần có thêm 1 bên dùng.

## 10. Việc chưa chốt

- **[Đã chốt]** Mâu thuẫn immutability vs reuse (mục 4): chọn phương án
  **`agentcore_agents` mutable, chặn update ở tầng ứng dụng** khi còn case
  `RUNNING`/`WAITING_HUMAN` tham chiếu tới nó (qua Temporal, không phải DB
  constraint) — chi tiết ở mục 4. Còn lại chưa chốt từ quyết định này:
  - Có cần quy trình "force override" cho tình huống khẩn cấp (agent lỗi cần
    vá ngay, không thể đợi mọi case sống kết thúc) hay không — nếu có, ai
    được phép bấm, và case đang chạy dựa trên bản cũ có bị escalate chủ động
    hay cứ để chạy tiếp với config cũ (rủi ro không nhất quán nếu code AgentCore
    mới đã đổi hành vi).
  - Race condition: giữa lúc backend kiểm tra "không còn case sống" và lúc
    thực sự chạy `UPDATE`, 1 case mới có thể vừa được submit và bắt đầu tham
    chiếu agent này — chưa thiết kế cơ chế khoá (transaction/advisory lock)
    để đóng cửa sổ này.
- Thiết kế chi tiết endpoint admin CRUD cho `usecases`/`usecase_versions`/
  `usecase_agents`/`agentcore_agents` (mục 6) — ai được phép sửa, có cần
  approval flow khi gán lại `agentcore_agent_arn` cho 1 agent hay không.
- **[Đã chốt]** `usecase_versions` có cột `status` (`draft`/`ready`) tách
  khỏi `is_latest`, và bắt buộc đúng 1 `kind='orchestrator'` trước khi
  publish sang `ready` (mục 4, mục 6). Còn lại chưa xử lý: version bị
  "publish nhầm" có cách nào revert về `draft` không, hay chỉ có đường tạo
  version mới — hiện doc chưa có endpoint unpublish.
- **[Đã chốt]** Circuit breaker tự kiểm tra lại `max_iterations_cap` trong
  Workflow (defense-in-depth), không chỉ tin backend clamp lúc tạo case —
  mục 3, mục 5 (`get_usecase_limits`).
- **[Đã chốt]** Tên bảng SQLAlchemy override tường minh (không dùng default
  `cls.__name__.lower()` của `BaseTableModel`), và giữ nguyên `created_by`/
  `updated_by` trên mọi bảng — mục 4.
- **[Đã chốt]** Quy ước đặt tên `usecase_agents.agent_name`: backend tự sinh
  `{usecase_key}__{agent_key}`, không nhận free-text từ admin UI — chi tiết
  ở mục 4. Còn lại chưa xử lý: ca cần liên kết cùng 1 agent 2 lần vào cùng 1
  usecase version dưới 2 vai trò khác nhau (mục 4) — hiện quy tắc sinh tên
  không cho phép, chưa có nhu cầu thực tế nên chưa thiết kế hậu tố phân biệt.
- Chiến lược cache cho registry lookup trong Activity (mục 5) — hiện query
  DB mỗi lần gọi, có thể cần TTL cache nếu tần suất cao.
- Cách chính xác Activity gọi AgentCore Runtime bằng ARN (protocol, request/
  response shape, cách map kết quả AgentCore trả về thành `decision`/`result`
  dict mà Workflow hiện đang mong đợi) — phụ thuộc AgentCore đã deploy có
  interface gì, chưa xác nhận.
- Enforce `secrets` khai trong `agentcore_agents` phải có trong env lúc
  worker start (fail-fast) — hiện chọn không enforce, chỉ dựa vào review, có
  thể cần xem lại khi số lượng usecase/agent tăng lên.
- Cơ chế dọn `usecase_versions` cũ khi chắc chắn không còn case nào tham
  chiếu — hiện để thủ công.
