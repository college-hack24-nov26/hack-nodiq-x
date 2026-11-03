/**
 * Screen Intelligence: Live Screen Scraper & Metallurgical Metric Interpreter
 * Allows NodiqBot to read, interpret, explain, and vocalize any metric, report,
 * or metallurgical phenomenon, combining live DOM state with domain expertise.
 */

class ScreenIntelligence {
  /**
   * Scrapes structured metrics, KPIs, and data currently visible in the DOM
   */
  scrape() {
    if (typeof document === "undefined" || typeof window === "undefined") {
      return {
        path: "",
        title: "",
        kpis: [],
        alerts: [],
        tables: [],
        reportSummary: null,
      };
    }

    const data = {
      path: window.location?.pathname || "",
      title: document.querySelector("h1, h2")?.innerText?.trim() || "",
      kpis: [],
      alerts: [],
      tables: [],
      reportSummary: null,
    };

    // 1. Scrape KPI cards (Nodularity, Carbide, Grain Size, Flakes, Summary Chips)
    const cardSelectors = [
      ".kpi-card",
      ".metric-card",
      ".wci-kpi-card",
      ".analysis-metric-card",
      ".summary-metric-chip",
      ".stat-card",
      "[data-metric]",
    ];

    const cards = Array.from(document.querySelectorAll(cardSelectors.join(", ")));
    cards.forEach((card) => {
      const label = card.querySelector(".kpi-label, .metric-label, .wci-kpi-label, .metric-chip-label, .stat-label, h3, h4")?.innerText?.trim() || "";
      const value = card.querySelector(".kpi-value, .metric-value, .wci-kpi-value, .metric-chip-val, .stat-value, .value, strong")?.innerText?.trim() || "";
      const sub = card.querySelector(".kpi-sub, .metric-sub, .wci-kpi-sub, .stat-sub, .unit, small")?.innerText?.trim() || "";
      if (label && value) {
        data.kpis.push({ label, value, sub });
      }
    });

    // 2. Scrape generic metric boxes if specific classes are not present
    if (data.kpis.length === 0) {
      const genericBoxes = Array.from(document.querySelectorAll(".analysis-card div, .results-section div")).filter((d) => {
        return /\b(\d+(?:\.\d+)?%|\d+\s*(?:px|µm|um|flakes|nodules|G))\b/i.test(d.innerText || "") && (d.innerText || "").length < 120;
      });
      genericBoxes.slice(0, 8).forEach((box) => {
        const text = box.innerText.trim();
        if (text && !data.kpis.some((k) => k.value === text)) {
          data.kpis.push({ label: "Measurement", value: text, sub: "" });
        }
      });
    }

    // 3. Scrape advisories & validation notices
    const alertElements = Array.from(
      document.querySelectorAll(".analysis-advisory, .wci-advisory-box, [role='alert'], [role='status'], .alert-notice")
    );
    data.alerts = alertElements.map((el) => el.innerText.trim()).filter(Boolean);

    // 4. Scrape active report metadata & summary text
    const reportTitle = document.querySelector(".technical-report-header h1, .report-title, #report-title")?.value || document.querySelector(".technical-report-header h1, .report-title")?.innerText?.trim();
    const reportText = document.querySelector(".report-summary-text, .ai-summary-body")?.innerText?.trim();
    if (reportTitle || reportText) {
      data.reportSummary = {
        title: reportTitle || "Microstructure Analysis Report",
        sampleId: document.querySelector("#sample-id")?.value || document.querySelector("[data-field='sampleId'], .meta-sample-id")?.innerText?.trim() || "Sample",
        verdict: document.querySelector(".verdict-badge, .acceptance-badge")?.innerText?.trim() || "Analyzed",
        text: reportText || "",
      };
    }

    return data;
  }

