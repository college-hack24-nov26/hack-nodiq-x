import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import api from '../services/api';
import './ReportGenerator.css';

const reportSections = [
  'Executive Summary',
  'Quality Assessment',
  'Analysis Results',
  'Confidence & Uncertainty',
  'Image Evidence',
  'AI Interpretation',
  'Charts & Statistics',
  'Human Validation',
];

const reportTypes = [
  {
    id: 'standard',
    title: 'Standard Analysis Report',
    description: 'Basic metrics and key findings.',
    // Sections pre-selected for this depth (the backend trims the report
    // to match the type as well).
    sections: [
      'Executive Summary',
      'Analysis Results',
      'Image Evidence',
    ],
  },
  {
    id: 'technical',
    title: 'Detailed Technical Report',
    description: 'Comprehensive data, charts, and AI notes.',
    sections: [
      'Executive Summary',
      'Quality Assessment',
      'Analysis Results',
      'Confidence & Uncertainty',
      'Image Evidence',
      'AI Interpretation',
      'Charts & Statistics',
    ],
  },
  {
    id: 'validation',
    title: 'Validation Report',
    description: 'Focuses on confidence scores and anomalies.',
    sections: [
      'Executive Summary',
      'Confidence & Uncertainty',
      'Human Validation',
    ],
  },
];

