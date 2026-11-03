/**
 * NODIQ-X API service.
 * Talks to the Flask backend (see server.py at the project root).
 * In dev, vite proxies /api -> http://127.0.0.1:8001 (vite.config.js).
 * In production the Flask server serves the built frontend itself.
 *
 * Every request is cookie-authenticated: the server sets the HttpOnly
 * `nodiq_session` cookie at login, and the browser attaches it automatically
 * to same-origin requests. 401 responses throw a clear error.
 */

import { getCurrentUser } from './authService';

const BASE = "";

function withHeaders(extra = {}) {
  // No Authorization header: browsers attach the HttpOnly session cookie
  // themselves — the token is never exposed to JavaScript.
  return { ...extra };
}

async function handle(resp) {
  let body = null;
  try {
    body = await resp.json();
  } catch {
    body = null;
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      throw new Error("Session expired — please sign in again.");
    }
    const message = body?.error || `Request failed (${resp.status})`;
    throw new Error(message);
  }
  return body;
}

function get(path) {
  // Session-aware gating: when no cached session exists, don't fire
  // authenticated GETs at all — the server would 401 them and pollute the
  // console for every logged-out visitor. Callers receive a rejected
  // promise, which pages already handle as their empty/error state.
  if (!getCurrentUser()) return Promise.reject(new Error("Not signed in"));
  return fetch(`${BASE}${path}`, { headers: withHeaders(), credentials: "same-origin" }).then(handle);
}

function post(path, payload, options = {}) {
  // Same gating for POSTs, EXCEPT auth endpoints (login/signup must reach
  // the server without a token by definition).
  const isAuthEndpoint = /^\/api\/auth\/(login|signup|firebase|forgot-password|reset-password)/.test(path);
  if (!isAuthEndpoint && !getCurrentUser()) {
    return Promise.reject(new Error("Not signed in"));
  }
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: withHeaders({ "Content-Type": "application/json" }),
    credentials: "same-origin",
    body: JSON.stringify(payload),
    ...options,
  }).then(handle);
}

function del(path) {
  if (!getCurrentUser()) return Promise.reject(new Error("Not signed in"));
  return fetch(`${BASE}${path}`, { method: "DELETE", headers: withHeaders(), credentials: "same-origin" }).then(handle);
}

