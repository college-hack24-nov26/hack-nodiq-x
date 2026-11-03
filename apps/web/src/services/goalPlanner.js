/**
 * Goal Planner: Multi-Step Task Sequencing & Navigation Coordinator
 * Orchestrates cross-page workflows, navigation, parameter injection,
 * and multi-stage action pipelines across NODIQ-X.
 */

import domActionEngine, { normalizeVoiceText } from "./domActionEngine.js";

const ROUTES = [
  {
    keywords: ["dashboard", "board", "home metrics", "overview", "home board"],
    path: "/dashboard",
    name: "Dashboard",
  },
  {
    keywords: ["home"],
    path: "/home",
    name: "Home",
  },
  {
    keywords: [
      "start new analysis",
      "new analysis",
      "start new anlysis",
      "another analysis",
      "start another analysis",
      "start cast iron",
      "nodular cast iron",
      "nodular iron",
      "nodular",
      "ductile iron",
      "ductile cast iron",
      "cast iron analysis",
      "cast iron",
      "microstructure analysis",
    ],
    path: "/new-analysis",
    name: "Nodular Cast Iron Analysis",
  },
  {
    keywords: [
      "steel",
      "steel size",
      "dteel size",
      "dteel",
      "grain size",
      "steel grain size",
      "steel grain",
      "steel analysis",
      "astm grain",
      "grain",
    ],
    path: "/steel-analysis",
    name: "Steel Grain Size Analysis",
  },
  {
    keywords: [
      "white cast iron",
      "white cast iron carbide",
      "carbide analysis",
      "cementite",
      "ledeburite",
    ],
    path: "/white-cast-iron",
    name: "White Cast Iron Carbide Analysis",
  },
  {
    keywords: [
      "gray cast iron flakes",
      "grey cast iron flakes",
      "gray cast iron flake",
      "grey cast iron flake",
      "gray cast iron",
      "grey cast iron",
      "cast iron flakes",
      "cast iron flake",
      "gray flakes",
      "grey flakes",
      "gray flake",
      "grey flake",
      "gray iron",
      "grey iron",
      "graphite flakes",
      "graphite flake",
      "flake analysis",
      "flakes analysis",
      "flakes",
      "flake",
      "s-metallograph",
      "s metallograph",
    ],
    path: "/gray-cast-iron",
    name: "Gray Cast Iron Flake Analysis",
  },
  {
    keywords: [
      "my analyses",
      "my analysis",
      "my anlysis",
      "analyses",
      "all analyses",
      "all analysis",
      "analysis history",
      "past analyses",
      "past analysis",
      "recent analyses",
      "previous analyses",
      "history",
      "records",
    ],
    path: "/analyses",
    name: "My Analyses",
  },
  {
    keywords: [
      "copilot",
      "copliot",
      "nodiq copilot",
      "ai copilot",
      "copilot chat",
      "ai assistant",
      "assistant",
      "metallurgy copilot",
      "copilot ai",
    ],
    path: "/copilot",
    name: "Copilot",
  },
  {
    keywords: [
      "sessions",
      "session",
      "seesion",
      "seesions",
      "sesion",
      "sesions",
      "work sessions",
      "analysis sessions",
      "login sessions",
      "recent sessions",
    ],
    path: "/sessions",
    name: "Sessions",
  },
  {
    keywords: [
      "analytics",
      "trends",
      "yield",
      "charts",
      "production analytics",
      "metrics analytics",
      "performance charts",
    ],
    path: "/analytics",
    name: "Analytics",
  },
  {
    keywords: [
      "lots",
      "lot",
      "heat",
      "heats",
      "batch lots",
      "production lots",
      "casting lots",
      "lot tracking",
    ],
    path: "/lots",
    name: "Lots",
  },
  {
    keywords: [
      "review",
      "review center",
      "verification portal",
      "approval",
      "approvals",
      "audits",
      "verify",
    ],
    path: "/review-center",
    name: "Review Center",
  },
  {
    keywords: [
      "reports",
      "back to reports",
      "report list",
      "generated reports",
      "technical report",
      "technical reports",
    ],
    path: "/reports",
    name: "Reports",
  },
  {
    keywords: [
      "anomalies",
      "defects",
      "outliers",
      "defect analysis",
      "defect list",
    ],
    path: "/anomalies",
    name: "Anomalies",
  },
  {
    keywords: [
      "batch",
      "batch analysis",
      "bulk",
      "bulk analysis",
      "multi image",
      "multi image analysis",
    ],
    path: "/batch-analysis",
    name: "Batch Analysis",
  },
  {
    keywords: [
      "compare",
      "comparison",
      "side by side",
      "split comparison",
      "sample comparison",
    ],
    path: "/compare",
    name: "Compare",
  },
  {
    keywords: [
      "settings",
      "preferences",
      "configuration",
      "config",
    ],
    path: "/settings",
    name: "Settings",
  },
  {
    keywords: [
      "profile",
      "my profile",
      "account profile",
      "user profile",
      "account",
      "user info",
    ],
    path: "/profile",
    name: "Profile",
  },
];

