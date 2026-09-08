import { useCallback, useEffect, useRef, useState } from "react";
import { approveCase, getCase, rejectCase, submitCase } from "@/lib/api";
import { navigate } from "@/lib/router";
import type { CaseState } from "@/types";
import { IncidentForm } from "@/components/IncidentForm";
import { ExecutionTrace } from "@/components/ExecutionTrace";
import { ApprovalPanel } from "@/components/ApprovalPanel";
import { NavBar } from "@/components/NavBar";

const POLL_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(["FINISHED", "ESCALATED"]);

interface Props {
  usecaseKey: string;
}

export function CaseWorkspaceScreen({ usecaseKey }: Props) {
  const [caseId, setCaseId] = useState<string | null>(null);
  const [state, setState] = useState<CaseState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const poll = useCallback(
    async (id: string) => {
      try {
        const next = await getCase(id);
        setState(next);
        if (TERMINAL_STATUSES.has(next.status)) stopPolling();
      } catch (err) {
        // Backend/Temporal có thể đang khởi động — bỏ qua, thử lại ở lần poll sau.
        console.warn("poll error", err);
      }
    },
    [stopPolling],
  );

  useEffect(() => stopPolling, [stopPolling]);
  // Đổi usecase (điều hướng sang case-workspace khác) -> reset state cũ, không
  // để lẫn case của usecase trước.
  useEffect(() => {
    stopPolling();
    setCaseId(null);
    setState(null);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usecaseKey]);

  const handleSubmit = async (input: { description: string; scenarioId: string; maxIterations: number }) => {
    setSubmitting(true);
    setError(null);
    stopPolling();
    try {
      const { case_id } = await submitCase({ usecaseKey, ...input });
      setCaseId(case_id);
      setState(null);
      void poll(case_id);
      pollRef.current = setInterval(() => void poll(case_id), POLL_INTERVAL_MS);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDecide = async (action: "approve" | "reject", note: string) => {
    if (!caseId) return;
    if (action === "approve") await approveCase(caseId, note);
    else await rejectCase(caseId, note);
    void poll(caseId);
  };

  return (
    <>
      <NavBar active="cases" />
      <header>
        <button className="link-back" onClick={() => navigate("/usecases")}>
          ← Usecases
        </button>
        <h1>
          🧪 Incident Analysis — <code>{usecaseKey}</code>
        </h1>
        <p>Submit case, theo dõi Orchestrator/Agent điều tra realtime, và approve/reject proposal.</p>
      </header>

      <main>
        <div>
          <IncidentForm onSubmit={handleSubmit} submitting={submitting} lastCaseId={caseId} error={error} />
          {state?.status === "WAITING_HUMAN" && state.proposal && (
            <ApprovalPanel rcaProposal={state.proposal} onDecide={handleDecide} />
          )}
        </div>
        <ExecutionTrace state={state} />
      </main>
    </>
  );
}
