import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import {
  captureImage,
  getCameraStatus,
  quickQualityCheck,
  startLivePreview,
} from "../services/microscopeAgent";
import "./Analysis.css";
import "./WhiteCastIronAnalysis.css";

/* White Cast Iron — Carbide Analysis (CARDE Classical Top-Hat & Otsu Pipeline)
   Submits to /api/analyze with analysis_type=white_cast_iron_carbide and
   method=carde_otsu. Strictly independent from graphite nodularity and steel pipelines.
*/

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_MS = 10 * 60 * 1000;

const fmt = (v, digits = 2) =>
  v === undefined || v === null || Number.isNaN(v) ? "—" : Number(v).toFixed(digits);

const WhiteCastIronAnalysis = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const previewRef = useRef(null);
  const runningRef = useRef(false);

  // method + engines
  const method = "carde_otsu";
  const [engineInfo, setEngineInfo] = useState(null);

  // input
  const [pendingFile, setPendingFile] = useState(null);
  const [imageUrl, setImageUrl] = useState("");
  const [imageMeta, setImageMeta] = useState({ width: 0, height: 0, name: "", sizeKb: 0 });
  const [inputSource, setInputSource] = useState("upload");
  const [dragActive, setDragActive] = useState(false);
  const [inputError, setInputError] = useState("");

  // viewer controls
  const [zoom, setZoom] = useState(1);
  const [overlay, setOverlay] = useState(true);
  const zoomIn = () => setZoom((prev) => Math.min(prev + 0.1, 2));
  const zoomOut = () => setZoom((prev) => Math.max(prev - 0.1, 0.5));
  const resetZoom = () => setZoom(1);

  // calibration
  const [umPerPx, setUmPerPx] = useState("");

  // camera integration
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraStatus, setCameraStatus] = useState(null);
  const [cameraError, setCameraError] = useState("");
  const [capturing, setCapturing] = useState(false);
  const [captureNotice, setCaptureNotice] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [, setPreviewState] = useState("off");

  // run state
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [resultId, setResultId] = useState("");
  const [artifactUrls, setArtifactUrls] = useState({});
  const [activeArtifact, setActiveArtifact] = useState("");
  const [sideBySide, setSideBySide] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState("");

  /* ---------------- engine availability ---------------- */
  useEffect(() => {
    api
      .whiteCastIronEngines()
      .then((data) => setEngineInfo(data?.carde || null))
      .catch(() => setEngineInfo(null));
  }, []);

  const openImagePicker = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
      fileInputRef.current.click();
    }
  };

  /* ---------------- file validation ---------------- */
  const validateAndSetFile = (file, source = "upload") => {
    setInputError("");
    setError("");
    if (!file) return;
    const okType = /\.(png|jpe?g|bmp|tiff?)$/i.test(file.name);
    if (!okType) {
      setInputError("Please select a standard image file (PNG, JPG, BMP, TIFF).");
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      setImageMeta({
        width: img.naturalWidth,
        height: img.naturalHeight,
        name: file.name,
        sizeKb: Math.round(file.size / 1024) || 0,
      });
      setImageUrl(url);
      setPendingFile(file);
      setInputSource(source);
      setResult(null);
      setArtifactUrls({});
      setZoom(1);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      setInputError("Could not read this image file.");
    };
    img.src = url;
  };

  const handleFileDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) validateAndSetFile(file, "upload");
  };

  const resetSelection = () => {
    setPendingFile(null);
    setImageUrl("");
    setImageMeta({ width: 0, height: 0, name: "", sizeKb: 0 });
    setResult(null);
    setResultId("");
    setArtifactUrls({});
    setError("");
    setInputError("");
    setZoom(1);
  };

  /* ---------------- microscope integration ---------------- */
  const refreshCameraStatus = async () => {
    try {
      const s = await getCameraStatus();
      setCameraStatus(s);
      setCameraError("");
    } catch (e) {
      setCameraStatus(null);
      setCameraError(e.message || "Microscope agent unreachable");
    }
  };

  const stopPreview = () => {
    if (previewRef.current) {
      previewRef.current.stop();
      previewRef.current = null;
    }
    setPreviewState("off");
    setPreviewUrl("");
  };

  const startPreviewLoop = () => {
    stopPreview();
    setPreviewState("connecting");
    previewRef.current = startLivePreview({
      onFrame: (url) => {
        setPreviewUrl(url);
        setPreviewState("live");
      },
      onStateChange: (state, err) => {
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
      startPreviewLoop();
    } else {
      stopPreview();
    }
  };

  useEffect(() => () => previewRef.current?.stop(), []);

  const captureFromMicroscope = async () => {
    setCapturing(true);
    setCameraError("");
    setCaptureNotice("Capturing…");
    try {
      const file = await captureImage();
      const check = await quickQualityCheck(file);
      const ready = "Capture ready — press RUN CARBIDE ANALYSIS to analyze.";
      setCaptureNotice(check.hint ? `${check.hint} ${ready}` : `✓ ${ready}`);
      stopPreview();
      setCameraOpen(false);
      validateAndSetFile(file, "microscope");
    } catch (e) {
      setCaptureNotice("");
      setCameraError(e.message || "Capture failed");
    } finally {
      setCapturing(false);
    }
  };

  /* ---------------- run + poll ---------------- */
  const calibrationValue = () => {
    const raw = String(umPerPx || "").trim();
    if (!raw) return undefined;
    const val = Number(raw);
    if (!Number.isFinite(val) || val <= 0) return "invalid";
    return val;
  };

  const applyResult = (detail, id) => {
    const analysis = detail.analysis || detail;
    setResult(analysis);
    setResultId(id);
    setError("");
    const kinds = (analysis.artifacts || []).map((a) => a.kind);
    const urls = {};
    kinds.forEach((kind) => {
      const path = analysis[`${kind}_url`] || `/api/analyses/${id}/artifact/${kind}`;
      api
        .fetchImage(path)
        .then((blobUrl) => {
          setArtifactUrls((prev) => ({ ...prev, [kind]: blobUrl }));
        })
        .catch(() => {
          setArtifactUrls((prev) => ({ ...prev, [kind]: null }));
        });
    });
    setArtifactUrls(urls);
    if (kinds.length) setActiveArtifact((prev) => prev || kinds[0]);
  };

  const startAnalysis = async () => {
    if (runningRef.current || running) return;
    if (!pendingFile) {
      setError("Select a micrograph first — upload a file or pick from dataset.");
      return;
    }
    const cal = calibrationValue();
    if (cal === "invalid") {
      setError("Calibration must be a positive number of micrometres per pixel (or left empty for pixel-only).");
      return;
    }
    if (engineInfo && !engineInfo.available) {
      setError(`CARDE engine is unavailable: ${engineInfo.hint || "Check environment"}`);
      return;
    }
    runningRef.current = true;
    setRunning(true);
    setProgress(10);
    setError("");
    setReportError("");
    setResult(null);
    setArtifactUrls({});
    try {
      const resp = await api.analyzeUpload(pendingFile, {
        analysisType: "white_cast_iron_carbide",
        method,
        micronsPerPixel: cal,
        inputSource,
      });
      const pollId = resp?.analysis_id;
      if (!pollId || resp?.status !== "processing") {
        applyResult({ analysis: resp }, pollId || "wci-sync");
        setProgress(100);
        return;
      }
      const deadline = Date.now() + POLL_MAX_MS;
      let done = false;
      while (!done && Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        const detail = await api.analysisDetail(pollId);
        const status = detail?.status || detail?.record?.status;
        if (status === "completed" && detail.analysis) {
          applyResult(detail, pollId);
          setProgress(100);
          done = true;
        } else if (status === "failed") {
          throw new Error(detail?.error || detail?.record?.error || "Analysis failed on the server.");
        } else {
          setProgress(detail?.progress || detail?.record?.progress || 40);
        }
      }
      if (!done) {
        throw new Error("Analysis is taking unusually long — check My Analyses in a few minutes.");
      }
    } catch (e) {
      setError(e.message || "Analysis failed");
    } finally {
      runningRef.current = false;
      setRunning(false);
      setProgress(0);
    }
  };

  const generateReport = async () => {
    if (!resultId) return;
    setReportBusy(true);
    setReportError("");
    try {
      const report = await api.generateReport({ analysis_id: resultId });
      if (report?.id) navigate(`/reports/${report.id}`);
      else throw new Error("Report generation returned no report id.");
    } catch (e) {
      setReportError(e.message || "Report generation failed");
    } finally {
      setReportBusy(false);
    }
  };

  const wci = result?.white_cast_iron || {};
  const meas = wci.measurements || {};
  const cal = result?.calibration || {};
  const exp = wci.experimental_interpretations || {};
  const artifacts = result?.artifacts || [];

  return (
    <main className="analysis-page white-cast-iron-page">
      {/* Hidden native file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple={false}
        onChange={(e) => validateAndSetFile(e.target.files?.[0], "upload")}
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

      {/* PAGE HEADER (matching Image 1) */}
      <section className="analysis-section-enter">
        <div style={{ display: "flex", alignItems: "center", gap: "14px", marginBottom: "8px" }}>
          <div className="analysis-header-accent" />
          <div>
            <div className="analysis-eyebrow">NODIQ-X / MATERIAL INTELLIGENCE</div>
            <h1 style={{ margin: "6px 0 0", fontSize: "30px", fontWeight: 600, color: "var(--color-text)" }}>
              White Cast Iron — Carbide Analysis
            </h1>
          </div>
        </div>
        <p style={{ margin: "0 0 28px 19px", color: "var(--color-text-secondary)", fontSize: "13px" }}>
          AI-powered carbide precipitate segmentation and matrix characterization on the CARDE classical engine
        </p>
      </section>

      {/* INPUT WORKSPACE CARD (Image 1 Blueprint) */}
      <section className="analysis-card analysis-section-enter" style={{ marginBottom: "32px" }}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #252e33", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: "12px", fontWeight: 500, color: "var(--color-text)" }}>INPUT WORKSPACE</div>
            <div style={{ marginTop: "3px", fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--color-text-tertiary)" }}>
              MICROSTRUCTURE IMAGE ACQUISITION
            </div>
          </div>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: running ? "var(--color-primary, #FF7A18)" : result ? "var(--color-success, #39C27F)" : (pendingFile || imageUrl) ? "var(--color-primary, #FF7A18)" : "var(--color-text-tertiary)" }}>
            {running ? "ANALYZING..." : result ? "ANALYSIS COMPLETE" : (pendingFile || imageUrl) ? "READY TO ANALYZE" : "WAITING FOR INPUT"}
          </span>
        </div>

        {/* Camera capture quality hint */}
        {captureNotice && (
          <div role="status" style={{ margin: "14px 18px 0", padding: "8px 12px", fontSize: "11px", lineHeight: 1.5, color: "var(--color-text-secondary)", border: "1px solid #252e33", borderRadius: "6px", background: "var(--color-bg-2)" }}>
            {captureNotice}
          </div>
        )}

        <div style={{ padding: "18px" }}>
          {!pendingFile && !imageUrl ? (
            <>
              {/* IMAGE 1: UPLOAD ZONE */}
              <div
                className={`upload-zone${dragActive ? " drag-active" : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={() => setDragActive(false)}
                onDrop={handleFileDrop}
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
                    Upload a metallographic image to segment carbide precipitates and matrix constituents.
                  </p>

                  <p style={{ margin: "8px 0 22px", fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--color-text-tertiary)" }}>
                    SUPPORTED: JPG / PNG &nbsp;•&nbsp; MAX 25 MB &nbsp;•&nbsp; OR DROP A FILE ON THIS ZONE
                  </p>

                  <button
                    type="button"
                    className="nodiq-button-primary"
                    onClick={openImagePicker}
                  >
                    SELECT IMAGE
                  </button>

                  <div style={{ marginTop: "15px", fontSize: "10px", color: "var(--color-text-tertiary)" }}>
                    or drag &amp; drop your file here
                  </div>

                  {/* Actions Row: Microscope */}
                  <div style={{ marginTop: "18px", display: "flex", gap: "10px", justifyContent: "center", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      onClick={toggleCameraPanel}
                      aria-expanded={cameraOpen}
                      style={{
                        background: cameraOpen ? "rgba(255,122,24,0.1)" : "transparent",
                        border: "1px solid " + (cameraOpen ? "#FF7A18" : "#2c363c"),
                        color: cameraOpen ? "#FF7A18" : "var(--color-text-secondary)",
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
                </div>
              </div>

              {/* Microscope Live Camera Panel */}
              {cameraOpen && (
                <div
                  role="region"
                  aria-label="Microscope camera"
                  style={{
                    marginTop: "18px",
                    width: "100%",
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
                      {cameraStatus?.connected ? "● Connected" : "○ Camera disconnected"}
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

                  {cameraStatus?.connected && (
                    <>
                      <div style={{ fontSize: "11px", lineHeight: 1.6, color: "var(--color-text-secondary)", marginBottom: "10px" }}>
                        Camera: <b style={{ color: "var(--color-text)" }}>{cameraStatus.model}</b>
                        {cameraStatus.serial ? <> · S/N {cameraStatus.serial}</> : null}
                      </div>

                      <div
                        style={{
                          position: "relative",
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
                            Connecting live preview…
                          </div>
                        )}
                        {capturing && (
                          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(10,14,16,0.65)", fontSize: "12px", fontWeight: 600, color: "#FF7A18", letterSpacing: "0.08em" }}>
                            CAPTURING FRAME…
                          </div>
                        )}
                      </div>
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
                      border: "1px solid #FF7A18",
                      background: "rgba(255,122,24,0.12)",
                      color: "#FF7A18",
                      fontSize: "11px",
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      cursor: capturing || !cameraStatus?.connected ? "not-allowed" : "pointer",
                      opacity: capturing || !cameraStatus?.connected ? 0.55 : 1,
                    }}
                  >
                    {capturing ? "CAPTURING…" : "CAPTURE FRAME"}
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              {/* MICROSTRUCTURE VIEWER (Image Loaded) */}
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
                      {imageUrl && (
                        <img
                          src={(overlay && artifactUrls.overlay) ? artifactUrls.overlay : imageUrl}
                          alt="White cast iron microstructure"
                          style={{ display: "block", maxWidth: "80vw", maxHeight: "420px", objectFit: "contain", background: "#111", opacity: running ? 0.4 : 1 }}
                        />
                      )}
                    </div>
                  </div>
                </div>

                {running && (
                  <div style={{
                    position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: "10px", alignItems: "center", justifyContent: "center",
                    fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-primary, #FF7A18)",
                    letterSpacing: "0.14em", pointerEvents: "none", background: "rgba(10,14,16,0.65)",
                  }}>
                    <span>CARBIDE PRECIPITATE SEGMENTATION RUNNING…</span>
                    <div style={{ width: "220px", height: "4px", borderRadius: "2px", background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                      <div style={{
                        width: `${progress}%`, height: "100%",
                        background: "linear-gradient(90deg, #FF7A18, #39c27f)",
                        transition: "width 0.6s ease-in-out",
                      }} />
                    </div>
                    <span style={{ fontSize: "10px", color: "var(--color-text-tertiary)" }}>{progress}% — CARDE Otsu &amp; Top-Hat pipeline</span>
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
                      title="Toggle reticle"
                    >
                      <span className="overlay-toggle-knob" />
                    </button>
                  </div>
                </div>
              </div>

              {/* ACTION & CALIBRATION BAR */}
              <div className="wci-action-bar">
                <div className="wci-action-bar-left">
                  <span className="viewer-action-bar__file mono" title={imageMeta.name}>
                    {imageMeta.name || "micrograph.png"}
                  </span>
                  <div className="wci-calibration-box">
                    <span style={{ fontSize: "11px", fontWeight: 500, color: "var(--color-text-secondary)" }}>
                      Scale (µm / pixel):
                    </span>
                    <input
                      type="number"
                      step="any"
                      min="0.0001"
                      placeholder="e.g. 0.45"
                      value={umPerPx}
                      onChange={(e) => setUmPerPx(e.target.value)}
                      className="wci-calibration-input"
                    />
                    <span style={{ fontSize: "10px", color: "var(--color-text-tertiary)" }}>(Optional)</span>
                  </div>
                  <div style={{ fontSize: "11px", color: engineInfo?.available ? "var(--color-success)" : "var(--color-text-tertiary)" }}>
                    ● CARDE Classical Engine: {engineInfo?.available ? "Ready" : "Checking…"}
                  </div>
                </div>

                <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                  {!running && !result && (
                    <>
                      <button
                        type="button"
                        className="nodiq-button-secondary"
                        onClick={resetSelection}
                        style={{ padding: "8px 16px", borderRadius: "4px", fontSize: "11px", fontWeight: 600, cursor: "pointer" }}
                      >
                        CHANGE IMAGE
                      </button>
                      <button
                        type="button"
                        disabled={running}
                        className="nodiq-button-primary"
                        onClick={startAnalysis}
                      >
                        {running ? "ANALYZING..." : "RUN CARBIDE ANALYSIS"}
                      </button>
                    </>
                  )}
                  {!running && result && (
                    <button
                      type="button"
                      className="nodiq-button-secondary"
                      onClick={resetSelection}
                      style={{ padding: "8px 16px", borderRadius: "4px", fontSize: "11px", fontWeight: 600, cursor: "pointer" }}
                    >
                      ANALYZE ANOTHER MICROGRAPH
                    </button>
                  )}
                </div>
              </div>
            </>
          )}

          {/* Action error */}
          {(error || inputError) && (
            <div
              className="analysis-card"
              role="alert"
              style={{ padding: "12px 16px", marginTop: "14px", borderLeft: "3px solid #ef4444", color: "#ef4444", fontSize: "12px", background: "rgba(239,68,68,0.06)" }}
            >
              {error || inputError}
            </div>
          )}
        </div>
      </section>

      {/* RESULTS SECTION (Exact Image 1 Divider & Layout) */}
      <section className="results-section analysis-section-enter">
        <div style={{ display: "flex", alignItems: "center", gap: "16px", marginBottom: "28px" }}>
          <div className="results-divider" />
          <div className="results-title">
            <h2>Analysis Results</h2>
            <p>{result ? `Engine output for ${imageMeta.name || result.filename}` : "AI-generated material characterization"}</p>
          </div>
          <div className="results-divider" />
        </div>

        {running && (
          <div className="analysis-card" style={{ padding: "22px 18px", marginBottom: "24px", color: "var(--color-primary, #FF7A18)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.12em" }}>
            PROCESSING — PREPROCESSING → TOP-HAT FILTERING → OTSU THRESHOLDING → MORPHOLOGICAL ANALYSIS… ({progress}%)
          </div>
        )}

        {!result && !running && (
          <div className="analysis-card" style={{ padding: "32px 20px", marginBottom: "24px", color: "var(--color-text-secondary)", fontSize: "12px", textAlign: "center" }}>
            Upload an image or capture via microscope — live engine results
            (carbide count, area fraction %, mean equivalent diameter, visual masks and engineering report) appear here.
          </div>
        )}

        {result && !running && (
          <section className="analysis-card" style={{ padding: "20px 24px", marginBottom: "32px" }}>
            {/* Results Header */}
            <div className="wci-results-header">
              <div>
                <h3 style={{ fontSize: "18px", margin: "0 0 4px 0", color: "var(--color-text)" }}>
                  Carbide Analysis Results
                </h3>
                <div style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>
                  ANALYSIS ID: <strong style={{ color: "var(--color-primary, #FF7A18)" }}>{resultId || "WCI-ANALYSIS"}</strong> &nbsp;|&nbsp;
                  RESOLUTION: {result.source_width || imageMeta.width} × {result.source_height || imageMeta.height} PX &nbsp;|&nbsp;
                  METHOD: CARDE Classical Otsu
                </div>
              </div>

              <div>
                <button
                  type="button"
                  className="nodiq-button-primary"
                  onClick={generateReport}
                  disabled={reportBusy}
                >
                  {reportBusy ? "GENERATING REPORT…" : "GENERATE ENGINEERING REPORT"}
                </button>
              </div>
            </div>

            {reportError && (
              <div style={{ color: "#ef4444", marginBottom: "14px", fontSize: "12px" }}>{reportError}</div>
            )}

            {/* Metallurgical Honesty / Validation Advisory */}
            <div className="wci-advisory-box">
              <strong style={{ color: "var(--color-primary, #FF7A18)" }}>Metallurgical Validation Notice: </strong>
              {wci.validation_status || "EXPERIMENTAL / UNVALIDATED on white cast iron micrographs."}
              <div style={{ marginTop: "4px", fontSize: "11px", color: "var(--color-text-tertiary)" }}>
                Otsu top-hat thresholding distinguishes high-contrast precipitates from the matrix. It does <strong>NOT</strong> confirm cementite stoichiometry or ledeburite eutectic fractions.
              </div>
            </div>

            {/* KPI Metric Cards */}
            <div className="wci-kpi-grid">
              <div className="wci-kpi-card">
                <div className="wci-kpi-label">Carbide Count</div>
                <div className="wci-kpi-value" style={{ color: "var(--color-primary, #FF7A18)" }}>
                  {fmt(wci.carbide_count, 0)}
                </div>
                <div className="wci-kpi-sub">Segmented regions</div>
              </div>

              <div className="wci-kpi-card">
                <div className="wci-kpi-label">Area Fraction</div>
                <div className="wci-kpi-value" style={{ color: "var(--color-primary, #FF7A18)" }}>
                  {fmt(meas.area_fraction_pct, 2)}%
                </div>
                <div className="wci-kpi-sub">Of field of view</div>
              </div>

              <div className="wci-kpi-card">
                <div className="wci-kpi-label">Total Carbide Area</div>
                <div className="wci-kpi-value">
                  {fmt(meas.total_area_px2, 0)} <span style={{ fontSize: "13px", fontWeight: 400 }}>px²</span>
                </div>
                <div className="wci-kpi-sub">
                  {cal.available ? `${fmt(meas.total_area_um2, 1)} µm²` : "Physical scale unavailable"}
                </div>
              </div>

              <div className="wci-kpi-card">
                <div className="wci-kpi-label">Mean Equiv Diameter</div>
                <div className="wci-kpi-value">
                  {fmt(meas.mean_equiv_diameter_px, 2)} <span style={{ fontSize: "13px", fontWeight: 400 }}>px</span>
                </div>
                <div className="wci-kpi-sub">
                  {cal.available ? `${fmt(meas.mean_equiv_diameter_um, 2)} µm` : "Physical scale unavailable"}
                </div>
              </div>

              <div className="wci-kpi-card">
                <div className="wci-kpi-label">Mean Solidity</div>
                <div className="wci-kpi-value">
                  {fmt(meas.mean_solidity, 3)}
                </div>
                <div className="wci-kpi-sub">Region convex ratio</div>
              </div>
            </div>

            {/* Experimental Metallurgical Interpretations */}
            <div style={{ background: "var(--color-bg-3)", border: "1px solid var(--color-border)", borderRadius: "6px", padding: "14px 18px", marginBottom: "22px" }}>
              <div style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "8px" }}>
                Experimental Metallurgical Interpretation (Non-Validated)
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", fontSize: "12px", color: "var(--color-text-secondary)" }}>
                <div>
                  <strong>Cementite Identification: </strong>
                  <span style={{ color: "var(--color-text)" }}>{exp.cementite_identification || "UNVALIDATED / NOT IDENTIFIED"}</span>
                </div>
                <div>
                  <strong>Ledeburite Phase Eutectic: </strong>
                  <span style={{ color: "var(--color-text)" }}>{exp.ledeburite_presence || "UNVALIDATED / NOT IDENTIFIED"}</span>
                </div>
              </div>
            </div>

            {/* Visual Segmentation Artifacts */}
            {artifacts.length > 0 && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px", flexWrap: "wrap", gap: "10px" }}>
                  <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--color-text)" }}>
                    Visual Segmentation Artifacts
                  </div>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    {artifacts.map((a) => (
                      <button
                        key={a.kind}
                        type="button"
                        className={`wci-artifact-tab ${activeArtifact === a.kind ? "active" : ""}`}
                        onClick={() => setActiveArtifact(a.kind)}
                      >
                        {a.label}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="wci-artifact-tab"
                      onClick={() => setSideBySide(!sideBySide)}
                    >
                      {sideBySide ? "Single View" : "Side-by-Side"}
                    </button>
                  </div>
                </div>

                {sideBySide ? (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px" }}>
                    <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "6px", padding: "12px" }}>
                      <div style={{ fontSize: "11px", marginBottom: "6px", fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>
                        ORIGINAL MICROGRAPH
                      </div>
                      {imageUrl && <img src={imageUrl} alt="Original" style={{ width: "100%", borderRadius: "4px", display: "block" }} />}
                    </div>
                    <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "6px", padding: "12px" }}>
                      <div style={{ fontSize: "11px", marginBottom: "6px", fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>
                        {artifacts.find((a) => a.kind === activeArtifact)?.label || "SEGMENTATION"}
                      </div>
                      {artifactUrls[activeArtifact] ? (
                        <img src={artifactUrls[activeArtifact]} alt="Artifact" style={{ width: "100%", borderRadius: "4px", display: "block" }} />
                      ) : (
                        <div style={{ padding: "60px", textAlign: "center", color: "var(--color-text-tertiary)" }}>Loading artifact…</div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "6px", padding: "16px", textAlign: "center" }}>
                    {artifactUrls[activeArtifact] ? (
                      <img
                        src={artifactUrls[activeArtifact]}
                        alt="Active Artifact"
                        style={{ maxHeight: "520px", maxWidth: "100%", borderRadius: "4px", margin: "0 auto", display: "block" }}
                      />
                    ) : (
                      <div style={{ padding: "80px", color: "var(--color-text-tertiary)" }}>Loading visual artifact…</div>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        )}
      </section>
    </main>
  );
};

export default WhiteCastIronAnalysis;
