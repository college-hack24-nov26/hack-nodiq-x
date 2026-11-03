import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import "./Analytics.css";

/**
 * Analytics — batch statistics and statistical process control over the REAL
 * analysis history (server: /api/batch/stats + /api/spc). Pure SVG charts, no
 * chart libraries, no mock data: every number comes from the server.
 */

const METRICS = [
  { key: "nodularity", label: "ISO Nodularity %" },
  { key: "jis_nodularity", label: "JIS Nodularity %" },
  { key: "nodule_count", label: "Nodule Count" },
  { key: "self_check_accuracy", label: "Self-Check %" },
];  
function dist(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toFixed(1).replace(/\.0$/, "");
}

function Analytics() {
  const navigate = useNavigate();
  const [batch, setBatch] = useState(null);
  const [metric, setMetric] = useState("nodularity");
  const [spc, setSpc] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.batchStats().then(setBatch).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setSpc(null);
    api.spc(metric)
      .then(setSpc)
      .catch(() => {});
  }, [metric]);

  const nod = batch?.nodularity;
  const count = batch?.nodule_count;
  const sc = batch?.self_check_accuracy;
  const hist = batch?.histogram_iso;

  // SPC sparkline geometry (pure SVG, no library)
  const chart = useMemo(() => {
    if (!spc?.sufficient_data || !Array.isArray(spc.values) || spc.values.length < 2) {
      return null;
    }
    const values = spc.values;
    const w = 720;
    const h = 200;
    const pad = 10;
    const lo = Math.min(...values, spc.lcl ?? Infinity);
    const hi = Math.max(...values, spc.ucl ?? -Infinity);
    const span = hi - lo || 1;
    const x = (i) => pad + (i / (values.length - 1)) * (w - 2 * pad);
    const y = (v) => pad + (1 - (v - lo) / span) * (h - 2 * pad);
    const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const outlierIdx = new Set((spc.outliers || []).map((o) => o.index));
    return { w, h, pad, path, x, y, lo, hi, values, outlierIdx, ucl: spc.ucl, lcl: spc.lcl, mean: spc.mean, ids: spc.ids || [] };
  }, [spc]);

  const outlierList = useMemo(() => {
    if (!spc?.sufficient_data || !Array.isArray(spc.values)) return [];
    return (spc.outliers || []).map((o) => ({
      ...o,
      label: spc.values[o.index] != null ? `point #${o.index + 1}` : `index ${o.index}`,
    }));
  }, [spc]);

  const totalSamples = hist ? hist.counts.reduce((a, b) => a + b, 0) : 0;

  return (
    <main className="analytics-page">
      <header className="analytics-header">
        <div className="analytics-header-text">
          <h1>Analytics</h1>
          <p>
            Batch statistics and SPC from your {batch ? batch.samples : "…"} stored analyses
            (ISO acceptance ≥ {batch ? batch.iso_accept_threshold : "—"}%).
          </p>
        </div>
        <button className="analytics-new-btn" onClick={() => navigate("/new-analysis")}>
          + New Analysis
        </button>
      </header>

      {error && (
        <div className="analytics-content">
          <div className="analytics-panel">
            <div className="analytics-panel-body analytics-error">
              Could not load analytics: {error}
            </div>
          </div>
        </div>
      )}

      {!batch && !error && (
        <div className="analytics-content">
          <div className="analytics-panel">
            <div className="analytics-panel-body analytics-empty">Loading batch statistics…</div>
          </div>
        </div>
      )}

      {batch && (
        <div className="analytics-content">
          {/* Summary metrics */}
          <section className="analytics-metrics">
            <div className="metric-card">
              <span className="metric-label">SAMPLES</span>
              <span className="metric-value">{batch.samples}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">PASS RATE</span>
              <span className="metric-value">{dist(batch.pass_rate_pct)}%</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">FAIL RATE</span>
              <span className="metric-value error-text">{dist(batch.fail_rate_pct)}%</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">MEAN NODULARITY</span>
              <span className="metric-value">{nod ? `${dist(nod.mean)}%` : "—"}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">STD DEV</span>
              <span className="metric-value">{nod ? dist(nod.std) : "—"}</span>
            </div>
          </section>

          {/* Nodularity distribution */}
          <section className="analytics-panel">
              <div className="analytics-panel-header">
                <h2>ISO Nodularity Distribution</h2>
                <span className="analytics-panel-sub">n = {totalSamples}</span>
              </div>
              <div className="analytics-panel-body">
                {hist ? (
                  <div className="analytics-hist">
                    <div className="analytics-hist-bars">
                      {hist.counts.map((c, i) => {
                        const max = Math.max(...hist.counts, 1);
                        const binStart = hist.bins[i];
                        const last = i === hist.counts.length - 1;
                        return (
                          <div className="analytics-hist-col" key={i}>
                            {c > 0 && <span className="analytics-hist-count">{c}</span>}
                            <div
                              className={
                                "analytics-hist-bar " +
                                (c === 0 ? "empty " : "") +
                                (binStart >= (batch.iso_accept_threshold || 80) ? "pass" : "fail")
                              }
                              style={{ height: `${Math.max(3, (c / max) * 100)}%` }}
                              title={`${c} samples in [${binStart}, ${hist.bins[i + 1] ?? "?"}${last ? "+" : ")"}`}
                            />
                          </div>
                        );
                      })}
                    </div>
                    <div className="analytics-hist-axis">
                      {hist.bins.slice(0, -1).map((b, i) => (
                        <span className="analytics-hist-tick" key={i}>
                          {b}
                          {i === hist.bins.length - 2 ? "+" : ""}
                        </span>
                      ))}
                    </div>
                    <div className="analytics-legend">
                      <span>
                        <i className="fail" /> below {batch.iso_accept_threshold}%
                      </span>
                      <span>
                        <i className="pass" /> meets ISO ≥ {batch.iso_accept_threshold}%
                      </span>
                    </div>
                  </div>
                ) : (
                  <p className="analytics-empty">No data yet.</p>
                )}
              </div>
            </section>

          {/* Descriptive statistics table */}
          <section className="analytics-panel">
            <div className="analytics-panel-header">
              <h2>Descriptive Statistics</h2>
            </div>
              <div className="analytics-panel-body table-container" style={{ padding: 0 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>Mean</th>
                      <th>Median</th>
                      <th>Min</th>
                      <th>Max</th>
                      <th>Std</th>
                      <th>CV%</th>
                      <th>P25</th>
                      <th>P75</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      { name: "ISO Nodularity %", d: nod },
                      { name: "Nodule Count", d: count },
                      { name: "Self-Check Accuracy %", d: sc },
                    ].map(({ name, d }) => (
                      <tr key={name}>
                        <td className="sample-id">{name}</td>
                        <td>{d ? dist(d.mean) : "—"}</td>
                        <td>{d ? dist(d.median) : "—"}</td>
                        <td>{d ? dist(d.min) : "—"}</td>
                        <td>{d ? dist(d.max) : "—"}</td>
                        <td>{d ? dist(d.std) : "—"}</td>
                        <td>{d ? dist(d.cv_pct) : "—"}</td>
                        <td>{d ? dist(d.p25) : "—"}</td>
                        <td>{d ? dist(d.p75) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
          </section>

          {/* SPC */}
          <section className="analytics-panel">
            <div className="analytics-panel-header">
              <h2>
                Statistical Process Control
                {spc?.sufficient_data ? ` — ${spc.metric}${spc.trend ? ` · trend: ${spc.trend}` : ""}` : ""}
              </h2>
            </div>

            <div className="analytics-toolbar">
              <span className="analytics-toolbar-label">Metric</span>
              {METRICS.map((m) => (
                <button
                  key={m.key}
                  className={"analytics-chip" + (metric === m.key ? " active" : "")}
                  onClick={() => setMetric(m.key)}
                >
                  {m.label}
                </button>
              ))}
            </div>

            <div className="analytics-panel-body">
              {spc && !spc.sufficient_data && (
                <p className="analytics-empty">
                  Not enough data for control limits yet (need ≥ 8 stored analyses; have {spc.n ?? 0}).
                  Limits are never invented from insufficient data.
                </p>
              )}

              {chart && (
                <>
                  <div className="analytics-chart-wrap">
                    <svg viewBox={`0 0 ${chart.w} ${chart.h}`} role="img" aria-label="SPC control chart">
                      {/* control limits */}
                      <line x1={chart.pad} x2={chart.w - chart.pad} y1={chart.y(chart.ucl)} y2={chart.y(chart.ucl)} stroke="var(--color-error)" strokeDasharray="5 4" strokeWidth="1" />
                      <line x1={chart.pad} x2={chart.w - chart.pad} y1={chart.y(chart.mean)} y2={chart.y(chart.mean)} stroke="var(--color-text-secondary)" strokeWidth="1" />
                      <line x1={chart.pad} x2={chart.w - chart.pad} y1={chart.y(chart.lcl)} y2={chart.y(chart.lcl)} stroke="var(--color-error)" strokeDasharray="5 4" strokeWidth="1" />
                      <text x={chart.w - 12} y={chart.y(chart.ucl) - 5} textAnchor="end" fontSize="11" fill="var(--color-error)" fontFamily="inherit">UCL {dist(chart.ucl)}</text>
                      <text x={chart.w - 12} y={chart.y(chart.mean) - 5} textAnchor="end" fontSize="11" fill="var(--color-text-secondary)" fontFamily="inherit">x̄ {dist(chart.mean)}</text>
                      <text x={chart.w - 12} y={chart.y(chart.lcl) - 5} textAnchor="end" fontSize="11" fill="var(--color-error)" fontFamily="inherit">LCL {dist(chart.lcl)}</text>
                      {/* run chart */}
                      <path d={chart.path} fill="none" stroke="var(--color-primary)" strokeWidth="2" />
                      {chart.values.map((v, i) => (
                        <circle
                          key={i}
                          cx={chart.x(i)}
                          cy={chart.y(v)}
                          r={chart.outlierIdx.has(i) ? 4 : 2.2}
                          fill={chart.outlierIdx.has(i) ? "var(--color-error)" : "var(--color-primary)"}
                          style={{ cursor: chart.ids[i] ? "pointer" : "default" }}
                          onClick={() => {
                            if (chart.ids[i]) navigate("/analyses");
                          }}
                        >
                          <title>{`${chart.ids[i] || `#${i + 1}`}: ${dist(v)}${chart.outlierIdx.has(i) ? " (out-of-control signal)" : ""}`}</title>
                        </circle>
                      ))}
                    </svg>
                  </div>

                  {outlierList.length > 0 ? (
                    <ul className="analytics-notes">
                      {outlierList.map((o, i) => (
                        <li key={i}>
                          <span className="warning-text">Out-of-control:</span> {o.label} — {o.reason}
                          {o.z != null ? ` (z = ${dist(o.z)})` : ""}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="analytics-empty" style={{ marginTop: 12, fontSize: 12.5 }}>
                      No out-of-control signals — process is within ±3σ limits.
                    </p>
                  )}
                </>
              )}

              {!spc && <p className="analytics-empty">Loading SPC…</p>}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default Analytics;