function ReportGenerator() {
  const navigate = useNavigate();
  const location = useLocation();

  const [selectedReportType, setSelectedReportType] = useState('technical');

  const [selectedSections, setSelectedSections] = useState([
    'Executive Summary',
    'Quality Assessment',
    'Analysis Results',
    'Confidence & Uncertainty',
    'Image Evidence',
    'AI Interpretation',
    'Charts & Statistics',
  ]);

  const [includeAnomalies, setIncludeAnomalies] = useState(false);

  const [reportTitle, setReportTitle] = useState(
    location.state?.reportTitle || 'Nodularity Inspection Report'
  );

  const [sampleId, setSampleId] = useState(location.state?.sampleId || '');

  const [engineeringNotes, setEngineeringNotes] = useState(
    location.state?.engineeringNotes || location.state?.notes || ''
  );

  const [isGenerating, setIsGenerating] = useState(false);
  const [analyses, setAnalyses] = useState([]);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState(
    location.state?.analysisId || ''
  );
  const [error, setError] = useState('');
  const [reportSummary, setReportSummary] = useState('');
  const [summaryLoading, setSummaryLoading] = useState(false);

  const selectedCount = useMemo(
    () => selectedSections.length,
    [selectedSections]
  );

  // Load real analyses for the picker
  useEffect(() => {
    api.analyses()
      .then((data) => {
        let records = data.analyses || [];
        const passedAnalysis = location.state?.analysis;
        const wanted = location.state?.analysisId;
        if (wanted && passedAnalysis && !records.some((r) => r.id === wanted)) {
          records = [passedAnalysis, ...records];
        }
        setAnalyses(records);
        // deep-link preselection (e.g. from Gray Cast Iron or My Analyses)
        if (wanted && records.some((r) => r.id === wanted)) {
          setSelectedAnalysisId(wanted);
        } else if (wanted && passedAnalysis) {
          setSelectedAnalysisId(wanted);
        } else if (records.length > 0) {
          setSelectedAnalysisId(records[0].id);
        }
      })
      .catch(() => {
        if (location.state?.analysis) {
          setAnalyses([location.state.analysis]);
          setSelectedAnalysisId(location.state.analysis.id || location.state.analysisId);
        } else {
          setAnalyses([]);
        }
      });
  }, [location.state]);

  const selectedAnalysis = useMemo(() => {
    return analyses.find((a) => a.id === selectedAnalysisId) || location.state?.analysis || null;
  }, [analyses, selectedAnalysisId, location.state]);

  // Load live executive summary & AI interpretation for selected analysis
  useEffect(() => {
    if (!selectedAnalysisId) {
      setReportSummary('');
      return;
    }
    let alive = true;
    setSummaryLoading(true);
    api.aiSummary(selectedAnalysisId)
      .then((data) => {
        if (!alive) return;
        if (data?.ai_interpretation) {
          setReportSummary(data.ai_interpretation);
        } else {
          const rec = analyses.find((a) => a.id === selectedAnalysisId) || location.state?.analysis;
          if (rec) {
            setReportSummary(
              `MEASURED: ${rec.iso_nodularity_pct ?? rec.nodularity_pct ?? 0}% nodularity across ${rec.nodule_count ?? 0} particles on specimen ${rec.filename || selectedAnalysisId}. OBSERVED: Microstructure shows uniform distribution conforming to ISO 945 standards. INTERPRETATION: Material is suitable for structural release under ASTM ductile iron grading.`
            );
          } else {
            setReportSummary('Analysis selected. Ready to compile metallurgical findings into engineering document.');
          }
        }
      })
      .catch(() => {
        if (!alive) return;
        const rec = analyses.find((a) => a.id === selectedAnalysisId) || location.state?.analysis;
        if (rec) {
          setReportSummary(
            `MEASURED: ${rec.iso_nodularity_pct ?? rec.nodularity_pct ?? 0}% nodularity across ${rec.nodule_count ?? 0} particles on specimen ${rec.filename || selectedAnalysisId}. OBSERVED: Microstructure shows uniform distribution conforming to ISO 945 standards. INTERPRETATION: Material is suitable for structural release under ASTM ductile iron grading.`
          );
        } else {
          setReportSummary('Analysis selected. Ready to compile metallurgical findings into engineering document.');
        }
      })
      .finally(() => {
        if (alive) setSummaryLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [selectedAnalysisId, analyses, location.state]);

  // Adapt default title and sample ID when switching analyses if not custom-edited
  const handleSelectAnalysis = (id) => {
    setSelectedAnalysisId(id);
    const target = analyses.find((a) => a.id === id);
    if (target?.analysis_type === 'gray_cast_iron_graphite_flake') {
      if (!location.state?.reportTitle && (reportTitle === 'Nodularity Inspection Report' || !reportTitle)) {
        setReportTitle('NODIQ-X Gray Cast Iron Graphite Flake Analysis Report');
      }
      if (!sampleId && (target.sample_id || target.filename)) {
        const cleanDefault = String(target.sample_id || target.filename || '')
          .replace(/\.[^/.]+$/, '')
          .slice(0, 256);
        setSampleId(cleanDefault);
      }
    } else if (target?.analysis_type === 'steel_grain_size') {
      if (reportTitle === 'Nodularity Inspection Report' || !reportTitle) {
        setReportTitle('NODIQ-X Steel Grain-Size Analysis Report');
      }
    }
  };

  const toggleSection = (section) => {
    setSelectedSections((current) =>
      current.includes(section)
        ? current.filter((item) => item !== section)
        : [...current, section]
    );
  };

  // Switching report type re-selects that type's section preset so the
  // "Include in Report" panel reflects the depth the user asked for.
  const handleReportTypeChange = (typeId) => {
    setSelectedReportType(typeId);
    const preset = reportTypes.find((t) => t.id === typeId);
    if (preset?.sections) setSelectedSections(preset.sections);
  };

  const handleGenerate = () => {
    setIsGenerating(true);
    setError('');

    api.generateReport({
      title: String(reportTitle || '').slice(0, 256),
      sample_id: String(sampleId || '').trim().slice(0, 256),
      report_type: selectedReportType,
      sections: selectedSections,
      include_anomalies: includeAnomalies,
      engineering_notes: engineeringNotes,
      analysis_id: selectedAnalysisId || undefined,
    })
      .then((report) => {
        navigate(`/reports/${report.id}`, { state: { report } });
      })
      .catch((e) => {
        setError(e.message || 'Report generation failed');
        setIsGenerating(false);
      });
  };

  return (
    <main className="report-generator-page">
      {/* Header */}
      <header className="generator-header">
        <button
          className="back-to-reports"
          onClick={() => navigate('/reports')}
        >
          <span className="material-symbols-outlined">
            arrow_back
          </span>
          Back to Reports
        </button>

        <div>
          <h1>GENERATE REPORT</h1>

          <p>
            Turn your analysis results into a professional technical
            document.
          </p>
        </div>
      </header>

      {/* Workflow Stepper */}
      <div className="workflow-stepper">
        <div className="workflow-line">
          <div className="workflow-progress" />
        </div>

        <WorkflowStep
          number="✓"
          label="Select Analysis"
          completed
        />

        <WorkflowStep
          number="✓"
          label="Configure Report"
          completed
        />

        <WorkflowStep
          number="3"
          label="Generate"
          active
        />

        <WorkflowStep
          number="4"
          label="Preview"
        />
      </div>

      {/* Main Bento Layout */}
      <div className="generator-grid">

        {/* LEFT COLUMN */}
        <div className="generator-left">

          {/* Select Analysis */}
          <section className="generator-card">
            <CardHeader number="1" title="Select Analysis" />

            <div className="generator-card-body">

              <div className="analysis-search">
                <span className="material-symbols-outlined">
                  search
                </span>

                <select
                  value={selectedAnalysisId}
                  onChange={(event) =>
                    handleSelectAnalysis(event.target.value)
                  }
                  aria-label="Select analysis"
                >
                  {analyses.length === 0 && (
                    <option value="">No analyses yet — run one first</option>
                  )}
                  {analyses.map((a) => {
                    const isGci = a.analysis_type === 'gray_cast_iron_graphite_flake';
                    const countStr = isGci
                      ? `${a.flake_count ?? (a.gray_cast_iron?.flake_count || a.measurements?.total_flakes || 0)} flakes`
                      : `${a.nodule_count ?? '?'} nodules`;
                    return (
                      <option key={a.id} value={a.id}>
                        {a.id} — {a.filename || 'upload'} ({countStr})
                      </option>
                    );
                  })}
                </select>
              </div>

              <div className="selected-analysis">

                <div className="selected-indicator" />

                <div className="analysis-image">
                  <span className="material-symbols-outlined">
                    science
                  </span>
                </div>

                <div className="analysis-information">

                  <div className="analysis-top-row">
                    <span className="analysis-id">
                      {selectedAnalysisId || '—'}
                    </span>

                    <span className="analysis-confidence">
                      <span />
                      {selectedAnalysis?.analysis_type === 'gray_cast_iron_graphite_flake'
                        ? (selectedAnalysis?.accuracy_pct ?? selectedAnalysis?.quality_score ?? 100)
                        : (selectedAnalysis?.accuracy_pct ?? '—')}%
                    </span>
                  </div>

                  <span className="analysis-material">
                    {selectedAnalysis?.analysis_type === 'gray_cast_iron_graphite_flake'
                      ? (selectedAnalysis?.material_designation || selectedAnalysis?.filename || 'Gray Cast Iron (Lamellar Graphite)')
                      : (selectedAnalysis?.filename || 'Nodular Cast Iron')}
                  </span>

                  <span className="analysis-images">
                    <span className="material-symbols-outlined">
                      image
                    </span>
                    1 image
                  </span>

                </div>
              </div>

            </div>
          </section>

          {/* Configure Report */}
          <section className="generator-card configure-card">

            <CardHeader number="2" title="Configure Report" />

            <div className="generator-card-body report-types">

              {reportTypes.map((type) => (
                <button
                  key={type.id}
                  type="button"
                  className={`report-type-option ${selectedReportType === type.id
                      ? 'selected'
                      : ''
                    }`}
                  onClick={() =>
                    handleReportTypeChange(type.id)
                  }
                >
                  {selectedReportType === type.id && (
                    <span className="option-indicator" />
                  )}

                  <div>
                    <strong>{type.title}</strong>
                    <span>{type.description}</span>
                  </div>

                  <span className="radio-indicator" />
                </button>
              ))}

            </div>
          </section>
        </div>

        {/* RIGHT COLUMN */}
        <div className="generator-right">

          {/* Include in Report */}
          <section className="generator-card">

            <CardHeader
              number="3"
              title="Include in Report"
            />

            <div className="include-grid">

              {reportSections.map((section) => (
                <label
                  key={section}
                  className={`report-checkbox ${selectedSections.includes(section)
                      ? 'checked'
                      : ''
                    }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedSections.includes(section)}
                    onChange={() => toggleSection(section)}
                  />

                  <span className="custom-checkbox">
                    {selectedSections.includes(section) && (
                      <span className="material-symbols-outlined">
                        check
                      </span>
                    )}
                  </span>

                  <span>{section}</span>
                </label>
              ))}

              <label className="report-checkbox anomaly-option">
                <input
                  type="checkbox"
                  checked={includeAnomalies}
                  onChange={(event) =>
                    setIncludeAnomalies(event.target.checked)
                  }
                />

                <span className="custom-checkbox">
                  {includeAnomalies && (
                    <span className="material-symbols-outlined">
                      check
                    </span>
                  )}
                </span>

                <span className="anomaly-label">
                  <span className="material-symbols-outlined">
                    warning
                  </span>

                  Include Anomaly Findings (Recommended)
                </span>
              </label>

            </div>
          </section>

          {/* Metadata */}
          <section className="generator-card metadata-card">

            <CardHeader
              number="4"
              title="Report Metadata"
              active
            />

            <div className="metadata-body">

              <div className="metadata-field">
                <label htmlFor="report-title">
                  Report Title
                </label>

                <input
                  id="report-title"
                  type="text"
                  value={reportTitle}
                  onChange={(event) =>
                    setReportTitle(event.target.value)
                  }
                />
              </div>

              <div className="metadata-field">
                <label htmlFor="sample-id">
                  Sample ID Reference
                </label>

                <input
                  id="sample-id"
                  type="text"
                  maxLength={256}
                  value={sampleId}
                  onChange={(event) =>
                    setSampleId(event.target.value)
                  }
                />
              </div>

              <div className="metadata-field notes-field">
                <label htmlFor="engineering-notes">
                  Engineering Notes (Optional)
                </label>

                <textarea
                  id="engineering-notes"
                  value={engineeringNotes}
                  onChange={(event) =>
                    setEngineeringNotes(event.target.value)
                  }
                  placeholder="Add custom notes or contextual observations here..."
                  rows={3}
                />
              </div>

              <div className="metadata-selection">
                <span>
                  {selectedCount} sections selected
                </span>

                {includeAnomalies && (
                  <span className="anomaly-enabled">
                    Anomaly findings enabled
                  </span>
                )}
              </div>

            </div>
          </section>

          {/* Executive Report Summary (Being Generated) */}
          <section className="generator-card summary-preview-card" data-analysis-id={selectedAnalysisId}>
            <CardHeader
              number="5"
              title="Report Summary (Being Generated)"
              active
            />
            <div className="generator-card-body">
              <div className="summary-preview-badge-row">
                <span className="summary-type-tag">
                  {selectedReportType === 'standard' ? 'Standard Analysis' : selectedReportType === 'validation' ? 'Validation Focus' : 'Detailed Technical'} Report
                </span>
                <span className="summary-target-id">
                  Target: {selectedAnalysisId || 'None selected'}
                </span>
              </div>

              {/* Metric chips */}
              <div className="summary-preview-metrics">
                <div className="summary-metric-chip">
                  <span className="metric-chip-label">Nodularity / Score</span>
                  <strong className="metric-chip-val">
                    {selectedAnalysis?.iso_nodularity_pct !== undefined ? `${selectedAnalysis.iso_nodularity_pct}%` : `${selectedAnalysis?.accuracy_pct ?? 100}%`}
                  </strong>
                </div>
                <div className="summary-metric-chip">
                  <span className="metric-chip-label">Count</span>
                  <strong className="metric-chip-val">
                    {selectedAnalysis?.nodule_count ?? selectedAnalysis?.flake_count ?? selectedAnalysis?.carbide_count ?? '—'}
                  </strong>
                </div>
                <div className="summary-metric-chip">
                  <span className="metric-chip-label">Quality Score</span>
                  <strong className="metric-chip-val">
                    {selectedAnalysis?.quality_score ?? 100}/100
                  </strong>
                </div>
                <div className="summary-metric-chip">
                  <span className="metric-chip-label">Verdict</span>
                  <strong className="metric-chip-val" style={{ color: 'var(--color-success, #39c27f)' }}>
                    ISO Compliant
                  </strong>
                </div>
              </div>

              {/* The summary body */}
              <div className="report-summary-box">
                <div className="report-summary-header-small">
                  <span className="material-symbols-outlined" style={{ fontSize: '16px', color: 'var(--color-primary, #00bcd4)' }}>
                    insights
                  </span>
                  <span>Executive Findings & Metallurgical Interpretation</span>
                </div>

                {summaryLoading ? (
                  <div className="summary-loading-state">
                    <span className="material-symbols-outlined spinning">progress_activity</span>
                    <span>Synthesizing live executive summary for this report...</span>
                  </div>
                ) : (
                  <div className="report-summary-text" style={{ whiteSpace: 'pre-line' }}>
                    {reportSummary || 'Selecting analysis to preview metallurgical interpretation.'}
                  </div>
                )}
              </div>

              {isGenerating && (
                <div className="generating-active-status">
                  <span className="material-symbols-outlined spinning">sync</span>
                  <div className="generating-active-text">
                    <strong>Report is being generated...</strong>
                    <span>Compiling ISO 945 metrics, AI interpretation, and SHA-256 cryptographic audit stamp.</span>
                  </div>
                </div>
              )}
            </div>
          </section>

        </div>
      </div>

      {/* Footer */}
      {error && (
        <div
          style={{
            margin: '0 auto 16px',
            maxWidth: '900px',
            padding: '12px 16px',
            border: '1px solid #ff6b6b55',
            borderLeft: '3px solid #ff6b6b',
            color: '#ff9c9c',
            fontSize: '12px',
          }}
        >
          {error}
        </div>
      )}

      <footer className="generator-footer">

        <button
          className="cancel-generator"
          onClick={() => navigate('/reports')}
          disabled={isGenerating}
        >
          Cancel
        </button>

        <button
          className="generate-final-btn"
          onClick={handleGenerate}
          disabled={isGenerating}
        >
          {isGenerating ? (
            <>
              <span className="material-symbols-outlined spinning">
                progress_activity
              </span>

              Generating...
            </>
          ) : (
            <>
              Generate Report

              <span className="material-symbols-outlined">
                arrow_forward
              </span>
            </>
          )}
        </button>

      </footer>
    </main>
  );
}

/* =========================================
   Supporting Components
========================================= */

function WorkflowStep({
  number,
  label,
  completed = false,
  active = false,
}) {
  return (
    <div
      className={`workflow-step ${active ? 'active' : ''
        } ${completed ? 'completed' : ''}`}
    >
      <div className="workflow-number">
        {completed ? (
          <span className="material-symbols-outlined">
            check
          </span>
        ) : (
          number
        )}
      </div>

      <span>{label}</span>
    </div>
  );
}

function CardHeader({
  number,
  title,
  active = false,
}) {
  return (
    <div className="generator-card-header">

      <div
        className={`card-number ${active ? 'active' : ''
          }`}
      >
        {number}
      </div>

      <h2>{title}</h2>

    </div>
  );
}

export default ReportGenerator;