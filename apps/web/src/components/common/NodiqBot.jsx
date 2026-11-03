import React, { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import voiceAgent, { isInterruptionCommand, WAKE_WORDS } from "../../services/voiceAgent";
import nodiqIntentEngine from "../../services/nodiqIntentEngine";
import goalPlanner from "../../services/goalPlanner";
import voiceDiagnostics from "../../services/voiceDiagnostics";
import PhraseSegmenter from "../../services/phraseSegmenter";
import "./NodiqBot.css";

const BENCHMARK_SPECIMENS = [
  {
    filename: "micrograph_0001.png",
    label: "Specimen #0001",
    grade: "ISO 945 Class V/VI",
    details: "High nodularity benchmark (78.4% JIS nodularity)",
  },
  {
    filename: "micrograph_0004.png",
    label: "Specimen #0004",
    grade: "EN-GJS-500-7",
    details: "Standard industrial casting (61.0% ISO nodularity, 43 nodules)",
  },
  {
    filename: "micrograph_0012.png",
    label: "Specimen #0012",
    grade: "ASTM A536 80-55-06",
    details: "Ductile iron sample with fine graphite distribution",
  },
  {
    filename: "micrograph_0025.png",
    label: "Specimen #0025",
    grade: "EN-GJS-400-15",
    details: "Ferritic ductile iron verification sample",
  },
];

const AI_SUGGESTIONS = [
  { label: "Analyze Nodularity", icon: "🔬", cmd: "Run nodularity analysis on specimen" },
  { label: "Set Scale 100 μm", icon: "📏", cmd: "Set optical scale to 100 micrometers" },
  { label: "Check ASTM A536", icon: "📊", cmd: "Check ASTM A536 classification" },
  { label: "Executive Briefing", icon: "📑", cmd: "Generate executive briefing report" },
];

// Helper to parse unstructured report text into clean executive briefing card data
function parseExecutiveReport(text, structuredData = null) {
  if (structuredData && structuredData.isReportSummary) {
    return structuredData;
  }
  if (!text || typeof text !== "string") return null;

  const hasExecutivePattern =
    text.includes("Executive Summary") ||
    text.includes("Report Briefing") ||
    text.includes("Metallurgical evaluation:") ||
    text.includes("Acceptance Verdict") ||
    text.includes("CONFORMITY INDEX") ||
    text.includes("MEASURED:") ||
    /ANL-[A-Z0-9]{6}/.test(text);

  if (!hasExecutivePattern) return null;

  // Extract Analysis ID
  const analysisMatch = text.match(/ANL-[A-Z0-9]{6}/i);
  const analysisId = analysisMatch ? analysisMatch[0] : "";

  // Extract Conformity
  const conformityMatch =
    text.match(/CONFORMITY INDEX:?\s*([0-9.]+%?)/i) ||
    text.match(/Conformity(?:\s*Index)?:?\s*([0-9.]+%?)/i);
  const conformity = conformityMatch ? conformityMatch[1] : "";

  // Extract Verdict
  const verdictMatch =
    text.match(/Acceptance Verdict:\s*([^.\n]+?\([^)]+\)\.)/i) ||
    text.match(/Acceptance Verdict:\s*([^.\n]+?(?:\.[0-9]+%[^.\n]*?)?\.)/i) ||
    text.match(/Acceptance Verdict:\s*([^.\n]+)/i);
  const verdict = verdictMatch ? verdictMatch[1].replace(/\.$/, "").trim() : "";

  // Extract Target Application
  const targetAppMatch =
    text.match(/Target Application:\s*([^.\n]+(?:\.[^.\n]+)?)/i) ||
    text.match(/Recommended for\s*([^.\n]+)/i);
  const targetApplication = targetAppMatch ? targetAppMatch[1].replace(/\.$/, "").trim() : "";

  // Extract Findings / Evaluation
  let findings = "";
  if (text.includes("Metallurgical evaluation:") || text.includes("Evaluation finding:")) {
    let afterEval = text.includes("Metallurgical evaluation:")
      ? text.split("Metallurgical evaluation:")[1]
      : text.split("Evaluation finding:")[1];

    if (verdictMatch) {
      afterEval = afterEval.replace(verdictMatch[0], "");
    }

    findings = afterEval
      .replace(/\b(gavel|check_circle|verified|warning|insights|science|summarize)\b/gi, "")
      .replace(/ACCEPTANCE VERDICT & LOT DISPOSITION/gi, "")
      .replace(/[-·]?\s*CONFORMITY INDEX:?\s*[0-9.]+%?/gi, "")
      .replace(/Acceptance Verdict:\s*[^.]+\./gi, "")
      .replace(/Target Application:\s*[^.]+\.?/gi, "")
      .replace(/Recommended for\s*[^.]+\.?/gi, "")
      .replace(/\s+/g, " ")
      .trim();
  } else if (text.includes("INTERPRETATION:")) {
    const interpMatch = text.match(/INTERPRETATION:\s*([^.\n]+(?:\.[^.\n]+)?)/i);
    if (interpMatch) findings = interpMatch[1].trim();
  }

  // Extract Title / Specimen
  let title = "Industrial Metallurgical Report";
  const titleMatch = text.match(/report being generated for\s+([^()]+?)(?:\s*\(|$)/i) ||
                     text.match(/Executive Summary for\s+([^()]+?)(?:\s*\(|$)/i);
  if (titleMatch) {
    title = titleMatch[1].replace(/^ANL-[A-Z0-9]{6}\s*—\s*/i, "").trim();
  } else if (text.includes("Gray Cast Iron")) {
    title = "Gray Cast Iron — Detailed Technical Report";
  } else if (text.includes("Nodular") || text.includes("Ductile")) {
    title = "Ductile Cast Iron Nodularity Report";
  } else if (text.includes("Steel")) {
    title = "Steel Grain-Size Analysis Report";
  }

  // Extract Metrics
  const metrics = [];
  if (conformity) metrics.push({ label: "Conformity", value: conformity });

  const nodMatch = text.match(/(?:nodularity|ISO nodularity)[:\s]*([0-9.]+%)/i);
  if (nodMatch) metrics.push({ label: "Nodularity", value: nodMatch[1] });

  const countMatch = text.match(/(\d+)\s*(?:graphite nodules|nodules|flakes|particles)/i);
  if (countMatch) metrics.push({ label: "Particle Count", value: countMatch[1] });

  const accMatch = text.match(/accuracy[:\s]*([0-9.]+%)/i);
  if (accMatch) metrics.push({ label: "Accuracy", value: accMatch[1] });

  const qualMatch = text.match(/quality[:\s]*([0-9]+(?:\/100)?%?)/i);
  if (qualMatch) metrics.push({ label: "Quality", value: qualMatch[1].includes("/") ? qualMatch[1] : `${qualMatch[1]}/100` });

  return {
    isReportSummary: true,
    title,
    analysisId,
    sampleId: analysisId || "Specimen",
    status: text.includes("READY") ? "READY" : text.includes("COMPLIANT") ? "COMPLIANT" : "APPROVED",
    conformity,
    verdict: verdict || (conformity ? `Conformity Index: ${conformity}` : "ISO Standard Compliant"),
    findings: findings || "Microstructure demonstrates standard compliance with verified metallurgical criteria.",
    targetApplication,
    metrics: metrics.slice(0, 4),
  };
}

const NodiqBot = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const [hudOpen, setHudOpen] = useState(false);
  const [agentState, setAgentState] = useState("idle"); // idle | listening | thinking | speaking
  const [transcript, setTranscript] = useState("");
  const [lastAction, setLastAction] = useState("");
  const [botReply, setBotReply] = useState(
    "Nodiq-X Voice Intelligence online. Ready for metallurgical commands, workspace navigation, and microstructure analysis."
  );
  const [reportBriefingData, setReportBriefingData] = useState(null);
  const [copiedBriefing, setCopiedBriefing] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [handsFree, setHandsFree] = useState(true);
  const [customInput, setCustomInput] = useState("");
  const [imageModalOpen, setImageModalOpen] = useState(false);

  const hudRef = useRef(null);
  const executeCommandRef = useRef(null);
  const requestGenerationRef = useRef(0);
  const abortControllerRef = useRef(null);
  const sessionIdRef = useRef(`nodiq-voice-${Date.now()}`);
  const historyRef = useRef([]);
  const conversationActiveRef = useRef(0);

  // Sync navigator with goal planner on location changes
  useEffect(() => {
    goalPlanner.setNavigator(navigate, location);
  }, [navigate, location]);

  // Tab visibility guard: if tab is hidden (e.g. user in a lecture/video in another tab),
  // immediately halt AI request generation, silence voice output, and reset conversation window
  useEffect(() => {
    const handleTabVisibility = () => {
      if (typeof document !== "undefined" && (document.hidden || document.visibilityState === "hidden")) {
        if (abortControllerRef.current) {
          abortControllerRef.current.abort();
          abortControllerRef.current = null;
        }
        if (voiceAgent.isSpeaking) {
          voiceAgent.stopSpeaking();
        }
        conversationActiveRef.current = 0;
      }
    };

    document.addEventListener("visibilitychange", handleTabVisibility);
    return () => document.removeEventListener("visibilitychange", handleTabVisibility);
  }, []);

  // Listen for voice-triggered image modal popup
  useEffect(() => {
    const handleOpenModal = () => setImageModalOpen(true);
    window.addEventListener("nodiq:open-image-modal", handleOpenModal);
    return () => window.removeEventListener("nodiq:open-image-modal", handleOpenModal);
  }, []);

  // Connect Voice Agent with robust listener cleanup & interruption support
  useEffect(() => {
    const unsubState = voiceAgent.onStateChange((state) => {
      setAgentState(state);
    });

    const unsubTranscript = voiceAgent.onTranscript((liveText) => {
      if (!liveText) return;
      const lower = liveText.toLowerCase().trim();
      const containsWake = WAKE_WORDS.some((w) => lower.includes(w));
      const isConversing = hudOpen || Date.now() < conversationActiveRef.current;

      // Only display live transcript and pop open HUD if wake word was detected or user is actively engaged
      if (containsWake || isConversing) {
        setTranscript(liveText);
        setHudOpen(true);
      }
    });

    const unsubStreamQueue = voiceAgent.streamQueue.onStateChange((qState) => {
      if (qState === "speaking") {
        setAgentState("speaking");
      } else if (qState === "idle" && agentState === "speaking") {
        setAgentState(voiceAgent.isListening ? "listening" : "idle");
      }
    });

    const unsubInterruption = voiceAgent.onInterruption(({ text, reason }) => {
      // Advance generation to invalidate any in-flight conversational responses
      requestGenerationRef.current++;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      setAgentState(voiceAgent.isListening ? "listening" : "idle");
      setLastAction(reason === "vad_speech_start" ? "Barge-in Interrupted" : "Speech Cancelled");
      if (text) {
        setTranscript(text);
      }
    });

    const unsubCommand = voiceAgent.onCommand(async ({ commandText, hasWakeWord }) => {
      // Background tab check: never execute if tab is hidden
      if (typeof document !== "undefined" && (document.hidden || document.visibilityState === "hidden")) {
        return;
      }

      const isConversing = hudOpen || Date.now() < conversationActiveRef.current;

      // Anti-eavesdropping guard: if no wake word was used and the user is NOT actively conversing,
      // strictly ignore background speech (e.g. online lectures, videos, podcasts, room conversations)
      if (!hasWakeWord && !isConversing) {
        return;
      }

      // Mark conversation active for 20 seconds
      conversationActiveRef.current = Date.now() + 20000;

      if (!commandText && hasWakeWord) {
        setHudOpen(true);
        setAgentState("speaking");
        const greeting = "Nodiq-X Voice Intelligence active. Ready for commands or analysis.";
        setBotReply(greeting);
        voiceAgent.speak(greeting);
        return;
      }

      if (commandText && executeCommandRef.current) {
        setHudOpen(true);
        await executeCommandRef.current(commandText);
      }
    });

    // Start hands-free monitoring if supported
    if (voiceAgent.supported) {
      voiceAgent.enableHandsFree(true);
    }

    return () => {
      unsubState?.();
      unsubTranscript?.();
      unsubStreamQueue?.();
      unsubInterruption?.();
      unsubCommand?.();
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      voiceAgent.destroy();
    };
  }, [hudOpen]);

  // Execution pipeline with request sequencing & race-condition protection
  const executeCommand = async (commandString) => {
    // Dedicated interruption trap: if user issued a stop-speaking command, cancel speech directly
    if (isInterruptionCommand(commandString, voiceAgent.isSpeaking)) {
      voiceAgent.handleInterruption(commandString);
      return;
    }

    // Cancel any previous conversational in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    const generation = ++requestGenerationRef.current;

    // If assistant was actively speaking when a new command arrives, halt speech immediately
    if (voiceAgent.isSpeaking) {
      voiceAgent.stopSpeaking();
    }

    voiceAgent.streamQueue.setGeneration(generation);

    setHudOpen(true);
    setTranscript(commandString);
    setAgentState("thinking");
    setLastAction("Processing telemetry…");

    const segmenter = new PhraseSegmenter();
    let isStreamActive = false;

    segmenter.onPhrase((phrase) => {
      if (generation !== requestGenerationRef.current) return;
      voiceDiagnostics.mark("first_phrase");
      voiceAgent.streamQueue.enqueue(phrase, generation);
    });

    const onToken = (delta, accumulated) => {
      if (generation !== requestGenerationRef.current) return;
      isStreamActive = true;
      voiceDiagnostics.mark("first_token");
      setAgentState("responding");
      setBotReply(accumulated);
      segmenter.push(delta);
    };

    try {
      const outcome = await nodiqIntentEngine.processCommand(commandString, {
        signal: abortController.signal,
        generation,
        sessionId: sessionIdRef.current,
        history: historyRef.current,
        onToken,
      });

      // Verify that response belongs to the latest request generation before updating UI/speech
      if (generation !== requestGenerationRef.current) {
        return;
      }

      segmenter.flush();

      setLastAction(outcome.actionName || "Telemetry Executed");
      const speech = typeof outcome.speech === "string" ? outcome.speech : (outcome.speech?.speech || "Action complete.");
      voiceDiagnostics.mark("first_response_text");
      setBotReply(speech);
      
      const parsedData = outcome.reportData || parseExecutiveReport(speech);
      setReportBriefingData(parsedData);
      conversationActiveRef.current = Date.now() + 20000;

      // Speak feedback if not already streaming phrases
      if (speech && !outcome.isStreamed && !isStreamActive) {
        voiceDiagnostics.mark("first_response_audio");
        voiceAgent.speak(speech);
      }

      // Record successful conversational exchange in session history
      historyRef.current.push({ role: "user", content: commandString });
      historyRef.current.push({ role: "assistant", content: speech });
      if (historyRef.current.length > 12) {
        historyRef.current = historyRef.current.slice(-12);
      }
    } catch (err) {
      // Don't show or speak errors if request was aborted or superseded by a newer command
      if (err?.name === "AbortError" || generation !== requestGenerationRef.current) {
        return;
      }
      console.error("NodiqBot execution error:", err);
      const fallback = "Encountered a processing exception. Please repeat your instruction.";
      setBotReply(fallback);
      setReportBriefingData(null);
      voiceAgent.speak(fallback);
    } finally {
      if (generation === requestGenerationRef.current && !voiceAgent.streamQueue.isBusy()) {
        setAgentState(voiceAgent.isListening ? "listening" : "idle");
      }
    }
  };
  executeCommandRef.current = executeCommand;

  const handleCopyBriefing = (data) => {
    if (!data) return;
    const txt = `${data.title} (${data.analysisId || "ANL"})\nVerdict: ${data.verdict || "Standard"}\nConformity: ${data.conformity || "Standard"}\nFindings: ${data.findings || ""}\nTarget Application: ${data.targetApplication || "Industrial castings"}`;
    navigator.clipboard?.writeText(txt);
    setCopiedBriefing(true);
    setTimeout(() => setCopiedBriefing(false), 2000);
  };

  const handleOpenReport = (analysisId) => {
    setHudOpen(false);
    conversationActiveRef.current = 0;
    if (analysisId) {
      navigate("/reports/generate", { state: { analysisId } });
    } else {
      navigate("/reports");
    }
  };

  const handleOrbClick = () => {
    if (!hudOpen) {
      setHudOpen(true);
      conversationActiveRef.current = Date.now() + 20000;
      if (!voiceAgent.isListening) {
        voiceAgent.startListening();
      }
    } else {
      setHudOpen(false);
      conversationActiveRef.current = 0;
      if (voiceAgent.isSpeaking) {
        voiceAgent.stopSpeaking();
      }
    }
  };

  const toggleMute = (e) => {
    e.stopPropagation();
    const muted = voiceAgent.toggleMute();
    setIsMuted(muted);
  };

  const toggleHandsFree = (e) => {
    e.stopPropagation();
    const next = !handsFree;
    setHandsFree(next);
    voiceAgent.enableHandsFree(next);
    if (!next) {
      conversationActiveRef.current = 0;
    }
  };

  const handleTextSubmit = (e) => {
    e.preventDefault();
    if (!customInput.trim()) return;
    const text = customInput.trim();
    setCustomInput("");
    conversationActiveRef.current = Date.now() + 20000;
    executeCommand(text);
  };

  // Specimen selection handler
  const handleSelectSpecimen = async (specimen) => {
    const analysisPaths = ["/new-analysis", "/steel-analysis", "/white-cast-iron", "/gray-cast-iron"];
    if (!analysisPaths.includes(location.pathname)) {
      navigate("/new-analysis");
      await new Promise((r) => setTimeout(r, 250));
    }
    window.dispatchEvent(
      new CustomEvent("nodiq:select-dataset-image", { detail: { name: specimen.filename } })
    );
    setImageModalOpen(false);
    const msg = `Specimen ${specimen.label} loaded and staged for analysis.`;
    setLastAction(`Loaded ${specimen.label}`);
    setBotReply(msg);
    voiceAgent.speak(msg);
  };

  const handleTriggerLocalUpload = async () => {
    setImageModalOpen(false);
    const analysisPaths = ["/new-analysis", "/steel-analysis", "/white-cast-iron", "/gray-cast-iron"];
    if (!analysisPaths.includes(location.pathname)) {
      navigate("/new-analysis");
      await new Promise((r) => setTimeout(r, 250));
    }
    const fileInput = document.querySelector("input[type='file']");
    if (fileInput) {
      fileInput.click();
    }
  };

  const handleOpenDatasetDrawer = async () => {
    setImageModalOpen(false);
    const analysisPaths = ["/new-analysis", "/steel-analysis", "/white-cast-iron", "/gray-cast-iron"];
    if (!analysisPaths.includes(location.pathname)) {
      navigate("/new-analysis");
      await new Promise((r) => setTimeout(r, 250));
    }
    const datasetBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.innerText || "").toLowerCase().includes("browse dataset")
    );
    if (datasetBtn) {
      datasetBtn.click();
    }
  };

  const handleTriggerMicroscope = async () => {
    setImageModalOpen(false);
    const analysisPaths = ["/new-analysis", "/steel-analysis", "/white-cast-iron", "/gray-cast-iron"];
    if (!analysisPaths.includes(location.pathname)) {
      navigate("/new-analysis");
      await new Promise((r) => setTimeout(r, 250));
    }
    const microBtn = Array.from(document.querySelectorAll("button")).find(
      (b) =>
        (b.innerText || "").toLowerCase().includes("microscope") ||
        (b.getAttribute("aria-label") || "").toLowerCase().includes("microscope")
    );
    if (microBtn) {
      microBtn.click();
    }
  };

  return (
    <aside className="nodiqbot-container" aria-label="NodiqBot Industrial Voice Intelligence">
      {/* PROFESSIONAL METALLURGICAL SPECIMEN SELECTION MODAL */}
      {imageModalOpen && (
        <div className="nodiq-modal-backdrop" onClick={() => setImageModalOpen(false)}>
          <div className="nodiq-modal-card" onClick={(e) => e.stopPropagation()}>
            {/* Modal Header */}
            <div className="nodiq-modal-header">
              <div className="nodiq-modal-title">
                <span className="nodiq-modal-title-dot" />
                MICROGRAPH SPECIMEN SELECTION
              </div>
              <button
                type="button"
                className="nodiq-modal-close"
                onClick={() => setImageModalOpen(false)}
                title="Close Specimen Selector"
              >
                ×
              </button>
            </div>

            {/* Modal Subtitle */}
            <div className="nodiq-modal-subtitle">
              Select an industrial benchmark specimen below or upload an uncompressed metallographic inspection from your workstation.
            </div>

            {/* Benchmark Specimen Grid */}
            <div className="nodiq-specimen-grid">
              {BENCHMARK_SPECIMENS.map((spec) => (
                <div
                  key={spec.filename}
                  className="nodiq-specimen-card"
                  onClick={() => handleSelectSpecimen(spec)}
                >
                  <div className="nodiq-specimen-thumb-wrap">
                    <img
                      src={`/dataset/${spec.filename}`}
                      alt={spec.label}
                      className="nodiq-specimen-thumb"
                      onError={(e) => {
                        e.target.style.opacity = "0.3";
                      }}
                    />
                    <span className="nodiq-specimen-badge">{spec.grade}</span>
                  </div>
                  <div className="nodiq-specimen-info">
                    <div className="nodiq-specimen-name">{spec.label}</div>
                    <div className="nodiq-specimen-desc">{spec.details}</div>
                  </div>
                  <button type="button" className="nodiq-specimen-select-btn">
                    SELECT SPECIMEN
                  </button>
                </div>
              ))}
            </div>

            {/* Workstation Actions Bar */}
            <div className="nodiq-modal-actions">
              <button
                type="button"
                className="nodiq-modal-action-btn primary"
                onClick={handleTriggerLocalUpload}
              >
                <span className="nodiq-btn-icon">📁</span>
                <span>UPLOAD LOCAL FILE (BROWSE DISK)</span>
              </button>

              <button
                type="button"
                className="nodiq-modal-action-btn"
                onClick={handleOpenDatasetDrawer}
              >
                <span>OPEN FULL 1,000-IMAGE DATASET</span>
              </button>

              <button
                type="button"
                className="nodiq-modal-action-btn"
                onClick={handleTriggerMicroscope}
              >
                <span>🔬 MICROSCOPE CAMERA SCAN</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* EXECUTIVE VOICE TERMINAL HUD POPOVER */}
      {hudOpen && (
        <div className="nodiqbot-hud" ref={hudRef}>
          {/* HUD Header */}
          <div className="nodiqbot-hud-header">
            <div className="nodiqbot-hud-brand">
              <div className="nodiqbot-ai-avatar">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z" />
                </svg>
              </div>
              <div className="nodiqbot-brand-info">
                <div className="nodiqbot-brand-title-row">
                  <span className="nodiqbot-brand-name">NODIQ AI</span>
                  <span className="nodiqbot-model-pill">CORE v2.5</span>
                </div>
                <div className="nodiqbot-status-row">
                  <span className={`nodiqbot-status-dot ${agentState}`} />
                  <span className="nodiqbot-status-text">
                    {agentState === "thinking"
                      ? "Analyzing query…"
                      : agentState === "speaking"
                      ? "Transmitting…"
                      : agentState === "listening"
                      ? "Listening…"
                      : "Ready"}
                  </span>
                </div>
              </div>
            </div>

            <div className="nodiqbot-hud-actions">
              <button
                type="button"
                className={`nodiqbot-hud-icon-btn ${handsFree ? "active" : ""}`}
                onClick={toggleHandsFree}
                title={handsFree ? "Auto-Listening Mode (Active)" : "Enable Auto-Listening"}
                aria-label="Toggle Auto-Listen Mode"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="22" />
                </svg>
              </button>

              <button
                type="button"
                className={`nodiqbot-hud-icon-btn ${isMuted ? "muted" : "active"}`}
                onClick={toggleMute}
                title={isMuted ? "Unmute Voice Telemetry" : "Mute Voice Telemetry"}
                aria-label="Toggle Audio Output"
              >
                {isMuted ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="1" y1="1" x2="23" y2="23" />
                    <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6" />
                    <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                    <line x1="8" y1="23" x2="16" y2="23" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                    <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                    <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
                  </svg>
                )}
              </button>

              <button
                type="button"
                className="nodiqbot-hud-icon-btn close"
                onClick={() => {
                  setHudOpen(false);
                  conversationActiveRef.current = 0;
                  if (voiceAgent.isSpeaking) {
                    voiceAgent.stopSpeaking();
                  }
                }}
                title="Close AI Assistant"
                aria-label="Close AI Assistant"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* HUD Content Area */}
          <div className="nodiqbot-hud-body">
            {/* Live User Speech Box */}
            {transcript && (
              <div className="nodiqbot-transcript-box">
                <div className="nodiqbot-transcript-label">
                  <span className="nodiqbot-wave-indicator" />
                  OPERATOR COMMAND INPUT
                </div>
                <div className="nodiqbot-transcript-text">“{transcript}”</div>
              </div>
            )}

            {/* Real-Time Action Status Pill */}
            {lastAction && (
              <div className="nodiqbot-action-pill">
                <span className="nodiqbot-pill-dot" />
                <span className="nodiqbot-pill-prefix">OPERATION //</span>
                <span>{lastAction}</span>
              </div>
            )}

            {/* AI Intelligence Response */}
            <div className={`nodiqbot-response-bubble ${reportBriefingData ? "has-executive-card" : ""}`}>
              <div className="nodiqbot-response-header">
                <div className="nodiqbot-response-author">
                  <span className="nodiqbot-sparkle-mark">✦</span>
                  <span className="nodiqbot-response-name">NODIQ INTELLIGENCE</span>
                </div>
                <span className="nodiqbot-executive-badge">
                  {reportBriefingData ? "EXECUTIVE BRIEFING" : "METALLURGICAL AI"}
                </span>
              </div>

              {/* Dynamic Sound Waveform when talking or processing */}
              {(agentState === "speaking" || agentState === "thinking" || agentState === "listening") && (
                <div className={`nodiqbot-waveform-bar ${agentState}`}>
                  <span className="nodiqbot-wave-pill" />
                  <span className="nodiqbot-wave-pill" />
                  <span className="nodiqbot-wave-pill" />
                  <span className="nodiqbot-wave-pill" />
                  <span className="nodiqbot-wave-pill" />
                  <span className="nodiqbot-wave-pill" />
                  <span className="nodiqbot-wave-pill" />
                </div>
              )}

              {reportBriefingData ? (
                <div className="nodiqbot-executive-report-card">
                  {/* Top Header */}
                  <div className="nodiq-report-card-top">
                    <div className="nodiq-report-title-group">
                      <div className="nodiq-report-specimen-title">
                        {reportBriefingData.title || "Industrial Microstructure Report"}
                      </div>
                      <div className="nodiq-report-id-row">
                        {reportBriefingData.analysisId && (
                          <span className="nodiq-report-chip-id">{reportBriefingData.analysisId}</span>
                        )}
                        <span className="nodiq-report-chip-sample">
                          {reportBriefingData.sampleId && reportBriefingData.sampleId !== "Sample" ? reportBriefingData.sampleId : "Specimen"}
                        </span>
                      </div>
                    </div>
                    <span className="nodiq-report-status-badge ready">
                      <span className="nodiq-status-live-dot" />
                      {reportBriefingData.status || "READY"}
                    </span>
                  </div>

                  {/* Metrics Grid */}
                  {reportBriefingData.metrics && reportBriefingData.metrics.length > 0 && (
                    <div className="nodiq-report-metrics-grid">
                      {reportBriefingData.metrics.map((m, idx) => (
                        <div key={idx} className="nodiq-report-metric-tile">
                          <span className="metric-tile-label">{m.label}</span>
                          <strong className="metric-tile-val">{m.value}</strong>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Acceptance Verdict Callout */}
                  {reportBriefingData.verdict && (
                    <div className={`nodiq-report-verdict-box ${/marginal|sub-optimal|warning/i.test(reportBriefingData.verdict) ? "marginal" : "compliant"}`}>
                      <div className="nodiq-verdict-header">
                        <span className="material-symbols-outlined verdict-icon">
                          {/marginal|warning/i.test(reportBriefingData.verdict) ? "gavel" : "verified"}
                        </span>
                        <span className="nodiq-verdict-title">Acceptance Verdict & Lot Disposition</span>
                        {reportBriefingData.conformity && (
                          <span className="nodiq-conformity-pill">Index: {reportBriefingData.conformity}</span>
                        )}
                      </div>
                      <div className="nodiq-verdict-statement">{reportBriefingData.verdict}</div>
                    </div>
                  )}

                  {/* Findings / Metallurgical Evaluation */}
                  {reportBriefingData.findings && (
                    <div className="nodiq-report-findings-section">
                      <div className="nodiq-findings-label">
                        <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>insights</span>
                        Metallurgical Evaluation & Process Findings
                      </div>
                      <p className="nodiq-findings-text">{reportBriefingData.findings}</p>
                    </div>
                  )}

                  {/* Target Application Footer Tag */}
                  {reportBriefingData.targetApplication && (
                    <div className="nodiq-report-app-tag">
                      <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>precision_manufacturing</span>
                      <span><strong>Target Application:</strong> {reportBriefingData.targetApplication}</span>
                    </div>
                  )}

                  {/* Quick Action Toolbar */}
                  <div className="nodiq-report-quick-actions">
                    <button
                      type="button"
                      className="nodiq-report-action-btn primary"
                      onClick={() => handleOpenReport(reportBriefingData.analysisId)}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>visibility</span>
                      View Report
                    </button>
                    <button
                      type="button"
                      className="nodiq-report-action-btn"
                      onClick={() => handleCopyBriefing(reportBriefingData)}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>content_copy</span>
                      {copiedBriefing ? "Copied!" : "Copy Briefing"}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="nodiqbot-response-text">{botReply}</div>
                  <div className="nodiqbot-suggestions-group">
                    <span className="nodiqbot-suggestions-label">SUGGESTED ACTIONS</span>
                    <div className="nodiqbot-suggestions-row">
                      {AI_SUGGESTIONS.map((s, idx) => (
                        <button
                          key={idx}
                          type="button"
                          className="nodiqbot-suggestion-chip"
                          onClick={() => executeCommand(s.cmd)}
                          title={`Execute: "${s.cmd}"`}
                        >
                          <span className="suggestion-icon">{s.icon}</span>
                          <span>{s.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Modern AI Floating Prompt Input Row */}
          <form onSubmit={handleTextSubmit} className="nodiqbot-hud-input-row">
            <div className="nodiqbot-hud-input-wrap">
              <span className="nodiqbot-input-sparkle">✦</span>
              <input
                type="text"
                placeholder="Ask Nodiq AI or type command (e.g. Set scale 100 μm)..."
                value={customInput}
                onChange={(e) => setCustomInput(e.target.value)}
                className="nodiqbot-hud-input"
              />
              <button
                type="submit"
                disabled={!customInput.trim()}
                className={`nodiqbot-hud-send-btn ${customInput.trim() ? "ready" : ""}`}
                title="Send Command (Enter)"
                aria-label="Send Command"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </button>
            </div>
          </form>
        </div>
      )}

      {/* FLOATING TELEMETRY ORB BUTTON */}
      <button
        type="button"
        className={`nodiqbot-orb ${agentState}`}
        onClick={handleOrbClick}
        title="NODIQ-X Voice Intelligence (Click to engage terminal)"
        aria-label="Engage NODIQ-X Voice Assistant"
      >
        <div className="nodiqbot-orb-ring" />
        <div className="nodiqbot-orb-ring-inner" />

        {agentState === "speaking" ? (
          <div className="nodiqbot-eq-bars">
            <span className="nodiqbot-eq-bar" />
            <span className="nodiqbot-eq-bar" />
            <span className="nodiqbot-eq-bar" />
            <span className="nodiqbot-eq-bar" />
            <span className="nodiqbot-eq-bar" />
          </div>
        ) : (
          <div className="nodiqbot-orb-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="22" />
            </svg>
          </div>
        )}
      </button>
    </aside>
  );
};

export default NodiqBot;
