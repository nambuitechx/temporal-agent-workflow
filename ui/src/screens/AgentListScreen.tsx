import { Fragment, useEffect, useState } from "react";
import { adminCreateAgent, adminGetAgentUsage, adminListAgents, adminUpdateAgent } from "@/lib/api";
import type { AgentcoreAgent, AgentUsage } from "@/types";
import { NavBar } from "@/components/NavBar";

type RefMode = "arn" | "local_tool_ref";

const EMPTY_CREATE_FORM = {
  agent_key: "",
  label: "",
  mode: "local_tool_ref" as RefMode,
  ref_value: "",
  read_only: true,
  default_timeout_seconds: 120,
};

export function AgentListScreen() {
  const [agents, setAgents] = useState<AgentcoreAgent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editRefValue, setEditRefValue] = useState("");
  const [editReadOnly, setEditReadOnly] = useState(true);
  const [editTimeout, setEditTimeout] = useState(120);

  const [usageById, setUsageById] = useState<Record<string, AgentUsage>>({});

  const reload = () => {
    adminListAgents()
      .then((res) => setAgents(res.agents))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  };

  useEffect(reload, []);

  const handleCreate = async () => {
    if (!createForm.agent_key.trim() || !createForm.label.trim() || !createForm.ref_value.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await adminCreateAgent({
        agent_key: createForm.agent_key,
        label: createForm.label,
        agentcore_agent_arn: createForm.mode === "arn" ? createForm.ref_value : null,
        local_tool_ref: createForm.mode === "local_tool_ref" ? createForm.ref_value : null,
        read_only: createForm.read_only,
        default_timeout_seconds: createForm.default_timeout_seconds,
      });
      setCreateForm(EMPTY_CREATE_FORM);
      setShowCreate(false);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (agent: AgentcoreAgent) => {
    setEditingId(agent.id);
    setEditRefValue(agent.agentcore_agent_arn ?? agent.local_tool_ref ?? "");
    setEditReadOnly(agent.read_only);
    setEditTimeout(agent.default_timeout_seconds);
  };

  const handleSaveEdit = async (agent: AgentcoreAgent) => {
    setBusy(true);
    setError(null);
    try {
      const isArn = agent.agentcore_agent_arn !== null;
      await adminUpdateAgent(agent.id, {
        ...(isArn ? { agentcore_agent_arn: editRefValue } : { local_tool_ref: editRefValue }),
        read_only: editReadOnly,
        default_timeout_seconds: editTimeout,
      });
      setEditingId(null);
      reload();
    } catch (err) {
      // mục 4 design doc: bị chặn 409 nếu còn case RUNNING/WAITING_HUMAN dùng agent này.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const loadUsage = async (agentId: string) => {
    try {
      const usage = await adminGetAgentUsage(agentId);
      setUsageById((prev) => ({ ...prev, [agentId]: usage }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <>
      <NavBar active="agents" />
      <header>
        <h1>🤖 Deployed Agents</h1>
        <p>
          Identity của agent — độc lập usecase (bảng <code>agentcore_agents</code>), tái sử dụng qua nhiều usecase
          khác nhau. Sửa bị chặn nếu còn case sống đang tham chiếu.
        </p>
      </header>

      <main className="stack">
        {error && (
          <p className="muted" style={{ color: "var(--danger)" }}>
            {error}
          </p>
        )}

        <section className="panel">
          <div className="row space-between">
            <h2 style={{ margin: 0 }}>Danh sách agent</h2>
            <button className="primary" onClick={() => setShowCreate((v) => !v)}>
              {showCreate ? "Đóng" : "+ Đăng ký agent mới"}
            </button>
          </div>

          {showCreate && (
            <div className="stack" style={{ marginTop: 14 }}>
              <div className="row">
                <div>
                  <label htmlFor="agent_key">agent_key (slug)</label>
                  <input
                    id="agent_key"
                    value={createForm.agent_key}
                    onChange={(e) => setCreateForm({ ...createForm, agent_key: e.target.value })}
                  />
                </div>
                <div>
                  <label htmlFor="agent_label">Label</label>
                  <input
                    id="agent_label"
                    value={createForm.label}
                    onChange={(e) => setCreateForm({ ...createForm, label: e.target.value })}
                  />
                </div>
              </div>

              <label htmlFor="agent_mode">Kiểu định danh</label>
              <select
                id="agent_mode"
                value={createForm.mode}
                onChange={(e) => setCreateForm({ ...createForm, mode: e.target.value as RefMode })}
              >
                <option value="local_tool_ref">local_tool_ref (mô phỏng cục bộ, module:function)</option>
                <option value="agentcore_agent_arn">agentcore_agent_arn (AgentCore thật)</option>
              </select>

              <label htmlFor="agent_ref_value">
                {createForm.mode === "arn" ? "ARN" : "local_tool_ref (vd agents.log_agent.tool:run)"}
              </label>
              <input
                id="agent_ref_value"
                value={createForm.ref_value}
                onChange={(e) => setCreateForm({ ...createForm, ref_value: e.target.value })}
              />

              <div className="row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={createForm.read_only}
                    onChange={(e) => setCreateForm({ ...createForm, read_only: e.target.checked })}
                  />
                  read_only
                </label>
                <div>
                  <label htmlFor="agent_timeout">default_timeout_seconds</label>
                  <input
                    id="agent_timeout"
                    type="number"
                    min={1}
                    value={createForm.default_timeout_seconds}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, default_timeout_seconds: Number(e.target.value) || 120 })
                    }
                  />
                </div>
              </div>

              <div className="row">
                <button className="primary" disabled={busy} onClick={() => void handleCreate()}>
                  Tạo agent
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="panel">
          {agents === null && <p className="muted">Đang tải...</p>}
          {agents !== null && agents.length === 0 && <p className="muted">Chưa có agent nào.</p>}
          {agents !== null && agents.length > 0 && (
            <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>agent_key</th>
                  <th>Label</th>
                  <th>Định danh</th>
                  <th>read_only</th>
                  <th>timeout(s)</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => {
                  const isEditing = editingId === a.id;
                  const usage = usageById[a.id];
                  return (
                    <Fragment key={a.id}>
                      <tr>
                        <td>
                          <code>{a.agent_key}</code>
                        </td>
                        <td>{a.label}</td>
                        <td>
                          {isEditing ? (
                            <input value={editRefValue} onChange={(e) => setEditRefValue(e.target.value)} />
                          ) : (
                            <code className="muted">{a.agentcore_agent_arn ?? a.local_tool_ref}</code>
                          )}
                        </td>
                        <td>
                          {isEditing ? (
                            <input
                              type="checkbox"
                              checked={editReadOnly}
                              onChange={(e) => setEditReadOnly(e.target.checked)}
                            />
                          ) : a.read_only ? (
                            "✅"
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          {isEditing ? (
                            <input
                              type="number"
                              min={1}
                              value={editTimeout}
                              onChange={(e) => setEditTimeout(Number(e.target.value) || 120)}
                            />
                          ) : (
                            a.default_timeout_seconds
                          )}
                        </td>
                        <td className="table-actions">
                          {isEditing ? (
                            <>
                              <button className="ok" disabled={busy} onClick={() => void handleSaveEdit(a)}>
                                Lưu
                              </button>
                              <button disabled={busy} onClick={() => setEditingId(null)}>
                                Huỷ
                              </button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => void loadUsage(a.id)}>Usage</button>
                              <button onClick={() => startEdit(a)}>Sửa</button>
                            </>
                          )}
                        </td>
                      </tr>
                      {usage && !isEditing && (
                        <tr>
                          <td colSpan={6}>
                            <p className="muted" style={{ margin: "4px 0" }}>
                              {usage.live_case_count > 0 ? (
                                <>
                                  ⚠️ Đang có <strong>{usage.live_case_count}</strong> case RUNNING/WAITING_HUMAN dùng
                                  agent này — sửa sẽ bị chặn (409) cho tới khi các case này kết thúc.
                                </>
                              ) : (
                                "Không có case RUNNING/WAITING_HUMAN nào đang dùng agent này — sửa được ngay."
                              )}
                              {usage.referenced_versions.length > 0 && (
                                <> ({usage.referenced_versions.length} usecase_version đang tham chiếu)</>
                              )}
                            </p>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
