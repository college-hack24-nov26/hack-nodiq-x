import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Lots.css";

/**
 * Lots — heat/lot traceability (Advancement).
 *
 * Lists every tagged lot with acceptance rates; click a lot for its full
 * summary and per-sample drill-down. All data from /api/lots (SQLite store).
 */

async function lotsFetch(path) {
  const resp = await fetch(path, { credentials: "same-origin" });
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(body?.error || `Request failed (${resp.status})`);
  return body;
}

function Lots() {
  const navigate = useNavigate();
  const [lots, setLots] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    lotsFetch("/api/lots")
      .then((d) => setLots(d.lots || []))
      .catch((e) => setError(e.message));
  }, []);

  const openLot = async (lotId) => {
    try {
      const detail = await lotsFetch(
        `/api/lots/${encodeURIComponent(lotId)}`);
      setSelected(detail);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="lots-page">
      <header className="lots-header">
        <div>
          <h1>Lots</h1>
          <p>Heat/lot traceability — per-lot acceptance over your tagged analyses.</p>
        </div>
      </header>

      <div className="lots-content">
        {error && <div className="lots-panel"><div className="lots-body lots-error">{error}</div></div>}

        {!lots && !error && (
          <div className="lots-panel"><div className="lots-body lots-empty">Loading lots…</div></div>
        )}

        {lots && lots.length === 0 && (
          <div className="lots-panel"><div className="lots-body lots-empty">
            No tagged lots yet. Open an analysis and tag it with a heat/lot id to
            start traceability.
          </div></div>
        )}

        {lots && lots.length > 0 && (
          <div className="lots-grid">
            {lots.map((lot) => (
              <button
                key={lot.lot_id}
                className={"lots-card" + (selected?.lot_id === lot.lot_id ? " active" : "")}
                onClick={() => openLot(lot.lot_id)}
              >
                <div className="lots-card-top">
                  <span className="lots-id">{lot.lot_id}</span>
                  <span className={"lots-rate " + (lot.pass_rate_pct >= 80 ? "good" : "bad")}>
                    {lot.pass_rate_pct}%
                  </span>
                </div>
                <div className="lots-card-stats">
                  <span><strong>{lot.samples}</strong> samples</span>
                  <span><strong>{lot.pass_count}</strong> pass</span>
                  <span><strong>{lot.fail_count}</strong> fail</span>
                </div>
                <div className="lots-card-stats">
                  <span>mean <strong>{lot.mean_nodularity_pct}%</strong></span>
                  <span>std <strong>{lot.std_nodularity_pct}</strong></span>
                </div>
              </button>
            ))}
          </div>
        )}

        {selected && (
          <div className="lots-panel">
            <div className="lots-panel-header">
              <h2>Lot {selected.lot_id}</h2>
              <span className="lots-sub">
                threshold ≥ {selected.accept_threshold_pct}% ISO
              </span>
            </div>
            <div className="lots-body">
              <div className="lots-detail-stats">
                <div><span>Samples</span><strong>{selected.samples}</strong></div>
                <div><span>Pass rate</span><strong>{selected.pass_rate_pct}%</strong></div>
                <div><span>Mean</span><strong>{selected.mean_nodularity_pct}%</strong></div>
                <div><span>Std</span><strong>{selected.std_nodularity_pct}</strong></div>
                <div><span>Min</span><strong>{selected.min_nodularity_pct}%</strong></div>
                <div><span>Max</span><strong>{selected.max_nodularity_pct}%</strong></div>
              </div>

              <h3 className="lots-section-title">Samples in this lot</h3>
              <table className="lots-table">
                <thead>
                  <tr><th>Analysis</th><th>ISO nodularity</th><th>Verdict</th></tr>
                </thead>
                <tbody>
                  {selected.values_chronological.map((v, i) => (
                    <tr key={i}>
                      <td className="lots-sample-id">{selected.sample_ids[i]}</td>
                      <td>{v}%</td>
                      <td>
                        <span className={"lots-verdict " + (v >= selected.accept_threshold_pct ? "pass" : "fail")}>
                          {v >= selected.accept_threshold_pct ? "PASS" : "FAIL"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <button className="lots-open-btn" onClick={() => navigate("/analyses")}>
                Open My Analyses →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Lots;