  /**
   * Generates a conversational vocal summary of what is on screen
   */
  summarizeCurrentScreen() {
    const data = this.scrape();
    const parts = [];

    if (data.title) {
      parts.push(`You are currently viewing ${data.title}.`);
    }

    if (data.kpis.length > 0) {
      const kpiDescriptions = data.kpis
        .slice(0, 5)
        .map((k) => `${k.label}: ${k.value}${k.sub ? " (" + k.sub + ")" : ""}`)
        .join("; ");
      parts.push(`Live metrics: ${kpiDescriptions}.`);
    } else {
      parts.push("No analysis results have been generated on this screen yet. Select an image or click Run Analysis to execute the engine.");
    }

    if (data.alerts.length > 0) {
      parts.push(`Notice: ${data.alerts[0].slice(0, 140)}.`);
    }

    return parts.join(" ");
  }

  /**
   * Explains metallurgical concepts with screen context
   */
  explainConcept(query) {
    const q = query.toLowerCase();
    const data = this.scrape();

    // Nodularity Explanation
    if (q.includes("nodularity") || q.includes("nodule")) {
      const match = data.kpis.find((k) => /nodularity/i.test(k.label));
      const count = data.kpis.find((k) => /nodule|count/i.test(k.label));

      let exp = "Nodularity is the percentage of graphite that crystallized into compact, spherical nodules (ISO 945-4 Type V and VI) rather than weakened flakes. Spheroidal nodules minimize stress concentrations, giving ductile iron its high tensile strength and impact resistance.";
      if (match) {
        exp += ` On your current screen, the measured nodularity is ${match.value}${count ? " across " + count.value + " counted nodules." : "."}`;
      }
      return exp;
    }

    // Carbide Explanation (White Cast Iron)
    if (q.includes("carbide") || q.includes("cementite") || q.includes("ledeburite")) {
      const frac = data.kpis.find((k) => /fraction/i.test(k.label));
      const count = data.kpis.find((k) => /carbide count/i.test(k.label));

      let exp = "White cast iron carbide analysis quantifies hard cementite (Fe3C) precipitates in a pearlitic or martensitic matrix. High carbide fraction provides extreme abrasive wear resistance but low toughness.";
      if (frac || count) {
        exp += ` Active results show an area fraction of ${frac?.value || "unmeasured"} with ${count?.value || "uncounted"} segmented regions.`;
      }
      return exp;
    }

    // Graphite Flakes Explanation (Gray Cast Iron)
    if (q.includes("flake") || q.includes("gray cast iron")) {
      const flake = data.kpis.find((k) => /flake/i.test(k.label));
      const frac = data.kpis.find((k) => /fraction/i.test(k.label));

      let exp = "Gray cast iron contains interconnected graphite flakes that absorb vibration and dissipate thermal energy, but lower tensile ductility compared to nodular ductile iron.";
      if (flake || frac) {
        exp += ` Current analysis counts ${flake?.value || "uncounted"} flakes with an area fraction of ${frac?.value || "unmeasured"}.`;
      }
      return exp;
    }

    // Grain Size Explanation (Steel)
    if (q.includes("grain") || q.includes("astm")) {
      const grain = data.kpis.find((k) => /grain|astm/i.test(k.label));
      let exp = "Grain size measurement in steel uses the ASTM E112 planimetric or intercept procedure. Finer grain sizes (higher ASTM G numbers) generally improve yield strength and fracture toughness according to the Hall-Petch relationship.";
      if (grain) {
        exp += ` Current steel sample rating is ASTM G ${grain.value}.`;
      }
      return exp;
    }

    // Generic metric lookup
    const direct = data.kpis.find((k) => q.includes(k.label.toLowerCase()) || k.label.toLowerCase().includes(q));
    if (direct) {
      return `${direct.label} is currently measured at ${direct.value} ${direct.sub || ""}.`;
    }

    return null;
  }

