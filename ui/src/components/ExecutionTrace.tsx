import type { IncidentState } from "@/types";

function formatContent(content: unknown): string {
  return typeof content === "string" ? content : JSON.stringify(content, null, 2);
}

export function ExecutionTrace({ state }: { state: IncidentState | null }) {
  const status = state?.status ?? "IDLE";

  return (
    <section className="panel">
      <h2>
        2. Execution Trace <span className={`status-badge status-${status}`}>{status}</span>
      </h2>
      <p className="muted">
        Iteration: {state?.iteration ?? 0} — dựng lại từ Temporal Event History qua{" "}
        <code>get_state()</code> query, không cần hệ thống log riêng.
      </p>
      <ul className="timeline">
        {(state?.history ?? []).map((entry, idx) => (
          <li key={idx}>
            <div className="role">{entry.role}</div>
            <pre>{formatContent(entry.content)}</pre>
          </li>
        ))}
        {state?.final_answer && (
          <li>
            <div className="role">final_answer</div>
            <pre>{state.final_answer}</pre>
          </li>
        )}
      </ul>
    </section>
  );
}
