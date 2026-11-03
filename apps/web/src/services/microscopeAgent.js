/**
 * NODIQ-X microscope camera client (Phase 2).
 *
 * ALL communication with the local NODIQ-X camera agent lives here —
 * Analysis.jsx (or any other page) never talks to the hardware directly.
 *
 * Agent API (nodiq-camera-agent/agent_server.py, http://127.0.0.1:8765):
 *   GET /status    -> { connected, device_id, model, manufacturer, serial,
 *                       resolution: {width, height} | null }
 *   GET /capture   -> image/png bytes (fresh frame, lossless)
 *   GET /preview   -> image/jpeg bytes (fresh frame, quick view)
 *
 * Security: the agent answers only allowed origins (localhost:5173 dev SPA)
 * and Chrome's Private Network Access preflight; the Flask CSP was extended
 * with this origin in server.py (connect-src only).
 */

// Configurable so a deployment can move the agent without code changes.
const AGENT_BASE =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_CAMERA_AGENT_URL) ||
  "http://127.0.0.1:8765";

const DEFAULT_TIMEOUT_MS = 20_000; // capture includes exposure (~4 s measured)

export class MicroscopeAgentError extends Error {
  constructor(code, message, httpStatus = 0) {
    super(message);
    this.name = "MicroscopeAgentError";
    this.code = code;          // 'unavailable' | 'camera_busy' | 'camera_not_found'
                               // | 'capture_failed' | 'sdk_unavailable' | 'timeout'
    this.httpStatus = httpStatus;
  }
}

async function agentFetch(path, { timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${AGENT_BASE}${path}`, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });
    return resp;
  } catch (err) {
    if (err?.name === "AbortError") {
      throw new MicroscopeAgentError(
        "timeout", "The camera agent did not answer in time. Is it running?");
    }
    // Network-level failure: agent not started, port blocked, or PNA refusal.
    throw new MicroscopeAgentError(
      "unavailable",
      `Cannot reach the camera agent at ${AGENT_BASE}. Start it with: python agent_server.py`);
  } finally {
    clearTimeout(timer);
  }
}

async function agentError(resp) {
  let payload = null;
  try { payload = await resp.json(); } catch { /* non-JSON */ }
  const map = {
    409: "camera_busy",
    503: payload?.error === "sdk_unavailable" ? "sdk_unavailable" : "camera_not_found",
    504: "capture_failed",
  };
  throw new MicroscopeAgentError(
    map[resp.status] || "capture_failed",
    payload?.message || `Camera agent error (${resp.status})`,
    resp.status);
}

/**
 * Live camera status. Returns the /status JSON (connected false when no
 * camera is plugged in — that is a normal state, not an error).
 */
export async function getCameraStatus() {
  const resp = await agentFetch("/status", { timeoutMs: 8_000 });
  if (!resp.ok) await agentError(resp);
  return resp.json();
}

/**
 * One fresh frame as PNG bytes. Returns a browser File ready for the
 * existing upload funnel (runOnFile) — no camera logic outside this module.
 */
export async function captureImage({ filename = `microscope_${DateStamp()}.png` } = {}) {
  const resp = await agentFetch("/capture");
  if (!resp.ok) await agentError(resp);
  const blob = await resp.blob();
  if (!blob.size) {
    throw new MicroscopeAgentError("capture_failed", "The agent returned an empty image.");
  }
  return new File([blob], filename, { type: blob.type || "image/png" });
}

/**
 * One fresh frame as JPEG blob URL for quick display (downscaled by the
 * agent for light polling). Caller owns the URL (URL.revokeObjectURL).
 */
export async function capturePreview() {
  const resp = await agentFetch("/preview");
  if (!resp.ok) await agentError(resp);
  return URL.createObjectURL(await resp.blob());
}

/**
 * Live preview loop (Phase 3): repeatedly fetches /preview until stopped.
 * - The agent serves downscaled JPEGs and keeps the device open between
 *   polls (idle-closed after 15 s), so a 1 s interval is light.
 * - onFrame(blobUrl, meta) receives each frame; onState(state, detail)
 *   reports 'live' | 'error' | 'stopped' so the UI can show status.
 * - Sequential polling (no overlap): a slow frame delays the next poll
 *   instead of piling up requests on the camera.
 * Returns a stop() function; callers MUST stop when the panel closes.
 */
export function startLivePreview({ intervalMs = 1000, onFrame, onState } = {}) {
  let stopped = false;
  let timer = null;
  let lastUrl = null;

  const cleanup = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    if (lastUrl) { URL.revokeObjectURL(lastUrl); lastUrl = null; }
  };

  const tick = async () => {
    if (stopped) return;
    try {
      const url = await capturePreview();
      if (stopped) { URL.revokeObjectURL(url); return; }
      if (lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = url;
      const img = new Image();
      img.onload = () => {
        if (!stopped) onFrame?.(url, { width: img.naturalWidth, height: img.naturalHeight });
      };
      img.src = url;
      onState?.("live");
    } catch (err) {
      if (stopped) return;
      onState?.("error", err);
    } finally {
      if (!stopped) timer = setTimeout(tick, intervalMs);
    }
  };

  timer = setTimeout(tick, 0);
  return {
    stop() {
      stopped = true;
      cleanup();
      onState?.("stopped");
    },
  };
}

/**
 * Lightweight visual sanity check on a captured frame (Phase 3 feature 5).
 * ONLY flags obviously unusable frames (pitch black / fully saturated);
 * the server's microstructure-validity gate stays the sole authority on
 * whether something is a micrograph — this never rejects a File.
 * Returns { ok, hint } where hint is a human message or null.
 */
export async function quickQualityCheck(file) {
  try {
    const bitmap = await createImageBitmap(file);
    const side = 128;                       // tiny sample is plenty
    const canvas = document.createElement("canvas");
    canvas.width = side; canvas.height = side;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(bitmap, 0, 0, side, side);
    bitmap.close?.();
    const { data } = ctx.getImageData(0, 0, side, side);
    let sum = 0;
    let black = 0;
    let white = 0;
    const n = side * side;
    for (let i = 0; i < data.length; i += 4) {
      const lum = 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
      sum += lum;
      if (lum < 8) black += 1;
      if (lum > 247) white += 1;
    }
    const mean = sum / n;
    if (mean < 12 || black / n > 0.9) {
      return { ok: false, hint: "Image appears too dark. Check microscope illumination." };
    }
    if (mean > 243 || white / n > 0.9) {
      return { ok: false, hint: "Image appears fully saturated (white). Check exposure/illumination." };
    }
    return { ok: true, hint: null, mean };
  } catch {
    // If the browser cannot decode it, let the server decide — never block.
    return { ok: true, hint: null };
  }
}

function DateStamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}
