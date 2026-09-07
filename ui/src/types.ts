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

export interface IncidentState {
  incident_id: string;
  status: WorkflowStatus;
  iteration: number;
  history: HistoryEntry[];
  evidence: unknown[];
  rca_proposal: RcaProposal | null;
  final_answer: string | null;
}