class GoalPlanner {
  constructor() {
    this.navigate = null;
    this.location = null;
  }

  setNavigator(navigate, location) {
    this.navigate = navigate;
    this.location = location;
  }

  /**
   * Resolves a spoken destination to an internal route using longest-keyword matching
   * Ensures specific routes ("gray cast iron flakes") always beat generic ones ("cast iron")
   */
  resolveRoute(query) {
    const q = normalizeVoiceText(query);
    if (!q) return null;

    let bestMatch = null;
    let longestKeywordLength = 0;

    for (const r of ROUTES) {
      for (const kw of r.keywords) {
        const kwNorm = normalizeVoiceText(kw);
        if (q === kwNorm) {
          return r; // Immediate exact match
        }
        if (q.includes(kwNorm) && kwNorm.length > longestKeywordLength) {
          longestKeywordLength = kwNorm.length;
          bestMatch = r;
        }
      }
    }

    if (bestMatch) return bestMatch;

    // Secondary match: multi-word keywords all present
    for (const r of ROUTES) {
      for (const kw of r.keywords) {
        const kwWords = kw.split(/\s+/).filter(Boolean);
        if (kwWords.length > 1 && kwWords.every((w) => q.includes(w))) {
          if (kw.length > longestKeywordLength) {
            longestKeywordLength = kw.length;
            bestMatch = r;
          }
        }
      }
    }

    return bestMatch;
  }

  /**
   * Navigates to a route with smooth visual feedback
   */
  async goToRoute(path) {
    if (!this.navigate) {
      window.location.href = path;
      return true;
    }
    if (this.location?.pathname === path) {
      return true; // Already there
    }
    this.navigate(path);
    // Give React time to mount the new route view
    await new Promise((r) => setTimeout(r, 450));
    return true;
  }

  /**
   * Sets spatial scale/calibration across any analysis workspace
   */
  setCalibration(value) {
    const numeric = String(value).replace(/[^0-9.]/g, "");
    if (!numeric) return false;

    // Try finding scale or calibration inputs
    const inputs = domActionEngine.scanInputs();
    const targetInput = inputs.find((inp) => {
      const label = (inp.closest("label")?.innerText || "").toLowerCase();
      const placeholder = (inp.placeholder || "").toLowerCase();
      const id = (inp.id || "").toLowerCase();
      return (
        label.includes("scale") ||
        label.includes("µm") ||
        label.includes("micron") ||
        placeholder.includes("0.45") ||
        placeholder.includes("scale") ||
        id.includes("scale")
      );
    });

    if (targetInput) {
      return domActionEngine.setValue(targetInput, numeric);
    }

    // Generic fallback: find any input containing scale
    return domActionEngine.findAndSetValue("scale", numeric);
  }

  /**
   * Executes a multi-step workflow sequence
   */
  async executeSequence(steps, onStepProgress) {
    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      if (onStepProgress) onStepProgress(step.name, i + 1, steps.length);

      if (step.type === "navigate") {
        await this.goToRoute(step.target);
      } else if (step.type === "click") {
        const found = domActionEngine.findClickable(step.target);
        if (found) domActionEngine.click(found.element);
      } else if (step.type === "calibrate") {
        this.setCalibration(step.value);
      } else if (step.type === "wait") {
        await new Promise((r) => setTimeout(r, step.ms || 500));
      }
    }
  }

  /**
   * Toggles light / dark mode
   */
  toggleTheme() {
    const themeBtn = document.querySelector("[aria-label*='theme' i], button[title*='theme' i], .theme-toggle, .btn-theme");
    if (themeBtn) {
      domActionEngine.click(themeBtn);
      return true;
    }
    const iconBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      b.innerHTML.includes("dark_mode") || b.innerHTML.includes("light_mode")
    );
    if (iconBtn) {
      domActionEngine.click(iconBtn);
      return true;
    }
    return false;
  }

  /**
   * Highlights or hovers key areas like dashboard cards or KPI boards
   */
  hoverTarget(query) {
    const candidates = Array.from(
      document.querySelectorAll(".analysis-card, .dashboard-card, .kpi-card, .metric-card, header, .analysis-page")
    );
    const target = candidates.find((c) => (c.innerText || "").toLowerCase().includes(query.toLowerCase())) || candidates[0];
    if (target) {
      domActionEngine.highlightElement(target, 2200);
      return true;
    }
    return false;
  }
}

export const goalPlanner = new GoalPlanner();
export default goalPlanner;