export const api = {
  health: () => get("/api/health"),

  /* ---------------- auth ---------------- */
  signup: ({ name, phone, email, password }) =>
    fetch(`${BASE}/api/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, phone, email, password }),
    }).then(handle),

  login: (email, password) =>
    fetch(`${BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }).then(handle),

  me: () => get("/api/auth/me"),
  changePassword: ({ currentPassword, newPassword }) =>
    post("/api/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    }),
  forgotPassword: (email) =>
    post("/api/auth/forgot-password", {
      email,
      app_url: window.location.origin,
    }),
  resetPassword: ({ token, password }) =>
    post("/api/auth/reset-password", { token, password }),

  /* ---------------- dataset (public) ---------------- */
  dataset: () => get("/api/dataset"),

  datasetImageUrl: (name) => `${BASE}/dataset/${name}`,

  datasetAnalysis: (name) => get(`/api/dataset/analysis/${name}`),

  /* ---------------- analysis ---------------- */
  // opts (all optional, backward compatible with the plain upload call):
  //   analysisType: "graphite_nodularity" | "steel_grain_size"
  //   method:       "gsat" | "astm_estimator" | "compare"  (steel only)
  //   micronsPerPixel: positive number (manual spatial calibration)
  //   inputSource:  "upload" | "microscope" | "dataset" (traceability)
  analyzeUpload: async (file, opts = {}) => {
    const form = new FormData();
    form.append("image", file);
    if (opts.analysisType) form.append("analysis_type", opts.analysisType);
    if (opts.method) form.append("method", opts.method);
    if (opts.micronsPerPixel) {
      form.append("microns_per_pixel", String(opts.micronsPerPixel));
    }
    if (opts.inputSource) form.append("input_source", opts.inputSource);
    const resp = await fetch(`${BASE}/api/analyze`, {
      method: "POST",
      headers: withHeaders(),
      credentials: "same-origin",
      body: form,
    });
    return handle(resp);
  },

  analyzeDatasetImage: (name) => post("/api/analyze", { dataset_image: name }),

  /* ------------- steel grain-size analysis ------------- */
  // Prerequisite status of the two steel pipelines (GSAT / ASTM estimator)
  steelEngines: () => get("/api/steel/engines"),

  // Auto-detect optical scale bar and return micron-per-pixel calibration
  detectSteelScale: async (fileOrData) => {
    let body;
    let headers = withHeaders();
    if (fileOrData instanceof File || fileOrData instanceof Blob) {
      body = new FormData();
      body.append("file", fileOrData);
    } else if (fileOrData?.analysis_id) {
      headers = withHeaders({ "Content-Type": "application/json" });
      body = JSON.stringify(fileOrData);
    } else {
      throw new Error("Invalid input for scale detection");
    }
    const resp = await fetch(`${BASE}/api/steel/detect-scale`, {
      method: "POST",
      headers,
      credentials: "same-origin",
      body,
    });
    return handle(resp);
  },

  // Artifact image for a completed steel analysis (e.g. "gsat_mask",
  // "gsat_overlay", "gsat_intercept", "astm_mask", "astm_overlay").
  // Use fetchImage() with the returned path — the session cookie rides
  // along, which a plain <img src> cannot do for protected routes.
  steelArtifactUrl: (id, kind) => `${BASE}/api/analyses/${id}/artifact/${kind}`,

  /* ------------- white cast iron carbide analysis ------------- */
  whiteCastIronEngines: () => get("/api/white-cast-iron/engines"),

  /* ------------- gray cast iron graphite flake analysis ------------- */
  grayCastIronEngines: () => get("/api/gray-cast-iron/engines"),

  /* ---------------- analyses history ---------------- */
  analyses: () => get("/api/analyses"),

  // Async analysis polling: returns the live status/progress record while a
  // job runs (status "processing"), and record+analysis once it completes.
  analysisDetail: (id) => get(`/api/analyses/${id}`),

  deleteAnalysis: (id) => del(`/api/analyses/${id}`),

  analysisStats: () => get("/api/analyses/stats"),

  /* ---------------- review / validation ---------------- */
  // reviewer identity is derived server-side from the verified token —
  // a client-supplied reviewer name is deliberately not sent
  setReview: (id, { status, comment = "" }) =>
    post(`/api/analyses/${id}/review`, {
      status: status === "clear" ? null : status,
      comment,
    }),

  /* ---------------- reports ---------------- */
  reports: () => get("/api/reports"),

  report: (id) => get(`/api/reports/${id}`),

  deleteReport: (id) => del(`/api/reports/${id}`),

  generateReport: (payload) => post("/api/reports/generate", payload),

  /* ---------------- copilot ---------------- */
  copilot: (message, history = [], sessionId = "default", context = {}, options = {}) =>
    post("/api/copilot", { message, history, session_id: sessionId, context }, options),

  copilotStream: async function* (message, history = [], sessionId = "default", context = {}, options = {}) {
    try {
      const payload = { message, history, session_id: sessionId, context };
      const res = await fetch(`${BASE}/api/copilot/stream`, {
        method: "POST",
        headers: withHeaders({ "Content-Type": "application/json" }),
        credentials: "same-origin",
        body: JSON.stringify(payload),
        signal: options.signal,
      });

      if (!res.ok) {
        // Fallback to non-streaming copilot endpoint on error
        const fallbackRes = await api.copilot(message, history, sessionId, context, options);
        const reply = fallbackRes?.reply || fallbackRes?.response || fallbackRes?.message || "";
        yield { type: "token", delta: reply };
        yield { type: "done", ...fallbackRes, reply };
        return;
      }

      if (!res.body || typeof res.body.getReader !== "function") {
        const data = await res.json().catch(() => ({}));
        yield { type: "token", delta: data?.reply || "" };
        yield { type: "done", ...data };
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith("data:")) {
              const jsonStr = trimmed.slice(5).trim();
              if (jsonStr) {
                try {
                  const parsed = JSON.parse(jsonStr);
                  yield parsed;
                } catch {}
              }
            }
          }
        }
        buffer += decoder.decode();
        if (buffer.trim().startsWith("data:")) {
          const jsonStr = buffer.trim().slice(5).trim();
          if (jsonStr) {
            try {
              yield JSON.parse(jsonStr);
            } catch {}
          }
        }
      } finally {
        try {
          reader.releaseLock();
        } catch {}
      }
    } catch (err) {
      if (err?.name === "AbortError") throw err;
      // Fallback to standard copilot call on network/streaming exception
      const fallbackRes = await api.copilot(message, history, sessionId, context, options);
      const reply = fallbackRes?.reply || fallbackRes?.response || fallbackRes?.message || "";
      yield { type: "token", delta: reply };
      yield { type: "done", ...fallbackRes, reply };
    }
  },

  aiStatus: () => get("/api/ai/status"),

  copilotCapabilities: () => get("/api/copilot/capabilities"),

  /* ---------------- multi-field sampling sessions ---------------- */

  multifieldCreate: (label) => post("/api/multifield", { label }),

  multifieldList: () => get("/api/multifield"),

  multifieldGet: (sid) => get(`/api/multifield/${encodeURIComponent(sid)}`),

  multifieldAddField: (sid, analysisId) =>
    post(`/api/multifield/${encodeURIComponent(sid)}/fields`,
      { analysis_id: analysisId }),

  /* ---------------- work sessions ---------------- */
  sessions: () => get("/api/sessions"),

  session: (id) => get(`/api/sessions/${id}`),

  deleteSession: (id) => del(`/api/sessions/${id}`),

  /* ------------- intelligence services ------------- */
  qualityFor: (id) => get(`/api/quality/${id}`),

  calibration: (payload) => post("/api/calibration", payload),

  analysisImageUrl: (id) => `${BASE}/api/analyses/${id}/image`,

  /* Authenticated image fetch: the session cookie is attached automatically,
     which a plain <img src> cannot do for protected endpoints — so we fetch
     a blob URL instead. */
  fetchImage: async (path) => {
    if (!getCurrentUser()) throw new Error("Not signed in");
    const resp = await fetch(path.startsWith("http") ? path : `${BASE}${path}`, {
      credentials: "same-origin",
    });
    if (!resp.ok) throw new Error(`image ${resp.status}`);
    const blob = await resp.blob();
    return URL.createObjectURL(blob);
  },

  analysisNodules: (id) => get(`/api/analyses/${id}/nodules`),

  noduleDetails: (id, noduleId) =>
    get(`/api/analyses/${id}/nodules/${noduleId}`),

  compare: (a, b) => post("/api/compare", { analysis_a: a, analysis_b: b }),

  batchStats: () => get("/api/batch/stats"),

  spc: (metric = "nodularity") =>
    get(`/api/spc?metric=${encodeURIComponent(metric)}`),

  anomalies: () => get("/api/anomalies"),

  anomalyFor: (id) => get(`/api/anomalies/${id}`),

  decisionSupport: (id) => post("/api/decision-support", { analysis_id: id }),

  validationSummary: () => get("/api/validation"),

  runValidation: (kind, n = 5) => post("/api/validation/run", { kind, n }),

  aiSummary: (analysisId) => post("/api/reports/ai-summary", { analysis_id: analysisId }),

  reportDownloadUrl: (reportId, format = "pdf") =>
    `${BASE}/api/reports/${reportId}/download?format=${format}`,

  /* Authenticated file download as a Blob (PDF/CSV/JSON). The session
     cookie rides along automatically; a plain <a href> download also would,
     but we need error-message handling around failures. */
  downloadReport: async (reportId, format = "pdf") => {
    const resp = await fetch(
      `${BASE}/api/reports/${reportId}/download?format=${format}`,
      { credentials: "same-origin" });
    if (!resp.ok) {
      let message = `Download failed (${resp.status})`;
      try {
        const body = await resp.json();
        if (body?.error) message = body.error;
      } catch {
        /* non-JSON error body */
      }
      throw new Error(message);
    }
    return resp.blob();
  },
};

export default api;
