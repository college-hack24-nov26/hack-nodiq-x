import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import "./Sessions.css";

/**
 * Sessions — login-scoped work sessions.
 *
 * Every login (or signup) starts a fresh session; analyses created during
 * that login are tagged to it. Past sessions stay browsable here forever.
 */

function fmtWhen(iso) {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function fmtAvg(v) {
  return v == null ? "—" : `${v.toFixed(1)}%`;
}

function Sessions() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.sessions()
      .then((d) => setRows(d.sessions || []))
      .catch((e) => setError(e.message));
  }, []);

  const open = async (id) => {
    try {
      const detail = await api.session(id);
      setSelected(detail);
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this session? Its analyses stay in History (untagged).")) return;
    try {
      await api.deleteSession(id);
      setRows((r) => (r || []).filter((s) => s.id !== id));
      if (selected?.session?.id === id) setSelected(null);
    } catch (e) {
      setError(e.message);
    }
  };

  const inSession = selected ? selected.analyses || [] : [];

  return (
    <div className="sess-page">
      <header className="sess-header">
        <div>
          <h1>Sessions</h1>
          <p>Every login starts a new work session — analyses are grouped automatically, previous ones stay here.</p>
        </div>
      </header>

      <div className="sess-content">
        {error && <div className="sess-panel"><div className="sess-body sess-error">{error}</div></div>}

        {!rows && !error && (
          <div className="sess-panel"><div className="sess-body sess-empty">Loading sessions…</div></div>
        )}

        {rows && rows.length === 0 && (
          <div className="sess-panel"><div className="sess-body sess-empty">
            No sessions yet — they start automatically the moment you sign in.
          </div></div>
        )}

        {rows && rows.length > 0 && (
          <div className="sess-grid">
            {rows.map((s) => (
              <button key={s.id} className={`sess-card ${selected?.session?.id === s.id ? "active" : ""}`}
                      onClick={() => open(s.id)}>
                <div className="sess-card-top">
                  <span className="sess-id">{s.id}</span>
                  <span className={`sess-badge ${s.ended_at ? "ended" : "live"}`}>
                    {s.ended_at ? "ended" : "live"}
                  </span>
                </div>
                {s.label && <div className="sess-label">{s.label}</div>}
                <div className="sess-meta">
                  <span>{fmtWhen(s.started_at)}</span>
                  <span>{s.analysis_count} {s.analysis_count === 1 ? "analysis" : "analyses"}</span>
                  <span>avg {fmtAvg(s.avg_iso_pct)}</span>
                </div>
                <div className="sess-card-actions">
                  <span className="sess-open" onClick={(e) => { e.stopPropagation(); open(s.id); }}>open</span>
                  <span className="sess-del" onClick={(e) => { e.stopPropagation(); remove(s.id); }}>delete</span>
                </div>
              </button>
            ))}
          </div>
        )}

        {selected && (
          <div className="sess-panel">
            <div className="sess-body">
              <div className="sess-detail-head">
                <div>
                  <h2>{selected.session.label || selected.session.id}</h2>
                  <p>
                    {fmtWhen(selected.session.started_at)}
                    {" → "}
                    {selected.session.ended_at ? fmtWhen(selected.session.ended_at) : "ongoing"}
                  </p>
                </div>
                <button className="sess-close" onClick={() => setSelected(null)}>close</button>
              </div>

              {inSession.length === 0 ? (
                <p className="sess-empty">No analyses were created in this session.</p>
              ) : (
                <table className="sess-table">
                  <thead>
                    <tr>
                      <th>Analysis</th><th>When</th><th>ISO nodularity</th><th>JIS nodularity</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {inSession.map((a) => (
                      <tr key={a.id}>
                        <td className="mono">{a.id}</td>
                        <td>{fmtWhen(a.created_at)}</td>
                        <td>{a.iso_nodularity_pct != null ? `${a.iso_nodularity_pct.toFixed(1)}%` : "—"}</td>
                        <td>{a.jis_nodularity_pct != null ? `${a.jis_nodularity_pct.toFixed(1)}%` : "—"}</td>
                        <td>
                          <span className="sess-open" onClick={() => navigate(`/analyses/${a.id}`)}>view</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Sessions;
