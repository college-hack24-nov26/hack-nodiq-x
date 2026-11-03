import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { sharePdfFile, saveBlob } from '../utils/shareReport';
import './Reports.css';

const formatDateTime = (date) => {
  return new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
};

const REPORTS_PAGE_SIZE = 8;

/* Server records use snake_case (analysis_id, created_at); older UI code
   expects camelCase. Normalize once at load so filters/sorting keep working. */
const normalizeReport = (r) => ({
  ...r,
  analysisId: r.analysis_id || r.analysisId || '—',
  createdAt: r.created_at ? new Date(r.created_at) : r.createdAt || new Date(),
});

function StatusBadge({ status }) {
  const statusClass = status.toLowerCase();

  return (
    <div className={`report-status status-${statusClass}`}>
      {status === 'Generating' && <span className="status-shimmer" />}
      {status !== 'Generating' && <span className="status-dot" />}
      <span>{status}</span>
    </div>
  );
}

function Reports() {
  const navigate = useNavigate();

  const [reports, setReports] = useState([]);
  const [page, setPage] = useState(0);
  const [dateDesc, setDateDesc] = useState(true);

  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [notice, setNotice] = useState(null);

  // Report loading
  useEffect(() => {
    api.reports()
      .then((data) => setReports((data.reports || []).map(normalizeReport)))
      .catch(() => setReports([]));

  }, []);

  const reportCounts = useMemo(() => {
    return {
      total: reports.length,
      ready: reports.filter((report) => report.status === 'Ready').length,
      drafts: reports.filter((report) => report.status === 'Draft').length,
      archived: reports.filter((report) => report.status === 'Archived').length,
    };
  }, [reports]);

  const filteredReports = useMemo(() => {
    const result = reports.filter((report) => {
      const matchesSearch =
        report.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        report.analysisId.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesType =
        typeFilter === 'All' || report.type === typeFilter;

      const matchesStatus =
        statusFilter === 'All' || report.status === statusFilter;

      return matchesSearch && matchesType && matchesStatus;
    });

    return result.sort((a, b) => {
      const ta = new Date(a.created_at || a.createdAt || 0).getTime();
      const tb = new Date(b.created_at || b.createdAt || 0).getTime();
      return dateDesc ? tb - ta : ta - tb;
    });
  }, [reports, searchQuery, typeFilter, statusFilter, dateDesc]);

  const pagedReports = useMemo(() => {
    const start = page * REPORTS_PAGE_SIZE;
    return filteredReports.slice(start, start + REPORTS_PAGE_SIZE);
  }, [filteredReports, page]);

  const pageCount = Math.max(1, Math.ceil(filteredReports.length / REPORTS_PAGE_SIZE));

  useEffect(() => {
    setPage(0);
  }, [searchQuery, typeFilter, statusFilter]);

  const handleRetry = (id) => {
    setReports((previousReports) =>
      previousReports.map((report) =>
        report.id === id
          ? { ...report, status: 'Generating' }
          : report
      )
    );

    // Re-generate server-side from the linked analysis, keeping the
    // report's original type (defaults to technical for legacy reports).
    api.generateReport({
      analysis_id: report.analysisId,
      report_type: report.report_type || 'technical',
      title: report.title,
      sample_id: report.sample_id,
    })
      .then((newReport) => {
        setReports((previousReports) =>
          previousReports.map((report) =>
            report.id === id
              ? {
                  ...report,
                  status: 'Ready',
                  createdAt: new Date(newReport.created_at || Date.now()),
                  metrics: newReport.metrics,
                  summary: newReport.summary,
                }
              : report
          )
        );
      })
      .catch(() => {
        setReports((previousReports) =>
          previousReports.map((report) =>
            report.id === id ? { ...report, status: 'Failed' } : report
          )
        );
      });
  };

  const handleCancelGeneration = (id) => {
    setReports((previousReports) =>
      previousReports.map((report) =>
        report.id === id
          ? { ...report, status: 'Draft' }
          : report
      )
    );
  };

  /* Real PDF from the deterministic report engine (report_builder.to_pdf). */
  const pdfFilename = (report) =>
    `${report.id}-${(report.title || 'report').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.pdf`;

  const handleDownload = (report) => {
    api.downloadReport(report.id, 'pdf')
      .then((blob) => {
        saveBlob(blob, pdfFilename(report));
        setNotice({ tone: 'ok', text: `PDF downloaded (${report.id}).` });
      })
      .catch((e) =>
        setNotice({ tone: 'error', text: e.message || 'PDF download failed.' }));
  };

  const handleShare = (report) => {
    api.downloadReport(report.id, 'pdf')
      .then((blob) => sharePdfFile(
        blob,
        pdfFilename(report),
        'NODIQ-X Analysis Report',
        `NODIQ-X analysis report ${report.id} — ${report.title || ''}`.trim(),
      ))
      .then((result) => {
        setNotice(result.method === 'share'
          ? { tone: 'ok', text: `Report ${report.id} shared successfully.` }
          : {
              tone: 'ok',
              text: `Sharing is not available in this browser — ${report.id} was downloaded instead (attach the PDF from Downloads).`,
            });
      })
      .catch((e) => {
        if (e?.message !== 'SHARE_CANCELLED') {
          setNotice({ tone: 'error', text: e.message || 'Share failed.' });
        }
      });
  };

  const handleMore = (report) => {
    const action = window.confirm(
      `${report.title}\n\nOK = Delete report, Cancel = Keep`
    );
    if (action) {
      api.deleteReport(report.id)
        .then(() =>
          setReports((previousReports) =>
            previousReports.filter((r) => r.id !== report.id)
          )
        )
        .catch(() => {});
    }
  };

  return (
    <div className="reports-page">
      {/* Page Header */}
      <section className="reports-header">
        <div>
          <div className="reports-eyebrow">
            REPORT MANAGEMENT
          </div>

          <h1>REPORTS</h1>

          <p>
            Generated reports and technical documentation from your analyses.
          </p>
        </div>

        <button
          className="generate-report-btn"
          onClick={() => navigate('/reports/generate')}
        >
          <span className="material-symbols-outlined">add</span>
          Generate Report
        </button>
      </section>

      {/* Share/download feedback — honest success/error only */}
      {notice && (
        <div
          className={`reports-notice ${notice.tone === 'error' ? 'reports-notice--error' : ''}`}
          role="status"
        >
          <span className="material-symbols-outlined">
            {notice.tone === 'error' ? 'error' : 'check_circle'}
          </span>
          <span>{notice.text}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setNotice(null)}
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
      )}

      {/* Summary Cards */}
      <section className="report-summary-grid">
        <div className="report-summary-card">
          <span>Total Reports</span>
          <strong>{reportCounts.total}</strong>
        </div>

        <div className="report-summary-card">
          <span>Ready</span>

          <div className="summary-value-row">
            <span className="summary-dot ready" />
            <strong>{reportCounts.ready}</strong>
          </div>
        </div>

        <div className="report-summary-card">
          <span>Drafts</span>

          <div className="summary-value-row">
            <span className="summary-dot draft" />
            <strong>{reportCounts.drafts}</strong>
          </div>
        </div>

        <div className="report-summary-card">
          <span>Archived</span>

          <div className="summary-value-row">
            <span className="summary-dot archived" />
            <strong>{reportCounts.archived}</strong>
          </div>
        </div>
      </section>

      {/* Reports List */}
      <section className="reports-container">
        {/* Toolbar */}
        <div className="reports-toolbar">
          <div className="reports-search">
            <span className="material-symbols-outlined">
              search
            </span>

            <input
              type="text"
              placeholder="Search reports..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>

          <div className="reports-filters">
            <select
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
            >
              <option value="All">Report Type</option>
              <option value="Standard">Standard</option>
              <option value="Technical">Technical</option>
              <option value="Validation">Validation</option>
            </select>

            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="All">Status</option>
              <option value="Ready">Ready</option>
              <option value="Generating">Generating</option>
              <option value="Draft">Draft</option>
              <option value="Failed">Failed</option>
            </select>

            <button
              className="date-filter-btn"
              title="Toggle newest / oldest first"
              onClick={() => setDateDesc((v) => !v)}
            >
              <span className="material-symbols-outlined">
                calendar_today
              </span>
              {dateDesc ? 'Newest' : 'Oldest'}
            </button>
          </div>
        </div>

        {/* Desktop Table Header */}
        <div className="reports-table-header">
          <span>Report Title</span>
          <span>Analysis ID</span>
          <span>Type</span>
          <span>Creation Date</span>
          <span>Status / Actions</span>
        </div>

        {/* Reports */}
        <div className="reports-list">
          {filteredReports.length === 0 ? (
            <div className="reports-empty">
              <span className="material-symbols-outlined">
                description
              </span>

              <h3>No reports found</h3>

              <p>
                Try changing your search or filter settings.
              </p>
            </div>
          ) : (
            pagedReports.map((report) => (
              <div
                className="report-row"
                key={report.id}
              >
                <div className="report-title">
                  <span>{report.title}</span>
                </div>

                <div className="report-field">
                  <span className="mobile-label">
                    Analysis ID
                  </span>

                  <span className="technical-text">
                    {report.analysisId}
                  </span>
                </div>

                <div className="report-field">
                  <span className="mobile-label">
                    Type
                  </span>

                  <span>{report.type}</span>
                </div>

                <div className="report-field">
                  <span className="mobile-label">
                    Date
                  </span>

                  <span className="technical-text">
                    {formatDateTime(report.createdAt)}
                  </span>
                </div>

                <div className="report-actions">
                  <StatusBadge status={report.status} />

                  <div className="action-buttons">
                    {report.status === 'Ready' && (
                      <>
                        <button
                          title="View"
                          onClick={() =>
                            navigate(`/reports/${report.id}`)
                          }
                        >
                          <span className="material-symbols-outlined">
                            visibility
                          </span>
                        </button>

                        <button
                          title="Download PDF"
                          onClick={() => handleDownload(report)}
                        >
                          <span className="material-symbols-outlined">
                            download
                          </span>
                        </button>

                        <button
                          title="Share PDF"
                          onClick={() => handleShare(report)}
                        >
                          <span className="material-symbols-outlined">
                            share
                          </span>
                        </button>

                        <button
                          title="More"
                          onClick={() => handleMore(report)}
                        >
                          <span className="material-symbols-outlined">
                            more_vert
                          </span>
                        </button>
                      </>
                    )}

                    {report.status === 'Generating' && (
                      <>
                        <button
                          title="Cancel"
                          onClick={() =>
                            handleCancelGeneration(report.id)
                          }
                        >
                          <span className="material-symbols-outlined">
                            close
                          </span>
                        </button>

                        <button
                          title="More"
                          onClick={() => handleMore(report)}
                        >
                          <span className="material-symbols-outlined">
                            more_vert
                          </span>
                        </button>
                      </>
                    )}

                    {report.status === 'Draft' && (
                      <>
                        <button
                          title="Edit"
                          onClick={() =>
                            navigate('/reports/generate')
                          }
                        >
                          <span className="material-symbols-outlined">
                            edit
                          </span>
                        </button>

                        <button
                          title="More"
                          onClick={() => handleMore(report)}
                        >
                          <span className="material-symbols-outlined">
                            more_vert
                          </span>
                        </button>
                      </>
                    )}

                    {report.status === 'Failed' && (
                      <>
                        <button
                          title="Retry"
                          onClick={() => handleRetry(report.id)}
                        >
                          <span className="material-symbols-outlined">
                            refresh
                          </span>
                        </button>

                        <button
                          title="More"
                          onClick={() => handleMore(report)}
                        >
                          <span className="material-symbols-outlined">
                            more_vert
                          </span>
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      {/* Pagination */}
      <div className="reports-pagination">
        <span>
          Showing {pagedReports.length} of {filteredReports.length} reports
        </span>

        <div className="pagination-buttons">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            &lt; Prev
          </button>

          <button
            disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            Next &gt;
          </button>
        </div>
      </div>
    </div>
  );
}

export default Reports;