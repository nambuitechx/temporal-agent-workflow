import { useEffect, useState } from "react";
import type { Scenario } from "@/types";
import { listScenarios } from "@/lib/api";

interface Props {
  onSubmit: (input: { description: string; scenarioId: string; maxIterations: number }) => Promise<void>;
  submitting: boolean;
  lastIncidentId: string | null;
  error: string | null;
}

export function IncidentForm({ onSubmit, submitting, lastIncidentId, error }: Props) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioIndex, setScenarioIndex] = useState(0);
  const [description, setDescription] = useState("");
  const [maxIterations, setMaxIterations] = useState(15);

  useEffect(() => {
    listScenarios().then((res) => {
      setScenarios(res.scenarios);
      if (res.scenarios.length > 0) setDescription(res.scenarios[0].description);
    });
  }, []);

  const handleScenarioChange = (index: number) => {
    setScenarioIndex(index);
    setDescription(scenarios[index]?.description ?? "");
  };

  const handleSubmit = () => {
    const scenario = scenarios[scenarioIndex];
    if (!scenario) return;
    void onSubmit({ description, scenarioId: scenario.id, maxIterations });
  };

  return (
    <section className="panel">
      <h2>1. Submit Incident</h2>

      <label htmlFor="scenario">Scenario (mục 2 của POC design)</label>
      <select
        id="scenario"
        value={scenarioIndex}
        onChange={(e) => handleScenarioChange(Number(e.target.value))}
      >
        {scenarios.map((s, idx) => (
          <option key={`${s.id}-${idx}`} value={idx}>
            {s.label}
          </option>
        ))}
      </select>

      <label htmlFor="description">Mô tả incident</label>
      <textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} />

      <label htmlFor="maxIterations">Max iterations (circuit breaker)</label>
      <input
        id="maxIterations"
        type="number"
        min={1}
        max={100}
        value={maxIterations}
        onChange={(e) => setMaxIterations(Number(e.target.value) || 15)}
      />

      <div className="row">
        <button className="primary" disabled={submitting || scenarios.length === 0} onClick={handleSubmit}>
          {submitting ? "Đang submit..." : "Submit incident"}
        </button>
      </div>

      {lastIncidentId && (
        <p className="muted">
          Incident: <span className="incident-id">{lastIncidentId}</span>
        </p>
      )}
      {error && <p className="muted" style={{ color: "var(--danger)" }}>{error}</p>}
    </section>
  );
}
