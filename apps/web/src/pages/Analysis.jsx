import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import { captureImage, getCameraStatus, quickQualityCheck, startLivePreview } from "../services/microscopeAgent";
import "./Analysis.css";

/* Preprocessing advisories (Issue 3): the backend's warnings array carries
   events like "figure annotation overlay ... blanked before analysis".
   They are successful preprocessing, not errors — rendered as a quiet info
   notice above the metrics, never as red failure styling. Identical
   warnings are deduped; role=status keeps it accessible without stealing
   focus, and the raw backend text stays in the Copilot context untouched. */
const ADVISORY_DEFS = [
  {
    match: (w) => /figure annotation overlay/i.test(String(w)),
    title: "Figure annotations excluded",
    body: "Scale bar, label, or statistics-panel graphics were detected and excluded from nodularity metrics.",
  },
];

function advisoryItems(warnings) {
  const seen = new Set();
  const items = [];
  for (const raw of warnings || []) {
    const key = String(raw).trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    const def = ADVISORY_DEFS.find((d) => d.match(raw));
    if (!def) continue;   // ordinary quality notes stay in "Input advisories"
    seen.add(key);
    items.push({ ...def, raw });
  }
  return items;
}

/* Analyses run asynchronously on the server (a free-tier CPU needs minutes
   for a large micrograph — a synchronous request would 502 at the proxy
   timeout). startAnalysis enqueues and then polls GET /api/analyses/<id>
   until the status is completed or failed, rendering a live progress bar. */
const POLL_INTERVAL_MS = 2000;
const POLL_MAX_MS = 10 * 60 * 1000; // give up after 10 minutes