  /**
   * Discovers the active analysis ID from DOM, URL, or local storage
   */
  getActiveAnalysisId() {
    if (typeof document === "undefined") return "";
    return (
      document.querySelector("[data-analysis-id]")?.getAttribute("data-analysis-id") ||
      document.querySelector(".completion-title")?.innerText?.match(/ANL-[A-Z0-9]{6}/)?.[0] ||
      document.querySelector(".analysis-id")?.innerText?.match(/ANL-[A-Z0-9]{6}/)?.[0] ||
      document.querySelector(".summary-target-id")?.innerText?.match(/ANL-[A-Z0-9]{6}/)?.[0] ||
      document.querySelector("select[aria-label='Select analysis']")?.value ||
      (typeof window !== "undefined" && window.location?.pathname?.match(/ANL-[A-Z0-9]{6}/)?.[0]) ||
      (typeof localStorage !== "undefined" ? localStorage.getItem("nodiq_active_analysis") : "") ||
      ""
    );
  }

  /**
   * Generates a brief or comprehensive executive voice summary of the current report
   */
  async summarizeReport(brief = false) {
    const data = this.scrape();

    // 1. Identify active analysis ID if present in DOM, URL, or local storage
    let analysisId = this.getActiveAnalysisId();

    const { default: api } = await import("./api");

    // If still no analysis ID, fetch latest completed analysis from API
    if (!analysisId) {
      try {
        const list = await api.analyses();
        if (list?.analyses?.length > 0) {
          analysisId = list.analyses[0].id;
        }
      } catch {
        // ignore
      }
    }

    // 2. Title, sample, and kind
    const headerTitle =
      document.querySelector("#report-title")?.value ||
      document.querySelector(".technical-report-header h1, .report-topbar h2, .report-title, h1, h2")?.innerText?.trim() ||
      data.reportSummary?.title ||
      "Industrial Microstructure Analysis Report";
    const sampleId =
      document.querySelector("#sample-id")?.value ||
      document.querySelector("[data-field='sampleId'], .sample-id, .meta-sample-id")?.innerText?.trim() ||
      data.reportSummary?.sampleId ||
      analysisId ||
      "Specimen";

    // Helper to safely extract clean text without material icon names
    const getCleanNodeText = (el) => {
      if (!el) return "";
      try {
        const clone = el.cloneNode(true);
        clone.querySelectorAll(".material-symbols-outlined, .material-icons, svg, button").forEach((n) => n.remove());
        return (clone.innerText || "").replace(/\s+/g, " ").trim();
      } catch {
        return (el.innerText || "")
          .replace(/\b(gavel|check_circle|verified|warning|insights|science|summarize|content_copy|arrow_forward|arrow_back|psychology|download|share|sync|progress_activity|check_small|done|close)\b/gi, "")
          .replace(/\s+/g, " ")
          .trim();
      }
    };

    // 3. Verdict / Release status & Acceptance disposition
    const statusTxt =
      getCleanNodeText(document.querySelector(".ready-badge, .status-approved-txt, .badge-label, .verdict-badge, .verdict-title")) ||
      "READY";

    // 4. Check for AcceptanceVerdictMeter specific fields
    const verdictBox = document.querySelector(".verdict-summary-box, .ai-summary.verdict-summary-box");
    let conformity = "";
    let verdictStatement = "";
    let targetApp = "";
    let findings = "";

    if (verdictBox) {
      const fullVerdictRaw = getCleanNodeText(verdictBox);
      const confMatch = fullVerdictRaw.match(/Conformity Index:?\s*([0-9.]+%?)/i);
      if (confMatch) conformity = confMatch[1];

      const vMatch = fullVerdictRaw.match(/Acceptance Verdict:\s*([^.]+?(?:\.[0-9]+%[^.]*?)?\.)/i);
      if (vMatch) verdictStatement = vMatch[1].replace(/\.$/, "").trim();

      const appMatch = fullVerdictRaw.match(/Target Application:\s*([^.\n]+)/i);
      if (appMatch) targetApp = appMatch[1].replace(/\.$/, "").trim();

      const fMatch = fullVerdictRaw.match(/Microstructure Input:\s*([^.\n]+)/i);
      if (fMatch) findings = fMatch[1].replace(/\.$/, "").trim();
      else {
        // Text after the verdict statement
        if (vMatch && fullVerdictRaw.includes(vMatch[0])) {
          findings = fullVerdictRaw.split(vMatch[0])[1]?.replace(/Target Application:[^.]+\.?/i, "")?.trim() || "";
        }
      }
    }

    // 5. Quantitative metrics
    let metricPairs = data.kpis.slice(0, 6).map((k) => `${k.label}: ${k.value}${k.sub ? " " + k.sub : ""}`);

    // 6. Look for AI / Metallurgical interpretation in DOM
    const rawAiEl = document.querySelector(".report-summary-text, .ai-summary-body:not(.verdict-summary-box .ai-summary-body), .ai-interpretation, .metallurgical-remarks");
    let aiText = getCleanNodeText(rawAiEl);

    // 7. Query backend ai-summary if needed or to augment
    if (analysisId) {
      try {
        const backendData = await api.aiSummary(analysisId);
        if (!aiText && backendData?.ai_interpretation) {
          aiText = backendData.ai_interpretation;
        }
      } catch {
        // Fallback
      }
    }

    // 8. If still no metrics, fetch analysis detail
    if (metricPairs.length === 0 && analysisId) {
      try {
        const detail = await api.analysisDetail(analysisId);
        const a = detail?.analysis || detail?.record || detail;
        if (a) {
          if (a.iso_nodularity_pct !== undefined) metricPairs.push(`Nodularity: ${a.iso_nodularity_pct}%`);
          if (a.nodule_count !== undefined) metricPairs.push(`Count: ${a.nodule_count} nodules`);
          if (a.accuracy_pct !== undefined) metricPairs.push(`Accuracy: ${a.accuracy_pct}%`);
          if (a.quality_score !== undefined) metricPairs.push(`Quality: ${a.quality_score}/100`);
        }
      } catch {
        // Fallback
      }
    }

    if (!findings && aiText) {
      const cleanAi = aiText
        .replace(/\*\*/g, "")
        .replace(/NODIQ-X Metallurgical Intelligence/gi, "")
        .replace(/\s+/g, " ")
        .trim();
      const sentences = cleanAi.split(/(?<=[.!?])\s+/);
      findings = sentences.slice(0, brief ? 2 : 4).join(" ");
    }

    // Clean spoken sentence for voice output
    const cleanSample = (sampleId && sampleId !== "Sample" && sampleId !== "Specimen") ? sampleId : (analysisId || "inspected specimen");
    let speech = `Executive Summary for ${headerTitle} (${cleanSample}). Status: ${statusTxt}.`;

    if (conformity) {
      speech += ` Conformity Index is ${conformity}.`;
    }
    if (verdictStatement) {
      speech += ` Acceptance Verdict: ${verdictStatement}.`;
    }
    if (metricPairs.length > 0 && !conformity) {
      speech += ` Key parameters: ${metricPairs.slice(0, 3).join(", ")}.`;
    }
    if (findings) {
      speech += ` Evaluation finding: ${findings}.`;
    }
    if (targetApp) {
      speech += ` Recommended for ${targetApp}.`;
    }

    const structuredMetrics = [];
    if (conformity) structuredMetrics.push({ label: "Conformity", value: conformity });
    data.kpis.forEach((k) => {
      if (structuredMetrics.length < 4 && !structuredMetrics.some((sm) => sm.label.toLowerCase() === k.label.toLowerCase())) {
        structuredMetrics.push({ label: k.label, value: k.value });
      }
    });

    return {
      speech,
      isReportSummary: true,
      title: headerTitle,
      analysisId: analysisId,
      sampleId: cleanSample,
      status: statusTxt,
      conformity: conformity,
      verdict: verdictStatement,
      findings: findings,
      targetApplication: targetApp,
      metrics: structuredMetrics,
      fullSummaryText: aiText || findings,
    };
  }
}

export const screenIntelligence = new ScreenIntelligence();
export default screenIntelligence;
