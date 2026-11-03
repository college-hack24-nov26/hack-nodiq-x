/**
 * Phrase Segmenter for Streaming Conversational Voice Output
 *
 * Buffers streaming text tokens and segments them into clean, speakable
 * phrases at natural sentence boundaries without speaking individual tokens
 * or waiting for the entire LLM response.
 *
 * Features:
 *  - Preserves abbreviations (e.g., i.e., fig., no., vol., approx., astm., iso.)
 *  - Preserves decimal numbers and measurements (82.5%, 0.45 um, 100 mm)
 *  - Filters fenced action blocks (```action ... ```), markdown headers (###),
 *    bold/italic markers (**), and HTML tags.
 *  - Prefers natural sentence terminations over splitting at every comma.
 */

const KNOWN_ABBREVIATIONS = new Set([
  "e.g", "i.e", "fig", "no", "vol", "approx", "spec", "vs", "dr", "mr", "mrs", "ms", "astm", "iso", "jis", "al"
]);

export class PhraseSegmenter {
  constructor(options = {}) {
    this.minPhraseLength = options.minPhraseLength || 40;
    this.buffer = "";
    this.inActionBlock = false;
    this.phraseCallbacks = [];
  }

  onPhrase(cb) {
    this.phraseCallbacks.push(cb);
    return () => {
      this.phraseCallbacks = this.phraseCallbacks.filter((c) => c !== cb);
    };
  }

  emitPhrase(phrase) {
    const cleaned = this.cleanForSpeech(phrase);
    if (!cleaned) return;
    for (const cb of this.phraseCallbacks) {
      try {
        cb(cleaned);
      } catch (err) {
        console.warn("Phrase callback error:", err);
      }
    }
  }

  cleanForSpeech(text) {
    if (!text || typeof text !== "string") return "";
    return text
      .replace(/```action[\s\S]*?```/gi, "")
      .replace(/```json[\s\S]*?```/gi, "")
      .replace(/```tool[\s\S]*?```/gi, "")
      .replace(/```[\s\S]*?```/gi, "")
      .replace(/`([^`]+)`/g, "$1") // inline code backticks
      .replace(/\*\*([^*]+)\*\*/g, "$1") // bold
      .replace(/\*([^*]+)\*/g, "$1") // italic
      .replace(/[*_#~[\]()]/g, " ") // formatting markers
      .replace(/<[^>]*>/g, "") // HTML tags
      .replace(/\s+/g, " ")
      .trim();
  }

  push(token) {
    if (typeof token !== "string" || !token) return;

    this.buffer += token;

    // Filter fenced action/tool blocks if partially arriving
    if (this.buffer.includes("```action") || this.buffer.includes("```json") || this.buffer.includes("```tool")) {
      const match = this.buffer.match(/```(?:action|json|tool)[\s\S]*?```/i);
      if (match) {
        this.buffer = this.buffer.replace(match[0], " ");
      } else {
        // Still inside unclosed action block, wait for fence closing
        return;
      }
    }

    // Sentence boundary detection with abbreviation & decimal guards
    const sentenceRegex = /([.!?\n]+)\s+/g;
    let match;

    while ((match = sentenceRegex.exec(this.buffer)) !== null) {
      const punc = match[1];
      const matchIndex = match.index;
      const splitPos = matchIndex + match[0].length;
      const preText = this.buffer.slice(0, matchIndex).trim();

      // Check if the period is part of a decimal number (e.g. "82.5")
      if (punc === "." && matchIndex > 0) {
        const prevChar = this.buffer[matchIndex - 1];
        if (/\d/.test(prevChar)) {
          // Check if followed by digit or unit
          const postChar = this.buffer[splitPos];
          if (/\d|%|um|mm/i.test(postChar || "")) {
            continue; // Decimal, do not split
          }
        }
      }

      // Check if preceded by a known abbreviation (e.g. "e.g.", "Fig.")
      if (punc === ".") {
        const lastWordMatch = preText.match(/(?:[a-zA-Z]+\.[a-zA-Z]+|[a-zA-Z]+)$/);
        if (lastWordMatch) {
          const lastWord = lastWordMatch[0].toLowerCase();
          if (KNOWN_ABBREVIATIONS.has(lastWord)) {
            continue; // Abbreviation, do not split
          }
        }
      }

      if (preText.length >= 8) {
        this.emitPhrase(preText + (punc !== "\n" ? punc[0] : "."));
        this.buffer = this.buffer.slice(splitPos);
        sentenceRegex.lastIndex = 0;
        return;
      }
    }

    // Secondary clause pause only on very long sentences (>= minPhraseLength)
    if (this.buffer.length >= this.minPhraseLength) {
      const clauseMatch = /([,;:])\s+/g.exec(this.buffer);
      if (clauseMatch && clauseMatch.index >= 30) {
        const splitPos = clauseMatch.index + clauseMatch[0].length;
        const candidate = this.buffer.slice(0, splitPos).trim();
        this.emitPhrase(candidate);
        this.buffer = this.buffer.slice(splitPos);
      }
    }
  }

  flush() {
    if (this.buffer.trim().length > 0) {
      this.emitPhrase(this.buffer.trim());
      this.buffer = "";
    }
  }

  reset() {
    this.buffer = "";
    this.inActionBlock = false;
  }
}

export default PhraseSegmenter;
