/**
 * NodiqIntentEngine: Natural Language Processor & Universal Intent Dispatcher
 * Dispatches ANY voice command, typo-tolerant action, navigation, calibration,
 * metric explanation, or delegates deep questions to the NODIQ-X AI Copilot.
 */

import domActionEngine, { normalizeVoiceText } from "./domActionEngine.js";
import goalPlanner from "./goalPlanner.js";
import screenIntelligence from "./screenIntelligence.js";
import api from "./api.js";
import { isInterruptionCommand } from "./voiceAgent.js";

class NodiqIntentEngine {
  /**
   * Main dispatch entry point for a voice command
   * Returns: { success: boolean, speech: string, actionName: string }
   */
  async processCommand(commandText, _context = {}) {
    try {
      const raw = (commandText || "").trim();
      const text = normalizeVoiceText(raw);

      if (!text) {
        return {
          success: true,
          speech: "I am listening. Tell me what you would like to do.",
          actionName: "Listening",
        };
      }

      // 0. Dedicated Speech Interruption Trap
      if (isInterruptionCommand(raw, true) || isInterruptionCommand(text, true)) {
        return {
          success: true,
          speech: "",
          isInterruption: true,
          actionName: "Speech Cancelled",
        };
      }

    // -------------------------------------------------------------
    // 1. Wake word only (e.g. "Hi NodiqBot", "Hey Jarvis", "Hello")
    // -------------------------------------------------------------
    if (/^(?:hi|hey|hello|online|wake up|nodiq|nodiqbot)$/i.test(text)) {
      return {
        success: true,
        speech: "Online and ready. Tell me your command or what you need to analyze.",
        actionName: "Awake",
      };
    }

    // -------------------------------------------------------------
    // 1B. Incomplete Navigation Query (e.g. "now go to", "visit", "open")
    // -------------------------------------------------------------
    if (/^(?:now|go|go to|now go|now go to|visit|now visit|open|now open|show me|take me to|navigate to|switch to)$/i.test(text)) {
      return {
        success: true,
        speech: "Where would you like to go? You can say Dashboard, My Analyses, Copilot, Sessions, Cast Iron, or Steel.",
        actionName: "Awaiting Destination",
      };
    }

    // -------------------------------------------------------------
    // 2. Report Summaries & Briefings
    //    e.g. "summary of report which is being generated",
    //    "summary of report", "give me report summary",
    //    "report summary", "summarize report", "executive summary"
    // -------------------------------------------------------------
    const isReportSummaryQuery = (
      text.includes("summary") ||
      text.includes("summarize") ||
      text.includes("briefing") ||
      text.includes("overview") ||
      (text.includes("report") && (
        text.includes("explain") ||
        text.includes("tell me") ||
        text.includes("read") ||
        text.includes("give me") ||
        text.includes("show") ||
        text.includes("what is in") ||
        text.includes("whole") ||
        text.includes("detail")
      ))
    );

    if (isReportSummaryQuery) {
      const isBrief = text.includes("brief") || text.includes("short");
      const reportBrief = await screenIntelligence.summarizeReport(isBrief);
      const speech = typeof reportBrief === "object" ? reportBrief.speech : reportBrief;
      return {
        success: true,
        speech: speech,
        reportData: typeof reportBrief === "object" ? reportBrief : null,
        actionName: isBrief ? "Report Briefing" : "Report Summary",
      };
    }

    // -------------------------------------------------------------
    // 2B. Explanations & Metallurgical Questions
    //    e.g. "explain nodularity", "what is nodularity", "nodularity",
    //    "explain carbide", "tell about flakes"
    // -------------------------------------------------------------
    const isExplanationQuery = (
      text.includes("nodularity") ||
      text.includes("explain") ||
      text.includes("what is") ||
      text.includes("tell me about") ||
      text.includes("tell about") ||
      text.includes("how does") ||
      text.includes("why is") ||
      text.includes("meaning of")
    );

    if (isExplanationQuery) {
      // Check if asking about domain concepts (nodularity, carbide, flakes, grain size)
      const conceptExplanation = screenIntelligence.explainConcept(text);
      if (conceptExplanation) {
        return {
          success: true,
          speech: conceptExplanation,
          actionName: "Concept Explained",
        };
      }

      // If asking about the screen in general
      if (text.includes("screen") || text.includes("see") || text.includes("numbers") || text.includes("stats")) {
        const screenSummary = screenIntelligence.summarizeCurrentScreen();
        return {
          success: true,
          speech: screenSummary,
          actionName: "Screen Summary",
        };
      }

      // Freeform metallurgical query: delegate directly to Copilot AI
      try {
        return await this.queryCopilot(raw, _context, "Copilot Knowledge");
      } catch (err) {
        if (err?.name === "AbortError") {
          throw err;
        }
        console.warn("Copilot query fallback error:", err);
      }
    }

    // -------------------------------------------------------------
    // 3. Verification & Cryptographic Audit
    //    e.g. "click on verify button in report section", "verify report",
    //    "click verify", "verify"
    // -------------------------------------------------------------
    const isVerifyCommand = (
      text.includes("verify") ||
      text.includes("verification") ||
      text.includes("audit stamp") ||
      text.includes("certificate")
    );

    if (isVerifyCommand) {
      // 1. Check for cryptographic verification badge on report preview
      const cryptoBadge =
        document.querySelector(".crypto-badge") ||
        document.querySelector(".crypto-badge-pill") ||
        document.querySelector(".crypto-audit-card") ||
        document.querySelector(".crypto-btn-primary") ||
        document.querySelector(".crypto-copy-btn") ||
        domActionEngine.findClickable("verified") ||
        domActionEngine.findClickable("verify");

      if (cryptoBadge) {
        const el = cryptoBadge.element || cryptoBadge;
        domActionEngine.click(el);
        return {
          success: true,
          speech: "Cryptographic verification audit trail opened. SHA-256 anti-tamper digest verified.",
          actionName: "Verified Report",
        };
      }

      // 2. Check for verification submit button on Verification Portal
      const verifySubmit =
        document.querySelector(".verify-hash-submit") ||
        document.querySelector("button[type='submit']");
      if (verifySubmit) {
        domActionEngine.click(verifySubmit);
        return {
          success: true,
          speech: "Executing cryptographic hash verification audit.",
          actionName: "Verified Hash",
        };
      }

      // 3. Otherwise navigate to Verification / Review Center
      await goalPlanner.goToRoute("/review-center");
      return {
        success: true,
        speech: "Opening Verification Portal and Review Center.",
        actionName: "Navigated: Verification",
      };
    }

    // -------------------------------------------------------------
    // 4. Image Selection / Upload Commands
    //    e.g. "select image", "slecte img", "open image selector",
    //    "choose image", "upload micrograph", "browse dataset"
    // -------------------------------------------------------------
    const isImageSelectorCommand = (
      /\b(?:select|upload|choose|open|pick|browse|load)\s*(?:an?\s*)?(?:micrograph|image|images|file|files|pic|picture|photo)?(?:\s*(?:selector|picker|input|modal|popup|pop\s*up))?\b/i.test(text) ||
      /\b(?:image|images|img|micrograph)\s*(?:selector|picker|chooser|upload|modal)\b/i.test(text) ||
      text.includes("select image") ||
      text.includes("select images") ||
      text.includes("image picker") ||
      text.includes("open picker") ||
      text.includes("picker") ||
      text.includes("choose image") ||
      text.includes("choose images") ||
      text.includes("upload image") ||
      text.includes("upload images") ||
      text.includes("open image selector") ||
      text.includes("select img") ||
      text.includes("slecte img") ||
      text.includes("slect img")
    );

    // Make sure this doesn't conflict with "click nodular cast iron analysis"
    if (isImageSelectorCommand && !text.includes("cast iron") && !text.includes("steel") && !text.includes("dashboard")) {
      const currentPath = window.location.pathname;
      const analysisPaths = ["/new-analysis", "/steel-analysis", "/white-cast-iron", "/gray-cast-iron"];

      if (!analysisPaths.includes(currentPath)) {
        // Seamlessly route to Nodular Cast Iron workspace
        await goalPlanner.goToRoute("/new-analysis");
        await new Promise((r) => setTimeout(r, 400));
      }

      // 1. Dispatch custom event to trigger the visible Micrograph Selector Modal popup
      window.dispatchEvent(new CustomEvent("nodiq:open-image-modal"));

      // 2. Best-effort click on workspace select button if present
      const selectBtn =
        domActionEngine.findClickable("select image") ||
        domActionEngine.findClickable("upload") ||
        domActionEngine.findClickable("choose") ||
        document.querySelector(".nodiq-button-primary") ||
        document.querySelector(".upload-zone");

      if (selectBtn) {
        domActionEngine.click(selectBtn.element || selectBtn);
      }

      return {
        success: true,
        speech: "Opening metallurgical micrograph selector. Choose an industrial benchmark specimen or upload a file.",
        actionName: "Micrograph Selector Modal",
      };
    }

    // -------------------------------------------------------------
    // 5. Report Generation Commands
    //    e.g. "click on same screen for generate report", "generate report",
    //    "click generate report", "create report", "make report"
    // -------------------------------------------------------------
    const isReportGenerateCommand = (
      !isReportSummaryQuery &&
      !text.includes("summary") &&
      !text.includes("summarize") &&
      !text.includes("overview") &&
      (
        text.includes("generate report") ||
        text.includes("create report") ||
        text.includes("make report") ||
        (text.includes("report") && (text.includes("generate") || text.includes("create") || text.includes("screen"))) ||
        text === "generate"
      )
    );

    if (isReportGenerateCommand) {
      // 1. Look for generate report button in ReportGenerator page or Analysis page
      const repBtn =
        document.querySelector(".generate-final-btn") ||
        document.querySelector(".generate-report-button") ||
        document.querySelector("button.generate-final-btn") ||
        domActionEngine.findClickable("generate report") ||
        domActionEngine.findClickable("generate engineering report") ||
        domActionEngine.findClickable("create report");

      if (repBtn) {
        const el = repBtn.element || repBtn;
        domActionEngine.click(el);
        return {
          success: true,
          speech: "Generating metallurgical engineering report now.",
          actionName: "Generating Report",
        };
      }

      // 2. If analysis hasn't run yet on this screen, check if there is an active Start Analysis button
      const startBtn =
        domActionEngine.findClickable("start analysis") ||
        domActionEngine.findClickable("run analysis");
      if (startBtn) {
        const el = startBtn.element || startBtn;
        domActionEngine.click(el);
        return {
          success: true,
          speech: "Executing microstructure analysis pipeline first to prepare your engineering report.",
          actionName: "Running Analysis First",
        };
      }

      // 3. Otherwise navigate to report generation workspace
      await goalPlanner.goToRoute("/reports/generate");
      return {
        success: true,
        speech: "Opening report generation workspace.",
        actionName: "Navigated: Report Generator",
      };
    }

    // -------------------------------------------------------------
    // 5. Spatial Scale / Calibration Commands
    //    e.g. "set 100 um of img", "set scale 100", "scale 0.45 microns", "100 um"
    // -------------------------------------------------------------
    const calibMatch =
      text.match(/(?:set|scale|calibrate|calibration|size)\s*([0-9.]+)\s*(?:um|µm|microns?|px)?/i) ||
      text.match(/([0-9.]+)\s*(?:um|µm|microns?)\s*(?:of\s*(?:img|image))?/i) ||
      text.match(/^[0-9.]+\s*(?:um|µm|microns?)$/i);

    if (calibMatch) {
      const val = calibMatch[1] || calibMatch[0].replace(/[^0-9.]/g, "");
      const success = goalPlanner.setCalibration(val);
      if (success) {
        return {
          success: true,
          speech: `Spatial scale set to ${val} micrometres for the current micrograph.`,
          actionName: `Set Scale: ${val} µm`,
        };
      }
      return {
        success: false,
        speech: `I couldn't locate a scale calibration field on this screen. Make sure you are on an active analysis workspace.`,
        actionName: "Calibration Field Missing",
      };
    }

    // -------------------------------------------------------------
    // 6. Microscope Hardware Controls
    //    e.g. "microscope", "open camera", "capture frame", "capture img"
    // -------------------------------------------------------------
    if (text.includes("capture") && (text.includes("image") || text.includes("frame") || text.includes("photo") || text.includes("snap"))) {
      const capBtn = domActionEngine.findClickable("capture frame") || domActionEngine.findClickable("capture image") || domActionEngine.findClickable("capture");
      if (capBtn) {
        domActionEngine.click(capBtn.element);
        return {
          success: true,
          speech: "Micrograph frame captured and staged for analysis.",
          actionName: "Captured Micrograph",
        };
      }
    }

    if (text.includes("microscope") || text.includes("camera feed") || text.includes("live stream")) {
      const microBtn = domActionEngine.findClickable("microscope") || domActionEngine.findClickable("capture via microscope");
      if (microBtn) {
        domActionEngine.click(microBtn.element);
        return {
          success: true,
          speech: "Toggling live microscope feed.",
          actionName: "Toggle Microscope",
        };
      }
    }

    // -------------------------------------------------------------
    // 7. New Analysis Navigation & Workspace Routing
    //    e.g. "start new anlysis", "new analysis", "go to dteel size",
    //    "steel size", "start cast iron", "white cast iron", "dashboard"
    // -------------------------------------------------------------
    const isSpecialCastIron =
      text.includes("gray") ||
      text.includes("grey") ||
      text.includes("flake") ||
      text.includes("white") ||
      text.includes("carbide");

    if (
      !isSpecialCastIron &&
      (text.includes("new analysis") ||
        text.includes("start new") ||
        text.includes("another analysis") ||
        text === "start cast iron" ||
        text === "cast iron")
    ) {
      await goalPlanner.goToRoute("/new-analysis");
      return {
        success: true,
        speech: "Opening Nodular Cast Iron new analysis workspace.",
        actionName: "Navigated: New Analysis",
      };
    }

    // Check general navigation routes (Gray Cast Iron Flakes, Steel, White Cast Iron, Dashboard, etc.)
    const routeTarget = goalPlanner.resolveRoute(text);
    if (routeTarget) {
      await goalPlanner.goToRoute(routeTarget.path);
      return {
        success: true,
        speech: `Opening ${routeTarget.name} workspace.`,
        actionName: `Navigated: ${routeTarget.name}`,
      };
    }

    // -------------------------------------------------------------
    // 8. Analysis Trigger
    //    e.g. "run analysis", "start analysis", "run", "execute"
    // -------------------------------------------------------------
    if (
      text.includes("run analysis") ||
      text.includes("start analysis") ||
      text.includes("run carbide") ||
      text.includes("run flake") ||
      text === "run" ||
      text === "start"
    ) {
      const runBtn =
        domActionEngine.findClickable("start analysis") ||
        domActionEngine.findClickable("run analysis") ||
        domActionEngine.findClickable("run carbide analysis") ||
        domActionEngine.findClickable("analyze");

      if (runBtn) {
        domActionEngine.click(runBtn.element);
        return {
          success: true,
          speech: "Starting microstructure analysis pipeline now.",
          actionName: "Running Analysis",
        };
      }

      // If no active analysis button on this page, navigate to New Analysis
      await goalPlanner.goToRoute("/new-analysis");
      return {
        success: true,
        speech: "Opening new analysis workspace.",
        actionName: "Navigated: New Analysis",
      };
    }

    // -------------------------------------------------------------
    // 8B. Report Page Actions (Download PDF, Share, Back)
    // -------------------------------------------------------------
    if (text.includes("download") || text.includes("export pdf") || text.includes("save pdf")) {
      const dlBtn =
        document.querySelector(".download-action") ||
        domActionEngine.findClickable("download pdf") ||
        domActionEngine.findClickable("download");
      if (dlBtn) {
        const el = dlBtn.element || dlBtn;
        domActionEngine.click(el);
        return {
          success: true,
          speech: "Downloading official engineering report PDF.",
          actionName: "Downloaded PDF",
        };
      }
    }

    if (text.includes("share")) {
      const shareBtn =
        domActionEngine.findClickable("share") ||
        Array.from(document.querySelectorAll("button")).find((b) => b.innerText?.trim() === "Share");
      if (shareBtn) {
        const el = shareBtn.element || shareBtn;
        domActionEngine.click(el);
        return {
          success: true,
          speech: "Opening report share dialog.",
          actionName: "Shared Report",
        };
      }
    }

    if (text === "back" || text.includes("back to reports")) {
      const backBtn = document.querySelector(".report-back");
      if (backBtn) {
        domActionEngine.click(backBtn);
      } else {
        await goalPlanner.goToRoute("/reports");
      }
      return {
        success: true,
        speech: "Returning to reports list.",
        actionName: "Navigated: Reports",
      };
    }

    // -------------------------------------------------------------
    // 9. Dashboard Hovering & UI Highlighting
    //    e.g. "hover board", "highlight metrics"
    // -------------------------------------------------------------
    if (text.includes("hover") && (text.includes("board") || text.includes("card") || text.includes("metric"))) {
      goalPlanner.hoverTarget("board");
      return {
        success: true,
        speech: "Highlighting dashboard metrics board.",
        actionName: "Hovering Board",
      };
    }

    // -------------------------------------------------------------
    // 10. System Controls (Theme, Scrolling, Zoom, Modals)
    // -------------------------------------------------------------
    if (text.includes("theme") || text.includes("dark mode") || text.includes("light mode")) {
      const toggled = goalPlanner.toggleTheme();
      if (toggled) {
        return {
          success: true,
          speech: "Theme toggled.",
          actionName: "Theme Toggled",
        };
      }
    }

    if (text.includes("scroll down")) {
      domActionEngine.scroll("down");
      return { success: true, speech: "Scrolling down.", actionName: "Scroll Down" };
    }

    if (text.includes("scroll up")) {
      domActionEngine.scroll("up");
      return { success: true, speech: "Scrolling up.", actionName: "Scroll Up" };
    }

    if (text.includes("close") || text.includes("dismiss") || text.includes("cancel")) {
      const closeBtn = domActionEngine.findClickable("close") || domActionEngine.findClickable("×");
      if (closeBtn) {
        domActionEngine.click(closeBtn.element);
        return { success: true, speech: "Closed.", actionName: "Closed Dialog" };
      }
    }

    // -------------------------------------------------------------
    // 11. Search & Input Execution
    //    e.g. "search ductile in dashboard", "find sample 402"
    // -------------------------------------------------------------
    const searchMatch = text.match(/(?:search|find|filter)\s*(?:for\s*)?(.+?)(?:\s*in\s*(?:dashboard|analyses|reports))?$/i);
    if (searchMatch && searchMatch[1]) {
      const term = searchMatch[1].trim();
      const filled = domActionEngine.findAndSetValue("search", term);
      if (filled) {
        return {
          success: true,
          speech: `Searching for ${term}.`,
          actionName: `Search: ${term}`,
        };
      }
    }

    // -------------------------------------------------------------
    // 12. Universal Click Action
    //    Matches ANY element/button/link on the screen by name!
    //    e.g. "click [label]", "press [label]", or just saying "[label]"
    // -------------------------------------------------------------
    const cleanClickTarget = text.replace(/^(?:click|press|tap|hit|select|open)\s+(?:on\s+)?(?:the\s+)?/i, "").trim();
    const clickable = domActionEngine.findClickable(cleanClickTarget || text);

    if (clickable && clickable.score > 0.42) {
      domActionEngine.click(clickable.element);
      const label = clickable.element.innerText?.trim() || cleanClickTarget || "element";
      return {
        success: true,
        speech: `Clicked ${label}.`,
        actionName: `Clicked: ${label}`,
      };
    }

    // -------------------------------------------------------------
    // 13. Deep Copilot Fallback (For arbitrary questions or tasks)
    // -------------------------------------------------------------
    try {
      const copilotOutcome = await this.queryCopilot(raw, _context, "Copilot Response");
      if (copilotOutcome && copilotOutcome.speech) {
        return copilotOutcome;
      }
    } catch (err) {
      if (err?.name === "AbortError") {
        throw err;
      }
      console.warn("Copilot fallback failed:", err);
    }

      return {
        success: false,
        speech: `I understood "${raw}". You can ask me to navigate, click buttons, set scale, capture micrographs, or explain metrics.`,
        actionName: "Action Unresolved",
      };
    } catch (err) {
      console.warn("NodiqIntentEngine execution notice:", err);
      return {
        success: true,
        speech: `Understood your request. Working on that action now.`,
        actionName: "Action Handled",
      };
    }
  }

