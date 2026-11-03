import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import "./Dashboard.css";
import "./Settings.css";

/**
 * Settings — platform settings (engine, AI providers, validation lab).
 * Distinct from Profile: this page is about the NODIQ-X SYSTEM, not the user
 * account. Every value is read live from the server; nothing is invented.
 */

function Settings() {
  const navigate = useNavigate();
  const [health, setHealth] = useState(null);
  const [ai, setAi] = useState(null);
  const [validation, setValidation] = useState(null);
  const [running, setRunning] = useState("");
  const [runResult, setRunResult] = useState(null);
  const [runError, setRunError] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.aiStatus().then(setAi).catch(() => {});
    api.validationSummary().then(setValidation).catch(() => {});
  }, []);

  const runValidation = async (kind) => {
    setRunning(kind);
    setRunResult(null);
    setRunError("");
    try {
      const r = await api.runValidation(kind, kind === "synthetic" ? 2 : 3);
      setRunResult({ kind, ...r });
    } catch (e) {
      setRunError(e.message);
    } finally {
      setRunning("");
    }
  };

  const chain = ai?.chain || {};
  const chainOrder = ["local", "gemini", "openai_compatible", "fallback"];

  const platformRows = [
    { label: "Status", value: health ? health.status : "unreachable", ok: health?.status === "ok" },
    { label: "Platform", value: health?.platform || "…" },
    { label: "CV Engine", value: health?.engine || "…" },
    { label: "Dataset images", value: health?.dataset_images ?? "…" },
    { label: "Offline mode", value: health ? (health.offline_mode ? "ON" : "OFF") : "…", ok: health ? !health.offline_mode : undefined },
  ];

  const defaultsRows = [
    { label: "ISO acceptance threshold", value: "80% (common criterion — verify against your specification)" },
    { label: "Nodule roundness cutoff", value: "roundness ≥ 0.6 → ISO class V/VI" },
    { label: "Self-check", value: "runs on every analysis (independent reference segmentation)", ok: true },
    { label: "Scale calibration", value: "manual pixels-per-µm via API; µm values never invented" },
  ];

  return (
    <main className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h1>Settings</h1>
          <p>Platform, engine and AI configuration — read live from the running server.</p>
        </div>
        <button className="new-analysis-btn" onClick={() => navigate("/profile")}>
          <span className="material-symbols-outlined">person</span>
          Account Settings
        </button>
      </header>

      <div className="dashboard-content">
        <section className="settings-grid">
          {/* Platform & Engine — read-only system status (server-configured) */}
          <div className="dashboard-panel settings-panel">
            <div className="panel-header">
              <h2>Platform & Engine</h2>
              <span className="settings-readonly-tag mono">READ-ONLY · SERVER CONFIG</span>
            </div>
            <table className="settings-table">
              <tbody>
                {platformRows.map((r) => (
                  <tr key={r.label}>
                    <td className="settings-label">{r.label}</td>
                    <td className={"settings-value" + (r.ok === true ? " ok" : r.ok === false ? " bad" : "")}>
                      {r.value}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* AI Providers — read-only status; configuration lives in server .env */}
          <div className="dashboard-panel settings-panel">
            <div className="panel-header">
              <h2>AI Providers (Copilot)</h2>
              <span className="settings-readonly-tag mono">READ-ONLY · SERVER CONFIG</span>
            </div>
            <table className="settings-table">
              <tbody>
                <tr>
                  <td className="settings-label">Active provider</td>
                  <td className={"settings-value " + (ai?.active_provider || ai?.provider ? "ok" : "bad")}>
                    {ai?.active_provider || ai?.provider || "none"}
                  </td>
                </tr>
                {chainOrder.filter((k) => k in chain).map((k) => (
                  <tr key={k}>
                    <td className="settings-label">{k.replace("_", " ")}</td>
                    <td className={"settings-value " + (chain[k]?.available ? "ok" : "")}>
                      {chain[k]?.available ? "available" : chain[k]?.note || "unavailable"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="settings-note">
              Configure via <code>AI_PROVIDER</code>, <code>AI_MODEL</code>,{" "}
              <code>AI_API_KEY</code>, <code>AI_BASE_URL</code> in a <code>.env</code> file —
              keys are never stored in the app. Without any key the deterministic NODIQ-X
              fallback answers from measured data.
            </p>
          </div>
        </section>

        {/* Validation Lab */}
        <div className="dashboard-panel settings-panel">
          <div className="panel-header">
            <h2>Validation Lab</h2>
            <span className="settings-hint">metrics never merged across sources</span>
          </div>

          {validation?.internal?.available && (
            <table className="settings-table">
              <tbody>
                <tr>
                  <td className="settings-label">Internal (1000-image batch)</td>
                  <td className="settings-value ok">
                    {validation.internal.count_accuracy_pct}% count accuracy · F1 {validation.internal.f1_pct}% · {validation.internal.image_count} images
                  </td>
                </tr>
                <tr>
                  <td className="settings-label">Ground truth</td>
                  <td className="settings-value">{validation.internal.ground_truth}</td>
                </tr>
                <tr>
                  <td className="settings-label">Artifacts</td>
                  <td className="settings-value mono">{validation.internal.artifacts}</td>
                </tr>
              </tbody>
            </table>
          )}

          <div className="settings-actions">
            {[
              { kind: "blind", label: "Run Blind Test" },
              { kind: "synthetic", label: "Run Synthetic Test" },
              { kind: "internal", label: "Re-check Internal" },
            ].map(({ kind, label }) => (
              <button
                key={kind}
                className="settings-action-btn"
                disabled={!!running}
                onClick={() => runValidation(kind)}
              >
                {running === kind ? "Running…" : label}
              </button>
            ))}
          </div>

          {runError && (
            <p className="settings-run-error">{runError}</p>
          )}

          {runResult && (
            <div className="settings-run-result">
              <div className="settings-run-head">
                <span className={"settings-dot" + ((runResult.count_accuracy_pct ?? 0) >= 99 ? " ok" : " bad")} />
                <strong style={{ textTransform: "capitalize" }}>{runResult.kind}</strong>
                <span>
                  count accuracy {runResult.count_accuracy_pct ?? "—"}% · precision{" "}
                  {runResult.precision_pct ?? "—"}% · recall {runResult.recall_pct ?? "—"}%
                </span>
              </div>
              {(runResult.per_image || []).slice(0, 5).map((p) => (
                <div key={p.file} className="settings-run-row">
                  <span>{p.file}</span>
                  <span>
                    detected {p.count ?? p.detected_count} · reference {p.reference_count ?? p.expected_count} · {p.accuracy_pct}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Analysis Defaults */}
        <div className="dashboard-panel settings-panel">
          <div className="panel-header"><h2>Analysis Defaults</h2></div>
          <table className="settings-table">
            <tbody>
              {defaultsRows.map((r) => (
                <tr key={r.label}>
                  <td className="settings-label">{r.label}</td>
                  <td className={"settings-value" + (r.ok ? " ok" : "")}>{r.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}

export default Settings;
