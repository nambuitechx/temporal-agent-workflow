import { useEffect, useState } from "react";
import {
  adminCreateVersion,
  adminGetUsecase,
  adminGetVersion,
  adminLinkAgent,
  adminListAgents,
  adminListVersions,
  adminPublishVersion,
  adminUnlinkAgent,
  adminUpdateUsecase,
} from "@/lib/api";
import { navigate } from "@/lib/router";
import type { AgentcoreAgent, AgentKind, Usecase, UsecaseVersion, UsecaseVersionDetail } from "@/types";
import { NavBar } from "@/components/NavBar";

interface Props {
  usecaseId: string;
}

export function UsecaseDetailScreen({ usecaseId }: Props) {
  const [usecase, setUsecase] = useState<Usecase | null>(null);
  const [versions, setVersions] = useState<UsecaseVersion[] | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [versionDetail, setVersionDetail] = useState<UsecaseVersionDetail | null>(null);
  const [allAgents, setAllAgents] = useState<AgentcoreAgent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [linkAgentId, setLinkAgentId] = useState("");
  const [linkKind, setLinkKind] = useState<AgentKind>("subagent");

  const reloadVersions = (selectId?: string) => {
    adminListVersions(usecaseId)
      .then((res) => {
        setVersions(res.versions);
        const latest = res.versions[0]; // đã order_by version_number desc
        const nextSelected = selectId ?? selectedVersionId ?? latest?.id ?? null;
        setSelectedVersionId(nextSelected);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  };

  useEffect(() => {
    adminGetUsecase(usecaseId)
      .then(setUsecase)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    adminListAgents()
      .then((res) => setAllAgents(res.agents))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    reloadVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usecaseId]);

  useEffect(() => {
    if (!selectedVersionId) {
      setVersionDetail(null);
      return;
    }
    adminGetVersion(selectedVersionId)
      .then(setVersionDetail)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedVersionId]);

  const handleCreateVersion = async () => {
    setBusy(true);
    setError(null);
    try {
      const v = await adminCreateVersion(usecaseId);
      reloadVersions(v.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleLinkAgent = async () => {
    if (!selectedVersionId || !linkAgentId) return;
    setBusy(true);
    setError(null);
    try {
      await adminLinkAgent(selectedVersionId, { agent_id: linkAgentId, kind: linkKind });
      setLinkAgentId("");
      const detail = await adminGetVersion(selectedVersionId);
      setVersionDetail(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleUnlinkAgent = async (linkId: string) => {
    if (!selectedVersionId) return;
    setBusy(true);
    setError(null);
    try {
      await adminUnlinkAgent(selectedVersionId, linkId);
      const detail = await adminGetVersion(selectedVersionId);
      setVersionDetail(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleToggleUsecaseStatus = async () => {
    if (!usecase) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await adminUpdateUsecase(usecase.id, {
        status: usecase.status === "active" ? "disabled" : "active",
      });
      setUsecase(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handlePublish = async () => {
    if (!selectedVersionId) return;
    setBusy(true);
    setError(null);
    try {
      await adminPublishVersion(selectedVersionId);
      const detail = await adminGetVersion(selectedVersionId);
      setVersionDetail(detail);
      reloadVersions(selectedVersionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const agentKeyById = (id: string) => allAgents?.find((a) => a.id === id)?.agent_key ?? id;

  return (
    <>
      <NavBar active="usecases" />
      <header>
        <button className="link-back" onClick={() => navigate("/usecases")}>
          ← Usecases
        </button>
        <div className="row space-between" style={{ marginTop: 0, alignItems: "flex-start" }}>
          <div>
            <h1 style={{ display: "flex", alignItems: "center", gap: 10 }}>
              🧩 {usecase?.label ?? usecase?.usecase_key ?? "..."}
              {usecase && <span className={`status-badge status-${usecase.status}`}>{usecase.status}</span>}
            </h1>
            <p>
              {usecase && (
                <>
                  <code>{usecase.usecase_key}</code> — {usecase.description || "(không có mô tả)"}
                </>
              )}
            </p>
          </div>
          {usecase && (
            <button disabled={busy} onClick={() => void handleToggleUsecaseStatus()}>
              {usecase.status === "active" ? "Disable usecase" : "Enable usecase"}
            </button>
          )}
        </div>
      </header>

      <main className="stack">
        {error && (
          <p className="muted" style={{ color: "var(--danger)" }}>
            {error}
          </p>
        )}

        <section className="panel">
          <div className="row space-between">
            <h2 style={{ margin: 0 }}>Versions (append-only — sửa gì cũng tạo version mới)</h2>
            <button className="primary" disabled={busy} onClick={() => void handleCreateVersion()}>
              + Tạo version mới
            </button>
          </div>
          <ul className="version-list">
            {(versions ?? []).map((v) => (
              <li key={v.id}>
                <button
                  className={`version-pill ${v.id === selectedVersionId ? "active" : ""}`}
                  onClick={() => setSelectedVersionId(v.id)}
                >
                  v{v.version_number} {v.is_latest && <span className="tag">latest</span>}
                  <span className={`status-badge status-${v.status}`}>{v.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        {versionDetail && (
          <section className="panel">
            <div className="row space-between">
              <h2 style={{ margin: 0 }}>
                v{versionDetail.version_number} — agent đã gán
              </h2>
              {versionDetail.status === "draft" ? (
                <button className="ok" disabled={busy} onClick={() => void handlePublish()}>
                  Publish (draft → ready)
                </button>
              ) : (
                <span className="muted">Đã publish — không sửa agent gán được nữa, tạo version mới nếu cần đổi.</span>
              )}
            </div>

            <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>agent_name (dùng trong prompt Orchestrator)</th>
                  <th>kind</th>
                  <th>agent_key</th>
                  {versionDetail.status === "draft" && <th></th>}
                </tr>
              </thead>
              <tbody>
                {versionDetail.agents.length === 0 && (
                  <tr>
                    <td colSpan={versionDetail.status === "draft" ? 4 : 3} className="muted">
                      Chưa gán agent nào.
                    </td>
                  </tr>
                )}
                {versionDetail.agents.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <code>{a.agent_name}</code>
                    </td>
                    <td>{a.kind}</td>
                    <td>{agentKeyById(a.agent_id)}</td>
                    {versionDetail.status === "draft" && (
                      <td style={{ textAlign: "right" }}>
                        <button disabled={busy} onClick={() => void handleUnlinkAgent(a.id)}>
                          Gỡ
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            </div>

            {versionDetail.status === "draft" && (
              <div className="stack" style={{ marginTop: 14 }}>
                <label htmlFor="link-agent">Gán thêm agent (từ danh sách Deployed Agents)</label>
                <div className="row">
                  <select id="link-agent" value={linkAgentId} onChange={(e) => setLinkAgentId(e.target.value)}>
                    <option value="">— chọn agent —</option>
                    {(allAgents ?? []).map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.agent_key} ({a.label})
                      </option>
                    ))}
                  </select>
                  <select value={linkKind} onChange={(e) => setLinkKind(e.target.value as AgentKind)}>
                    <option value="subagent">subagent</option>
                    <option value="orchestrator">orchestrator</option>
                  </select>
                  <button className="primary" disabled={busy || !linkAgentId} onClick={() => void handleLinkAgent()}>
                    Gán
                  </button>
                </div>
                <p className="muted">
                  Đúng 1 agent phải là <code>orchestrator</code> trước khi publish được — <code>agent_name</code> tự
                  sinh <code>{`{usecase_key}__{agent_key}`}</code>.
                </p>
              </div>
            )}
          </section>
        )}
      </main>
    </>
  );
}
