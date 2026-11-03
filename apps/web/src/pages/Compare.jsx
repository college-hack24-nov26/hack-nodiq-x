import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import "./Compare.css";

/**
 * Compare — side-by-side view of two stored analyses (Advancement 5).
 *
 * Pick A and B from your history; the page renders both micrographs, the
 * measured metric deltas from the server's comparison engine, and the
 * engine's narrative summary. All numbers come from /api/compare.
 */

const METRIC_ROWS = [
  { key: "nodularity", label: "ISO Nodularity", get: (m) => m.a_pct != null ? `${fmt(m.a_pct)}%` : "—", getB: (m) => m.b_pct != null ? `${fmt(m.b_pct)}%` : "—", delta: (m) => ppDelta(m.change_pp) },
  { key: "jis_nodularity", label: "JIS Nodularity", get: (m) => m.a_pct != null ? `${fmt(m.a_pct)}%` : "—", getB: (m) => m.b_pct != null ? `${fmt(m.b_pct)}%` : "—", delta: (m) => ppDelta(m.change_pp) },
  { key: "irregular_fraction", label: "Irregular fraction", get: (m) => m.a_pct != null ? `${fmt(m.a_pct)}%` : "—", getB: (m) => m.b_pct != null ? `${fmt(m.b_pct)}%` : "—", delta: (m) => ppDelta(m.change_pp) },
  { key: "nodule_count", label: "Nodule count", get: (m) => m.a ?? "—", getB: (m) => m.b ?? "—", delta: (m) => m.change != null ? signed(m.change) : "—", sub: (m) => m.change_pct != null ? `${signed(m.change_pct)}%` : null },
  { key: "mean_roundness", label: "Mean roundness", get: (m) => m.a ?? "—", getB: (m) => m.b ?? "—", delta: (m) => ppDelta(m.change_pp) },
];

function fmt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(1).replace(/\.0$/, "");
}

function signed(v) {
  if (v == null) return "—";
  return v > 0 ? `+${v}` : `${v}`;
}

function ppDelta(v) {
  if (v == null) return "—";
  return `${signed(v)} pp`;
}

function DeltaCell({ value, sub }) {
  if (value === "—" || value == null) return <span className="cmp-delta neutral">—</span>;
  const isPos = typeof value === "string" && value.startsWith("+");
  const isNeg = typeof value === "string" && value.startsWith("−");
  const cls = isPos ? "up" : isNeg ? "down" : "neutral";
  return (
    <span className={`cmp-delta ${cls}`}>
      {value}
      {sub ? <em>{sub}</em> : null}
    </span>
  );
}

