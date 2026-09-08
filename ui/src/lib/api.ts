import type {
  AgentcoreAgent,
  AgentUsage,
  CaseState,
  Scenario,
  Usecase,
  UsecaseVersion,
  UsecaseVersionDetail,
} from "@/types";

// Luôn gọi qua "/api" — cùng-origin ở mọi môi trường:
//   - `npm run dev`/`preview`: Vite proxy /api -> API_URL (xem vite.config.ts)
//   - Docker (nginx phục vụ static build): nginx proxy /api -> backend:8000
//     (xem ui/nginx.conf + docker-compose.yml)
const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} → HTTP ${res.status}: ${await res.text()}`);
  }
  // 204 No Content (vd DELETE) không có body — res.json() sẽ throw nếu gọi.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Cases — start/query/signal (mục 3/6 design doc)
// ---------------------------------------------------------------------------

export function listDemoScenarios(): Promise<{ scenarios: Scenario[] }> {
  return request("/demo-scenarios");
}

export function submitCase(body: {
  usecaseKey: string;
  description: string;
  scenarioId: string;
  maxIterations: number;
}): Promise<{ case_id: string }> {
  return request("/cases", {
    method: "POST",
    body: JSON.stringify({
      usecase_key: body.usecaseKey,
      case_context: { scenario_id: body.scenarioId, description: body.description },
      max_iterations: body.maxIterations,
    }),
  });
}

export function getCase(caseId: string): Promise<CaseState> {
  return request(`/cases/${caseId}`);
}

export function approveCase(caseId: string, note: string): Promise<unknown> {
  return request(`/cases/${caseId}/approve`, { method: "POST", body: JSON.stringify({ note }) });
}

export function rejectCase(caseId: string, note: string): Promise<unknown> {
  return request(`/cases/${caseId}/reject`, { method: "POST", body: JSON.stringify({ note }) });
}

// ---------------------------------------------------------------------------
// Admin — usecases / usecase_versions / usecase_agents (mục 6 design doc)
// ---------------------------------------------------------------------------

export function adminListUsecases(): Promise<{ usecases: Usecase[] }> {
  return request("/admin/usecases");
}

export function adminGetUsecase(usecaseId: string): Promise<Usecase> {
  return request(`/admin/usecases/${usecaseId}`);
}

export function adminCreateUsecase(body: {
  usecase_key: string;
  label: string;
  description: string;
  default_max_iterations: number;
  max_iterations_cap: number;
}): Promise<Usecase> {
  return request("/admin/usecases", { method: "POST", body: JSON.stringify(body) });
}

export function adminUpdateUsecase(
  usecaseId: string,
  body: Partial<{
    label: string;
    description: string;
    default_max_iterations: number;
    max_iterations_cap: number;
    status: "active" | "disabled";
  }>,
): Promise<Usecase> {
  return request(`/admin/usecases/${usecaseId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function adminListVersions(usecaseId: string): Promise<{ versions: UsecaseVersion[] }> {
  return request(`/admin/usecases/${usecaseId}/versions`);
}

export function adminCreateVersion(usecaseId: string): Promise<UsecaseVersion> {
  return request(`/admin/usecases/${usecaseId}/versions`, { method: "POST" });
}

export function adminGetVersion(versionId: string): Promise<UsecaseVersionDetail> {
  return request(`/admin/usecase-versions/${versionId}`);
}

export function adminLinkAgent(
  versionId: string,
  body: { agent_id: string; kind: "orchestrator" | "subagent"; timeout_seconds?: number | null },
): Promise<{ id: string; agent_name: string; kind: string }> {
  return request(`/admin/usecase-versions/${versionId}/agents`, { method: "POST", body: JSON.stringify(body) });
}

export function adminPublishVersion(versionId: string): Promise<UsecaseVersion> {
  return request(`/admin/usecase-versions/${versionId}/publish`, { method: "POST" });
}

export function adminUnlinkAgent(versionId: string, linkId: string): Promise<void> {
  return request(`/admin/usecase-versions/${versionId}/agents/${linkId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Admin — agentcore_agents (mục 6 design doc)
// ---------------------------------------------------------------------------

export function adminListAgents(): Promise<{ agents: AgentcoreAgent[] }> {
  return request("/admin/agentcore-agents");
}

export function adminCreateAgent(body: {
  agent_key: string;
  label: string;
  agentcore_agent_arn?: string | null;
  local_tool_ref?: string | null;
  read_only: boolean;
  default_timeout_seconds: number;
}): Promise<AgentcoreAgent> {
  return request("/admin/agentcore-agents", { method: "POST", body: JSON.stringify(body) });
}

export function adminUpdateAgent(agentId: string, body: Partial<AgentcoreAgent>): Promise<AgentcoreAgent> {
  return request(`/admin/agentcore-agents/${agentId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function adminGetAgentUsage(agentId: string): Promise<AgentUsage> {
  return request(`/admin/agentcore-agents/${agentId}/usage`);
}
