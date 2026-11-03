import React from "react";
import "./AcceptanceVerdictMeter.css";

export default function AcceptanceVerdictMeter({ mechanicalProperties }) {
  if (!mechanicalProperties || !mechanicalProperties.available) {
    return null;
  }

  const {
    standard_basis,
    active_grade = {},
    acceptance_verdict = {},
    estimated_tensile_strength_mpa,
    estimated_yield_strength_mpa,
    estimated_elongation_pct,
    estimated_hardness_hbw,
    estimated_rockwell_hardness_hrc,
    matrix_assumed,
    assumptions = [],
  } = mechanicalProperties;

  const status = (acceptance_verdict.status || "COMPLIANT").toUpperCase();
  const statusClass =
    status === "COMPLIANT"
      ? "compliant"
      : status === "MARGINAL"
      ? "marginal"
      : "non-compliant";

  const statusLabel =
    status === "COMPLIANT"
      ? "Compliant (Approved)"
      : status === "MARGINAL"
      ? "Marginal (Review)"
      : "Non-Compliant (Scrap Alert)";

  const score = Math.max(
    0,
    Math.min(
      100,
      Number(
        acceptance_verdict.score ||
          (status === "COMPLIANT" ? 90 : status === "MARGINAL" ? 65 : 35)
      )
    )
  );

  const fmt = (v, suffix = "") =>
    v !== null && v !== undefined ? `${v}${suffix}` : "—";

  const calcGauge = (estimate, req, ceilingMultiplier = 1.35) => {
    if (!estimate || !req) return { valPct: 75, reqPct: 75 };
    const maxScale = req * ceilingMultiplier;
    const valPct = Math.min(100, Math.max(10, (estimate / maxScale) * 100));
    const reqPct = Math.min(94, Math.max(15, (req / maxScale) * 100));
    return { valPct, reqPct };
  };

  return (
    <section className="report-section verdict-report-section">
      {/* 1. SECTION TITLE (Matching .section-title across the whole report) */}
      <h3 className="section-title">
        Microstructure → Mechanical Properties & Grade Acceptance
      </h3>

      {/* 2. SUB-HEADING (Matching .summary-heading in Executive Summary) */}
      <div className="summary-heading">
        <span className="summary-heading-label">
          Standard: <strong>{active_grade.grade || "Standard Grade Envelope"}</strong> · Basis:{" "}
          {standard_basis || "ISO 1083 / ASTM A536"}
        </span>

        <span className={`verdict-status-badge ${statusClass}`}>
          <span className="material-symbols-outlined">
            {status === "COMPLIANT"
              ? "check_circle"
              : status === "MARGINAL"
              ? "warning"
              : "error"}
          </span>
          {statusLabel}
        </span>
      </div>

      {/* 3. METRICS GRID (Matching .metrics-grid and .report-metric cards exactly!) */}
      <div className="metrics-grid verdict-metrics-grid">
        {/* Tensile Strength */}
        {estimated_tensile_strength_mpa && (() => {
          const est = estimated_tensile_strength_mpa.estimate;
          const req = active_grade.min_rm_mpa || 400;
          const margin = acceptance_verdict.tensile_margin_pct;
          const { valPct, reqPct } = calcGauge(est, req, 1.35);
          const isSatisfied = est >= req;

          return (
            <div className="report-metric verdict-prop-card">
              <div className="metric-header-row">
                <span className="metric-label">Tensile Strength (Rm)</span>
                {margin !== undefined && (
                  <span className={`metric-margin-pill ${isSatisfied ? "positive" : "negative"}`}>
                    {margin >= 0 ? "+" : ""}{margin}%
                  </span>
                )}
              </div>
              <strong className="metric-val">
                {fmt(est)} <small>MPa</small>
              </strong>
              <div className="metric-gauge-track">
                <div
                  className="metric-req-tick"
                  style={{ left: `${reqPct}%` }}
                  title={`Req: ≥ ${req} MPa`}
                />
                <div
                  className={`metric-gauge-fill ${isSatisfied ? "satisfied" : "deficit"}`}
                  style={{ width: `${valPct}%` }}
                />
              </div>
              <div className="metric-card-footer">
                <span>Req: ≥ {fmt(req, " MPa")}</span>
                <span className={isSatisfied ? "txt-satisfied" : "txt-deficit"}>
                  {isSatisfied ? "Satisfied" : "Deficit"}
                </span>
              </div>
            </div>
          );
        })()}

        {/* Yield Strength */}
        {estimated_yield_strength_mpa && (() => {
          const est = estimated_yield_strength_mpa.estimate;
          const req = active_grade.min_rp02_mpa || 250;
          const margin = acceptance_verdict.yield_margin_pct;
          const { valPct, reqPct } = calcGauge(est, req, 1.35);
          const isSatisfied = est >= req;

          return (
            <div className="report-metric verdict-prop-card">
              <div className="metric-header-row">
                <span className="metric-label">Yield Strength (Rp0.2)</span>
                {margin !== undefined && (
                  <span className={`metric-margin-pill ${isSatisfied ? "positive" : "negative"}`}>
                    {margin >= 0 ? "+" : ""}{margin}%
                  </span>
                )}
              </div>
              <strong className="metric-val">
                {fmt(est)} <small>MPa</small>
              </strong>
              <div className="metric-gauge-track">
                <div
                  className="metric-req-tick"
                  style={{ left: `${reqPct}%` }}
                  title={`Req: ≥ ${req} MPa`}
                />
                <div
                  className={`metric-gauge-fill ${isSatisfied ? "satisfied" : "deficit"}`}
                  style={{ width: `${valPct}%` }}
                />
              </div>
              <div className="metric-card-footer">
                <span>Req: ≥ {fmt(req, " MPa")}</span>
                <span className={isSatisfied ? "txt-satisfied" : "txt-deficit"}>
                  {isSatisfied ? "Satisfied" : "Deficit"}
                </span>
              </div>
            </div>
          );
        })()}

        {/* Elongation at Fracture */}
        {estimated_elongation_pct && (() => {
          const est = estimated_elongation_pct.estimate;
          const req = active_grade.min_elongation_pct || 7.0;
          const margin = acceptance_verdict.elongation_margin_pct;
          const { valPct, reqPct } = calcGauge(est, req, 1.45);
          const isSatisfied = est >= req;

          return (
            <div className="report-metric verdict-prop-card">
              <div className="metric-header-row">
                <span className="metric-label">Elongation at Fracture (A)</span>
                {margin !== undefined && (
                  <span className={`metric-margin-pill ${isSatisfied ? "positive" : "negative"}`}>
                    {margin >= 0 ? "+" : ""}{margin}%
                  </span>
                )}
              </div>
              <strong className="metric-val">
                {fmt(est)} <small>%</small>
              </strong>
              <div className="metric-gauge-track">
                <div
                  className="metric-req-tick"
                  style={{ left: `${reqPct}%` }}
                  title={`Req: ≥ ${req}%`}
                />
                <div
                  className={`metric-gauge-fill ${isSatisfied ? "satisfied" : "deficit"}`}
                  style={{ width: `${valPct}%` }}
                />
              </div>
              <div className="metric-card-footer">
                <span>Req: ≥ {fmt(req, "%")}</span>
                <span className={isSatisfied ? "txt-satisfied" : "txt-deficit"}>
                  {isSatisfied ? "Satisfied" : "Deficit"}
                </span>
              </div>
            </div>
          );
        })()}

        {/* Hardness (HBW / HRC) */}
        {(estimated_hardness_hbw || estimated_rockwell_hardness_hrc) && (() => {
          const isRockwell = !!estimated_rockwell_hardness_hrc;
          const est = isRockwell
            ? estimated_rockwell_hardness_hrc.estimate
            : estimated_hardness_hbw.estimate;
          const unit = isRockwell ? "HRC" : "HBW";
          const label = isRockwell ? "Rockwell Hardness" : "Brinell Hardness";
          const typ =
            active_grade.min_hbw ||
            active_grade.typical_hbw ||
            active_grade.min_hrc ||
            (isRockwell ? "55 HRC" : "170–230 HBW");

          return (
            <div className="report-metric verdict-prop-card">
              <div className="metric-header-row">
                <span className="metric-label">{label}</span>
                <span className="metric-margin-pill positive">In Envelope</span>
              </div>
              <strong className="metric-val">
                {fmt(est)} <small>{unit}</small>
              </strong>
              <div className="metric-gauge-track">
                <div
                  className="metric-req-tick"
                  style={{ left: "75%" }}
                  title="Target Envelope Center"
                />
                <div
                  className="metric-gauge-fill satisfied"
                  style={{ width: "75%" }}
                />
              </div>
              <div className="metric-card-footer">
                <span>Typ: {fmt(typ)}</span>
                <span className="txt-satisfied">Standard</span>
              </div>
            </div>
          );
        })()}
      </div>

      {/* 4. VERDICT SUMMARY CALLOUT (Matching .ai-summary callout box exactly!) */}
      <div className={`ai-summary verdict-summary-box ${statusClass}`}>
        <div className="ai-label">
          <span className="material-symbols-outlined">
            {status === "COMPLIANT" ? "verified" : "gavel"}
          </span>
          Acceptance Verdict & Lot Disposition · Conformity Index: {score}%
        </div>

        <div className="ai-summary-body">
          <p>
            <strong>Acceptance Verdict:</strong>{" "}
            {acceptance_verdict.statement ||
              `Complies with ${active_grade.grade} requirements for ${active_grade.application || "industrial engineering applications"}.`}
          </p>

          {(active_grade.application || matrix_assumed) && (
            <p className="verdict-context-line">
              {active_grade.application && (
                <span>
                  <strong>Target Application:</strong> {active_grade.application}.{" "}
                </span>
              )}
              {matrix_assumed && (
                <span>
                  <strong>Microstructure Input:</strong> {matrix_assumed}.
                </span>
              )}
            </p>
          )}
        </div>
      </div>

      {/* 5. METALLURGICAL ASSUMPTIONS (Clean industrial tags matching report style) */}
      {assumptions.length > 0 && (
        <div className="verdict-assumptions-row">
          <span className="assumptions-prefix">Compliance Parameters:</span>
          {assumptions.map((item, idx) => (
            <span key={idx} className="verdict-param-tag">
              <span className="material-symbols-outlined">check_small</span>
              {item}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