export default function Compare() {
  const navigate = useNavigate();
  const [analyses, setAnalyses] = useState([]);
  const [aId, setAId] = useState("");
  const [bId, setBId] = useState("");
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.analyses()
      .then((d) => {
        const rows = (d.analyses || []).filter((a) => a.id);
        setAnalyses(rows);
        if (rows.length >= 2) {
          setAId(rows[0].id);
          setBId(rows[1].id);
        } else if (rows.length === 1) {
          setAId(rows[0].id);
        }
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!aId || !bId || aId === bId) {
      setComparison(null);
      return;
    }
    setLoading(true);
    api.compare(aId, bId)
      .then(setComparison)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [aId, bId]);

  const distA = comparison?.size_distribution?.a || {};
  const distB = comparison?.size_distribution?.b || {};
  const sizeBins = useMemo(() => {
    const a = comparison?.size_distribution?.a || {};
    const b = comparison?.size_distribution?.b || {};
    return Array.from(new Set([...Object.keys(a), ...Object.keys(b)]));
  }, [comparison?.size_distribution]);

  const recA = analyses.find((r) => r.id === aId);
  const recB = analyses.find((r) => r.id === bId);

  const Selector = ({ value, onChange, label }) => (
    <label className="cmp-select">
      <span className="cmp-select-label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>choose an analysis…</option>
        {analyses.map((r) => (
          <option key={r.id} value={r.id}>
            {r.id} — {r.filename || r.title || "analysis"} ({fmt(r.iso_nodularity_pct)}%)
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="cmp-page">
      <header className="cmp-header">
        <div>
          <h1>Compare Analyses</h1>
          <p>Side-by-side comparison of two stored runs — measured values only, no invented context.</p>
        </div>
      </header>

      <div className="cmp-content">
        {error && (
          <div className="cmp-panel"><div className="cmp-body cmp-error">{error}</div></div>
        )}

        <div className="cmp-panel">
          <div className="cmp-panel-header"><h2>Samples</h2></div>
          <div className="cmp-body cmp-pickers">
            <Selector value={aId} onChange={setAId} label="SAMPLE A" />
            <span className="cmp-vs">vs</span>
            <Selector value={bId} onChange={setBId} label="SAMPLE B" />
          </div>
        </div>

        {!aId || !bId ? (
          <div className="cmp-panel"><div className="cmp-body cmp-empty">
            You need at least two stored analyses to compare. Run a new analysis first.
          </div></div>
        ) : aId === bId ? (
          <div className="cmp-panel"><div className="cmp-body cmp-empty">
            Pick two <em>different</em> analyses to compare.
          </div></div>
        ) : loading ? (
          <div className="cmp-panel"><div className="cmp-body cmp-empty">Comparing…</div></div>
        ) : comparison ? (
          <>
            <div className="cmp-grid">
              {[recA, recB].map((rec, i) => (
                <div className="cmp-panel" key={rec?.id || i}>
                  <div className="cmp-panel-header">
                    <h2>{i === 0 ? "A" : "B"} — {rec?.id}</h2>
                    <span className="cmp-sub">{rec?.filename}</span>
                  </div>
                  <div className="cmp-body cmp-image-body">
                    <img
                      className="cmp-image"
                      src={`/api/analyses/${rec.id}/image`}
                      alt={`${rec.id} micrograph`}
                      onClick={() => navigate(`/analyses`)}
                    />
                    <div className="cmp-image-stats">
                      <span><strong>{fmt(rec?.iso_nodularity_pct)}%</strong> ISO</span>
                      <span><strong>{fmt(rec?.jis_nodularity_pct)}%</strong> JIS</span>
                      <span><strong>{rec?.nodule_count ?? "—"}</strong> nodules</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="cmp-panel">
              <div className="cmp-panel-header"><h2>Measured Deltas</h2></div>
              <div className="cmp-body table-container">
                <table className="cmp-table">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>{aId}</th>
                      <th>{bId}</th>
                      <th>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {METRIC_ROWS.map(({ key, label, get, getB, delta, sub }) => {
                      const m = comparison[key];
                      if (!m) return null;
                      return (
                        <tr key={key}>
                          <td className="cmp-metric-name">{label}</td>
                          <td>{get(m)}</td>
                          <td>{getB(m)}</td>
                          <td><DeltaCell value={delta(m)} sub={sub?.(m)} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="cmp-grid">
              <div className="cmp-panel">
                <div className="cmp-panel-header"><h2>Size Distribution</h2></div>
                <div className="cmp-body">
                  <table className="cmp-table">
                    <thead>
                      <tr><th>Area bin (px²)</th><th>A</th><th>B</th></tr>
                    </thead>
                    <tbody>
                      {sizeBins.map((bin) => (
                        <tr key={bin}>
                          <td className="cmp-metric-name">{bin}</td>
                          <td>{distA[bin] ?? 0}</td>
                          <td>{distB[bin] ?? 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="cmp-panel">
                <div className="cmp-panel-header"><h2>Quality & Verification</h2></div>
                <div className="cmp-body">
                  <table className="cmp-table">
                    <tbody>
                      <tr>
                        <td className="cmp-metric-name">Image quality score</td>
                        <td>{fmt(comparison.quality?.a)}</td>
                        <td>{fmt(comparison.quality?.b)}</td>
                      </tr>
                      <tr>
                        <td className="cmp-metric-name">Self-check accuracy</td>
                        <td>{fmt(comparison.self_check?.a)}</td>
                        <td>{fmt(comparison.self_check?.b)}</td>
                      </tr>
                      <tr>
                        <td className="cmp-metric-name">Border-touching nodules</td>
                        <td>{comparison.border_touching?.a ?? "—"}</td>
                        <td>{comparison.border_touching?.b ?? "—"}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {comparison.summary && (
              <div className="cmp-panel">
                <div className="cmp-panel-header"><h2>Summary</h2></div>
                <div className="cmp-body cmp-summary">{comparison.summary}</div>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
