# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A runnable implementation of the **While-Loop + Orchestrator Agent** dynamic
agent loop pattern, generic across usecases (design docs:
`docs/2026-09-07-poc-design-dynamic-agent-loop.md` for the original POC,
`docs/2026-09-08-generic-agent-loop-design.md` for the runtime/domain split —
**read the second one first**, it supersedes the hardcoded-usecase framing of
the first). An LLM Orchestrator investigates a case by calling Specialized
Agents, proposes a result, and **must always** wait for human approve/reject
via Temporal signal before finishing — there is no "auto-finish" path. The
POC ships exactly 1 usecase (`incident_investigation`, seeded via `make
seed`) but the Workflow/Activity code has no usecase-specific logic left in it.

Stack: **uv** (backend + worker, Python 3.12) + **Vite/React/TypeScript** (ui)
+ **Postgres** (control-plane registry, SQLAlchemy async + Alembic) +
**AWS Bedrock** Converse API via raw `boto3` (not the `anthropic` SDK, not
Bedrock AgentCore — just a model provider swap, see
`agents/_common/llm.py`). Auth is via AWS credential chain (`~/.aws` mounted
read-only into the worker container) — no API keys.

## Commands

```bash
# Run everything (temporal + postgres + worker + backend + ui)
make run              # docker compose up -d --build
make down             # docker compose down
make migrate          # alembic upgrade head, inside the backend container
make seed             # seed usecase incident_investigation + 3 agents (idempotent)

# Run tests (mocked activities, no Bedrock/AWS/Postgres credentials needed —
# see tests/test_workflow.py docstring for why Postgres isn't required here)
docker run --rm -v "$PWD":/app -w /app python:3.12-slim bash -c "
  pip install temporalio==1.9.0 sqlalchemy==2.0.36 asyncpg==0.30.0 pytest==8.3.4 pytest-asyncio==0.24.0 &&
  PYTHONPATH=/app python -m pytest tests/ -v
"
# or, if deps are already installed locally:
PYTHONPATH=. pytest tests/ -v
# single test:
PYTHONPATH=. pytest tests/test_workflow.py::test_scenario_b_hitl_reject_then_continue -v

# UI dev mode (no Docker) — needs backend + worker + postgres running separately
cd ui && npm install && npm run dev     # http://localhost:3000, proxies /api -> :8000
cd backend && uv sync && uv run uvicorn backend.main:app --reload --port 8000
cd worker && uv sync && uv run python main.py

# UI typecheck
cd ui && npm run check
```

Before running against real Bedrock: `cp .env.example .env`, set
`AWS_PROFILE`/`AWS_REGION`/`BEDROCK_MODEL_ID` to match an account with Claude
3.5 Sonnet enabled in **Bedrock Model Access** for that region. After
`make run`, run `make migrate && make seed` once before submitting any case —
`POST /cases` fails with 409 if the usecase has no `usecase_version` at
`status=ready` yet. Scenario E never calls Bedrock (short-circuited by a test
hook keyed on `case_context.scenario_id`), so it works with no AWS
credentials at all — useful for a quick smoke test.

