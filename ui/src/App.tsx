import { useCallback, useEffect, useRef, useState } from "react";
import { approveIncident, getIncident, rejectIncident, submitIncident } from "@/lib/api";
import type { IncidentState } from "@/types";
import { IncidentForm } from "@/components/IncidentForm";
import { ExecutionTrace } from "@/components/ExecutionTrace";
import { ApprovalPanel } from "@/components/ApprovalPanel";

const POLL_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(["FINISHED", "ESCALATED"]);

export default function App() {
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [state, setState] = useState<IncidentState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const poll = useCallback(async (id: string) => {
    try {
      const next = await getIncident(id);
      setState(next);
      if (TERMINAL_STATUSES.has(next.status)) stopPolling();
    } catch (err) {
      // Backend/Temporal có thể đang khởi động — bỏ qua, thử lại ở lần poll sau.
      console.warn("poll error", err);
    }
  }, [stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  const handleSubmit = async (input: { description: string; scenarioId: string; maxIterations: number }) => {
    setSubmitting(true);
    setError(null);
    stopPolling();
    try {
      const { incident_id } = await submitIncident({
        description: input.description,
        scenario_id: input.scenarioId,
        max_iterations: input.maxIterations,
      });
      setIncidentId(incident_id);
      setState(null);
      void poll(incident_id);
      pollRef.current = setInterval(() => void poll(incident_id), POLL_INTERVAL_MS);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDecide = async (action: "approve" | "reject", note: string) => {
    if (!incidentId) return;
    if (action === "approve") await approveIncident(incidentId, note);
    else await rejectIncident(incidentId, note);
    void poll(incidentId);
  };

  return (
    <>
      <header>
        <h1>🧪 Xora POC — Dynamic Agent Loop + Multi-Agent + HITL</h1>
        <p>Web UI mô phỏng — submit incident, theo dõi Orchestrator/Agent điều tra realtime, và approve/reject RCA.</p>
      </header>

      <main>
        <div>
          <IncidentForm onSubmit={handleSubmit} submitting={submitting} lastIncidentId={incidentId} error={error} />
          {state?.status === "WAITING_HUMAN" && state.rca_proposal && (
            <ApprovalPanel rcaProposal={state.rca_proposal} onDecide={handleDecide} />
          )}
        </div>
        <ExecutionTrace state={state} />
      </main>
    </>
  );
}
