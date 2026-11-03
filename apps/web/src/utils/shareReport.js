/**
 * shareReport.js — real PDF sharing with honest fallbacks.
 *
 * Priority order:
 *   1. Web Share API with the actual PDF file (Android/Windows/mobile —
 *      shares to Gmail, WhatsApp, Teams, Drive, etc.)
 *   2. Download the PDF locally (universally supported)
 *   3. Copy a shareable link (only when a persistent URL exists)
 *
 * NEVER reports success unless the operation really succeeded; every
 * failure surfaces as a thrown Error with a user-facing message.
 */

/**
 * Trigger a browser download for a Blob.
 */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Give the browser a moment before revoking (some engines cancel the
  // download otherwise).
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/**
 * Share (or download) an actual PDF file.
 * @param {Blob} pdfBlob   the real PDF bytes
 * @param {string} filename
 * @param {string} title   share sheet title
 * @param {string} text    share sheet body text
 * @returns {Promise<{method: "share"|"download"}>}
 */
export async function sharePdfFile(pdfBlob, filename, title, text) {
  const file = new File([pdfBlob], filename, { type: "application/pdf" });

  const canShareFiles =
    typeof navigator !== "undefined" &&
    typeof navigator.canShare === "function" &&
    typeof navigator.share === "function" &&
    (() => {
      try {
        return navigator.canShare({ files: [file] });
      } catch {
        return false;
      }
    })();

  if (canShareFiles) {
    try {
      await navigator.share({ title, text, files: [file] });
      return { method: "share" };
    } catch (err) {
      // AbortError = the user closed the share sheet; not a failure.
      if (err?.name === "AbortError") {
        throw new Error("SHARE_CANCELLED");
      }
      // Fall through to download on any other share failure.
    }
  }

  saveBlob(pdfBlob, filename);
  return { method: "download" };
}

/**
 * Copy arbitrary text to the clipboard; throws when unavailable.
 */
export async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  throw new Error("Clipboard is not available in this browser.");
}
