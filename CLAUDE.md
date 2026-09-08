# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A runnable POC implementing the **While-Loop + Orchestrator Agent** dynamic
agent loop pattern (design doc: `docs/2026-09-07-poc-design-dynamic-agent-loop.md`), scaled
down from Xora Resolve's "Incident Investigation Runtime" idea. An LLM
Orchestrator investigates a fake incident by calling Specialized Agents
(`log_agent`, `metrics_agent`), proposes an RCA, and **must always** wait for
human approve/reject via Temporal signal before finishing — there is no
"auto-finish" path.

Stack: **uv** (backend + worker, Python 3.12) + **Vite/React/TypeScript** (ui)
+ **AWS Bedrock** Converse API via raw `boto3` (not the `anthropic` SDK, not
Bedrock AgentCore — just a model provider swap). Auth is via AWS credential
chain (`~/.aws` mounted read-only into the worker container) — no API keys.

## Commands

```bash
# Run everything (temporal + worker + backend + ui)
make run              # docker compose up -d --build
make down             # docker compose down

# Run tests (mocked activities, no Bedrock/AWS credentials needed)
docker run --rm -v "$PWD":/app -w /app python:3.12-slim bash -c "
  pip install temporalio==1.9.0 boto3==1.35.99 pytest==8.3.4 pytest-asyncio==0.24.0 &&
  PYTHONPATH=/app python -m pytest tests/ -v
"
# or, if deps are already installed locally:
PYTHONPATH=. pytest tests/ -v
# single test:
PYTHONPATH=. pytest tests/test_workflow.py::test_scenario_b_hitl_reject_then_continue -v

# UI dev mode (no Docker) — needs backend + worker running separately
cd ui && npm install && npm run dev     # http://localhost:3000, proxies /api -> :8000
cd backend && uv sync && uv run uvicorn backend.main:app --reload --port 8000
cd worker && uv sync && uv run python main.py

# UI typecheck
cd ui && npm run check
```

Before running against real Bedrock: `cp .env.example .env`, set
`AWS_PROFILE`/`AWS_REGION`/`BEDROCK_MODEL_ID` to match an account with Claude
3.5 Sonnet enabled in **Bedrock Model Access** for that region. Scenario E
never calls Bedrock (short-circuited by a test hook), so it works with no AWS
credentials at all — useful for a quick smoke test.

Ports once running: UI `:3000`, Backend/FastAPI docs `:8000/docs`, Temporal
Web UI (Event History, replay) `:8233`.

## Architecture

Four independent processes/containers, deliberately split by responsibility:

- **`worker/`** — Temporal Worker only. Registers `IncidentInvestigationWorkflow`
  + the 3 activities, polls the task queue. No HTTP surface.
- **`backend/`** — FastAPI app that is *only* a thin Temporal client (start
  workflow, query state, send approve/reject signals). No business logic, no
  LLM calls, does not register a Worker.
- **`shared/`** — code imported by both worker and backend:
  - `models.py` — the allowlists (`ALLOWED_ACTIONS`, `ALLOWED_AGENTS`) that
    are the actual guardrail. **`ALLOWED_ACTIONS` intentionally has no
    `"FINISH"`** — read the comment there before ever adding one back; a past
    iteration let the LLM self-report a confidence score and skip human
    review, which turned out to be an unenforceable, exploitable "guardrail."
  - `workflows.py` — `IncidentInvestigationWorkflow`: the deterministic
    while-loop. Only calls `workflow.execute_activity`/`workflow.wait_condition`,
    never touches the network/LLM/clock directly (Temporal determinism
    requirement) — all non-determinism lives in `activities.py`.
  - `activities.py` — the only place that calls Bedrock (`converse()` API)
    or reads fake tool data. `ask_orchestrator` validates the LLM's decision
    against the allowlists itself and raises a non-retryable
    `ApplicationError(type="GuardrailViolation")` if violated; `run_agent`
    re-validates `agent_name` again independently (defense-in-depth — the
    workflow never trusts a single validation layer).
  - `agents/` — system prompts for the Orchestrator + the 2 Specialized Agents.
  - `tools/` — fake data readers (`incident_logs.py`, `incident_metrics.py`)
    standing in for real observability APIs.
  - `data/scenarios/` — canned log/metric fixtures, one set per scenario.
- **`ui/`** — Vite/React/TS SPA, built static and served by nginx, which
  proxies `/api/*` to the backend container.

### Workflow control flow (`shared/workflows.py`)

Loop while `iteration < max_iterations`:
1. Call `ask_orchestrator` activity → get `action`.
2. `action == "NEEDS_HUMAN"` → set status `WAITING_HUMAN`, then
   `workflow.wait_condition` on the `approved` signal field — this suspends
   the workflow with **zero compute** until a signal arrives (verifiable in
   Temporal Web UI: Status stays `Running`, Pending Activities stays empty).
   - `approve` signal → `notify_human` activity → status `FINISHED`.
   - `reject` signal → status back to `RUNNING`, loop continues with the
     rejection note appended to history so the Orchestrator can react to it.
3. `action == "CALL_AGENT"` → call `run_agent` activity for `log_agent` or
   `metrics_agent`, append result to `evidence`, continue loop.
4. Any `ActivityError` (guardrail violation, unparseable model output) or
   unknown action → escalate immediately (status `ESCALATED`) via `_escalate`,
   never attempt to guess/retry the disallowed action.
5. Loop exceeds `max_iterations` → circuit breaker → escalate.

`get_state` is a `@workflow.query` — reads current state without waiting for
the workflow to complete or affecting Event History; this is what the backend
polls and what the UI timeline is built from.

### Demo scenarios (see design doc §2 and README for full detail)

- **A** — happy path → `WAITING_HUMAN` → Approve → `FINISHED`.
- **B** — same data as A, but Reject → loop continues with the note, expect a
  different RCA → eventually approved.
- **C** — evidence deliberately unambiguous (clear stacktrace) to check the
  LLM can't skip HITL even at very high self-reported confidence. This is the
  key regression scenario for the "no FINISH action" invariant.
- **D** — ambiguous data forcing >`max_iterations` calls → circuit breaker →
  `ESCALATED` (submit with `max_iterations=2` in the UI to trigger reliably).
- **E** — simulated guardrail violation (`agent_name="shell_agent"`) injected
  by a test hook in `ask_orchestrator` *before* any Bedrock call is made — the
  only scenario that needs no AWS credentials at all.

`tests/test_workflow.py` covers all 5 scenarios plus one regression test
(`test_legacy_finish_action_no_longer_completes_workflow`) locking in that a
`"FINISH"` action from any activity (rogue/legacy/buggy) can never complete
the workflow — it must fall through to `ESCALATED` like any other unknown
action. All activities are faked in these tests (`@activity.defn(name=...)`
overrides) using Temporal's time-skipping `WorkflowEnvironment` — no LLM is
called.

### Why Bedrock via raw boto3

`activities.py` calls `bedrock-runtime.converse(...)` directly with `boto3`,
not the `anthropic`/`AnthropicBedrock` SDK — this is AWS's own unified
Converse API across any Bedrock model, not Anthropic's Messages API format.
Keep this distinction if extending `_call_orchestrator_llm`/`run_agent`:
request/response shapes follow the Converse API, not Anthropic's API.
