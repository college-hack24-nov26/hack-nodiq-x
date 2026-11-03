/**
 * DOM Action Engine: Universal Semantic Scanner & Synthetic Event Dispatcher
 * Enables NodiqBot to find and interact with ANY element, button, input, or link
 * across any slide of the web application, resilient to typos, slang, and abbreviations.
 */

// Comprehensive synonyms & jargon mapping
export const SYNONYMS = {
  image: [
    "select image",
    "image",
    "img",
    "photo",
    "pic",
    "micrograph",
    "upload",
    "choose",
    "browse image",
    "choose image",
    "upload image",
    "open image",
    "image selector",
    "file picker",
    "micrograph image",
  ],
  analyze: [
    "run analysis",
    "start analysis",
    "run",
    "start",
    "execute",
    "analyze",
    "anlysis",
    "anlyse",
    "run carbide",
    "run carbide analysis",
    "run flake",
    "start grain size",
  ],
  report: [
    "generate report",
    "create report",
    "engineering report",
    "report",
    "make report",
    "generate engineering report",
    "generate",
  ],
  microscope: ["microscope", "camera", "live stream", "video", "feed", "cam"],
  capture: [
    "capture frame",
    "capture image",
    "take photo",
    "snapshot",
    "capture",
    "take picture",
    "snap",
  ],
  nodular: [
    "nodular",
    "nodularity",
    "ductile",
    "ductile iron",
    "nodular cast iron",
    "cast iron analysis",
    "cast iron",
  ],
  carbide: [
    "carbide",
    "cementite",
    "ledeburite",
    "white cast iron",
    "white cast iron carbide analysis",
  ],
  flake: [
    "flake",
    "flakes",
    "graphite flake",
    "graphite flakes",
    "gray cast iron",
    "grey cast iron",
    "gray cast iron flakes",
    "grey cast iron flakes",
    "gray flakes",
    "grey flakes",
    "cast iron flakes",
    "gray iron",
    "grey iron",
    "gray cast iron analysis",
    "flake analysis",
    "s-metallograph",
  ],
  steel: [
    "steel",
    "steel grain size",
    "grain size",
    "grain",
    "steel grain",
    "steel analysis",
    "steel size",
    "dteel size",
    "dteel",
    "steel grain size analysis",
  ],
  dashboard: ["dashboard", "board", "home metrics", "overview"],
  theme: ["theme", "dark mode", "light mode", "toggle theme"],
  zoom_in: ["zoom in", "plus", "enlarge", "zoom-in"],
  zoom_out: ["zoom out", "minus", "shrink", "zoom-out"],
  reset_zoom: ["reset zoom", "100%", "fit", "reset"],
  sidebyside: ["side-by-side", "side by side", "compare", "split view"],
  single: ["single view", "single"],
};

