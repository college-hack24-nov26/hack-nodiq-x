import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import "./Dashboard.css";

/**
 * Anomalies — the real anomaly registry from /api/anomalies (deterministic
 * statistical engine; every anomaly carries explicit reasons). Reuses the
 * Dashboard design system. No mock data.
 */

const SEVERITIES = ["ALL", "HIGH", "MEDIUM", "LOW"];

function Anomalies() {
  const navigate = useNavigate();
  const [all, setAll] = useState([]);
  const [filter, setFilter] = useState("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.anomalies()
      .then((data) => {
        const list = Array.isArray(data) ? data : (data.anomalies || []);
        setAll(list);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const flagged = useMemo(() => all.filter((a) => a.is_anomaly), [all]);
  const shown = useMemo(
    () => (filter === "ALL" ? flagged : flagged.filter((a) => a.severity === filter)),
    [flagged, filter]
  );

  const bySeverity = useMemo(() => {
    const m = { HIGH: 0, MEDIUM: 0, LOW: 0 };
    for (const a of flagged) m[a.severity] = (m[a.severity] || 0) + 1;
    return m;
  }, [flagged]);

  const openAnalysis = () => navigate("/analyses");

  return (
    <main className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h1>Anomalies</h1>
          <p>
            Deterministic screening over {all.length} analyses. Every flag carries its
            measured reasons — statistical evidence, not black-box scores.
          </p>
        </div>
        <button className="new-analysis-btn" onClick={() => navigate("/new-analysis")}>
          <span className="material-symbols-outlined">add</span>
          New Analysis
        </button>
      </header>

      {error && (
        <div className="dashboard-panel" style={{ padding: 16, color: "var(--color-error)" }}>
          Could not load anomalies: {error}
        </div>
      )}

      {loading && !error && (
        <div className="dashboard-panel" style={{ padding: 16 }}>Loading anomaly scan…</div>
      )}

      {!loading && !error && (
        <div className="dashboard-content">
          {/* Summary */}
          <section className="metrics-grid">
            <div className="metric-card">
              <span className="metric-label">SCREENED</span>
              <span className="metric-value">{all.length}</span>
            </div>
            <div className="metric-card anomaly-metric">
              <span className="metric-label">FLAGGED</span>
              <span className="metric-value error-text">{flagged.length}</span>
            </div>
            <div className="metric-card">
              <div className="metric-label-row">
                <span className="metric-label">HIGH</span>
              </div>
              <span className="metric-value error-text">{bySeverity.HIGH || 0}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">MEDIUM</span>
              <span className="metric-value">{bySeverity.MEDIUM || 0}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">CLEAN</span>
              <span className="metric-value">{all.length - flagged.length}</span>
            </div>
          </section>

          {/* Filter row */}
          <div className="dashboard-panel">
            <div className="panel-header">
              <h2>Anomaly Registry</h2>
              <div style={{ display: "flex", gap: 8 }}>
                {SEVERITIES.map((s) => (
                  <button
                    key={s}
                    className={"range-btn" + (filter === s ? " active" : "")}
                    onClick={() => setFilter(s)}
                  >
                    {s}
                    {s !== "ALL" && ` (${bySeverity[s] || 0})`}
                  </button>
                ))}
              </div>
            </div>

            {shown.length === 0 ? (
              <p className="secondary-text" style={{ padding: 16 }}>
                {filter === "ALL"
                  ? "No anomalies flagged — every stored analysis is within thresholds."
                  : `No ${filter} anomalies.`}
              </p>
            ) : (
              <div className="anomaly-list" style={{ padding: 16 }}>
                {shown.map((a) => (
                  <div
                    className="anomaly-card"
                    key={a.analysis_id}
                    onClick={() => openAnalysis(a.analysis_id)}
                    title="Open in My Analyses"
                  >
                    <div className="anomaly-card-top">
                      <span className="sample-id">{a.analysis_id}</span>
                      <span className={`severity ${(a.severity || "").toLowerCase()}`}>
                        {a.severity}
                      </span>
                    </div>

                    <p>
                      Score {a.anomaly_score}/100 — {a.signals?.join(", ")}
                    </p>

                    <ul style={{ margin: "4px 0 4px", paddingLeft: 18 }}>
                      {(a.reasons || []).map((r, i) => (
                        <li key={i} className="secondary-text" style={{ fontSize: 12 }}>
                          {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* How scoring works — honest explainer */}
          <div className="dashboard-panel">
            <div className="panel-header"><h2>How anomalies are detected</h2></div>
            <div style={{ padding: 16 }}>
              <p className="secondary-text" style={{ fontSize: 13, lineHeight: "22px" }}>
                A deterministic rule engine screens every stored analysis — no LLM involved.
                Signals include: low nodularity versus the 80% acceptance threshold, deviation
                from the batch mean (in standard deviations), unusual particle-size
                distribution, unusual roundness, high border-touching fraction, and poor image
                quality. The anomaly <em>score</em> summarizes how many signals fired and how
                strongly; the <em>reasons</em> are the measured evidence. Statistical deviation
                is not a metallurgical diagnosis — verify against process records.
              </p>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

export default Anomalies;