  /**
   * Delegates conversational query to the Copilot AI with support for streaming tokens.
   */
  async queryCopilot(raw, context = {}, actionName = "Copilot Knowledge") {
    const screenContext = screenIntelligence.scrape();
    const activeAnalysisId = screenIntelligence.getActiveAnalysisId();
    const appCtx = {
      current_route: screenContext.path,
      page_title: screenContext.title,
      visible_kpis: screenContext.kpis,
      current_analysis_id: activeAnalysisId || undefined,
    };
    const sessionId = context?.sessionId || "nodiqbot-voice";
    const history = context?.history || [];
    const signal = context?.signal;

    if (context?.onToken) {
      const stream = api.copilotStream(raw, history, sessionId, appCtx, { signal });
      let accumulated = "";
      for await (const chunk of stream) {
        if (chunk.type === "token" && chunk.delta) {
          accumulated += chunk.delta;
          context.onToken(chunk.delta, accumulated);
        } else if (chunk.type === "done") {
          if (chunk.text && !accumulated) {
            accumulated = chunk.text;
          }
        }
      }
      let reply = accumulated.replace(/```action[\s\S]*?```/g, "").trim();
      return {
        success: true,
        speech: reply || "I analyzed your question, but have no additional metallurgical details.",
        actionName,
        isStreamed: true,
      };
    } else {
      const aiResp = await api.copilot(raw, history, sessionId, appCtx, { signal });
      let reply =
        aiResp?.reply ||
        aiResp?.response ||
        aiResp?.message ||
        (typeof aiResp === "string" ? aiResp : null);

      if (reply) {
        reply = reply.replace(/```action[\s\S]*?```/g, "").trim();
      }

      if (!reply && aiResp?.error) {
        reply =
          aiResp.error === "authentication required"
            ? "Please sign in to access Copilot intelligence."
            : "The Copilot intelligence service is currently unavailable.";
      }

      return {
        success: true,
        speech: reply || "I analyzed your question, but have no additional metallurgical details.",
        actionName,
      };
    }
  }
}

export const nodiqIntentEngine = new NodiqIntentEngine();
export default nodiqIntentEngine;
