export interface Scenario {
  id: string;
  label: string;
  description: string;
}

export interface RcaProposal {
  hypothesis?: string;
  confidence?: number;
  supporting_evidence_refs?: string[];
}

export interface HistoryEntry {
  role: "user" | "orchestrator" | "tool" | "human" | string;
  content: unknown;
}

export type WorkflowStatus = "RUNNING" | "WAITING_HUMAN" | "FINISHED" | "ESCALATED";

export interface CaseState {
  case_id: string;
  usecase_id: string;
  usecase_version_id: string;
  status: WorkflowStatus;
  iteration: number;
  history: HistoryEntry[];
  artifacts: unknown[];
  proposal: RcaProposal | null;
  final_answer: string | null;
}

// ---------------------------------------------------------------------------
// Registry (mục 4 của docs/2026-09-08-generic-agent-loop-design.md)
// ---------------------------------------------------------------------------

export type UsecaseStatus = "active" | "disabled";
export type UsecaseVersionStatus = "draft" | "ready";
export type AgentKind = "orchestrator" | "subagent";

export interface Usecase {
  id: string;
  usecase_key: string;
  label: string;
  description: string;
  status: UsecaseStatus;
  default_max_iterations: number;
  max_iterations_cap: number;
}

export interface UsecaseVersion {
  id: string;
  usecase_id: string;
  version_number: number;
  is_latest: boolean;
  status: UsecaseVersionStatus;
}

export interface UsecaseVersionAgentLink {
  id: string;
  agent_name: string;
  kind: AgentKind;
  agent_id: string;
}

export interface UsecaseVersionDetail extends UsecaseVersion {
  agents: UsecaseVersionAgentLink[];
}

export interface AgentcoreAgent {
  id: string;
  agent_key: string;
  label: string;
  agentcore_agent_arn: string | null;
  local_tool_ref: string | null;
  read_only: boolean;
  secrets: string[];
  default_timeout_seconds: number;
  default_retry_policy: Record<string, unknown>;
  agent_metadata: Record<string, unknown>;
}

export interface AgentUsage {
  referenced_versions: { usecase_version_id: string; live_case_count: number }[];
  live_case_count: number;
}
