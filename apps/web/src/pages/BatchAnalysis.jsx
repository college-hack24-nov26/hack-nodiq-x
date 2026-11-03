import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import MultiFieldSessionPanel from "../components/multifield/MultiFieldSessionPanel";
import "./Dashboard.css";
import "./BatchAnalysis.css";

/**
 * Batch Analysis — queue multiple dataset micrographs, run the real engine on
 * each sequentially, and tabulate live results with a batch summary.
 * Every run is a genuine analysis (saved to history), same engine as single.
 */

const MAX_BATCH = 12;
const POLL_INTERVAL_MS = 2000;
const POLL_MAX_MS = 10 * 60 * 1000; // per-image cap: give up after 10 minutes

const pct = (v) => (v == null ? "—" : `${v}%`);

function BatchAnalysis() {
  const navigate = useNavigate();
  const [dataset, setDataset] = useState([]);
  const [selected, setSelected] = useState([]);
  const [queue, setQueue] = useState([]);        // [{key, name, kind, status, result?, error?}]
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [uploads, setUploads] = useState([]);    // [{id, name, file}] — user's own images
  const [reviewState, setReviewState] = useState({}); // { [analysisId]: review }
  const [reviewBusy, setReviewBusy] = useState(null); // analysisId being reviewed
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);

  useEffect(() => {
    api.dataset()
      .then((d) => setDataset((d.images || []).map((it) =>
        typeof it === "string" ? it : it.name)))
      .catch(() => setDataset([]));
  }, []);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = q ? dataset.filter((n) => n.includes(q)) : dataset;
    return list.slice(0, 60);
  }, [dataset, search]);

  const toggle = (name) => {
    setSelected((cur) => {
      if (cur.includes(name)) return cur.filter((n) => n !== name);
      if (cur.length >= MAX_BATCH) return cur;
      return [...cur, name];
    });
  };

  const pickRandom = (n = 5) => {
    const pool = [...dataset];
    const picks = [];
    while (picks.length < Math.min(n, pool.length)) {
      const i = Math.floor(Math.random() * pool.length);
      picks.push(pool.splice(i, 1)[0]);
    }
    setSelected(picks);
  };

  const addUploads = (fileList) => {
    const files = Array.from(fileList || []).filter(
      (f) => f.type.startsWith("image/") || /\.(png|jpe?g|tif|tiff|bmp)$/i.test(f.name));
    if (files.length === 0) return;
    setUploads((cur) => {
      const room = MAX_BATCH - selected.length - cur.length;
      if (room <= 0) return cur;
      const taken = new Set(cur.map((u) => `${u.name}:${u.file.size}`));
      const next = [];
      for (const f of files) {
        if (next.length >= room) break;
        const key = `${f.name}:${f.size}`;
        if (taken.has(key)) continue;
        taken.add(key);
        next.push({ id: `${f.name}-${f.size}-${Math.random().toString(36).slice(2, 7)}`, name: f.name, file: f });
      }
      return [...cur, ...next];
    });
  };

  const removeUpload = (id) =>
    setUploads((cur) => cur.filter((u) => u.id !== id));

  const runBatch = async () => {
    const items = [
      ...selected.map((name) => ({ key: name, name, kind: "dataset" })),
      ...uploads.map((u) => ({ key: u.id, name: u.name, kind: "upload", file: u.file })),
    ];
    if (items.length === 0 || running) return;
    setRunning(true);
    setError("");
    setQueue(items.map((it) => ({
      ...it,
      status: "queued",
      progress: 0,
      // uploads have no public URL — a local object URL feeds the row thumbnail
      previewUrl: it.kind === "upload" ? URL.createObjectURL(it.file) : null,
    })));

    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      setQueue((q) => q.map((item, idx) =>
        idx === i ? { ...item, status: "running" } : item));
      try {
        // /api/analyze is async: it enqueues and returns 202
        // {analysis_id, status: "processing"} — the metrics only exist once
        // the worker stores them, so poll the detail endpoint until
        // "completed" (same contract as the single-analysis page). Without
        // the poll the row would read "done" with every metric em-dash.
        const resp = it.kind === "upload"
          ? await api.analyzeUpload(it.file)
          : await api.analyzeDatasetImage(it.name);
        let result = resp;
        const pollId = resp?.analysis_id;
        // Poll whenever the server handed us an id but no metrics yet — the
        // 202 envelope (status "processing") never carries them. (A future
        // synchronous payload that already has metrics skips the poll.)
        // Without this the row would read "done" with every metric em-dash.
        const hasMetrics = result?.iso_nodularity_pct != null;
        if (pollId && !hasMetrics) {
          const deadline = Date.now() + POLL_MAX_MS;
          let finished = false;
          let pollErrors = 0;
          while (!finished && Date.now() < deadline) {
            await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
            let detail = null;
            try {
              detail = await api.analysisDetail(pollId);
              pollErrors = 0;
            } catch {
              // one dropped poll (laptop sleep, proxy hiccup) must not kill
              // a five-minute analysis — tolerate a few consecutive misses
              pollErrors += 1;
              if (pollErrors >= 3) {
                throw new Error("Lost contact with the server while polling "
                  + "the analysis — check My Analyses in a minute.");
              }
              continue;
            }
            // surface live server-side progress (5 → 45 → 70 → 90 → 100)
            const prog = detail?.progress ?? detail?.record?.progress;
            if (typeof prog === "number") {
              setQueue((q) => q.map((item, idx) =>
                idx === i ? { ...item, progress: prog } : item));
            }
            const status = detail?.status || detail?.record?.status;
            if (status === "completed" && detail.analysis) {
              result = {
                ...detail.analysis,
                filename: detail.analysis.filename || it.name,
              };
              // a decision recorded earlier for this image lives on the record
              if (detail.record?.review) result.review = detail.record.review;
              finished = true;
            } else if (status === "failed") {
              throw new Error(detail?.error || detail?.record?.error
                || "Analysis failed on the server.");
            }
          }
          if (!finished) {
            throw new Error("Analysis is taking unusually long — find it "
              + "under My Analyses; it may still be running.");
          }
        }
        setQueue((q) => q.map((item, idx) =>
          idx === i ? { ...item, status: "done", result } : item));
        // every batch run is a saved analysis — keep its id for review/report
        // links, and surface a decision recorded earlier for this image
        if (result?.analysis_id) {
          setReviewState((s) => result.review
            ? { ...s, [result.analysis_id]: result.review } : s);
        }
      } catch (e) {
        setQueue((q) => q.map((item, idx) =>
          idx === i ? { ...item, status: "failed", error: e.message } : item));
      }
    }
    setRunning(false);
  };

  const done = queue.filter((q) => q.status === "done");
  const failed = queue.filter((q) => q.status === "failed");
  const progress = queue.length
    ? Math.round(((done.length + failed.length) / queue.length) * 100)
    : 0;

  const summary = useMemo(() => {
    if (done.length === 0) return null;
    const isos = done.map((d) => d.result.iso_nodularity_pct).filter((v) => v != null);
    const counts = done.map((d) => d.result.nodule_count).filter((v) => v != null);
    const accs = done.map((d) => d.result.self_check?.count_accuracy_pct).filter((v) => v != null);
    const mean = (a) => (a.length ? Math.round((a.reduce((x, y) => x + y, 0) / a.length) * 10) / 10 : null);
    return {
      n: done.length,
      meanIso: mean(isos),
      minIso: isos.length ? Math.min(...isos) : null,
      maxIso: isos.length ? Math.max(...isos) : null,
      meanCount: mean(counts),
      meanAcc: mean(accs),
      pass: isos.filter((v) => v >= 80).length,
    };
  }, [done]);

  return (
    <main className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h1>Batch Analysis</h1>
          <p>
            Queue up to {MAX_BATCH} micrographs from the validated dataset — the engine runs
            each one sequentially and every result is saved to your history.
          </p>
        </div>
        <button className="new-analysis-btn" onClick={() => navigate("/new-analysis")}>
          <span className="material-symbols-outlined">add</span>
          Single Analysis
        </button>
      </header>

      <div className="dashboard-content">
        {/* Picker + queue side by side */}
        <section className="batch-grid">
          {/* Dataset picker */}
          <div className="dashboard-panel batch-picker">
            <div className="panel-header">
              <h2>1 · Select Images</h2>
              <span className="secondary-text" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
                {selected.length + uploads.length}/{MAX_BATCH} selected
              </span>
            </div>

            <div className="batch-picker-toolbar">
              <div className="my-analyses-search batch-search">
                <span className="material-symbols-outlined">search</span>
                <input
                  type="text"
                  placeholder="Search dataset…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <button className="range-btn" onClick={() => pickRandom(5)} disabled={running}>
                Pick 5 random
              </button>
              <button className="range-btn" onClick={() => setSelected([])} disabled={running || !selected.length}>
                Clear
              </button>
            </div>

            <div className="batch-upload-row">
              <button
                className="range-btn batch-upload-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={running}
              >
                <span className="material-symbols-outlined">upload</span>
                Add images
              </button>
              <button
                className="range-btn batch-upload-btn"
                onClick={() => folderInputRef.current?.click()}
                disabled={running}
              >
                <span className="material-symbols-outlined">drive_folder_upload</span>
                Add folder
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(e) => { addUploads(e.target.files); e.target.value = ""; }}
              />
              <input
                ref={folderInputRef}
                type="file"
                multiple
                hidden
                {...{ webkitdirectory: "", directory: "" }}
                onChange={(e) => { addUploads(e.target.files); e.target.value = ""; }}
              />
              {uploads.length > 0 && (
                <button className="range-btn" onClick={() => setUploads([])} disabled={running}>
                  Clear mine
                </button>
              )}
              <span className="secondary-text batch-upload-hint">
                PNG · JPG · TIFF · BMP — pick a folder to grab every image inside
              </span>
            </div>

            {uploads.length > 0 && (
              <div className="batch-uploads">
                {uploads.map((u) => (
                  <span key={u.id} className="batch-upload-chip" title={`${u.name} (${Math.round(u.file.size / 1024)} KB)`}>
                    <span className="material-symbols-outlined">image</span>
                    <span className="batch-upload-chip-name">{u.name}</span>
                    <button
                      className="batch-upload-chip-x"
                      onClick={() => removeUpload(u.id)}
                      disabled={running}
                      aria-label={`Remove ${u.name}`}
                    >
                      <span className="material-symbols-outlined">close</span>
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="batch-thumb-grid">
              {shown.map((name) => {
                const isSel = selected.includes(name);
                const num = name.match(/(\d+)/)?.[1] || "";
                return (
                  <button
                    key={name}
                    className={"batch-thumb" + (isSel ? " selected" : "")}
                    onClick={() => toggle(name)}
                    disabled={running}
                    title={name}
                  >
                    <img src={api.datasetImageUrl(name)} alt={name} loading="lazy" />
                    <span className="batch-thumb-label">#{num}</span>
                    {isSel && (
                      <span className="batch-thumb-check">
                        <span className="material-symbols-outlined">check</span>
                      </span>
                    )}
                  </button>
                );
              })}
              {shown.length === 0 && (
                <p className="secondary-text" style={{ padding: 12 }}>No dataset images match.</p>
              )}
            </div>
          </div>

          {/* Run + summary */}
          <div className="dashboard-panel batch-run">
            <div className="panel-header">
              <h2>2 · Run Batch</h2>
            </div>
            <div style={{ padding: 16 }}>
              <button
                className="new-analysis-btn batch-run-btn"
                onClick={runBatch}
                disabled={selected.length + uploads.length === 0 || running}
              >
                <span className="material-symbols-outlined">play_arrow</span>
                {running
                  ? `Analyzing… (${progress}%)`
                  : `Analyze ${selected.length + uploads.length || ""} image${selected.length + uploads.length === 1 ? "" : "s"}`}
              </button>

              {queue.length > 0 && (
                <div className="batch-progress-track">
                  <span style={{ width: `${progress}%` }} />
                </div>
              )}

              {error && <p className="warning-text" style={{ fontSize: 13 }}>{error}</p>}

              {summary && (
                <div className="batch-summary">
                  <h3>Batch Summary ({summary.n} completed{failed.length ? `, ${failed.length} failed` : ""})</h3>
                  <div className="traceability-grid">
                    <div className="trace-item">
                      <span>Mean ISO</span>
                      <strong>{summary.meanIso != null ? `${summary.meanIso}%` : "—"}</strong>
                    </div>
                    <div className="trace-item">
                      <span>Min–Max ISO</span>
                      <strong>{summary.minIso != null ? `${summary.minIso}% – ${summary.maxIso}%` : "—"}</strong>
                    </div>
                    <div className="trace-item">
                      <span>Mean Count</span>
                      <strong>{summary.meanCount ?? "—"}</strong>
                    </div>
                    <div className="trace-item">
                      <span>Mean Self-Check</span>
                      <strong>{summary.meanAcc != null ? `${summary.meanAcc}%` : "—"}</strong>
                    </div>
                    <div className="trace-item">
                      <span>Pass (≥80%)</span>
                      <strong>{summary.pass}/{summary.n}</strong>
                    </div>
                  </div>
                  <button
                    className="range-btn"
                    style={{ marginTop: 12 }}
                    onClick={() => navigate("/analytics")}
                  >
                    Open full Analytics →
                  </button>
                </div>
              )}

              {queue.length === 0 && (
                <p className="secondary-text" style={{ fontSize: 13 }}>
                  Select dataset images or add your own, then run. Results appear below as they complete.
                </p>
              )}
            </div>
          </div>
        </section>

        {/* Multi-field sampling session (additive — backend is authoritative) */}
        <MultiFieldSessionPanel />

        {/* Results table */}
        {queue.length > 0 && (
          <div className="dashboard-panel">
            <div className="panel-header">
              <h2>3 · Results</h2>
              <span className="secondary-text" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
                {done.length} done · {failed.length} failed · {queue.length - done.length - failed.length} pending
              </span>
            </div>
            <div className="table-container batch-results-table">
              <table>
                <thead>
                  <tr>
                    <th>Image</th>
                    <th>Status</th>
                    <th className="num">Nodules</th>
                    <th className="num">ISO %</th>
                    <th className="num">JIS %</th>
                    <th className="num">Self-Check</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map((item) => {
                    const r = item.result;
                    const iso = r?.iso_nodularity_pct;
                    const aid = r?.analysis_id || null;
                    return (
                      <tr key={item.key}
                          title={item.status === "failed" ? item.error : undefined}
                          className={item.status === "failed" ? "batch-row-failed" : undefined}>
                        <td className="sample-id">
                          <span className="batch-cell-img">
                            <img
                              className="batch-row-thumb"
                              src={item.previewUrl || api.datasetImageUrl(item.name)}
                              alt=""
                              loading="lazy"
                              onError={(e) => { e.currentTarget.style.visibility = "hidden"; }}
                            />
                            <span className="batch-cell-name">
                              {item.name}
                              {item.kind === "upload" && <span className="batch-kind-badge">your image</span>}
                            </span>
                          </span>
                        </td>
                        <td><StatusCell item={item} /></td>
                        <td className="num">{r?.nodule_count ?? "—"}</td>
                        <td className="num">{pct(iso)}</td>
                        <td className="num">{pct(r?.jis_nodularity_pct)}</td>
                        <td className="num">{pct(r?.self_check?.count_accuracy_pct)}</td>
                        <td>
                          <VerdictCell
                            iso={iso}
                            analysisId={aid}
                            review={reviewState[aid]}
                            busy={reviewBusy === aid}
                            onReview={async (status, comment) => {
                              if (!aid) return;
                              setReviewBusy(aid);
                              try {
                                const res = await api.setReview(aid, { status, comment });
                                setReviewState((s) => ({ ...s, [aid]: res.review }));
                              } catch (e) {
                                setError(`Review failed for ${item.name}: ${e.message}`);
                              } finally {
                                setReviewBusy(null);
                              }
                            }}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

export default BatchAnalysis;

/** Status column: queued / live progress / failure reason / completed —
 *  a bare lowercase "done" with no context reads as unfinished. */
function StatusCell({ item }) {
  if (item.status === "queued") {
    return (
      <span className="batch-status-line">
        <span className="status-dot queued" />
        <span className="secondary-text">Queued</span>
      </span>
    );
  }
  if (item.status === "running") {
    return (
      <span className="batch-status-running">
        <span className="batch-status-line">
          <span className="material-symbols-outlined processing-icon">progress_activity</span>
          Analyzing…
        </span>
        <span className="batch-progress-track batch-mini-track">
          <span style={{ width: `${Math.max(5, item.progress || 0)}%` }} />
        </span>
      </span>
    );
  }
  if (item.status === "failed") {
    return (
      <span className="batch-status-running">
        <span className="batch-status-line">
          <span className="status-dot error" />
          Failed
        </span>
        {item.error && <span className="batch-status-error">{item.error}</span>}
      </span>
    );
  }
  // done
  if (item.result?.iso_nodularity_pct == null) {
    // Defensive: the poll loop makes this near-impossible, but if the server
    // ever completes without metrics, say so instead of a wall of em-dashes.
    return (
      <span className="batch-status-running">
        <span className="batch-status-line">
          <span className="status-dot success" />
          Completed
        </span>
        <span className="batch-status-hint">
          No metrics in the server payload — open this analysis under My Analyses.
        </span>
      </span>
    );
  }
  return (
    <span className="batch-status-line">
      <span className="status-dot success" />
      Completed
    </span>
  );
}

/** Verdict column for completed rows: ≥80% ISO passes outright (with a direct
 *  route to its report); below the threshold the engineering sign-off flow
 *  (same workflow as Review Center) takes over. */
function VerdictCell({ iso, analysisId, review, busy, onReview }) {
  const navigate = useNavigate();
  if (iso == null) return <span className="batch-empty">—</span>;
  if (iso >= 80) {
    return (
      <span className="batch-verdict">
        <span className="batch-verdict-chip pass">PASS</span>
        <button
          className="batch-report-link"
          disabled={!analysisId}
          onClick={() => navigate("/reports/generate", { state: { analysisId } })}
          title="Open the report generator for this analysis"
        >
          <span className="material-symbols-outlined">description</span>
          Report
        </button>
      </span>
    );
  }
  return <ReviewButton review={review} busy={busy} onReview={onReview} onViewReport={analysisId} />;
}

/** Sign-off flow for below-threshold rows: shows the recorded decision when
 *  one exists, otherwise opens a menu with report access + one-click decision
 *  (same workflow as Review Center — identity is recorded server-side). */
const MENU_W = 208; // px — keep in sync with .batch-review-menu min-width

function ReviewButton({ review, busy, onReview, onViewReport }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState(null); // fixed-position anchor {top, left} in viewport coords
  const btnRef = useRef(null);
  const [reportId, setReportId] = useState(undefined); // undefined = unchecked, null = none, string = openable

  // Lazily resolve whether a report exists for this analysis (only when the
  // menu is first opened) so "Review report" either opens it or starts one.
  const resolveReport = () => {
    if (reportId !== undefined) return;
    setReportId(null);
    api.reports()
      .then((data) => {
        const match = (data.reports || []).find(
          (r) => r.analysis_id === onViewReport,
        );
        setReportId(match ? match.id : null);
      })
      .catch(() => setReportId(null));
  };

  if (review?.status) {
    const tone = review.status === "approved"
      ? "var(--color-success)"
      : review.status === "rejected"
        ? "var(--color-error, #d32f2f)"
        : "var(--nodiq-cyan, #00bcd4)";
    return (
      <span className="batch-review-decided" title={review.comment || ""}>
        <span style={{ color: tone, fontWeight: 600 }}>{review.status}</span>
        {review.reviewed_by && (
          <span className="secondary-text" style={{ fontSize: 11 }}> · {review.reviewed_by}</span>
        )}
        <button
          className="batch-review-clear"
          disabled={busy}
          onClick={() => onReview("clear")}
          title="Clear review decision"
        >
          clear
        </button>
      </span>
    );
  }

  return (
    <span className="batch-review-wrap">
      <button
        ref={btnRef}
        className="batch-review-btn"
        disabled={busy}
        onClick={() => {
          if (!open && btnRef.current) {
            const r = btnRef.current.getBoundingClientRect();
            // fixed anchor: above the button — escapes the scrollable table
            // container's overflow clipping; left clamped so the menu never
            // runs off the right edge of the viewport
            setAnchor({
              top: r.top,
              left: Math.max(8, Math.min(r.right, window.innerWidth - MENU_W - 8)),
            });
          }
          setOpen((o) => !o);
          resolveReport();
        }}
        title="Review this analysis: open its report, then record a decision"
      >
        {busy ? "saving…" : "REVIEW"}
      </button>
      {open && anchor && (
        <>
          <span
            style={{ position: "fixed", inset: 0, zIndex: 25 }}
            onClick={() => setOpen(false)}
          />
          <span className="batch-review-menu" style={{ position: "fixed", top: anchor.top, left: anchor.left }}>
            <button
              className="batch-review-menu__report"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                navigate("/reports/generate", {
                  state: onViewReport ? { analysisId: onViewReport } : undefined,
                });
              }}
            >
              <span className="material-symbols-outlined">description</span>
              {reportId ? "Review report" : "Review & create report"}
            </button>
            <span className="batch-review-menu__sep" />
            <button disabled={busy} onClick={() => { setOpen(false); onReview("approved"); }} style={{ color: "var(--color-success)" }}>Approve</button>
            <button disabled={busy} onClick={() => { setOpen(false); onReview("changes_requested"); }} style={{ color: "var(--nodiq-cyan, #00bcd4)" }}>Changes requested</button>
            <button disabled={busy} onClick={() => { setOpen(false); onReview("rejected"); }} style={{ color: "var(--color-error, #d32f2f)" }}>Reject</button>
          </span>
        </>
      )}
    </span>
  );
}
