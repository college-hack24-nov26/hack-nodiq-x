import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";

/**
 * Multi-Field Session — additive panel for the Batch Analysis page.
 *
 * Talks to the backend's ISO 945-4 sampling endpoints (create / attach /
 * view / refresh). The BACKEND is the single source of truth: every value
 * shown here comes from `GET /api/multifield/<sid>` responses. This
 * component never averages field percentages and never recomputes
 * aggregates in JavaScript.
 *
 * Targets come from the methodology (5 fields, 500 particles) and mirror
 * what the backend reports; they are informational only — no percentage
 * "compliance score" is derived from them.
 */

const FIELD_TARGET = 5;
const PARTICLE_TARGET = 500;

const SAMPLING_LABEL = {
  no_fields: "No fields attached",
  below_field_target: "Below field target (<5)",
  below_particle_target: "Below particle target (<500)",
  meets_field_and_particle_target: "Field & particle targets met",
};

const pct = (v) => (v == null ? "—" : `${v}%`);

function sizeFilterSummary(agg) {
  const cal = agg?.calibration || {};
  if (!agg || agg.field_count === 0) return "—";
  if (cal.complete) return "Applied";
  if (cal.fields_calibrated === 0) return "Unavailable";
  return "Mixed";
}

export default function MultiFieldSessionPanel() {
  const navigate = useNavigate();
  const [session, setSession] = useState(null); // aggregate from the backend
  const [busy, setBusy] = useState("");        // "" | "create" | "add" | "refresh"
  const [error, setError] = useState("");
  const [pick, setPick] = useState("");        // selected analysis_id to attach
  const [history, setHistory] = useState([]);  // recent completed analyses

  const loadHistoryRef = useRef(null);
  const loadHistory = useCallback(async () => {
    // Existing analyses endpoint — completed runs become attachable fields.
    try {
      const d = await api.analyses();
      setHistory((d.analyses || []).filter((a) => a.status === "completed"));
    } catch {
      setHistory([]);
    }
  }, []);
  loadHistoryRef.current = loadHistory;

  const refresh = useCallback(async (sid, silent = false) => {
    if (!sid) return;
    if (!silent) setBusy("refresh");
    try {
      const agg = await api.multifieldGet(sid);
      setSession(agg);
      setError("");
      // Also reload the analyses list so newly completed runs become
      // attachable without a page reload.
      loadHistoryRef.current?.();
    } catch (e) {
      if (!silent) setError(e.message);
    } finally {
      if (!silent) setBusy("");
    }
  }, []);

  // On mount: resume the most recent session if one exists (read-only GETs).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await api.multifieldList();
        const newest = (d.sessions || [])[0];
        if (alive && newest?.id) {
          const agg = await api.multifieldGet(newest.id);
          if (alive) setSession(agg);
          loadHistory();
        }
      } catch {
        /* no session yet — the empty state offers Create */
      }
    })();
    return () => { alive = false; };
  }, [loadHistory]);

  const createSession = async () => {
    if (busy) return;
    setBusy("create");
    setError("");
    try {
      const agg = await api.multifieldCreate(
        "DEMO / SOFTWARE VALIDATION — dataset images are not physically "
        + "independent microscope fields");
      setSession(agg);
      loadHistory();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const addField = async () => {
    if (!session || !pick || busy) return;
    setBusy("add");
    setError("");
    try {
      // Backend responds with the full updated aggregate — use it directly.
      const agg = await api.multifieldAddField(session.session_id, pick);
      setSession(agg);
      setPick("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const attached = new Set((session?.fields || []).map((f) => f.analysis_id));
  const attachable = history
    .filter((a) => !attached.has(a.id))
    .slice(0, 50);

  const cal = session?.calibration || {};
  const sampling = SAMPLING_LABEL[session?.sampling_status]
    ?? session?.sampling_status
    ?? "—";
  const uncalibrated = session && session.field_count > 0
    ? session.field_count - (cal.fields_calibrated || 0)
    : 0;

  return (
    <div className="dashboard-panel mf-session">
      <div className="panel-header">
        <h2>Multi-Field Session</h2>
        <span className="secondary-text" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
          ISO 945-4 sampling · {FIELD_TARGET} fields · {PARTICLE_TARGET} particles
        </span>
      </div>

      <div style={{ padding: 16 }}>
        {!session && (
          <>
            <p className="secondary-text" style={{ fontSize: 13 }}>
              Group completed analyses into an ISO 945-4 sampling session: every
              field stays independently traceable, ISO aggregates the underlying
              areas and JIS the class counts — never averages of field values.
            </p>
            <button
              className="new-analysis-btn batch-run-btn"
              onClick={createSession}
              disabled={busy === "create"}
            >
              <span className="material-symbols-outlined">library_add</span>
              {busy === "create" ? "Creating…" : "Create Multi-Field Session"}
            </button>
          </>
        )}

        {session && (
          <>
            <div className="mf-session-meta">
              <span className="sample-id" style={{ fontFamily: "var(--font-mono)" }}>
                {session.session_id}
              </span>
              <span className="secondary-text mf-session-label" title={session.label}>
                {session.label || "Multi-field session"}
              </span>
              <button
                className="range-btn mf-session-btn"
                onClick={() => refresh(session.session_id)}
                disabled={busy === "refresh"}
              >
                <span className="material-symbols-outlined">refresh</span>
                {busy === "refresh" ? "Refreshing…" : "Refresh"}
              </button>
            </div>

            <div className="traceability-grid mf-summary-grid">
              <div className="trace-item">
                <span>Fields</span>
                <strong>{session.field_count} / {FIELD_TARGET} target</strong>
              </div>
              <div className="trace-item">
                <span>Particles</span>
                <strong>{session.total_particle_count} / {PARTICLE_TARGET} target</strong>
              </div>
              <div className="trace-item">
                <span>Sampling</span>
                <strong>{sampling}</strong>
              </div>
              <div className="trace-item">
                <span>Calibration</span>
                <strong>{cal.fields_calibrated || 0} / {session.field_count} fields</strong>
              </div>
              <div className="trace-item">
                <span>10 µm filter</span>
                <strong>{sizeFilterSummary(session)}</strong>
              </div>
              <div className="trace-item">
                <span>Aggregate ISO (area-based)</span>
                <strong>{pct(session.aggregate_iso_nodularity_pct)}</strong>
              </div>
              <div className="trace-item">
                <span>Aggregate JIS (count-based)</span>
                <strong>{pct(session.aggregate_jis_nodularity_pct)}</strong>
              </div>
              <div className="trace-item">
                <span>Eligible fields</span>
                <strong>{session.eligible_field_count} / {session.field_count}</strong>
              </div>
            </div>

            <div className="mf-progress">
              <div className="mf-progress-row">
                <span className="secondary-text">Fields</span>
                <div className="batch-progress-track">
                  <span style={{
                    width: `${Math.min(100, (session.field_count / FIELD_TARGET) * 100)}%`,
                  }} />
                </div>
              </div>
              <div className="mf-progress-row">
                <span className="secondary-text">Particles</span>
                <div className="batch-progress-track">
                  <span style={{
                    width: `${Math.min(100,
                      (session.total_particle_count / PARTICLE_TARGET) * 100)}%`,
                  }} />
                </div>
              </div>
            </div>

            <p className={session.standards_aligned ? "mf-standards-ok" : "warning-text"}
              style={{ fontSize: 13, margin: "10px 0 0" }}>
              {session.standards_aligned
                ? "Standards-aligned sampling target reached"
                : "Sampling target not yet reached"}
              {session.aggregate_iso_nodularity_pct == null
                && session.eligible_field_count > 0
                && " — aggregate ISO pending a qualifying calibrated field"}
            </p>

            {uncalibrated > 0 && (
              <p className="warning-text" style={{ fontSize: 13, margin: "6px 0 0" }}>
                Physical calibration is missing for {uncalibrated} field(s);
                the 10 µm ISO size criterion cannot be evaluated for those fields.
              </p>
            )}
            {cal.consistent_scales === false && (
              <p className="warning-text" style={{ fontSize: 13, margin: "6px 0 0" }}>
                Fields use different physical scales; only fields sharing one
                scale group are aggregated (see field table).
              </p>
            )}

            {(session.notes || []).map((n, i) => (
              <p key={i} className="secondary-text" style={{ fontSize: 12, margin: "4px 0 0" }}>
                {n}
              </p>
            ))}

            <div className="mf-attach-row">
              <select
                className="mf-attach-select"
                value={pick}
                onChange={(e) => setPick(e.target.value)}
                disabled={busy === "add"}
              >
                <option value="">
                  {attachable.length
                    ? "Select a completed analysis to attach…"
                    : "No unattached completed analyses — run a batch first"}
                </option>
                {attachable.map((a) => (
                  <option key={a.id} value={a.id}>
                    {(a.filename || a.id)} — {a.id}
                    {a.nodule_count != null ? ` (${a.nodule_count} particles)` : ""}
                  </option>
                ))}
              </select>
              <button
                className="range-btn mf-session-btn"
                onClick={addField}
                disabled={!pick || busy === "add"}
              >
                <span className="material-symbols-outlined">add</span>
                {busy === "add" ? "Adding field…" : "Add Field"}
              </button>
            </div>

            {error && (
              <p className="warning-text" style={{ fontSize: 13, margin: "8px 0 0" }}>
                {error}
              </p>
            )}

            {(session.fields || []).length > 0 && (
              <div className="table-container mf-field-table">
                <table>
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Image</th>
                      <th>Analysis</th>
                      <th>Particles</th>
                      <th>Calibration</th>
                      <th>&lt;10 µm filter</th>
                      <th>ISO</th>
                      <th>JIS</th>
                      <th>Status</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {session.fields.map((f, i) => (
                      <tr key={f.analysis_id}
                        className={f.eligible ? undefined : "review-row"}>
                        <td className="sample-id" style={{ fontFamily: "var(--font-mono)" }}>
                          #{i + 1}
                        </td>
                        <td>{f.image_name || "—"}</td>
                        <td style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                          {f.analysis_id}
                        </td>
                        <td>{f.particle_count ?? "—"}{f.border_count
                          ? <span className="secondary-text"> ({f.border_count} border)</span>
                          : null}
                        </td>
                        <td>
                          {f.calibrated
                            ? `Valid (${f.microns_per_pixel} µm/px)`
                            : "Missing"}
                        </td>
                        <td>
                          {f.size_excluded_count != null
                            ? `Applied (${f.size_excluded_count} excl.)`
                            : "N/A"}
                        </td>
                        <td>{pct(f.iso_pct)}</td>
                        <td>{pct(f.jis_pct)}</td>
                        <td title={f.eligible ? undefined : f.exclusion_reason || ""}>
                          <span className="status">
                            <span className={`status-dot ${f.eligible ? "success" : "error"}`} />
                            {f.eligible ? "Included" : "Excluded"}
                          </span>
                        </td>
                        <td>
                          <button
                            className="mf-open-btn"
                            title="Ask NODIQ Copilot about this field"
                            aria-label={`Ask NODIQ Copilot about analysis ${f.analysis_id}`}
                            onClick={() => navigate("/copilot", {
                              state: {
                                analysisId: f.analysis_id,
                                seedMessage:
                                  `Explain field ${f.analysis_id} `
                                  + `(${f.image_name || "image"}) within its `
                                  + "multi-field session — measured values, "
                                  + "eligibility and how it contributes to the "
                                  + "aggregate.",
                              },
                            })}
                          >
                            <span className="material-symbols-outlined">smart_toy</span>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <p className="secondary-text" style={{ fontSize: 11, margin: "10px 0 0" }}>
              Fields reference existing analyses — attaching never duplicates or
              re-runs an analysis. ISO/JIS aggregates come from the backend;
              per-particle detail remains in the analysis views.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
