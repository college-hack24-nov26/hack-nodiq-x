import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Toast from "../components/common/Toast";
import api from "../services/api";
import "./MyAnalyses.css";


const STATUS_LABELS = {
  completed: "COMPLETED",
  processing: "PROCESSING",
  failed: "FAILED",
};

function StatusBadge({ status }) {
  return (
    <span className={`my-analysis-status my-analysis-status--${status}`}>
      <span className="my-analysis-status__dot" />
      {STATUS_LABELS[status]}
    </span>
  );
}

function AnalysisPreview({ analysis }) {
  const [imageUrl, setImageUrl] = useState(null);
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setImageUrl(null);
    setImageFailed(false);
    if (analysis.status !== "completed" || !analysis.id) return undefined;
    api.fetchImage(`/api/analyses/${analysis.id}/image`)
      .then((url) => { if (alive) setImageUrl(url); })
      .catch(() => { if (alive) setImageFailed(true); });
    return () => { alive = false; };
  }, [analysis.id, analysis.status]);

  if (analysis.status === "processing") {
    return (
      <div className="my-analysis-preview my-analysis-preview--processing">
        <div className="preview-grid" />
        <span className="material-symbols-outlined preview-processing-icon">
          pending
        </span>
      </div>
    );
  }

  if (analysis.status === "failed") {
    return (
      <div className="my-analysis-preview my-analysis-preview--failed">
        <div className="preview-grid preview-grid--failed" />
        <span className="material-symbols-outlined preview-error-icon">
          error
        </span>
      </div>
    );
  }

  return (
    <div className="my-analysis-preview">
      {imageUrl ? (
        <img
          className="analysis-real-preview"
          src={imageUrl}
          alt={analysis.title}
          loading="lazy"
        />
      ) : (
        <div className="microstructure-preview">
          {!imageFailed && Array.from({ length: 32 }).map((_, index) => (
            <span
              key={index}
              className="microstructure-particle"
              style={{
                "--x": `${(index * 37) % 94}%`,
                "--y": `${(index * 61) % 82}%`,
                "--size": `${5 + ((index * 13) % 12)}px`,
              }}
            />
          ))}
        </div>
      )}

      <div className="preview-scan-line" />
      <span className="preview-corner preview-corner--tl" />
      <span className="preview-corner preview-corner--tr" />
      <span className="preview-corner preview-corner--bl" />
      <span className="preview-corner preview-corner--br" />
    </div>
  );
}

