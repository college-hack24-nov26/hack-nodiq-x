/**
 * Review Center — expert QA & validation workspace.
 *
 * DELIBERATELY DIFFERENT from the Analysis page: Analysis is the automated
 * measurement view; Review Center is the reviewer's queue (kanban-style
 * buckets), sample triage and electronic sign-off with an audit trail.
 * All values shown come from the real engine records — nothing hardcoded.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Toast from "../components/common/Toast";
import api from "../services/api";
import "./ReviewCenter.css";

const BUCKETS = [
  {
    key: "pending",
    label: "Pending",
    hint: "Awaiting reviewer decision",
    tone: "neutral",
    icon: "inbox",
  },
  {
    key: "attention",
    label: "Needs attention",
    hint: "Quality or anomaly flags",
    tone: "warn",
    icon: "flag",
  },
  {
    key: "changes_requested",
    label: "Needs correction",
    hint: "Sent back for correction",
    tone: "warn",
    icon: "rate_review",
  },
  {
    key: "approved",
    label: "Approved",
    hint: "Signed off by a reviewer",
    tone: "ok",
    icon: "verified",
  },
  {
    key: "rejected",
    label: "Rejected",
    hint: "Failed review",
    tone: "bad",
    icon: "block",
  },
];

function bucketFor(item) {
  if (item.review?.status) return item.review.status;
  return item.needsAttention ? "attention" : "pending";
}

function statusLabel(item) {
  const b = bucketFor(item);
  return BUCKETS.find((x) => x.key === b)?.label || "Pending";
}

function pct(v) {
  return typeof v === "number" ? `${v.toFixed(1)}%` : "—";
}

function num(v) {
  return typeof v === "number" ? String(v) : "—";
}

function QualityChip({ item }) {
  const q = item.quality_score;
  const tone =
    typeof q === "number" && q >= 70 ? "ok" : typeof q === "number" ? "warn" : "neutral";
  return (
    <span className={`rc-chip rc-chip--${tone}`}>
      <span className="material-symbols-outlined">photo_camera</span>
      {typeof q === "number" ? `Quality ${q}` : "No quality data"}
    </span>
  );
}

function MetricCell({ label, value }) {
  return (
    <div className="rc-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ReviewCenter() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [activeBucket, setActiveBucket] = useState("pending");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [comment, setComment] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [reviewer, setReviewer] = useState("Reviewer");
  const [detailTab, setDetailTab] = useState("measurements");
  const [overlayUrl, setOverlayUrl] = useState(null);
  const [originalUrl, setOriginalUrl] = useState(null);
  const [toast, setToast] = useState({ open: false, message: "" });

  /* Reviewer identity comes from the real auth session (Profile stores the
     same user object). No fabricated reviewer names. */
  useEffect(() => {
    try {
      const raw =
        localStorage.getItem("nodiq_current_user") ||
        localStorage.getItem("nodiq_user_credentials");
      const u = raw ? JSON.parse(raw) : null;
      if (u?.name || u?.email) setReviewer(u.name || u.email);
    } catch {
      /* keep default */
    }
  }, []);

  const loadQueue = () => {
    setLoading(true);
    api
      .analyses()
      .then((data) => {
        const rows = (data.analyses || []).map((a) => ({
          ...a,
          needsAttention:
            (a.warnings || []).length > 0 ||
            (typeof a.accuracy_pct === "number" && a.accuracy_pct < 95) ||
            (typeof a.quality_score === "number" && a.quality_score < 60),
        }));
        setItems(rows);
        setLoadError("");
      })
      .catch((e) => setLoadError(e.message || "Could not load the review queue."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadQueue();
  }, []);

  /* -------- detail fetch (record + full payload + images) -------- */
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return undefined;
    }
    let alive = true;
    setDetail(null);
    setDetailTab("measurements");
    api
      .analysisDetail(selectedId)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch(() => {
        if (alive) setDetail({ record: null, analysis: null, fetchFailed: true });
      });
    const revOk = (u) => {
      if (alive) URL.revokeObjectURL(u);
    };
    api
      .fetchImage(api.analysisImageUrl(selectedId))
      .then((u) => {
        if (alive) setOriginalUrl(u);
        else revOk(u);
      })
      .catch(() => {});
    api
      .fetchImage(`/api/analyses/${selectedId}/overlay`)
      .then((u) => {
        if (alive) setOverlayUrl(u);
        else revOk(u);
      })
      .catch(() => {});
    return () => {
      alive = false;
      setOverlayUrl(null);
      setOriginalUrl(null);
    };
  }, [selectedId]);

  /* -------- queue segmentation -------- */
  const buckets = useMemo(() => {
    const b = Object.fromEntries(BUCKETS.map((x) => [x.key, []]));
    for (const item of items) b[bucketFor(item)].push(item);
    return b;
  }, [items]);

  const counts = useMemo(
    () => Object.fromEntries(BUCKETS.map((x) => [x.key, buckets[x.key].length])),
    [buckets],
  );

  const visibleItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    let rows = buckets[activeBucket] || [];
    if (q) {
      rows = rows.filter(
        (r) =>
          r.id?.toLowerCase().includes(q) ||
          r.filename?.toLowerCase().includes(q) ||
          r.title?.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [buckets, activeBucket, search]);

  const refreshSelected = () => {
    if (!selectedId) return;
    api
      .analysisDetail(selectedId)
      .then((d) => setDetail(d))
      .catch(() => {});
  };

  /* -------- reviewer actions (real sign-off API) -------- */
  const submitReview = (status) => {
    if (!selectedId) return;
    setActionBusy(true);
    api
      .setReview(selectedId, { status, comment, reviewer })
      .then(() => {
        setComment("");
        loadQueue();
        refreshSelected();
        setToast({
          open: true,
          message:
            status === "approved"
              ? `${selectedId} approved — sign-off recorded.`
              : status === "rejected"
                ? `${selectedId} rejected — decision recorded.`
                : `${selectedId} sent back for correction.`,
        });
      })
      .catch((e) => setToast({ open: true, message: e.message || "Review failed." }))
      .finally(() => setActionBusy(false));
  };

  const clearReview = () => {
    if (!selectedId) return;
    setActionBusy(true);
    api
      .setReview(selectedId, { status: "clear", comment: comment || "review cleared", reviewer })
      .then(() => {
        setComment("");
        loadQueue();
        refreshSelected();
        setToast({ open: true, message: `Review cleared for ${selectedId}.` });
      })
      .catch((e) => setToast({ open: true, message: e.message || "Could not clear review." }))
      .finally(() => setActionBusy(false));
  };

  const openInCopilot = () => {
    if (selectedId) localStorage.setItem("nodiq_active_analysis", selectedId);
    navigate("/copilot");
  };

  const rec = detail?.record || null;
  const full = detail?.analysis || null;
  const q = full?.quality || {};
  const cal = full?.calibration || {};
  const anomaly = full?.anomaly_summary || null;
  const review = rec?.review || null;
  const history = rec?.review_history || [];

  return (
    <div className="rc-page">
      {/* HEADER */}
      <header className="rc-header">
        <div>
          <span className="rc-eyebrow">
            <span className="material-symbols-outlined">fact_check</span>
            EXPERT QA &amp; VALIDATION
          </span>
          <h1>Review Center</h1>
          <p>
            Triage, validate and sign off engine results. Measurement values are
            produced by the NODIQ-X engine — the reviewer owns the decision.
          </p>
        </div>
        <div className="rc-header-side">
          <div className="rc-reviewer-badge">
            <span className="material-symbols-outlined">assignment_ind</span>
            <div>
              <span>On duty</span>
              <strong>{reviewer}</strong>
            </div>
          </div>
          <button type="button" className="rc-refresh" onClick={loadQueue}>
            <span className="material-symbols-outlined">refresh</span>
            Refresh queue
          </button>
        </div>
      </header>

      {/* QUEUE BUCKETS */}
      <section className="rc-buckets">
        {BUCKETS.map((b) => (
          <button
            key={b.key}
            type="button"
            className={`rc-bucket rc-bucket--${b.tone} ${activeBucket === b.key ? "active" : ""}`}
            onClick={() => setActiveBucket(b.key)}
          >
            <div className="rc-bucket-top">
              <span className="material-symbols-outlined">{b.icon}</span>
              <strong>{counts[b.key] ?? 0}</strong>
            </div>
            <span className="rc-bucket-label">{b.label}</span>
            <span className="rc-bucket-hint">{b.hint}</span>
          </button>
        ))}
      </section>

      {/* QUEUE LIST */}
      <section className="rc-queue">
        <div className="rc-queue-head">
          <h2>
            {BUCKETS.find((x) => x.key === activeBucket)?.label} queue
            <span className="rc-count">{visibleItems.length}</span>
          </h2>
          <div className="rc-search">
            <span className="material-symbols-outlined">search</span>
            <input
              type="text"
              placeholder="Search by id or filename..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {loading ? (
          <div className="rc-empty">
            <span className="material-symbols-outlined">hourglass_top</span>
            <p>Loading review queue…</p>
          </div>
        ) : loadError ? (
          <div className="rc-empty rc-empty--error">
            <span className="material-symbols-outlined">cloud_off</span>
            <p>{loadError}</p>
            <button type="button" onClick={loadQueue}>Retry</button>
          </div>
        ) : visibleItems.length === 0 ? (
          <div className="rc-empty">
            <span className="material-symbols-outlined">task_alt</span>
            <p>Nothing waiting in this bucket.</p>
          </div>
        ) : (
          <div className="rc-rows">
            {visibleItems.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`rc-row ${selectedId === item.id ? "selected" : ""}`}
                onClick={() => setSelectedId(item.id)}
              >
                <div className="rc-row-main">
                  <span className="rc-row-id">{item.id}</span>
                  <span className="rc-row-file">{item.filename || item.title || "upload"}</span>
                </div>
                <div className="rc-row-metrics">
                  <MetricCell label="Nodes" value={num(item.nodule_count)} />
                  <MetricCell label="ISO" value={pct(item.iso_nodularity_pct)} />
                  <MetricCell label="JIS" value={pct(item.jis_nodularity_pct)} />
                  <MetricCell label="F1" value={pct(item.confidence_pct)} />
                </div>
                <div className="rc-row-side">
                  <QualityChip item={item} />
                  {item.needsAttention && (
                    <span className="rc-chip rc-chip--warn">
                      <span className="material-symbols-outlined">flag</span>
                      {(item.warnings || []).length || 1} flag(s)
                    </span>
                  )}
                  <span className={`rc-status rc-status--${bucketFor(item)}`}>
                    {statusLabel(item)}
                  </span>
                </div>
                <span className="material-symbols-outlined rc-row-chevron">chevron_right</span>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* DETAIL DRAWER */}
      {selectedId && (
        <section className="rc-detail">
          <div className="rc-detail-head">
            <div>
              <span className="rc-eyebrow">SAMPLE {selectedId}</span>
              <h2>{rec?.filename || rec?.title || "Loading…"}</h2>
            </div>
            <button type="button" className="rc-close" onClick={() => setSelectedId(null)}>
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>

          {!detail ? (
            <div className="rc-empty"><p>Loading sample…</p></div>
          ) : detail.fetchFailed || (!rec && !full) ? (
            <div className="rc-empty rc-empty--error">
              <p>Sample detail could not be loaded from the server.</p>
            </div>
          ) : (
            <>
              {/* tabs */}
              <div className="rc-tabs">
                {["measurements", "images", "anomalies", "audit"].map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={`rc-tab ${detailTab === t ? "active" : ""}`}
                    onClick={() => setDetailTab(t)}
                  >
                    {t === "audit" ? "Audit trail" : t}
                  </button>
                ))}
              </div>

              {detailTab === "measurements" && (
                <div className="rc-detail-body">
                  <div className="rc-metric-grid">
                    <MetricCell label="Node count" value={num(rec?.nodule_count)} />
                    <MetricCell label="ISO nodularity" value={pct(rec?.iso_nodularity_pct)} />
                    <MetricCell label="JIS nodularity" value={pct(rec?.jis_nodularity_pct)} />
                    <MetricCell label="Self-check F1" value={pct(rec?.confidence_pct)} />
                    <MetricCell label="Count accuracy" value={pct(rec?.accuracy_pct)} />
                    <MetricCell
                      label="Image quality"
                      value={typeof q.score === "number" ? `${q.score}/100` : "Not assessed"}
                    />
                    <MetricCell
                      label="Calibration"
                      value={cal.available ? `${cal.um_per_px} µm/px` : "Pixels only"}
                    />
                    <MetricCell label="Analyzed" value={rec?.created_at || "—"} />
                  </div>

                  {(full?.warnings || []).length > 0 && (
                    <div className="rc-warnings">
                      <span className="material-symbols-outlined">warning</span>
                      <div>
                        {full.warnings.map((w, i) => (
                          <p key={i}>{w}</p>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {detailTab === "images" && (
                <div className="rc-images">
                  <figure>
                    {originalUrl ? (
                      <img src={originalUrl} alt="Original micrograph" />
                    ) : (
                      <div className="rc-img-fallback">Original image unavailable</div>
                    )}
                    <figcaption>Original micrograph</figcaption>
                  </figure>
                  <figure>
                    {overlayUrl ? (
                      <img src={overlayUrl} alt="Detection overlay" />
                    ) : (
                      <div className="rc-img-fallback">Overlay unavailable</div>
                    )}
                    <figcaption>Detection overlay (engine result)</figcaption>
                  </figure>
                </div>
              )}

              {detailTab === "anomalies" && (
                <div className="rc-anomaly">
                  {anomaly ? (
                    <>
                      <span className={`rc-chip rc-chip--${anomaly.is_anomaly ? "bad" : "ok"}`}>
                        {anomaly.is_anomaly ? "Flagged" : "No anomaly signals"} ·{" "}
                        {anomaly.severity || "—"} (score {anomaly.anomaly_score ?? "—"}/100)
                      </span>
                      <ul>
                        {(anomaly.reasons || []).map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <div className="rc-empty">
                      <p>
                        No anomaly assessment was computed for this sample. Run it from the
                        Anomalies page or ask the Copilot.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {detailTab === "audit" && (
                <div className="rc-audit">
                  {history.length === 0 ? (
                    <div className="rc-empty"><p>No review decisions recorded yet.</p></div>
                  ) : (
                    <ol>
                      {[...history].reverse().map((h, i) => (
                        <li key={i}>
                          <div className="rc-audit-line">
                            <strong>
                              {h.action === "cleared"
                                ? "Review cleared"
                                : `${h.previous_status || "—"} → ${h.new_status}`}
                            </strong>
                            <span>{h.reviewed_by} · {h.reviewed_at}</span>
                          </div>
                          {h.comment && <p>{h.comment}</p>}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )}

              {/* REVIEWER CONTROLS */}
              <div className="rc-decision">
                <div className="rc-decision-status">
                  <span>Current status</span>
                  <strong className={`rc-status rc-status--${bucketFor({ review })}`}>
                    {review ? `${review.status} · ${review.reviewed_by}` : statusLabel({ review: null, needsAttention: false })}
                  </strong>
                </div>
                <textarea
                  placeholder="Reviewer comment (recorded in the audit trail)…"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={2}
                />
                <div className="rc-decision-actions">
                  <button
                    type="button"
                    className="rc-btn rc-btn--ok"
                    disabled={actionBusy}
                    onClick={() => submitReview("approved")}
                  >
                    <span className="material-symbols-outlined">verified</span>
                    Approve
                  </button>
                  <button
                    type="button"
                    className="rc-btn rc-btn--warn"
                    disabled={actionBusy}
                    onClick={() => submitReview("changes_requested")}
                  >
                    <span className="material-symbols-outlined">rate_review</span>
                    Needs correction
                  </button>
                  <button
                    type="button"
                    className="rc-btn rc-btn--bad"
                    disabled={actionBusy}
                    onClick={() => submitReview("rejected")}
                  >
                    <span className="material-symbols-outlined">block</span>
                    Reject
                  </button>
                  {review && (
                    <button
                      type="button"
                      className="rc-btn rc-btn--ghost"
                      disabled={actionBusy}
                      onClick={clearReview}
                    >
                      <span className="material-symbols-outlined">undo</span>
                      Clear
                    </button>
                  )}
                </div>
                <div className="rc-decision-links">
                  <button type="button" onClick={openInCopilot}>
                    <span className="material-symbols-outlined">smart_toy</span>
                    Ask Copilot about this sample
                  </button>
                  <button type="button" onClick={() => navigate("/new-analysis")}>
                    <span className="material-symbols-outlined">add_box</span>
                    New Analysis
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      )}

      <Toast
        open={toast.open}
        tone="default"
        message={toast.message}
        onClose={() => setToast({ open: false, message: "" })}
      />
    </div>
  );
}

export default ReviewCenter;
