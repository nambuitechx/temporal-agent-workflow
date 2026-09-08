import { useEffect, useState } from "react";
import { adminCreateUsecase, adminListUsecases, adminUpdateUsecase } from "@/lib/api";
import { navigate } from "@/lib/router";
import type { Usecase } from "@/types";
import { NavBar } from "@/components/NavBar";

const EMPTY_FORM = { usecase_key: "", label: "", description: "", default_max_iterations: 15, max_iterations_cap: 30 };

export function UsecaseListScreen() {
  const [usecases, setUsecases] = useState<Usecase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const reload = () => {
    adminListUsecases()
      .then((res) => setUsecases(res.usecases))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  };

  useEffect(reload, []);

  const handleCreate = async () => {
    if (!form.usecase_key.trim() || !form.label.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await adminCreateUsecase(form);
      setForm(EMPTY_FORM);
      setShowForm(false);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const handleToggleStatus = async (uc: Usecase) => {
    setTogglingId(uc.id);
    setError(null);
    try {
      await adminUpdateUsecase(uc.id, { status: uc.status === "active" ? "disabled" : "active" });
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTogglingId(null);
    }
  };

  return (
    <>
      <NavBar active="usecases" />
      <header>
        <h1>📋 Usecases</h1>
        <p>Quản lý usecase — mỗi usecase gồm nhiều version (append-only), mỗi version gán 1 orchestrator + N subagent.</p>
      </header>

      <main className="stack">
        {error && (
          <p className="muted" style={{ color: "var(--danger)" }}>
            {error}
          </p>
        )}

        <section className="panel">
          <div className="row space-between">
            <h2 style={{ margin: 0 }}>Danh sách usecase</h2>
            <button className="primary" onClick={() => setShowForm((v) => !v)}>
              {showForm ? "Đóng" : "+ Tạo usecase mới"}
            </button>
          </div>

          {showForm && (
            <div className="stack" style={{ marginTop: 14 }}>
              <label htmlFor="usecase_key">usecase_key (slug, vd: incident_investigation)</label>
              <input
                id="usecase_key"
                value={form.usecase_key}
                onChange={(e) => setForm({ ...form, usecase_key: e.target.value })}
              />
              <label htmlFor="label">Label</label>
              <input id="label" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
              <label htmlFor="description">Description</label>
              <textarea
                id="description"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
              <div className="row">
                <div>
                  <label htmlFor="default_max_iterations">default_max_iterations</label>
                  <input
                    id="default_max_iterations"
                    type="number"
                    min={1}
                    value={form.default_max_iterations}
                    onChange={(e) => setForm({ ...form, default_max_iterations: Number(e.target.value) || 15 })}
                  />
                </div>
                <div>
                  <label htmlFor="max_iterations_cap">max_iterations_cap</label>
                  <input
                    id="max_iterations_cap"
                    type="number"
                    min={1}
                    value={form.max_iterations_cap}
                    onChange={(e) => setForm({ ...form, max_iterations_cap: Number(e.target.value) || 30 })}
                  />
                </div>
              </div>
              <div className="row">
                <button className="primary" disabled={creating} onClick={() => void handleCreate()}>
                  {creating ? "Đang tạo..." : "Tạo usecase"}
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="panel">
          {usecases === null && <p className="muted">Đang tải...</p>}
          {usecases !== null && usecases.length === 0 && <p className="muted">Chưa có usecase nào.</p>}
          {usecases !== null && usecases.length > 0 && (
            <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>usecase_key</th>
                  <th>Label</th>
                  <th>Status</th>
                  <th>max_iterations (default / cap)</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {usecases.map((uc) => (
                  <tr key={uc.id}>
                    <td>
                      <code>{uc.usecase_key}</code>
                    </td>
                    <td>{uc.label}</td>
                    <td>
                      <span className={`status-badge status-${uc.status}`}>{uc.status}</span>
                    </td>
                    <td>
                      {uc.default_max_iterations} / {uc.max_iterations_cap}
                    </td>
                    <td className="table-actions">
                      <button onClick={() => navigate(`/usecases/${uc.id}`)}>Chi tiết →</button>
                      <button
                        disabled={togglingId === uc.id}
                        onClick={() => void handleToggleStatus(uc)}
                        title={
                          uc.status === "active"
                            ? "Disable — chặn tạo case mới, không ảnh hưởng case đang chạy"
                            : "Enable lại usecase này"
                        }
                      >
                        {uc.status === "active" ? "Disable" : "Enable"}
                      </button>
                      <button
                        className="primary"
                        disabled={uc.status !== "active"}
                        onClick={() => navigate(`/cases/${encodeURIComponent(uc.usecase_key)}`)}
                      >
                        Incident Analysis →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