function MyAnalyses() {
  const navigate = useNavigate();

  const [analyses, setAnalyses] = useState([]);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState("all");
  const [sortOrder, setSortOrder] = useState("recent");
  const [openMenu, setOpenMenu] = useState(null);
  const [selectedAnalysis, setSelectedAnalysis] = useState(null);
  const [toast, setToast] = useState({ open: false, message: "" });

  useEffect(() => {
    api.analyses()
      .then((data) => {
        const records = (data.analyses || []).map((a) => ({
          ...a,
          time: a.created_at
            ? new Date(a.created_at).toLocaleString([], {
                month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
              })
            : "just now",
          images: a.filename ? `1 image (${a.filename})` : "1 image",
          anomalies: `${(a.warnings || []).length || 0} advisories`,
          confidence: a.confidence_pct != null ? `${a.confidence_pct}%` : "—",
          nodularity:
            a.iso_nodularity_pct != null ? `${a.iso_nodularity_pct}%` : "—",
          graphiteCount: a.nodule_count != null ? String(a.nodule_count) : "—",
          matrix: "Ductile Iron (polished)",
          // async analyses carry live server progress (5→100); legacy rows
          // without a progress field are completed by definition
          progress: a.progress ?? 100,
        }));
        setAnalyses(records);
      })
      .catch(() => setAnalyses([]));
  }, []);

  const filteredAnalyses = useMemo(() => {
    let result = [...analyses];

    if (search.trim()) {
      const query = search.toLowerCase();

      result = result.filter(
        (analysis) =>
          analysis.id.toLowerCase().includes(query) ||
          analysis.title.toLowerCase().includes(query) ||
          analysis.type.toLowerCase().includes(query),
      );
    }

    if (typeFilter !== "all") {
      result = result.filter((analysis) => analysis.type === typeFilter);
    }

    if (statusFilter !== "all") {
      result = result.filter((analysis) => analysis.status === statusFilter);
    }

    if (sortOrder === "name") {
      result.sort((a, b) => a.title.localeCompare(b.title));
    }

    if (sortOrder === "status") {
      result.sort((a, b) => a.status.localeCompare(b.status));
    }

    return result;
  }, [analyses, search, typeFilter, statusFilter, sortOrder]);

  const completedCount = analyses.filter(
    (analysis) => analysis.status === "completed",
  ).length;

  const processingCount = analyses.filter(
    (analysis) => analysis.status === "processing",
  ).length;

  const failedCount = analyses.filter(
    (analysis) => analysis.status === "failed",
  ).length;

  const handleRetry = () => {
    setToast({
      open: true,
      message:
        "Retry queues a fresh run — upload the same image on the New Analysis page for a full re-analysis.",
    });

    setOpenMenu(null);
  };

  const handleDelete = (analysis) => {
    api.deleteAnalysis(analysis.id)
      .catch(() => {})
      .finally(() => {
        setAnalyses((current) =>
          current.filter((item) => item.id !== analysis.id),
        );
      });

    setOpenMenu(null);
  };


  return (
    <div className="my-analyses-page">
      <div className="my-analyses-container">
        {/* PAGE HEADER */}
        <header className="my-analyses-header">
          <div>
            <span className="my-analyses-eyebrow">ANALYSIS HISTORY</span>

            <h1>My Analyses</h1>

            <p>
              View, manage and revisit all your metallographic AI analyses.
            </p>
          </div>

          <button
            type="button"
            className="my-analyses-new-button"
            onClick={() => navigate("/new-analysis")}
          >
            <span className="material-symbols-outlined">add</span>
            New Analysis
          </button>
        </header>

        {/* SUMMARY CARDS */}
        <section className="my-analyses-summary">
          <div className="summary-card summary-card--primary">
            <span>Total Analyses</span>
            <strong>{analyses.length}</strong>
          </div>

          <div className="summary-card summary-card--success">
            <span>Completed</span>
            <strong>{completedCount}</strong>
          </div>

          <div className="summary-card summary-card--processing">
            <span>Processing</span>
            <strong>{processingCount}</strong>
          </div>

          <div className="summary-card summary-card--error">
            <span>Issues Found</span>
            <strong>{failedCount}</strong>
          </div>
        </section>

        {/* TOOLBAR */}
        <section className="my-analyses-toolbar">
          <div className="my-analyses-search">
            <span className="material-symbols-outlined">search</span>

            <input
              type="text"
              placeholder="Search analyses..."
              aria-label="Search analyses"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>

          <div className="my-analyses-filters">
            <select
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
            >
              <option value="all">Type: All</option>
              <option value="Nodularity Analysis">
                Nodularity Analysis
              </option>
              <option value="Morphology Analysis">
                Morphology Analysis
              </option>
              <option value="Microstructure Analysis">
                Microstructure Analysis
              </option>
              <option value="Validation Analysis">
                Validation Analysis
              </option>
            </select>

            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="all">Status: All</option>
              <option value="completed">Completed</option>
              <option value="processing">Processing</option>
              <option value="failed">Failed</option>
            </select>

            <select
              value={dateFilter}
              onChange={(event) => setDateFilter(event.target.value)}
            >
              <option value="all">Date: All Time</option>
              <option value="7">Last 7 Days</option>
              <option value="30">Last 30 Days</option>
            </select>

            <button
              type="button"
              className="sort-button"
              onClick={() =>
                setSortOrder((current) =>
                  current === "recent" ? "name" : "recent",
                )
              }
            >
              <span className="material-symbols-outlined">sort</span>
              Sort: {sortOrder === "recent" ? "Recent" : "Name"}
            </button>
          </div>
        </section>

        {/* ANALYSIS LIST */}
        <section className="my-analyses-list">
          {filteredAnalyses.length === 0 ? (
            <div className="my-analyses-empty">
              <span className="material-symbols-outlined">search_off</span>
              <h3>No analyses found</h3>
              <p>Try changing your search or filters.</p>
            </div>
          ) : (
            filteredAnalyses.map((analysis) => (
              <article
                className={`analysis-history-card analysis-history-card--${analysis.status}`}
                key={analysis.id}
              >
                {analysis.status === "processing" && (
                  <div
                    className="processing-progress"
                    style={{ width: `${analysis.progress}%` }}
                  />
                )}

                <AnalysisPreview analysis={analysis} />

                <div className="analysis-history-content">
                  <div className="analysis-history-meta">
                    <StatusBadge status={analysis.status} />

                    <span className="analysis-history-time">
                      {analysis.time}
                    </span>
                  </div>

                  <h2>{analysis.title}</h2>

                  <p className="analysis-history-type">{analysis.type}</p>

                  {analysis.status === "processing" ? (
                    <div className="processing-info">
                      <div className="processing-track">
                        <span
                          style={{
                            width: `${analysis.progress}%`,
                          }}
                        />
                      </div>

                      <span>{analysis.progress}%</span>
                    </div>
                  ) : analysis.status === "failed" ? (
                    <div className="analysis-error">
                      <span className="material-symbols-outlined">
                        warning
                      </span>

                      <span>{analysis.error}</span>
                    </div>
                  ) : (
                    <div className="analysis-data">
                      <span>{analysis.images}</span>

                      <i />

                      <span className="analysis-data-danger">
                        {analysis.anomalies}
                      </span>

                      <i />

                      <span>{analysis.confidence} Confidence</span>
                    </div>
                  )}
                </div>

                <div className="analysis-history-actions">
                  <button
                    type="button"
                    className={`analysis-action-button ${
                      analysis.status === "failed"
                        ? "analysis-action-button--error"
                        : analysis.status === "completed"
                          ? "analysis-action-button--primary"
                          : ""
                    }`}
                    onClick={() =>
                      analysis.status === "failed"
                        ? handleRetry(analysis)
                        : setSelectedAnalysis(analysis)
                    }
                  >
                    {analysis.status === "processing"
                      ? "View Progress"
                      : analysis.status === "failed"
                        ? "Retry Analysis"
                        : "View Analysis"}
                  </button>

                  <div className="analysis-menu-wrapper">
                    <button
                      type="button"
                      className="analysis-menu-button"
                      onClick={() =>
                        setOpenMenu((current) =>
                          current === analysis.id ? null : analysis.id,
                        )
                      }
                      aria-label={`More options for ${analysis.title}`}
                    >
                      <span className="material-symbols-outlined">
                        more_vert
                      </span>
                    </button>

                    {openMenu === analysis.id && (
                      <div className="analysis-context-menu">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedAnalysis(analysis);
                            setOpenMenu(null);
                          }}
                        >
                          <span className="material-symbols-outlined">
                            visibility
                          </span>
                          View Details
                        </button>

                        <button
                          type="button"
                          onClick={() => handleDelete(analysis)}
                          className="context-menu-danger"
                        >
                          <span className="material-symbols-outlined">
                            delete
                          </span>
                          Delete Analysis
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </article>
            ))
          )}
        </section>
      </div>

      {/* DETAILS MODAL */}
      {selectedAnalysis && (
        <div
          className="analysis-detail-overlay"
          onClick={() => setSelectedAnalysis(null)}
        >
          <div
            className="analysis-detail-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="analysis-detail-header">
              <div>
                <span className="my-analyses-eyebrow">
                  ANALYSIS {selectedAnalysis.id}
                </span>
                <h2>{selectedAnalysis.title}</h2>
              </div>

              <button
                type="button"
                onClick={() => setSelectedAnalysis(null)}
                className="analysis-detail-close"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            <div className="analysis-detail-grid">
              <div>
                <span>Status</span>
                <StatusBadge status={selectedAnalysis.status} />
              </div>

              <div>
                <span>Analysis Type</span>
                <strong>{selectedAnalysis.type}</strong>
              </div>

              <div>
                <span>Nodularity</span>
                <strong>{selectedAnalysis.nodularity}</strong>
              </div>

              <div>
                <span>Graphite Nodules</span>
                <strong>{selectedAnalysis.graphiteCount}</strong>
              </div>

              <div>
                <span>Matrix</span>
                <strong>{selectedAnalysis.matrix}</strong>
              </div>

              <div>
                <span>Confidence</span>
                <strong>{selectedAnalysis.confidence || "—"}</strong>
              </div>
            </div>

            <div className="analysis-detail-actions">
              <button
                type="button"
                className="analysis-detail-primary"
                onClick={async () => {
                  // open the existing report for this analysis, or jump into
                  // the generator with this analysis preselected
                  try {
                    const data = await api.reports();
                    const match = (data.reports || []).find(
                      (r) => r.analysis_id === selectedAnalysis.id,
                    );
                    navigate(match ? `/reports/${match.id}` : "/reports/generate", {
                      state: match ? undefined : { analysisId: selectedAnalysis.id },
                    });
                  } catch {
                    navigate("/reports/generate", {
                      state: { analysisId: selectedAnalysis.id },
                    });
                  }
                }}
              >
                <span className="material-symbols-outlined">description</span>
                View Report
              </button>

              <button
                type="button"
                className="analysis-detail-secondary"
                onClick={() => navigate("/copilot")}
              >
                <span className="material-symbols-outlined">smart_toy</span>
                Ask NODIQ Copilot
              </button>
            </div>
          </div>
        </div>
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

export default MyAnalyses;