function escapeRegExp(str) {
  return String(str || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function safeWordMatch(targetStr, searchStr) {
  if (!targetStr || !searchStr) return false;
  const s = String(searchStr).trim();
  const t = String(targetStr).trim();
  if (!s || !t) return false;

  // Non-alphanumeric symbols or phrases use simple substring
  if (s.includes(" ") || !/^[a-z0-9]+$/i.test(s)) {
    return t.toLowerCase().includes(s.toLowerCase());
  }

  try {
    const escaped = escapeRegExp(s);
    return new RegExp(`\\b${escaped}\\b`, "i").test(t);
  } catch {
    return t.toLowerCase().includes(s.toLowerCase());
  }
}

/**
 * Normalizes voice input, fixing common typos and expanding abbreviations
 */
export function normalizeVoiceText(raw) {
  if (!raw) return "";
  let t = raw.toLowerCase().trim();

  // Strip filler prefixes with optional leading 'now'
  t = t.replace(
    /^(?:now\s+)?(?:please|can you|could you|i want you to|would you|go ahead and|tell me|tell to me|i want to|i wanna)\s+/i,
    ""
  );

  // Strip navigation command prefixes with optional leading 'now'
  t = t.replace(
    /^(?:now\s+)?(?:visit|go to|take me to|navigate to|open|show me|switch to|head to|jump to)\s+/i,
    ""
  );

  // Strip dangling leading 'now'
  t = t.replace(/^now\s+/i, "");

  // Common speech-to-text typos & phonetics
  t = t.replace(/\bcliick\b|\bclik\b|\bclk\b|\bclck\b/g, "click");
  t = t.replace(/\bslecte\b|\bslect\b|\bslct\b|\bchoos\b/g, "select");
  t = t.replace(
    /\banlyis\b|\banlysis\b|\banlyse\b|\banalys\b|\balaysis\b|\banalsis\b/g,
    "analysis"
  );
  t = t.replace(/\bcopliot\b|\bcopilit\b|\bco-pilot\b/g, "copilot");
  t = t.replace(
    /\bseesion\b|\bseesions\b|\bsesion\b|\bsesions\b/g,
    "sessions"
  );
  t = t.replace(/\bdteel\b|\bstele\b|\bstel\b|\bsteell\b/g, "steel");
  t = t.replace(/\bdteel size\b|\bsteel size\b/g, "steel grain size");
  t = t.replace(/\bgrey\b/g, "gray");
  t = t.replace(/\bflaks\b|\bflak\b|\bflke\b|\bflaek\b/g, "flake");
  t = t.replace(/\bimg\b|\bpic\b|\bphoto\b/g, "image");
  t = t.replace(/\bcam\b|\bmic\b/g, "microscope");
  t = t.replace(/\bscrn\b/g, "screen");
  t = t.replace(/\brpt\b|\brep\b/g, "report");
  t = t.replace(/\bgenrate\b|\bgnrate\b|\bgen\b|\bgenerat\b/g, "generate");
  t = t.replace(/\bverfy\b|\bverif\b|\bvrify\b|\bverifie\b/g, "verify");
  t = t.replace(/\bthern\b/g, "then");
  t = t.replace(/\bnoduler\b|\bnodularty\b/g, "nodularity");
  t = t.replace(/\bcastiron\b/g, "cast iron");
  t = t.replace(/\bliistening\b|\blestining\b|\blistning\b/g, "listening");

  return t.replace(/\s+/g, " ").trim();
}

/**
 * Calculates Levenshtein edit distance similarity between two strings (0.0 to 1.0)
 */
function levenshteinSimilarity(s1, s2) {
  if (s1 === s2) return 1.0;
  if (!s1 || !s2) return 0.0;
  const l1 = s1.length;
  const l2 = s2.length;
  if (Math.abs(l1 - l2) > 5) return 0.0;

  const d = [];
  for (let i = 0; i <= l1; i++) d[i] = [i];
  for (let j = 0; j <= l2; j++) d[0][j] = j;

  for (let i = 1; i <= l1; i++) {
    for (let j = 1; j <= l2; j++) {
      const cost = s1[i - 1] === s2[j - 1] ? 0 : 1;
      d[i][j] = Math.min(
        d[i - 1][j] + 1,
        d[i][j - 1] + 1,
        d[i - 1][j - 1] + cost
      );
    }
  }

  const maxLen = Math.max(l1, l2);
  return 1 - d[l1][l2] / maxLen;
}

class DomActionEngine {
  constructor() {
    this.spotlightTimeout = null;
    this.injectSpotlightStyles();
  }

  injectSpotlightStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("nodiq-spotlight-style")) return;
    const style = document.createElement("style");
    style.id = "nodiq-spotlight-style";
    style.textContent = `
      @keyframes nodiqSpotlightPulse {
        0% {
          box-shadow: 0 0 0 0 rgba(255, 122, 24, 0.8), inset 0 0 12px rgba(255, 122, 24, 0.5);
          outline-color: #FF7A18;
        }
        50% {
          box-shadow: 0 0 28px 8px rgba(0, 229, 255, 0.7), inset 0 0 18px rgba(0, 229, 255, 0.5);
          outline-color: #00E5FF;
        }
        100% {
          box-shadow: 0 0 0 0 rgba(255, 122, 24, 0), inset 0 0 0 rgba(255, 122, 24, 0);
          outline-color: transparent;
        }
      }
      .nodiq-spotlight-target {
        outline: 3px solid #FF7A18 !important;
        outline-offset: 4px !important;
        animation: nodiqSpotlightPulse 2s ease-in-out !important;
        transition: outline 0.3s ease !important;
        position: relative !important;
        z-index: 1000 !important;
      }
    `;
    document.head.appendChild(style);
  }

  highlightElement(element, durationMs = 2000) {
    if (!element) return;
    try {
      element.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
      element.classList.add("nodiq-spotlight-target");
      clearTimeout(this.spotlightTimeout);
      this.spotlightTimeout = setTimeout(() => {
        element.classList.remove("nodiq-spotlight-target");
      }, durationMs);
    } catch {
      // Ignore scroll or class errors
    }
  }

  /**
   * Scans the active DOM for all clickable and interactive elements on the active page
   * NOTE: Explicitly excludes sidebar navigation links and NodiqBot HUD itself
   * to guarantee generic in-page clicks never redirect to Profile or trigger HUD loops!
   */
  scanClickables() {
    const selector = [
      "button:not([disabled])",
      "a[href]",
      "input[type='button']:not([disabled])",
      "input[type='submit']:not([disabled])",
      "[role='button']:not([aria-disabled='true'])",
      "[role='tab']",
      ".nodiq-button-primary",
      ".nodiq-button-secondary",
      ".action-button",
      ".viewer-tool-button",
      ".overlay-toggle",
      ".wci-artifact-tab",
      ".gci-mode-option",
      ".generate-report-button",
      ".upload-zone",
    ].join(", ");

    const elements = Array.from(document.querySelectorAll(selector));
    return elements.filter((el) => {
      // Exclude sidebar navigation and NodiqBot HUD itself
      if (
        el.closest(
          ".nodiq-sidebar, aside, .sidebar-navigation, .sidebar-footer, .nodiqbot-container, .nodiqbot-hud"
        )
      ) {
        return false;
      }

      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        style.visibility !== "hidden" &&
        style.display !== "none" &&
        style.opacity !== "0"
      );
    });
  }

  /**
   * Scans all text/number inputs, textareas, and selects on the active page
   */
  scanInputs() {
    const selector =
      "input:not([type='hidden']):not([type='file']):not([disabled]), textarea:not([disabled]), select:not([disabled])";
    return Array.from(document.querySelectorAll(selector)).filter((el) => {
      // Exclude NodiqBot HUD input
      if (el.closest(".nodiqbot-container, .nodiqbot-hud")) {
        return false;
      }
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        style.visibility !== "hidden" &&
        style.display !== "none"
      );
    });
  }

  /**
   * Matches an element against a voice target query using fuzzy & semantic similarity
   */
  calculateSimilarity(element, query) {
    const q = normalizeVoiceText(query);
    if (!q) return 0;

    const text = normalizeVoiceText(element.innerText || element.textContent || "");
    const aria = normalizeVoiceText(element.getAttribute("aria-label") || "");
    const title = normalizeVoiceText(element.getAttribute("title") || "");
    const placeholder = normalizeVoiceText(element.getAttribute("placeholder") || "");
    const id = normalizeVoiceText(element.id || "");
    const name = normalizeVoiceText(element.getAttribute("name") || "");

    const pool = [text, aria, title, placeholder, id, name].filter(Boolean);

    // Exact matches
    for (const item of pool) {
      if (item === q) return 1.0;
      if (item.includes(q) && (q.length >= 4 || safeWordMatch(item, q))) {
        return 0.9;
      }
      if (q.includes(item) && item.length >= 3 && safeWordMatch(q, item)) {
        return 0.85;
      }

      // Levenshtein fuzzy match
      const lev = levenshteinSimilarity(item, q);
      if (lev > 0.82) return lev;
    }

    // Safe whole-term or phrase matching for synonyms
    const matchTerm = (targetStr, searchStr) => {
      return safeWordMatch(targetStr, searchStr);
    };

    // Synonym cluster matching
    for (const [, synList] of Object.entries(SYNONYMS)) {
      const qInSyn = synList.some((s) => matchTerm(q, s) || matchTerm(s, q));
      if (qInSyn) {
        for (const item of pool) {
          if (synList.some((s) => matchTerm(item, s) || matchTerm(s, item))) {
            return 0.92;
          }
        }
      }
    }

    // Token overlap score with length guard
    const queryTokens = q.split(/\s+/).filter((t) => t.length > 2);
    if (!queryTokens.length) return 0;

    let maxTokenScore = 0;
    for (const item of pool) {
      const itemTokens = item.split(/\s+/).filter((t) => t.length > 2);
      const overlap = queryTokens.filter((qt) =>
        itemTokens.some(
          (it) =>
            it === qt ||
            (it.length > 3 && qt.length > 3 && (it.includes(qt) || qt.includes(it))) ||
            levenshteinSimilarity(it, qt) > 0.82
        )
      ).length;
      const score = overlap / queryTokens.length;
      if (score > maxTokenScore) maxTokenScore = score;
    }

    return maxTokenScore * 0.8;
  }

  /**
   * Finds the best matching clickable element for a spoken query
   */
  findClickable(query) {
    const cleanQuery = normalizeVoiceText(query);
    const candidates = this.scanClickables();
    let best = null;
    let highestScore = 0.42; // slightly elevated confidence threshold

    for (const el of candidates) {
      const score = this.calculateSimilarity(el, cleanQuery);
      if (score > highestScore) {
        highestScore = score;
        best = el;
      }
    }

    return best ? { element: best, score: highestScore } : null;
  }

  /**
   * Dispatches human-like click events to trigger React and native handlers
   */
  click(element) {
    if (!element) return false;
    this.highlightElement(element);

    try {
      element.focus();
      // Invoke native DOM click to trigger React's synthetic onClick handler
      if (typeof element.click === "function") {
        element.click();
        return true;
      }
      const pointerDown = new PointerEvent("pointerdown", { bubbles: true, cancelable: true });
      const mouseDown = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
      const pointerUp = new PointerEvent("pointerup", { bubbles: true, cancelable: true });
      const mouseUp = new MouseEvent("mouseup", { bubbles: true, cancelable: true });
      const click = new MouseEvent("click", { bubbles: true, cancelable: true, view: window });

      element.dispatchEvent(pointerDown);
      element.dispatchEvent(mouseDown);
      element.dispatchEvent(pointerUp);
      element.dispatchEvent(mouseUp);
      element.dispatchEvent(click);
      return true;
    } catch (err) {
      console.warn("DOM click fallback:", err);
      try { element.click(); } catch {}
      return true;
    }
  }

  /**
   * Finds and sets value in an input field (e.g. scale, search, forms)
   */
  setValue(inputElement, value) {
    if (!inputElement) return false;
    this.highlightElement(inputElement);

    try {
      inputElement.focus();
      // Use prototype setter to trigger React's synthetic onChange
      const prototype = Object.getPrototypeOf(inputElement);
      const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
      if (descriptor && descriptor.set) {
        descriptor.set.call(inputElement, value);
      } else {
        inputElement.value = value;
      }

      inputElement.dispatchEvent(new Event("input", { bubbles: true }));
      inputElement.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    } catch (err) {
      console.warn("DOM setValue failed:", err);
      inputElement.value = value;
      return true;
    }
  }

  /**
   * Finds a specific input (e.g. "scale", "search", "calibration") and sets value
   */
  findAndSetValue(inputQuery, value) {
    const cleanQuery = normalizeVoiceText(inputQuery);
    const inputs = this.scanInputs();
    let best = null;
    let highestScore = 0.3;

    for (const inp of inputs) {
      const parentLabel = inp.closest("label")?.innerText || "";
      const text = `${parentLabel} ${inp.placeholder || ""} ${inp.name || ""} ${inp.id || ""}`;
      const score = this.calculateSimilarity({ innerText: text }, cleanQuery);

      if (score > highestScore) {
        highestScore = score;
        best = inp;
      }
    }

    if (best) {
      return this.setValue(best, value);
    }
    return false;
  }

  /**
   * Universal scroll handler
   */
  scroll(direction = "down") {
    const amount = direction === "up" ? -window.innerHeight * 0.65 : window.innerHeight * 0.65;
    window.scrollBy({ top: amount, behavior: "smooth" });
  }

  scrollToSection(query) {
    const clean = normalizeVoiceText(query);
    const headings = Array.from(document.querySelectorAll("h1, h2, h3, h4, section, .analysis-card, .results-section"));
    for (const h of headings) {
      if (normalizeVoiceText(h.innerText || "").includes(clean)) {
        h.scrollIntoView({ behavior: "smooth", block: "start" });
        this.highlightElement(h);
        return true;
      }
    }
    return false;
  }
}

export const domActionEngine = new DomActionEngine();
export default domActionEngine;
