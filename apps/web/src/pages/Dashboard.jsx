import NodularityChart from '../components/charts/NodularityChart';
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import "./Dashboard.css";

/* Filenames arriving from the backend are content hashes (audit issues
   8/10): show a short comparable stem and keep the full name on hover. */
function shortFile(name) {
  if (!name) return "";
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  const stem = dot > 0 ? name.slice(0, dot) : name;
  return stem.length > 10 ? `${stem.slice(0, 8)}…${ext}` : name;
}

/* Bold the measured parameters inside warning copy (audit issue 5) so
   pixel widths / percentages scan out of the sentence. */
const PARAM_RE = /(\d+(?:\.\d+)?\s*(?:px|%|µm|um))/g;
function emphasizeParams(text) {
  return String(text)
    .split(PARAM_RE)
    .map((part, i) =>
      part && /\d/.test(part) ? <strong key={i}>{part}</strong> : part
    );
}

function Dashboard() {
  const navigate = useNavigate();
  const [range, setRange] = useState("30D");
  const [stats, setStats] = useState(null);
  const [analyses, setAnalyses] = useState([]);

  useEffect(() => {
    api.analysisStats().then(setStats).catch(() => {});
    api.analyses()
      .then((data) => setAnalyses(data.analyses || []))
      .catch(() => {});
  }, []);

  /* Percentages render at one consistent decimal (audit issue 12: the old
     72.9% / 17.46% mix read as sloppy and slowed scanning). */
  const fmtPct = (v, fallback = "—") =>
    v != null ? `${Number(v).toFixed(1)}%` : fallback;

  /* Audit issue 11: sortable Recent Analyses headers — every column sorts,
     the chevron shows the live direction and aria-sort carries it to AT. */
  const [sort, setSort] = useState({ key: "date", dir: "desc" });

  const sortValue = (a) => {
    switch (sort.key) {
      case "id": return a.id || "";
      case "source": return a.filename || a.title || "";
      case "nodularity":
        return typeof a.iso_nodularity_pct === "number" ? a.iso_nodularity_pct : -1;
      case "count":
        return typeof a.nodule_count === "number" ? a.nodule_count : -1;
      case "confidence":
        return typeof a.confidence_pct === "number" ? a.confidence_pct : -1;
      case "status":
        return a.status === "completed" &&
          !(typeof a.accuracy_pct === "number" && a.accuracy_pct < 95)
          ? 1 : 0;
      default:
        return a.created_at ? new Date(a.created_at).getTime() : 0;
    }
  };

  const recent = [...analyses.slice(0, 6)].sort((x, y) => {
    const vx = sortValue(x);
    const vy = sortValue(y);
    const cmp = typeof vx === "string" ? vx.localeCompare(vy) : vx - vy;
    return sort.dir === "asc" ? cmp : -cmp;
  });

  const toggleSort = (key) =>
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "desc" }
    );

  const sortTh = (key, label, num) => (
    <th
      className={num ? "num" : undefined}
      aria-sort={
        sort.key === key
          ? (sort.dir === "asc" ? "ascending" : "descending")
          : undefined
      }
    >
      <button type="button" className="th-sort" onClick={() => toggleSort(key)}>
        {label}
        <span
          className={`material-symbols-outlined sort-glyph${
            sort.key === key ? " on" : ""
          }`}
          aria-hidden="true"
        >
          {sort.key === key
            ? (sort.dir === "asc" ? "arrow_upward" : "arrow_downward")
            : "unfold_more"}
        </span>
      </button>
    </th>
  );

  const anomalies = analyses.filter(
    (a) =>
      (a.warnings || []).length > 0 ||
      (typeof a.accuracy_pct === "number" && a.accuracy_pct < 95),
  );

  /* Real trend data: completed analyses with a date + ISO nodularity,
     filtered by the selected range. The 7D/30D control is functional —
     when nothing falls in the range the chart shows its honest empty state. */
  const nodularityData = useMemo(() => {
    const days = range === "7D" ? 7 : 30;
    const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
    return analyses
      .filter((a) => {
        if (a.status !== "completed") return false;
        if (typeof a.iso_nodularity_pct !== "number") return false;
        if (!a.created_at) return false;
        const t = new Date(a.created_at).getTime();
        return Number.isFinite(t) && t >= cutoff;
      })
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
      .map((a) => ({
        label: new Date(a.created_at).toLocaleDateString([], {
          month: "short", day: "numeric",
        }),
        value: a.iso_nodularity_pct,
      }));
  }, [analyses, range]);

  /* Activity derived from real records — nothing invented. */
  const activity = useMemo(() => {
    const items = [];
    for (const a of analyses.slice(0, 8)) {
      const flagged =
        a.status !== "completed" ||
        (a.warnings || []).length > 0 ||
        (typeof a.accuracy_pct === "number" && a.accuracy_pct < 95);
      items.push({
        id: a.id,
        kind: flagged ? "anomaly" : "analysis",
        text: flagged
          ? "flagged for review."
          : "completed.",
        at: a.created_at,
      });
    }
    return items;
  }, [analyses]);

  /* Accepts either an analysis record (created_at) or an activity item (at). */
  const timeLabel = (a) => {
    const raw = a.created_at || a.at;
    if (!raw) return "—";
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString([], {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  };

  return (
    <main className="dashboard-page">
      {/* Dashboard Header */}
      <header className="dashboard-header">
        <div>
          <h1>NODIQ-X Dashboard</h1>
          <p>Microstructure intelligence at a glance.</p>
        </div>

        <button className="new-analysis-btn" onClick={() => navigate("/new-analysis")}>
          <span className="material-symbols-outlined">add</span>
          New Analysis
        </button>
      </header>

      {/* Dashboard Content */}
      <div className="dashboard-content">

        {/* Summary Metrics */}
        <section className="metrics-grid">

          <div className="metric-card">
            <span className="metric-label">Total analyses</span>
            <span className="metric-value">
              {stats ? stats.total_analyses : "0"}
            </span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Images processed</span>

            <div className="metric-value-row">
              <span className="metric-value">
                {stats ? stats.images_processed : "0"}
              </span>

              <span className="metric-success">
                <span className="material-symbols-outlined">
                  check_circle
                </span>
                LIVE
              </span>
            </div>
          </div>

          <div className="metric-card">
            <span className="metric-label">Avg nodularity</span>
            <span className="metric-value">
              {stats ? fmtPct(stats.avg_nodularity_pct, "—") : "—"}
            </span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Avg self-check accuracy</span>
            <span className="metric-value">
              {stats ? fmtPct(stats.avg_confidence_pct, "—") : "—"}
            </span>
          </div>

          <div className="metric-card anomaly-metric">
            <div className="metric-label-row">
              <span className="metric-label">Active anomalies</span>
              <span className="anomaly-dot"></span>
            </div>

            <div className="metric-value-row">
              <span className="metric-value error-text">{anomalies.length}</span>
              <span className="needs-review">Needs review</span>
            </div>
          </div>

        </section>

         {/* Nodularity trend — real completed analyses within the selected range */}
        <NodularityChart
          data={nodularityData}
          range={range}
          onRangeChange={setRange}
        />

        {/* Lower Dashboard Grid */}
        <section className="dashboard-lower-grid">

          {/* Recent Analyses */}
          <div className="dashboard-panel recent-analyses">

            <div className="panel-header">
              <h2>Recent Analyses</h2>

              <button className="view-all-btn" onClick={() => navigate("/analyses")}>
                View All
                <span className="material-symbols-outlined">
                  arrow_forward
                </span>
              </button>
            </div>

            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    {sortTh("id", "Sample ID")}
                    {sortTh("source", "Source")}
                    {sortTh("nodularity", "Nodularity", true)}
                    {sortTh("count", "Count", true)}
                    {sortTh("confidence", "Confidence", true)}
                    {sortTh("status", "Status")}
                    {sortTh("date", "Date")}
                  </tr>
                </thead>

                <tbody>

                  {recent.length === 0 && (
                    <tr>
                      <td colSpan={7} className="secondary-text" style={{ textAlign: "center", padding: "18px 0" }}>
                        No analyses yet — run one from New Analysis.
                      </td>
                    </tr>
                  )}

                  {recent.map((a) => {
                    const acc = a.accuracy_pct;
                    const needsReview =
                      a.status !== "completed" ||
                      (typeof acc === "number" && acc < 95);
                    return (
                      <tr key={a.id} className={needsReview ? "review-row" : undefined}>
                        <td className="sample-id">{a.id}</td>
                        <td
                          className="secondary-text"
                          title={a.filename || a.title || undefined}
                        >
                          {shortFile(a.filename || a.title) || "—"}
                        </td>
                        <td className="num">
                          {a.iso_nodularity_pct != null
                            ? fmtPct(a.iso_nodularity_pct, "N/A")
                            : "N/A"}
                        </td>
                        <td className="num">{a.nodule_count ?? "N/A"}</td>
                        <td
                          className={
                            typeof acc === "number" && acc < 95
                              ? "warning-text num"
                              : "num"
                          }
                        >
                          {fmtPct(a.confidence_pct, "—")}
                        </td>
                        <td>
                          <span className="status">
                            <span className={`status-dot ${needsReview ? "error" : "success"}`} />
                            {needsReview ? "Needs Review" : "Verified"}
                          </span>
                        </td>
                        <td className="secondary-text">{timeLabel(a)}</td>
                      </tr>
                    );
                  })}

                </tbody>
              </table>
            </div>

          </div>

          {/* Recent Activity */}
          <div className="dashboard-panel recent-activity">

            <div className="panel-header">
              <h2>Recent Activity</h2>
            </div>

            <div className="activity-list">

              {activity.length === 0 && (
                <div className="activity-item">
                  <div className="activity-icon">
                    <span className="material-symbols-outlined">hourglass_empty</span>
                  </div>
                  <div>
                    <p>No activity yet — completed analyses appear here.</p>
                  </div>
                </div>
              )}

              {activity.map((item) => (
                <div className="activity-item" key={item.id}>
                  <div className={`activity-icon ${item.kind === "anomaly" ? "red" : "orange"}`}>
                    <span className="material-symbols-outlined">
                      {item.kind === "anomaly" ? "warning" : "check_circle"}
                    </span>
                  </div>

                  <div>
                    <p>
                      Analysis <span className="sample-id">{item.id}</span>{" "}
                      {item.text}
                    </p>

                    <span className="secondary-text">{timeLabel(item)}</span>
                  </div>
                </div>
              ))}

            </div>

          </div>

          {/* Quick Actions */}
          <div className="dashboard-panel quick-actions">

            <div className="panel-header">
              <h2>Quick Actions</h2>
            </div>

            <div className="quick-actions-grid">

              <button onClick={() => navigate("/new-analysis")}>
                <span className="material-symbols-outlined">
                  layers
                </span>
                <span>Batch Analysis</span>
              </button>

              <button onClick={() => navigate("/analyses")}>
                <span className="material-symbols-outlined">
                  rate_review
                </span>
                <span>Review Center</span>
              </button>

              <button onClick={() => navigate("/gray-cast-iron")}>
                <span className="material-symbols-outlined">
                  blur_on
                </span>
                <span>Gray Cast Iron</span>
              </button>

              <button className="full-action" onClick={() => navigate("/reports/generate")}>
                <span className="material-symbols-outlined">
                  description
                </span>
                <span>Generate Report</span>
              </button>

            </div>

          </div>

          {/* Active Anomalies */}
          <div className="dashboard-panel active-anomalies">

            <div className="panel-header">
              <h2>
                <span className="material-symbols-outlined error-text">
                  warning
                </span>
                Active Anomalies
              </h2>

              <span className="anomaly-count">{anomalies.length}</span>
            </div>

            <div className="anomaly-list">

              {anomalies.length === 0 && (
                <div className="anomaly-card">
                  <p>No anomalies — all recent runs are clean.</p>
                </div>
              )}

              {anomalies.slice(0, 3).map((a) => (
                <div className="anomaly-card" key={a.id}>
                  <div className="anomaly-card-top">
                    <span className="sample-id">{a.id}</span>
                    <span className="severity medium">ADV</span>
                  </div>

                  <p>
                    {emphasizeParams(
                      (a.warnings || [])[0] || "Below 95% self-check accuracy",
                    )}
                  </p>

                  <span
                    className="secondary-text"
                    title={a.filename || undefined}
                  >
                    {a.filename ? shortFile(a.filename) : "upload"}
                  </span>
                </div>
              ))}

            </div>

          </div>

        </section>

      </div>
    </main>
  );
}

export default Dashboard;