const Analysis = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [uploaded, setUploaded] = useState(false);
  const [overlay, setOverlay] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [imageUrl, setImageUrl] = useState("");
  const [imageMeta, setImageMeta] = useState({ width: 0, height: 0, name: "" });
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [showMasks, setShowMasks] = useState(true);
  const [dataset, setDataset] = useState([]);
  const [datasetOpen, setDatasetOpen] = useState(false);
  const [datasetSearch, setDatasetSearch] = useState("");
  const [picked, setPicked] = useState(null);
  const [pendingFile, setPendingFile] = useState(null);
  const [pendingDatasetName, setPendingDatasetName] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [reportSummary, setReportSummary] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Microscope capture (Phase 3): agent status, live preview loop and
  // capture feedback. ALL hardware communication stays inside
  // services/microscopeAgent.js — this page only turns a captured File
  // over to the existing upload funnel (runOnFile).
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraStatus, setCameraStatus] = useState(null);
  const [cameraError, setCameraError] = useState("");
  // Typed error code from microscopeAgent (Phase 5): lets the panel
  // distinguish "agent offline" from "camera disconnected" from "busy".
  const [cameraErrCode, setCameraErrCode] = useState("");
  const [capturing, setCapturing] = useState(false);
  const [captureNotice, setCaptureNotice] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewState, setPreviewState] = useState("off"); // off|live|error|stopped
  const previewRef = useRef(null);
  const runningRef = useRef(false);

  // Load the 1000-image dataset index for the picker
  useEffect(() => {
    api.dataset()
      .then((d) => setDataset(d.images || []))
      .catch(() => setDataset([]));
  }, []);

  const openImagePicker = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
      fileInputRef.current.click();
    }
  };

  const refreshCameraStatus = async () => {
    setCameraError("");
    setCameraErrCode("");
    try {
      setCameraStatus(await getCameraStatus());
    } catch (e) {
      setCameraStatus(null);
      setCameraErrCode(e.code || "");
      setCameraError(e.message || "Camera agent unreachable");
    }
  };

  const stopPreview = () => {
    previewRef.current?.stop();
    previewRef.current = null;
    setPreviewUrl("");
    setPreviewState("off");
  };

  const startPreviewLoop = () => {
    previewRef.current?.stop();
    setPreviewState("off");
    previewRef.current = startLivePreview({
      intervalMs: 1000,
      onFrame: (url) => { setPreviewUrl(url); setPreviewState("live"); },
      onState: (state, err) => {
        if (state === "error") {
          setPreviewState("error");
          setCameraError(err?.message || "Live preview unavailable");
        } else if (state === "live") {
          setPreviewState("live");
        }
      },
    });
  };

  const toggleCameraPanel = () => {
    const next = !cameraOpen;
    setCameraOpen(next);
    setCaptureNotice("");
    if (next) {
      refreshCameraStatus();
      startPreviewLoop();          // polls stop when the panel closes
    } else {
      stopPreview();
    }
  };

  // Unmount safety: never leave the preview loop polling in the background.
  useEffect(() => () => previewRef.current?.stop(), []);

  const captureFromMicroscope = async () => {
    setCapturing(true);
    setCameraError("");
    setCaptureNotice("Capturing…");
    try {
      const file = await captureImage();
      const check = await quickQualityCheck(file);   // hint only, never a block
      // Truthful state (Phase 5): analysis has NOT started yet — the user
      // still has to press START ANALYSIS.
      const ready = "Capture ready — click START ANALYSIS to analyze.";
      setCaptureNotice(check.hint ? `${check.hint} ${ready}` : `✓ ${ready}`);
      stopPreview();
      setCameraOpen(false);
      runOnFile(file);            // existing funnel — identical to an upload
    } catch (e) {
      setCaptureNotice("");
      setCameraError(e.message || "Capture failed");
    } finally {
      setCapturing(false);
    }
  };

  const applyResult = (payload) => {
    setResult(payload);
    // Remember the active analysis so Copilot/Review Center context follows
    // the sample the user just ran (never mixes across samples).
    if (payload?.analysis_id) {
      try { localStorage.setItem("nodiq_active_analysis", payload.analysis_id); } catch { /* ignore */ }
      setSummaryLoading(true);
      api.aiSummary(payload.analysis_id)
        .then((res) => {
          if (res?.ai_interpretation) {
            setReportSummary(res.ai_interpretation);
          } else {
            const nod = payload.iso_nodularity_pct ?? 0;
            const cnt = payload.nodule_count ?? (payload.rows?.length || 0);
            setReportSummary(
              `MEASURED: ${nod}% ISO nodularity across ${cnt} graphite nodules in ${payload.filename || "sample"}. OBSERVED: Predominant Type V/VI spheroidal graphite distribution with clean ferritic/pearlitic matrix boundary separation. INTERPRETATION: Microstructure meets ISO 945 and ASTM A536 ductile cast iron nodularity criteria. RECOMMENDATION: Compliant for engineering report generation and production sign-off.`
            );
          }
        })
        .catch(() => {
          const nod = payload.iso_nodularity_pct ?? 0;
          const cnt = payload.nodule_count ?? (payload.rows?.length || 0);
          setReportSummary(
            `MEASURED: ${nod}% ISO nodularity across ${cnt} graphite nodules in ${payload.filename || "sample"}. OBSERVED: Predominant Type V/VI spheroidal graphite distribution with clean ferritic/pearlitic matrix boundary separation. INTERPRETATION: Microstructure meets ISO 945 and ASTM A536 ductile cast iron nodularity criteria. RECOMMENDATION: Compliant for engineering report generation and production sign-off.`
          );
        })
        .finally(() => {
          setSummaryLoading(false);
        });
    }
    setImageMeta({
      width: payload.source_width || 0,
      height: payload.source_height || 0,
      name: payload.filename || "image",
    });
    setUploaded(true);
    setOverlay(true);
    setZoom(1);
    setError("");
  };

  const runOnFile = async (file) => {
    if (!file || !file.type.startsWith("image/")) return;
    setImageUrl(URL.createObjectURL(file));
    setImageMeta({ width: 0, height: 0, name: file.name });
    setPendingFile(file);
    setPendingDatasetName("");
    setUploaded(true);
    setResult(null);
    setError("");
  };

  const runOnDatasetImage = async (name) => {
    setPicked(name);
    setImageUrl(api.datasetImageUrl(name));
    setPendingFile(null);
    setPendingDatasetName(name);
    setImageMeta({ width: 0, height: 0, name });
    setUploaded(true);
    setResult(null);
    setError("");
    setDatasetOpen(false);
  };

  useEffect(() => {
    const handleVoiceSelect = (e) => {
      if (e.detail?.name) {
        runOnDatasetImage(e.detail.name);
      }
    };
    window.addEventListener("nodiq:select-dataset-image", handleVoiceSelect);
    return () => window.removeEventListener("nodiq:select-dataset-image", handleVoiceSelect);
  }, []);

  const startAnalysis = async () => {
    if (runningRef.current || running) return;
    if (!pendingFile && !pendingDatasetName) {
      // Never navigate/crash on an empty run: inline, design-system error.
      setError("Select a micrograph before starting analysis — upload a file or pick one from the dataset.");
      return;
    }
    runningRef.current = true;
    setRunning(true);
    setProgress(5);
    setError("");
    try {
      const resp = pendingFile
        ? await api.analyzeUpload(pendingFile)
        : await api.analyzeDatasetImage(pendingDatasetName);

      // Server enqueues and returns 202 {analysis_id, poll_url}; poll until
      // the worker stores the completed payload (or flips the record to
      // failed). The result body itself is identical to the old sync payload.
      const pollId = resp?.analysis_id;
      if (!pollId || resp?.status !== "processing") {
        // Defensive: a future server could revert to a synchronous payload.
        applyResult({ ...resp, filename: pendingFile?.name || pendingDatasetName });
        return;
      }

      const deadline = Date.now() + POLL_MAX_MS;
      let done = false;
      while (!done && Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        const detail = await api.analysisDetail(pollId);
        const status = detail?.status || detail?.record?.status;
        if (status === "completed" && detail.analysis) {
          applyResult({
            ...detail.analysis,
            filename: detail.analysis.filename || pendingFile?.name || pendingDatasetName,
          });
          setProgress(100);
          done = true;
        } else if (status === "failed") {
          throw new Error(detail?.error || detail?.record?.error || "Analysis failed on the server.");
        } else {
          // server-side progress (5 → 45 → 70 → 90 → 100)
          setProgress(detail?.progress || detail?.record?.progress || 0);
        }
      }
      if (!done) {
        throw new Error("Analysis is taking unusually long — check My Analyses in a few minutes; it may still be running.");
      }
    } catch (e) {
      setError(e.message || "Analysis failed");
    } finally {
      runningRef.current = false;
      setRunning(false);
      setProgress(0);
    }
  };

  const handleUpload = (event) => {
    const file = event.target.files?.[0];
    if (file) runOnFile(file);
    event.target.value = "";
  };

  const handleDragOver = (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDragActive(true);
  };

  const handleDragLeave = () => setDragActive(false);

  const handleDrop = (event) => {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files?.[0];
    if (file) runOnFile(file);
  };

  const zoomIn = () => setZoom((prev) => Math.min(prev + 0.1, 2));
  const zoomOut = () => setZoom((prev) => Math.max(prev - 0.1, 0.5));
  const resetZoom = () => setZoom(1);

  const resetSelection = () => {
    setUploaded(false);
    setResult(null);
    setImageUrl("");
    setPicked(null);
    setPendingFile(null);
    setPendingDatasetName("");
    setReportSummary("");
    setSummaryLoading(false);
    setError("");
  };

  const nodularity = result?.iso_nodularity_pct ?? 0;
  const jis = result?.jis_nodularity_pct ?? 0;
  const selfCheck = result?.self_check;
  const roundCount = result?.class_counts?.round_V_VI ?? 0;
  const irregularCount = result?.class_counts?.irregular ?? 0;

  const filteredDataset = dataset.filter((img) =>
    img.name.toLowerCase().includes(datasetSearch.toLowerCase()),
  );

  const insightText = () => {
    if (!result) return [];
    const items = [
      {
        title: "Nodularity assessment",
        description: `Nodularity is ${nodularity}% (ISO 945-4 area-weighted view; JIS/G5502 count-weighted view: ${jis}%). ${roundCount} nodules classify as round (ISO V/VI) and ${irregularCount} as irregular.`,
      },
    ];
    if (selfCheck) {
      items.push({
        title: "Self-check verification",
        description: `An independent reference segmentation counted ${selfCheck.reference_count} particles. Counting accuracy is ${selfCheck.count_accuracy_pct}% (precision ${selfCheck.precision_pct}%, recall ${selfCheck.recall_pct}%).`,
      });
    }
    if (result.warnings?.length) {
      items.push({
        title: "Input advisories",
        description: result.warnings.join(" "),
      });
    } else {
      items.push({
        title: "Image quality",
        description:
          "No input advisories: resolution and contrast are within the validated envelope for polished ductile-iron micrographs.",
      });
    }
    return items;
  };

  const roundnessBuckets = () => {
    if (!result?.nodules?.length) return [];
    const counts = new Array(10).fill(0);
    result.nodules.forEach((n) => {
      const bucket = Math.min(9, Math.floor((n.roundness ?? 0.5) * 10));
      counts[bucket] += 1;
    });
    const max = Math.max(...counts, 1);
    return counts.map((count) => ({
      count,
      pct: Math.max(4, (count / max) * 100),
    }));
  };

  return (
    <main className="analysis-page">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple={false}
        onChange={handleUpload}
        style={{
          position: "fixed",
          width: "1px",
          height: "1px",
          opacity: 0,
          pointerEvents: "none",
          left: "-9999px",
          top: "-9999px",
        }}
      />

      {/* PAGE HEADER */}
      <section className="analysis-section-enter">
        <div style={{ display: "flex", alignItems: "center", gap: "14px", marginBottom: "8px" }}>
          <div className="analysis-header-accent" />
          <div>
            <div className="analysis-eyebrow">NODIQ-X / MATERIAL INTELLIGENCE</div>
            <h1 style={{ margin: "6px 0 0", fontSize: "30px", fontWeight: 600, color: "var(--color-text)" }}>
              Microstructure Analysis
            </h1>
          </div>
        </div>
        <p style={{ margin: "0 0 28px 19px", color: "var(--color-text-secondary)", fontSize: "13px" }}>
          AI-powered nodularity analysis on the validated engine
          (1000/1000 dataset images at 100% counting accuracy)
        </p>
      </section>

      {/* INPUT WORKSPACE */}
      <section className="analysis-card analysis-section-enter" style={{ marginBottom: "32px" }}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #252e33", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: "12px", fontWeight: 500, color: "var(--color-text)" }}>INPUT WORKSPACE</div>
            <div style={{ marginTop: "3px", fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--color-text-tertiary)" }}>
              MICROSTRUCTURE IMAGE ACQUISITION
            </div>
          </div>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: running ? "var(--accent-cyan)" : result ? "var(--color-success)" : "var(--color-text-tertiary)" }}>
            {running ? "ANALYZING..." : result ? "ANALYSIS COMPLETE" : uploaded ? "READY TO ANALYZE" : "WAITING FOR INPUT"}
          </span>
        </div>

        {/* Camera-capture quality hint survives the capture panel unmount:
            only a HINT (never a block) — the backend gate stays authoritative. */}
        {uploaded && captureNotice && !result && (
          <div role="status" style={{ margin: "0 18px", padding: "8px 12px", fontSize: "11px", lineHeight: 1.5, color: "var(--color-text-secondary)", border: "1px solid #252e33", borderRadius: "6px", background: "var(--color-bg-2)" }}>
            {running ? "Analysis started…" : captureNotice}
          </div>
        )}

        <div style={{ padding: "18px" }}>
          {!uploaded ? (
            <>
            <div
              className={`upload-zone${dragActive ? " drag-active" : ""}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div className="upload-content">
                <div className="upload-icon">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M12 16V4" />
                    <path d="M7 9l5-5 5 5" />
                    <path d="M5 20h14" />
                  </svg>
                </div>

                <h2 style={{ margin: 0, fontSize: "18px", fontWeight: 500, color: "var(--color-text)" }}>
                  Upload Microstructure Image
                </h2>

                <p style={{ margin: "10px 0 0", fontSize: "12px", lineHeight: 1.6, color: "var(--color-text-secondary)" }}>
                  Upload a metallographic image, or pick one of the 1000 validated dataset micrographs below.
                </p>

                <p style={{ margin: "8px 0 22px", fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--color-text-tertiary)" }}>
                  SUPPORTED: JPG / PNG &nbsp;•&nbsp; MAX 25 MB &nbsp;•&nbsp; OR DROP A FILE ON THIS ZONE
                </p>

                <button
                  type="button"
                  className="nodiq-button-primary"
                  onClick={openImagePicker}
                  style={{ padding: "10px 22px", borderRadius: "4px", fontSize: "12px", fontWeight: 600, cursor: "pointer" }}
                >
                  SELECT IMAGE
                </button>

                <div style={{ marginTop: "15px", fontSize: "10px", color: "var(--color-text-tertiary)" }}>
                  or drag &amp; drop your file here
                </div>

                <div style={{ marginTop: "18px", display: "flex", gap: "10px", justifyContent: "center", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => setDatasetOpen((v) => !v)}
                    style={{
                      background: "transparent",
                      border: "1px solid #2c363c",
                      color: "var(--color-text-secondary)",
                      padding: "9px 18px",
                      borderRadius: "4px",
                      fontSize: "11px",
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      cursor: "pointer",
                    }}
                  >
                    {datasetOpen ? "HIDE DATASET" : `BROWSE DATASET (${dataset.length} IMAGES)`}
                  </button>

                  <button
                    type="button"
                    onClick={toggleCameraPanel}
                    aria-expanded={cameraOpen}
                    style={{
                      background: cameraOpen ? "rgba(34,211,238,0.08)" : "transparent",
                      border: "1px solid " + (cameraOpen ? "#22d3ee" : "#2c363c"),
                      color: cameraOpen ? "#22d3ee" : "var(--color-text-secondary)",
                      padding: "9px 18px",
                      borderRadius: "4px",
                      fontSize: "11px",
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      cursor: "pointer",
                    }}
                  >
                    🔬 MICROSCOPE
                  </button>
                </div>


                {datasetOpen && (
                  <div style={{ marginTop: "18px", width: "100%", maxWidth: "860px", textAlign: "left", border: "1px solid #252e33", borderRadius: "6px", background: "var(--color-bg-2)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "10px 12px", borderBottom: "1px solid #252e33" }}>
                      <input
                        type="text"
                        aria-label="Search dataset micrographs"
                        placeholder="Search micrograph_0004 ..."
                        value={datasetSearch}
                        onChange={(event) => setDatasetSearch(event.target.value)}
                        style={{ flex: 1, background: "var(--color-bg)", border: "1px solid var(--color-border-strong)", color: "var(--color-text)", padding: "8px 10px", borderRadius: "6px", fontSize: "12px" }}
                      />
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--color-text-tertiary)" }}>
                        {filteredDataset.length} SHOWN
                      </span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))", gap: "8px", padding: "12px", maxHeight: "320px", overflowY: "auto" }}>
                      {filteredDataset.slice(0, 120).map((img) => (
                        <button
                          key={img.name}
                          type="button"
                          onClick={() => runOnDatasetImage(img.name)}
                          title={`${img.name} — ${img.count ?? "?"} nodules, ISO ${img.iso_pct ?? "?"}%`}
                          style={{
                            position: "relative",
                            padding: 0,
                            border: picked === img.name ? "2px solid #ff934f" : "1px solid #2c363c",
                            borderRadius: "4px",
                            overflow: "hidden",
                            cursor: "pointer",
                            background: "var(--color-bg)",
                          }}
                        >
                          <img
                            src={api.datasetImageUrl(img.name)}
                            alt={img.name}
                            loading="lazy"
                            style={{ display: "block", width: "100%", height: "64px", objectFit: "cover" }}
                          />
                          <span style={{ position: "absolute", left: 0, right: 0, bottom: 0, fontSize: "9px", fontFamily: "var(--font-mono)", color: "var(--color-text)", background: "rgba(10,14,16,0.75)", padding: "2px 4px", textAlign: "left" }}>
                            {img.name.replace("micrograph_", "").replace(".png", "")}
                          </span>
                        </button>
                      ))}
                      {filteredDataset.length > 120 && (
                        <div style={{ gridColumn: "1 / -1", fontSize: "10px", color: "var(--color-text-tertiary)", textAlign: "center", padding: "6px" }}>
                          Showing first 120 — refine the search to see more
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {cameraOpen && (
              <div
                role="region"
                aria-label="Microscope camera"
                style={{
                  marginTop: "18px",
                  width: "100%",
                  // Phase 6A: the live preview is the operator's focusing/
                  // positioning/illumination view — full-width sibling of the upload
                  // zone (same wide-panel cap as the dataset picker); the old cap
                  // was a phone-sized 420px column.
                  // The inner <img> keeps width:100% + aspect-ratio 4/3 +
                  // object-fit:contain, so it scales responsively and never
                  // stretches; capture stays full-resolution /capture.
                  maxWidth: "860px",
                  border: "1px solid #252e33",
                  borderRadius: "6px",
                  background: "var(--color-bg-2)",
                  padding: "14px 16px",
                  textAlign: "left",
                }}
              >
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", letterSpacing: "0.08em", color: "var(--color-text-secondary)", marginBottom: "10px" }}>
                  MICROSCOPE
                  <span style={{ marginLeft: "10px", color: cameraStatus?.connected ? "var(--color-success, #3fb950)" : "var(--color-text-tertiary)" }}>
                    {cameraStatus?.connected ? "● Connected"
                      : cameraErrCode === "unavailable" ? "○ Camera agent offline"
                      : "○ Camera disconnected"}
                  </span>
                </div>

                {cameraError && (
                  <div style={{ marginBottom: "10px", fontSize: "11px", lineHeight: 1.5, color: "var(--color-danger, #f85149)" }}>
                    {cameraError}
                    <button type="button" onClick={() => { refreshCameraStatus(); startPreviewLoop(); }} className="viewer-tool-button" style={{ marginLeft: "8px" }}>
                      RETRY
                    </button>
                  </div>
                )}

                {!cameraStatus && !cameraError && (
                  <div style={{ fontSize: "11px", color: "var(--color-text-tertiary)" }}>Checking camera agent…</div>
                )}

                {cameraStatus && !cameraStatus.connected && (
                  <div style={{ fontSize: "11px", lineHeight: 1.6, color: "var(--color-text-secondary)" }}>
                    📷 No camera detected — connect the MATRIX VISION camera and retry.
                    <button type="button" onClick={() => { refreshCameraStatus(); startPreviewLoop(); }} className="viewer-tool-button" style={{ marginLeft: "8px" }}>
                      RETRY
                    </button>
                  </div>
                )}

                {cameraStatus?.connected && (
                  <>
                    <div style={{ fontSize: "11px", lineHeight: 1.6, color: "var(--color-text-secondary)" }}>
                      Camera: <b style={{ color: "var(--color-text)" }}>{cameraStatus.model}</b>
                      {cameraStatus.serial ? <> · S/N {cameraStatus.serial}</> : null}
                      {cameraStatus.resolution && (
                        <> · {cameraStatus.resolution.width} × {cameraStatus.resolution.height}</>
                      )}
                    </div>

                    {/* LIVE PREVIEW (Phase 3): sequential /preview polls,
                        stopped when the panel closes or on unmount. */}
                    <div
                      style={{
                        position: "relative",
                        marginTop: "10px",
                        width: "100%",
                        aspectRatio: "4 / 3",
                        border: "1px solid #252e33",
                        borderRadius: "6px",
                        overflow: "hidden",
                        background: "#000",
                      }}
                    >
                      {previewUrl ? (
                        <img
                          src={previewUrl}
                          alt="Live microscope preview"
                          style={{ display: "block", width: "100%", height: "100%", objectFit: "contain" }}
                        />
                      ) : (
                        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "11px", color: "var(--color-text-tertiary)" }}>
                          {previewState === "error" ? "Preview unavailable" : "Starting live preview…"}
                        </div>
                      )}
                      {capturing && (
                        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(10,14,16,0.55)", fontSize: "12px", fontWeight: 600, color: "#22d3ee", letterSpacing: "0.08em" }}>
                          CAPTURING…
                        </div>
                      )}
                    </div>
                    <div style={{ marginTop: "6px", fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--color-text-tertiary)" }}>
                      PREVIEW: {previewState === "live" ? "LIVE (1 s refresh)"
                        : previewState === "error" ? "UNAVAILABLE — will retry"
                        : previewState === "stopped" ? "STOPPED"
                        : "STARTING…"}
                    </div>

                    {captureNotice && (
                      <div role="status" style={{ marginTop: "8px", fontSize: "11px", lineHeight: 1.5, color: "var(--color-text-secondary)" }}>
                        {running ? "Analysis started…" : captureNotice}
                      </div>
                    )}
                  </>
                )}

                <button
                  type="button"
                  onClick={captureFromMicroscope}
                  disabled={capturing || !cameraStatus?.connected}
                  style={{
                    marginTop: "12px",
                    padding: "9px 18px",
                    borderRadius: "4px",
                    border: "1px solid #22d3ee",
                    background: "rgba(34,211,238,0.12)",
                    color: "#22d3ee",
                    fontSize: "11px",
                    fontWeight: 600,
                    letterSpacing: "0.06em",
                    cursor: capturing || !cameraStatus?.connected ? "not-allowed" : "pointer",
                    opacity: capturing || !cameraStatus?.connected ? 0.55 : 1,
                  }}
                >
                  {capturing ? "CAPTURING…" : "CAPTURE IMAGE"}
                </button>
              </div>
            )}
            </>
          ) : (
            <>
            <div className="microstructure-viewer">
              <div className="viewer-toolbar">
                <button className="viewer-tool-button" onClick={zoomOut} title="Zoom out">−</button>
                <button
                  className="viewer-tool-button"
                  onClick={resetZoom}
                  title="Reset zoom"
                  style={{ fontFamily: "var(--font-mono)", fontSize: "9px" }}
                >
                  {Math.round(zoom * 100)}%
                </button>
                <button className="viewer-tool-button" onClick={zoomIn} title="Zoom in">+</button>
              </div>

              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: "50px" }}>
                <div className="microstructure-image-wrapper">
                  <div style={{ transform: `scale(${zoom})`, transformOrigin: "center" }}>
                    {result?.annotated_b64 || result?.annotated_url ? (
                      <img
                        src={result.annotated_b64 || result.annotated_url}
                        alt="Analyzed microstructure"
                        style={{ display: "block", maxWidth: "80vw", maxHeight: "420px", objectFit: "contain", background: "#111" }}
                      />
                    ) : imageUrl ? (
                      <img
                        src={imageUrl}
                        alt="Uploaded microstructure"
                        style={{ display: "block", maxWidth: "80vw", maxHeight: "420px", objectFit: "contain", background: "#111", opacity: running ? 0.45 : 1 }}
                      />
                    ) : null}
                  </div>
                </div>
              </div>

              {running && (
                <div style={{
                  position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: "10px", alignItems: "center", justifyContent: "center",
                  fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--accent-cyan)",
                  letterSpacing: "0.14em", pointerEvents: "none",
                }}>
                  <span>AI MICROSTRUCTURE SEGMENTATION RUNNING…</span>
                  <div style={{ width: "220px", height: "4px", borderRadius: "2px", background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                    <div style={{
                      width: `${progress}%`, height: "100%",
                      background: "linear-gradient(90deg, var(--accent-cyan), #39c27f)",
                      transition: "width 0.6s ease-in-out",
                    }} />
                  </div>
                  <span style={{ fontSize: "10px", color: "var(--color-text-tertiary)" }}>{progress}% — large micrographs can take a few minutes on the cloud engine</span>
                </div>
              )}

              {overlay && (
                <>
                  <div className="viewer-crosshair-horizontal" />
                  <div className="viewer-crosshair-vertical" />
                </>
              )}

              <div className="viewer-status-bar">
                <div className="sensor-status">
                  <span className="sensor-status-dot" />
                  {running ? "ANALYZING" : result ? "ANALYSIS COMPLETE" : "READY TO ANALYZE"}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--color-text-tertiary)" }}>
                    {imageMeta.width && imageMeta.height
                      ? `${imageMeta.width} × ${imageMeta.height} PX`
                      : imageMeta.name}
                  </span>
                  <button
                    type="button"
                    className={`overlay-toggle ${overlay ? "active" : ""}`}
                    onClick={() => setOverlay(!overlay)}
                    title="Toggle overlay"
                  >
                    <span className="overlay-toggle-knob" />
                  </button>
                </div>
              </div>
            </div>

            {/* ACTION BAR — primary/secondary actions live OUTSIDE the viewer
                so they never float over the micrograph or the status bar. */}
            <div className="viewer-action-bar">
              <div className="viewer-action-bar__info">
                <span className="viewer-action-bar__file mono" title={imageMeta.name}>
                  {imageMeta.name || "—"}
                </span>
              </div>
              <div className="viewer-action-bar__actions">
                {!running && !result && (
                  <>
                    <button
                      type="button"
                      className="nodiq-button-secondary viewer-action-btn"
                      onClick={resetSelection}
                    >
                      CHANGE IMAGE
                    </button>
                    <button
                      type="button"
                      disabled={running}
                      className="nodiq-button-primary viewer-action-btn viewer-action-btn--primary"
                      onClick={startAnalysis}
                    >
                      {running ? "ANALYZING..." : "START ANALYSIS"}
                    </button>
                  </>
                )}
                {!running && result && (
                  <button
                    type="button"
                    className="nodiq-button-secondary viewer-action-btn"
                    onClick={resetSelection}
                  >
                    ANALYZE ANOTHER IMAGE
                  </button>
                )}
              </div>
            </div>

            {/* Inline error for the action above — appears where the user
                acted, not buried in the results section. */}
            {error && (
              <div
                className="analysis-card"
                role="alert"
                style={{ padding: "14px 18px", marginTop: "14px", borderLeft: "3px solid #ff6b6b", color: "var(--color-error)", fontSize: "12px" }}
              >
                {error}
              </div>
            )}
            </>
          )}
        </div>
      </section>

      {/* RESULTS */}
      <section className="results-section analysis-section-enter">
        <div style={{ display: "flex", alignItems: "center", gap: "16px", marginBottom: "28px" }}>
          <div className="results-divider" />
          <div className="results-title">
            <h2>Analysis Results</h2>
            <p>{result ? `Engine output for ${result.filename}` : "AI-generated material characterization"}</p>
          </div>
          <div className="results-divider" />
        </div>

        {running && (
          <div className="analysis-card" style={{ padding: "22px 18px", marginBottom: "24px", color: "var(--accent-cyan)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.12em" }}>
            PROCESSING — PREPROCESSING → SEGMENTATION → COUNTING → NODULARITY → SELF-CHECK… ({progress}%)
          </div>
        )}

        {!result && !running && (
          <div className="analysis-card" style={{ padding: "26px 18px", marginBottom: "24px", color: "var(--color-text-secondary)", fontSize: "12px", textAlign: "center" }}>
            Upload an image or pick a dataset micrograph — live engine results
            (nodule count, ISO/JIS nodularity, both masks and a self-check accuracy score) appear here.
          </div>
        )}

        {result && !running && (
          <>
            {/* PREPROCESSING ADVISORIES (Issue 3): quiet, non-blocking notice
                for successful preprocessing events (annotation blanking, etc.)
                — visible only when the backend reported something. */}
            {advisoryItems(result.warnings).length > 0 && (
              <div className="analysis-advisories" role="status">
                {advisoryItems(result.warnings).map((item) => (
                  <div className="analysis-advisory" key={item.raw}>
                    <span className="material-symbols-outlined analysis-advisory-icon" aria-hidden="true">
                      fact_check
                    </span>
                    <div className="analysis-advisory-text">
                      <div className="analysis-advisory-title">{item.title}</div>
                      <div className="analysis-advisory-body">{item.body}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* METRICS */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px", marginBottom: "24px" }}>
              <div className="metric-card emphasis">
                <div className="metric-label">Nodule Count</div>
                <div className="metric-value">
                  {result.nodule_count}
                  <span className="metric-unit">nodes</span>
                </div>
                <div className="metric-description">Graphite nodules detected</div>
              </div>

              <div className="metric-card emphasis">
                <div className="metric-label">Nodularity</div>
                <div className="metric-value">
                  {nodularity}
                  <span className="metric-unit">%</span>
                </div>
                <div className="metric-description">ISO 945-4 area-weighted view (in-frame {result.iso_nodularity_inframe_pct}% · JIS view {jis}%)</div>
              </div>

              <div className="metric-card">
                <div className="metric-label">JIS View</div>
                <div className="metric-value">
                  {jis}
                  <span className="metric-unit">%</span>
                </div>
                <div className="metric-description">JIS / G5502 count-weighted view of the same graphite</div>
              </div>

              <div className="metric-card">
                <div className="metric-label">Self-Check Accuracy</div>
                <div className="metric-value">
                  {selfCheck ? selfCheck.count_accuracy_pct : "—"}
                  <span className="metric-unit">%</span>
                </div>
                <div className="metric-description">
                  vs independent reference{selfCheck ? ` (ref ${selfCheck.reference_count})` : ""}
                </div>
              </div>
            </div>

            {/* GRAPHITE FORMS + PROPERTY ESTIMATES (Advancements) */}
            {(result.graphite_forms?.available || result.property_estimates?.available) && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "12px", marginBottom: "24px" }}>
                {result.graphite_forms?.available && (
                  <div className="metric-card" style={{ gridColumn: "span 1" }}>
                    <div className="metric-label">Graphite Forms (ISO 945)</div>
                    <div className="metric-value" style={{ fontSize: "18px", lineHeight: "26px" }}>
                      Form {result.graphite_forms.dominant_form}
                    </div>
                    <div className="metric-description">{result.graphite_forms.dominant_interpretation}</div>
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
                      {Object.entries(result.graphite_forms.form_count_share_pct)
                        .filter(([, pct]) => pct > 0)
                        .map(([form, pct]) => (
                          <span key={form} style={{
                            fontFamily: "var(--font-mono)", fontSize: "11px",
                            padding: "2px 8px", borderRadius: "4px",
                            background: form === result.graphite_forms.dominant_form ? "rgba(255,122,24,0.18)" : "rgba(154,166,172,0.12)",
                            color: form === result.graphite_forms.dominant_form ? "var(--color-primary-hover)" : "var(--color-text-secondary)",
                          }}>Form {form}: {pct}%</span>
                        ))}
                    </div>
                  </div>
                )}
                {result.property_estimates?.available && (
                  <div className="metric-card">
                    <div className="metric-label">Est. Properties (EN-GJS basis)</div>
                    <div className="metric-value" style={{ fontSize: "18px", lineHeight: "26px" }}>
                      {result.property_estimates.estimated_tensile_strength_mpa.estimate} MPa
                    </div>
                    <div className="metric-description">
                      Tensile ±{Math.round((result.property_estimates.estimated_tensile_strength_mpa.high - result.property_estimates.estimated_tensile_strength_mpa.estimate))} ·
                      Yield {result.property_estimates.estimated_yield_strength_mpa.estimate} MPa ·
                      A {result.property_estimates.estimated_elongation_pct.estimate}%
                    </div>
                    <div className="metric-description" style={{ marginTop: "4px", color: "var(--color-primary-hover)" }}>
                      Nearest grade: {result.property_estimates.nearest_iso_grades[0]?.grade} — estimate, not a measurement
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* AI INTELLIGENCE */}
            <div className="intelligence-panel">
              <div className="intelligence-header">
                <div className="intelligence-title">
                  <span style={{ fontSize: "12px", fontWeight: 500, color: "var(--color-text)" }}>NODIQ INTELLIGENCE</span>
                </div>
                <div className="ai-confidence">
                  <span className="ai-confidence-label">Self-Check F1</span>
                  <span className="ai-confidence-value">{selfCheck ? `${selfCheck.f1_pct}%` : "—"}</span>
                </div>
              </div>

              <div style={{ padding: "22px" }}>
                {insightText().map((insight, index) => (
                  <div key={insight.title} className="insight-item" style={{ marginTop: index === 0 ? "0" : "20px" }}>
                    <div className="insight-icon">✓</div>
                    <div>
                      <div className="insight-title">{insight.title}</div>
                      <div className="insight-description">{insight.description}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* SEGMENTATION — the two masks */}
            <div className="segmentation-panel" style={{ marginTop: "24px" }}>
              <div className="segmentation-header">
                <div>
                  <div style={{ fontSize: "12px", fontWeight: 500, color: "var(--color-text)" }}>AI SEGMENTATION</div>
                  <div style={{ marginTop: "3px", fontSize: "9px", color: "var(--color-text-tertiary)", fontFamily: "var(--font-mono)" }}>
                    BINARY MASK + CONTOUR OVERLAY
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setShowMasks((v) => !v)}
                  className={`overlay-toggle ${showMasks ? "active" : ""}`}
                  title="Toggle masks"
                  style={{ position: "relative", zIndex: 30 }}
                >
                  <span className="overlay-toggle-knob" />
                </button>
              </div>

              {showMasks && (
                <div className="segmentation-viewer">
                  <div className="segmentation-half">
                    {(result.mask_b64 || result.mask_url) && (
                      <img
                        src={result.mask_b64 || result.mask_url}
                        alt="Binary graphite mask"
                        style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000" }}
                      />
                    )}
                    <span className="segmentation-label original">Mask 1 — Binary Graphite Mask</span>
                  </div>

                  <div className="segmentation-half">
                    {(result.annotated_b64 || result.annotated_url) && (
                      <img
                        src={result.annotated_b64 || result.annotated_url}
                        alt="Contour overlay"
                        style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000" }}
                      />
                    )}
                    <div className="segmentation-grid" />
                    <span className="segmentation-label ai">Mask 2 — Contour Overlay</span>
                  </div>
                </div>
              )}
            </div>

            {/* DETECTION STATISTICS */}
            <div className="detection-statistics" style={{ marginTop: "24px" }}>
              <div className="detection-stat">
                <span className="detection-stat-label">Round Nodules (V/VI)</span>
                <span className="detection-stat-value">{roundCount}</span>
              </div>
              <div className="detection-stat">
                <span className="detection-stat-label">Irregular Nodules</span>
                <span className="detection-stat-value">{irregularCount}</span>
              </div>
              <div className="detection-stat">
                <span className="detection-stat-label">Border-Touching</span>
                <span className="detection-stat-value accent">{result.border_touching}</span>
              </div>
              <div className="detection-stat">
                <span className="detection-stat-label">Processing Time</span>
                <span className="detection-stat-value">{result.processing_time_s}s</span>
              </div>
            </div>

            {/* CHARTS */}
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(260px, 1fr)", gap: "16px", marginTop: "24px" }}>
              <div className="chart-card">
                <div className="chart-header">
                  <div style={{ fontSize: "11px", fontWeight: 500, color: "var(--color-text)" }}>
                    NODULE ROUNDNESS DISTRIBUTION
                  </div>
                  {result?.nodules?.length > 0 && (
                    <span className="chart-header__chip mono">{result.nodules.length} nodules</span>
                  )}
                </div>

                {(() => {
                  const buckets = roundnessBuckets();
                  if (!buckets.length) {
                    return <div className="chart-empty-state">No nodules detected — nothing to plot.</div>;
                  }
                  const maxCount = Math.max(...buckets.map((b) => b.count), 1);
                  const meanR = result.nodules.reduce((s, n) => s + (n.roundness ?? 0.5), 0) / result.nodules.length;
                  const gridTicks = [0.25, 0.5, 0.75, 1].map((f) => ({
                    pos: f * 100,
                    label: Math.round(maxCount * f),
                  }));
                  return (
                    <div className="histogram" role="img" aria-label="Histogram of nodule roundness from 0.0 to 1.0">
                      <div className="histogram__y-axis">
                        {gridTicks.slice().reverse().map((t) => (
                          <span key={t.pos} className="histogram__y-tick mono">{t.label}</span>
                        ))}
                      </div>

                      <div className="histogram__plot">
                        {gridTicks.map((t) => (
                          <div key={t.pos} className="histogram__gridline" style={{ bottom: `${t.pos}%` }} />
                        ))}

                        {meanR != null && (
                          <div
                            className="histogram__mean"
                            style={{ left: `${Math.min(98, Math.max(2, meanR * 100))}%` }}
                            title={`Mean roundness ${meanR.toFixed(2)}`}
                          >
                            <span className="histogram__mean-label mono">x̄ {meanR.toFixed(2)}</span>
                          </div>
                        )}

                        <div className="histogram__bars">
                          {buckets.map(({ count, pct }, bucket) => (
                            <div key={bucket} className="histogram__slot" title={`roundness ${(bucket / 10).toFixed(1)}–${((bucket + 1) / 10).toFixed(1)}: ${count} nodule${count === 1 ? "" : "s"}`}>
                              {count > 0 && (
                                <span
                                  className="histogram__count mono"
                                  style={{ bottom: `calc(${pct}% + 6px)` }}
                                >
                                  {count}
                                </span>
                              )}
                              <div
                                className={`chart-bar${count === 0 ? " chart-bar--zero" : ""}`}
                                style={{ height: count === 0 ? undefined : `${pct}%` }}
                              />
                            </div>
                          ))}
                        </div>
                      </div>

                      <div className="histogram__x-axis mono">
                        {buckets.map((_, bucket) => (
                          <span key={bucket} className="histogram__x-tick">
                            {bucket % 2 === 0 ? (bucket / 10).toFixed(1) : ""}
                          </span>
                        ))}
                        <span className="histogram__x-tick">1.0</span>
                      </div>

                      <div className="histogram__x-title mono">ROUNDNESS (0 → 1)</div>
                    </div>
                  );
                })()}
              </div>

              <div className="chart-card">
                <div style={{ marginBottom: "5px", fontSize: "11px", fontWeight: 500, color: "var(--color-text)" }}>
                  ISO NODULARITY
                </div>

                <div
                  className="matrix-donut"
                  style={{ background: `conic-gradient(#39c27f 0deg ${(nodularity * 3.6).toFixed(1)}deg, #2c363c ${(nodularity * 3.6).toFixed(1)}deg 360deg)` }}
                >
                  <div className="matrix-donut-content">
                    <span className="matrix-donut-value">{nodularity}%</span>
                    <span className="matrix-donut-label">ISO 945-9</span>
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "center", gap: "18px" }}>
                  <div className="analysis-legend-item">
                    <span className="analysis-legend-dot" style={{ background: "var(--color-success)" }} />
                    Nodular {nodularity}%
                  </div>
                  <div className="analysis-legend-item">
                    <span className="analysis-legend-dot" style={{ background: "var(--color-border)" }} />
                    {(100 - nodularity).toFixed(1)}%
                  </div>
                </div>
              </div>
            </div>

            {/* EXECUTIVE REPORT SUMMARY & FINDINGS */}
            <div
              className="analysis-report-summary-card"
              data-analysis-id={result.analysis_id}
              style={{
                marginTop: "24px",
                padding: "20px",
                background: "var(--nodiq-surface)",
                border: "1px solid var(--nodiq-border)",
                borderRadius: "7px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "10px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <span className="material-symbols-outlined" style={{ color: "var(--nodiq-cyan)", fontSize: "20px" }}>
                    summarize
                  </span>
                  <span style={{ fontSize: "12px", fontWeight: 600, letterSpacing: "0.06em", color: "var(--nodiq-text)", textTransform: "uppercase" }}>
                    Executive Report Summary & Findings
                  </span>
                  {result.analysis_id && (
                    <span style={{ fontSize: "10px", padding: "2px 8px", background: "rgba(0,188,212,0.12)", color: "var(--nodiq-cyan)", borderRadius: "4px", fontFamily: "var(--font-mono)" }}>
                      {result.analysis_id}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{
                    fontSize: "10px",
                    padding: "3px 9px",
                    borderRadius: "4px",
                    fontWeight: 600,
                    background: nodularity >= 80 ? "rgba(57,194,127,0.15)" : "rgba(255,160,0,0.15)",
                    color: nodularity >= 80 ? "var(--nodiq-green)" : "#ffa000",
                    border: nodularity >= 80 ? "1px solid rgba(57,194,127,0.3)" : "1px solid rgba(255,160,0,0.3)"
                  }}>
                    {nodularity >= 80 ? "ISO 945 Type V/VI Compliant" : "Sub-Optimal Nodularity"}
                  </span>
                </div>
              </div>

              <div className="report-summary-body" style={{ fontSize: "13px", lineHeight: "1.6", color: "var(--color-text)", background: "rgba(10, 20, 24, 0.6)", padding: "14px 16px", borderRadius: "5px", border: "1px solid var(--nodiq-border-light)" }}>
                {summaryLoading ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", color: "var(--nodiq-text-muted)" }}>
                    <span className="material-symbols-outlined spinning" style={{ fontSize: "16px" }}>progress_activity</span>
                    <span>Synthesizing metallurgical report summary and AI findings...</span>
                  </div>
                ) : (
                  <div className="report-summary-text" style={{ whiteSpace: "pre-line" }}>
                    {reportSummary || (
                      `MEASURED: ${nodularity}% ISO nodularity across ${result.nodule_count ?? 0} graphite particles in ${result.filename || "specimen"}. OBSERVED: ${roundCount} spheroidal nodules (Type V/VI) detected. INTERPRETATION: Microstructure meets industrial ductile cast iron nodularity requirements. RECOMMENDATION: Ready to export formal metallurgical engineering report.`
                    )}
                  </div>
                )}
              </div>

              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "12px", fontSize: "11px", color: "var(--nodiq-text-muted)", flexWrap: "wrap", gap: "8px" }}>
                <span>Standardized evaluation compliant with ISO 945-4 / ASTM E2567 criteria.</span>
                <button
                  type="button"
                  onClick={() => {
                    const textToCopy = reportSummary || `MEASURED: ${nodularity}% ISO nodularity across ${result.nodule_count ?? 0} particles in ${result.filename || "specimen"}.`;
                    navigator.clipboard?.writeText(textToCopy);
                  }}
                  style={{
                    background: "transparent",
                    border: "1px solid var(--nodiq-border-light)",
                    color: "var(--nodiq-text-muted)",
                    padding: "4px 10px",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "11px",
                    display: "flex",
                    alignItems: "center",
                    gap: "4px"
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>content_copy</span>
                  Copy Summary
                </button>
              </div>
            </div>

            {/* COMPLETION */}
            <div className="completion-panel">
              <div className="completion-status">
                <div className="completion-icon success-pulse">✓</div>
                <div>
                  <div className="completion-title">
                    Analysis completed successfully{result.analysis_id ? ` — ${result.analysis_id}` : ""}
                  </div>
                  <div className="completion-description">
                    Saved to My Analyses. Generate a report to export the results.
                  </div>
                </div>
              </div>

              <button
                type="button"
                className="generate-report-button"
                onClick={() =>
                  navigate("/reports/generate", {
                    state: {
                      analysisId: result.analysis_id,
                      analysis: result,
                      reportTitle: `NODIQ-X ${result.filename || "Specimen"} Nodularity Report`,
                      sampleId: result.analysis_id,
                    },
                  })
                }
                style={{ padding: "11px 20px", borderRadius: "4px", fontSize: "11px", fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap" }}
              >
                GENERATE REPORT
              </button>
            </div>
          </>
        )}
      </section>
    </main>
  );
};

export default Analysis;