Ports once running: UI `:3000`, Backend/FastAPI docs `:8000/docs`, Temporal
Web UI (Event History, replay) `:8233`, Postgres `:5432` (control-plane
registry — separate from Temporal's own internal SQLite).

## Architecture

Five independent processes/containers, deliberately split by responsibility
(see `docs/2026-09-08-generic-agent-loop-design.md` mục 0 for the full
rationale — this repo owns the Temporal runtime + registry metadata, NOT
agent execution, which is AWS Bedrock AgentCore's job once that integration
lands):

- **`worker/`** — Temporal Worker only. Registers `AgentLoopWorkflow` + 4
  activities (`ask_orchestrator`, `run_agent`, `notify_human`,
  `get_usecase_limits`), polls the task queue. No HTTP surface. Reads
  Postgres (via `shared/db/registry.py`) to resolve which agent to call.
- **`backend/`** — FastAPI app: a thin Temporal client (start/query/signal
  case) **plus** CRUD admin for the Postgres registry (usecases/versions/
  agent links/agent identities). No LLM calls, does not register a Worker.
- **`postgres/`** — control-plane registry (see Schema below). Independent
  from Temporal's own SQLite persistence.
- **`agents/`** — top-level, sibling of `shared/`/`worker/`/`backend/`. Source
  code (prompt + fake-tool implementation) for every agent, one flat
  directory per `agent_key` (`agents/log_agent/`, `agents/metrics_agent/`,
  `agents/incident_investigation_orchestrator/`), each with `prompt.md` +
  `tool.py::run(args, case_context) -> dict`. Deliberately NOT under
  `shared/` — this directory is meant to be lifted-and-shifted into an
  AgentCore deployment later without carrying Temporal runtime code with it.
  `agents/_common/llm.py` holds the shared Bedrock-calling helper (stand-in
  for AgentCore Runtime inference — gets replaced, not extended, once
  AgentCore integration lands).
- **`shared/`** — code imported by both worker and backend:
  - `models.py` — **runtime-only** constants: `ALLOWED_ACTIONS` (no
    `"FINISH"` — see comment there, a past iteration let the LLM self-report
    a confidence score and skip human review, an unenforceable guardrail),
    `TASK_QUEUE`. `ALLOWED_AGENTS` no longer lives here — allowed agents are
    now **data** per `usecase_version_id` (`shared/db/registry.list_allowed_agents`).
  - `workflows.py` — `AgentLoopWorkflow` (generic, was
    `IncidentInvestigationWorkflow`): the deterministic while-loop. Only
    calls `workflow.execute_activity`/`workflow.wait_condition`, never
    touches the network/LLM/DB/clock directly (Temporal determinism
    requirement) — all non-determinism lives in `activities.py`. State
    fields are usecase-neutral: `case_id`, `proposal`, `artifacts` (were
    `incident_id`/`rca_proposal`/`evidence`), plus new `usecase_id`/
    `usecase_version_id`. Circuit breaker is defense-in-depth: Workflow
    resolves `usecases.max_iterations_cap` itself via the
    `get_usecase_limits` activity and clamps against it, not trusting the
    backend's own clamp at case-creation time alone.
  - `activities.py` — the only place that queries Postgres or invokes an
    agent. `ask_orchestrator`/`run_agent` resolve a `ResolvedAgent` from
    `shared/db/registry.py` by `usecase_version_id`, then either call
    `agentcore_agent_arn` (not implemented yet — raises `ApplicationError`
    type `"NotImplemented"`) or import `local_tool_ref` (`module:function`,
    e.g. `agents.log_agent.tool:run`) and call it directly. Both activities
    independently validate against the allowlist (defense-in-depth — the
    workflow never trusts a single validation layer): `ask_orchestrator`
    validates `ALLOWED_ACTIONS` + DB-sourced `allowed_agents`; `run_agent`
    re-checks `allowed_agents` independently.
  - `db/` — `session.py` (async engine/sessionmaker, `DATABASE_URL` env),
    `models.py` (SQLAlchemy: `usecases`, `usecase_versions`,
    `agentcore_agents`, `usecase_agents` — see Schema below), `registry.py`
    (`get_orchestrator`/`get_agent`/`list_allowed_agents`/`get_usecase_limits`,
    all query fresh every call, no cache), `seed.py` (idempotent demo seed).
  - `alembic/` — migrations, `versions/0001_usecases.py` creates all 4
    tables. Run via root `alembic.ini` (`script_location = shared/alembic`).
  - `data/scenarios/` — canned log/metric fixtures per demo scenario, read
    by `agents/{log_agent,metrics_agent}/tool.py` (path stayed in `shared/`
    on purpose — only tool *code* moved to `agents/`, not fixture data).
- **`ui/`** — Vite/React/TS SPA, built static and served by nginx, which
  proxies `/api/*` to the backend container. Talks to `/cases`, `/demo-scenarios`
  (a UI-only convenience endpoint listing the 5 canned `case_context.scenario_id`
  presets — NOT part of the generic registry).

### Registry schema (Postgres, `shared/db/models.py`)

`usecases` (1 row/domain) → `usecase_versions` (append-only snapshot,
`status: draft|ready`, only `ready` versions get resolved for new cases) →
`usecase_agents` (N-N link: which `agentcore_agents` row plays orchestrator/
subagent in this version, `agent_name` auto-generated as
`{usecase_key}__{agent_key}`) → `agentcore_agents` (agent identity,
independent of usecase — `agentcore_agent_arn` XOR `local_tool_ref`, exactly
one required). A version needs exactly 1 `kind=orchestrator` link before it
can be published (`POST /admin/usecase-versions/{id}/publish`) to `ready`.
`agentcore_agents` is mutable but blocked at the application layer while any
`usecase_version` referencing it has a `RUNNING`/`WAITING_HUMAN` case (queried
against Temporal, not Postgres — see `backend/main.py::_live_case_count_for_agent`).
Full rationale: `docs/2026-09-08-generic-agent-loop-design.md` mục 4.

### Workflow control flow (`shared/workflows.py`)

1. Resolve `usecases.max_iterations_cap` via `get_usecase_limits` activity,
   clamp `max_iterations` from the request against it.
2. Loop while `iteration < effective_max_iterations`:
   - `ask_orchestrator` activity → `action`.
   - `NEEDS_HUMAN` → status `WAITING_HUMAN`, `workflow.wait_condition` on the
     `approved` signal field (0 compute while waiting, verifiable in Temporal
     Web UI). `approve` → `notify_human` → `FINISHED`. `reject` → back to
     `RUNNING`, loop continues with the rejection note in history.
   - `CALL_AGENT` → `run_agent` activity, result appended to `artifacts`, loop.
   - Any `ActivityError` (guardrail violation, registry error, unparseable
     model output) or unknown action → escalate immediately (`ESCALATED`),
     never guess/retry the disallowed action.
3. Loop exceeds `effective_max_iterations` → circuit breaker → escalate.

`get_state` is a `@workflow.query` — reads current state without waiting for
completion or affecting Event History; this is what the backend polls and
what the UI timeline is built from.

### Demo scenarios (`case_context.scenario_id`, see design docs for full detail)

Same 5 canned scenarios as the original POC (A–E), now selected via
`case_context.scenario_id` inside `POST /cases` instead of a top-level field
— `agents/{log_agent,metrics_agent}/tool.py` read `shared/data/scenarios/{scenario_id}/`.
Scenario E's guardrail-violation test hook lives in
`shared/activities.py::ask_orchestrator`, keyed on `case_context.scenario_id`.

`tests/test_workflow.py` covers all 5 scenarios plus 2 regression tests: 1)
`test_legacy_finish_action_no_longer_completes_workflow` locks in that a
`"FINISH"` action can never complete the workflow; 2)
`test_circuit_breaker_caps_at_usecase_max_iterations_cap` locks in the
defense-in-depth cap check (Workflow must not trust a request-supplied
`max_iterations` past `usecases.max_iterations_cap`). All 4 activities are
faked in these tests using Temporal's time-skipping `WorkflowEnvironment` —
no LLM or Postgres is called (fakes never touch `shared/db/registry.py`).

### Why Bedrock via raw boto3

`agents/_common/llm.py` calls `bedrock-runtime.converse(...)` directly with
`boto3`, not the `anthropic`/`AnthropicBedrock` SDK — this is AWS's own
unified Converse API across any Bedrock model, not Anthropic's Messages API
format. Keep this distinction if extending `call_llm_json`: request/response
shapes follow the Converse API, not Anthropic's API.
