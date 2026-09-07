import type { IncidentState, Scenario } from "@/types";

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
  return (await res.json()) as T;
}

export function listScenarios(): Promise<{ scenarios: Scenario[] }> {
  return request("/scenarios");
}

export function submitIncident(body: {
  description: string;
  scenario_id: string;
  max_iterations: number;
}): Promise<{ incident_id: string }> {
  return request("/incidents", { method: "POST", body: JSON.stringify(body) });
}

export function getIncident(incidentId: string): Promise<IncidentState> {
  return request(`/incidents/${incidentId}`);
}

export function approveIncident(incidentId: string, note: string): Promise<unknown> {
  return request(`/incidents/${incidentId}/approve`, { method: "POST", body: JSON.stringify({ note }) });
}

export function rejectIncident(incidentId: string, note: string): Promise<unknown> {
  return request(`/incidents/${incidentId}/reject`, { method: "POST", body: JSON.stringify({ note }) });
}
