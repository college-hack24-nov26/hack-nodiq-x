/**
 * Voice Agent: Web Speech Recognition (STT) + Speech Synthesis (TTS)
 * Provides continuous wake-word listening ("Hi NodiqBot"), live transcription,
 * echo-loopback cancellation, and natural voice feedback.
 */

export const WAKE_WORDS = [
  "hi nodiq bot",
  "hey nodiq bot",
  "nodiq bot",
  "nodiqbot",
  "hi jarvis",
  "hey jarvis",
  "ok nodiq",
  "okay nodiq",
  "hi nodiq",
  "hey nodiq",
  "nodiq",
];

// Configurable interruption phrases for immediate barge-in cancellation
export const INTERRUPTION_PATTERNS = [
  /^(?:please\s+)?(?:stop\s+talking|stop\s+speaking|stop\s+speech|stop\s+voice)\b/i,
  /^(?:please\s+)?(?:be\s+quiet|quiet\s+please)\b/i,
  /^(?:shut\s+up)\b/i,
  /^(?:cancel\s+(?:your\s+)?response|cancel\s+speech|cancel\s+talking)\b/i,
  /^(?:that'?s\s+enough|enough\s+already)\b/i,
  /^(?:pause\s+talking|pause\s+speech)\b/i,
  /^(?:hush|silence)\b/i,
];

/**
 * Checks whether an utterance is an intentional speech interruption command.
 * Avoids broad matching so compound commands like "stop analysis" are never misclassified.
 */
export function isInterruptionCommand(text, isCurrentlySpeaking = false) {
  if (!text || typeof text !== "string") return false;
  const trimmed = text.trim();
  if (INTERRUPTION_PATTERNS.some((pattern) => pattern.test(trimmed))) {
    return true;
  }
  // If the assistant is actively speaking, standalone "stop", "halt", "quiet", or "enough"
  // is an immediate voice interruption, but NOT ordinary compound commands like "stop analysis".
  if (isCurrentlySpeaking) {
    if (/^(?:please\s+)?(?:stop|halt|quiet|enough)(?:[.!?,]|\s*$)/i.test(trimmed)) {
      return true;
    }
  }
  return false;
}

// Pronunciation replacements for metallurgical terminology
const PRONUNCIATION_MAP = [
  { regex: /\bµm\b/gi, replacement: "micrometres" },
  { regex: /\bum\b/gi, replacement: "micrometres" },
  { regex: /\bpx²\b/gi, replacement: "square pixels" },
  { regex: /\bpx\b/gi, replacement: "pixels" },
  { regex: /\bISO\b/g, replacement: "I-S-O" },
  { regex: /\bASTM\b/g, replacement: "A-S-T-M" },
  { regex: /\bJIS\b/g, replacement: "J-I-S" },
  { regex: /\bFOV\b/g, replacement: "field of view" },
  { regex: /\bCARDE\b/g, replacement: "Carde" },
  { regex: /\bGSAT\b/g, replacement: "G-SAT" },
];

import audioCapturePipeline from "./audioCapturePipeline";
import voiceDiagnostics from "./voiceDiagnostics";
import PhraseSegmenter from "./phraseSegmenter";
import SpeechStreamQueue from "./speechStreamQueue";

class VoiceAgent {
  constructor() {
    this.recognition = null;
    this.audioPipeline = audioCapturePipeline;
    this.streamQueue = new SpeechStreamQueue(this);
    this.phraseSegmenter = new PhraseSegmenter();
    this.isListening = false;
    this.isHandsFree = true;
    this.isSpeaking = false;
    this.isMuted = false;
    this.transcriptCallback = null;
    this.commandCallback = null;
    this.stateCallback = null;
    this.interruptionCallback = null;
    this.levelCallback = null;
    this.currentUtterance = null;
    this.supported = false;
    this.selectedVoice = null;

    // Generation counter & active speech text for robust cancellation & echo avoidance
    this.speechGeneration = 0;
    this.currentSpeakingText = "";

    // Echo / loopback cancellation guards
    this.ignoreAudioUntil = 0;
    this.recentBotUtterances = [];
    this.watchdogInterval = null;

    // Debounce & duplicate dispatch prevention
    this.lastInterimCandidate = "";
    this.interimTimer = null;
    this.lastDispatchedCommand = "";
    this.lastDispatchTimestamp = 0;

    // Background tab visibility & anti-eavesdropping guards
    this.isTabHidden = typeof document !== "undefined" ? (document.hidden || document.visibilityState === "hidden") : false;
    this.wasHandsFreeBeforeHidden = this.isHandsFree;
    this.handleVisibilityChange = null;
    this.handleWindowBlur = null;
    this.bindVisibilityListeners();

    this.initSpeechRecognition();
    this.initAudioPipeline();
    this.initSpeechSynthesis();
    this.startWatchdog();
  }

  bindVisibilityListeners() {
    if (typeof document === "undefined") return;

    this.handleVisibilityChange = () => {
      const isHidden = !!(document.hidden || document.visibilityState === "hidden");
      this.isTabHidden = isHidden;

      if (isHidden) {
        // Tab moved to background (user switched to another tab, e.g. lecture/video)
        // Immediately halt mic capture, speech recognition, and speech playback
        this.wasHandsFreeBeforeHidden = this.isHandsFree;

        if (this.interimTimer) {
          clearTimeout(this.interimTimer);
          this.interimTimer = null;
        }
        this.lastInterimCandidate = "";

        if (this.audioPipeline && this.audioPipeline.isCapturing) {
          this.audioPipeline.stop();
        }
        if (this.isSpeaking) {
          this.stopSpeaking();
        }

        if (this.recognition && this.isListening) {
          try {
            this.recognition.stop();
          } catch {}
          this.isListening = false;
        }
        this.emitState("idle");
      } else {
        // Tab restored to foreground: resume if handsFree was active before tab switch
        if (this.wasHandsFreeBeforeHidden && !this.isListening) {
          setTimeout(() => {
            if (!this.isTabHidden && (typeof document === "undefined" || !document.hidden)) {
              if (this.isHandsFree && !this.isListening) {
                this.startListening();
              }
            }
          }, 400);
        }
      }
    };

    document.addEventListener("visibilitychange", this.handleVisibilityChange);
    if (typeof window !== "undefined") {
      this.handleWindowBlur = () => {
        if (document.hidden) {
          this.handleVisibilityChange();
        }
      };
      window.addEventListener("blur", this.handleWindowBlur);
    }
  }

  startWatchdog() {
    if (this.watchdogInterval) clearInterval(this.watchdogInterval);
    if (typeof window === "undefined") return;
    this.watchdogInterval = setInterval(() => {
      if (!this.supported) return;

      // DO NOT keep-alive or restart listening if tab is in the background
      if (typeof document !== "undefined" && (document.hidden || document.visibilityState === "hidden" || this.isTabHidden)) {
        return;
      }

      // 1. Check if browser speech synthesis actually stopped
      if (this.isSpeaking && (!window.speechSynthesis || !window.speechSynthesis.speaking)) {
        this.isSpeaking = false;
        this.currentSpeakingText = "";
      }

      // 2. Unstick speech synthesis if paused (common Chrome quirk)
      if (window.speechSynthesis && window.speechSynthesis.paused) {
        try { window.speechSynthesis.resume(); } catch {}
      }

      // 3. Keep-alive for Hands-Free recognition (foreground only)
      if (this.isHandsFree && !this.isListening) {
        this.startListening();
      }
    }, 1000);
  }

  initAudioPipeline() {
    if (!this.audioPipeline) return;

    this.audioPipeline.onSpeechStart((data) => {
      // Immediate Acoustic Speech-Start Barge-in:
      // If the assistant is actively speaking, halt playback immediately!
      if (this.isSpeaking) {
        voiceDiagnostics.mark("speech_start");
        this.handleInterruption("", "vad_speech_start");
      }
    });

    this.audioPipeline.onSpeechEnd(() => {
      voiceDiagnostics.mark("turn_end");
      // If we have a stable interim transcript and speech recognition has paused without isFinal:
      if (
        this.lastInterimCandidate &&
        !this.isSpeaking &&
        Date.now() - this.lastDispatchTimestamp > 1200
      ) {
        const candidate = this.lastInterimCandidate.trim();
        const isIncomplete =
          /^(?:please\s+)?(?:now|go|go to|now go|now go to|visit|now visit|open|now open|show|show me|take me|take me to|navigate|navigate to|switch|switch to|and|to|the|for|in|on|at|can you|could you|i want to|i wanna)?\s*$/i.test(
            candidate
          );
        if (!isIncomplete && candidate.length > 2) {
          this.lastInterimCandidate = "";
          this.handleFinalTranscript(candidate, "vad_turn_end");
        }
      }
    });

    this.audioPipeline.onLevel((lvl) => {
      if (this.levelCallback) {
        this.levelCallback(lvl);
      }
    });

    this.audioPipeline.onError((err) => {
      if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
        this.isListening = false;
        this.emitState("permission_denied");
      }
    });
  }

  initSpeechRecognition() {
    if (typeof window === "undefined") {
      this.supported = false;
      return;
    }
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      console.warn("NodiqBot: Web SpeechRecognition API is not supported in this browser.");
      this.supported = false;
      return;
    }
    this.supported = true;

    try {
      this.recognition = new SpeechRec();
      this.recognition.continuous = true;
      this.recognition.interimResults = true;
      this.recognition.lang = "en-US";

      this.recognition.onstart = () => {
        this.isListening = true;
        this.emitState("listening");
      };

      this.recognition.onresult = (event) => {
        // Tab background check: if tab is hidden (e.g. lecture in another tab), ignore all incoming audio
        if (typeof document !== "undefined" && (document.hidden || this.isTabHidden)) {
          return;
        }

        // Echo cancellation: if browser is no longer actively speaking, ensure isSpeaking is reset
        if (this.isSpeaking && !window.speechSynthesis?.speaking) {
          this.isSpeaking = false;
          this.currentSpeakingText = "";
        }

        let interimTranscript = "";
        let finalTranscript = "";

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
          } else {
            interimTranscript += transcript;
          }
        }

        const activeText = (finalTranscript || interimTranscript).trim();
        if (!activeText) return;

        // 1. Assistant Echo Guard: check if incoming audio is simply the assistant's own synthesized speech
        if (this.isAssistantEcho(activeText)) {
          return;
        }

        // 2. Reverb window guard: if speaking just finished within the last 300ms, ignore residual echo
        if (Date.now() < this.ignoreAudioUntil && this.isAssistantEcho(activeText, true)) {
          return;
        }

        // 3. Dedicated Interruption Trap: if the assistant is speaking and user issues an interruption
        if (isInterruptionCommand(activeText, this.isSpeaking)) {
          if (this.interimTimer) clearTimeout(this.interimTimer);
          this.lastInterimCandidate = "";
          this.handleInterruption(activeText, "interruption_phrase");
          return;
        }

        // 4. Substantive command barge-in: if the assistant is speaking and user speaks a new command
        if (this.isSpeaking && activeText.length > 3) {
          this.stopSpeaking();
        }

        if (this.transcriptCallback) {
          this.transcriptCallback(activeText, !!finalTranscript);
        }

        if (finalTranscript.trim()) {
          voiceDiagnostics.mark("final_result", { text: finalTranscript.trim() });
          if (this.interimTimer) clearTimeout(this.interimTimer);
          this.lastInterimCandidate = "";
          this.handleFinalTranscript(finalTranscript.trim(), "recognition_final");
        } else if (interimTranscript.trim().length > 2) {
          voiceDiagnostics.mark("interim_result");
          // Fallback debounce: if Chrome stalls isFinal on speech pause, process after 1400ms
          // DO NOT fire premature execution on incomplete connector prefixes like 'now go to'
          const candidate = interimTranscript.trim();
          this.lastInterimCandidate = candidate;
          if (this.interimTimer) clearTimeout(this.interimTimer);

          const isIncomplete =
            /^(?:please\s+)?(?:now|go|go to|now go|now go to|visit|now visit|open|now open|show|show me|take me|take me to|navigate|navigate to|switch|switch to|and|to|the|for|in|on|at|can you|could you|i want to|i wanna)?\s*$/i.test(
              candidate
            );

          if (!isIncomplete) {
            this.interimTimer = setTimeout(() => {
              if (this.lastInterimCandidate && !this.isSpeaking) {
                const pending = this.lastInterimCandidate;
                this.lastInterimCandidate = "";
                this.handleFinalTranscript(pending, "interim_debounce");
              }
            }, 1400);
          }
        }
      };

      this.recognition.onerror = (event) => {
        if (event.error === "no-speech" || event.error === "aborted") return;
        console.warn("NodiqBot voice recognition notice:", event.error);
        if (event.error === "not-allowed") {
          this.isListening = false;
          this.emitState("permission_denied");
        }
      };

      this.recognition.onend = () => {
        this.isListening = false;
        // If tab is in background, suppress restart
        if (typeof document !== "undefined" && (document.hidden || document.visibilityState === "hidden" || this.isTabHidden)) {
          this.emitState("idle");
          return;
        }
        // Keep listening in hands-free mode: schedule restart
        if (this.isHandsFree) {
          setTimeout(() => {
            if (this.isHandsFree && !this.isListening && !this.isTabHidden && (typeof document === "undefined" || !document.hidden)) {
              this.startListening();
            }
          }, 120);
        } else {
          this.emitState("idle");
        }
      };
    } catch (err) {
      console.warn("NodiqBot speech recognition setup failed:", err);
      this.supported = false;
    }
  }

  recreateRecognition() {
    try {
      if (this.recognition) {
        this.recognition.onstart = null;
        this.recognition.onresult = null;
        this.recognition.onerror = null;
        this.recognition.onend = null;
        try { this.recognition.abort(); } catch {}
      }
    } catch {}

    this.isListening = false;
    this.initSpeechRecognition();
    if (this.isHandsFree) {
      setTimeout(() => this.startListening(), 200);
    }
  }

  initSpeechSynthesis() {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;

    const loadVoices = () => {
      const voices = window.speechSynthesis.getVoices();
      this.selectedVoice =
        voices.find((v) => v.lang.startsWith("en") && /(natural|google|samantha|daniel|karen)/i.test(v.name)) ||
        voices.find((v) => v.lang.startsWith("en")) ||
        voices[0] ||
        null;
    };

    loadVoices();
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }

  /**
   * Distinguishes assistant speech echo and room reverberation from genuine user commands.
   */
  isAssistantEcho(candidate, _loose = false) {
    if (!candidate || typeof candidate !== "string") return false;
    const lower = candidate.toLowerCase().trim();
    if (lower.length < 4) return false;

    // Explicit interruption commands must never be filtered out as echo
    if (isInterruptionCommand(lower, true)) {
      return false;
    }

    // Check against currently spoken text
    if (this.currentSpeakingText) {
      if (this.currentSpeakingText.includes(lower)) return true;
      if (lower.length > 12 && this.currentSpeakingText.length > 12) {
        const candWords = lower.split(/\s+/).filter((w) => w.length > 3);
        const speakWords = new Set(this.currentSpeakingText.split(/\s+/).filter((w) => w.length > 3));
        if (candWords.length >= 2) {
          const matchCount = candWords.filter((w) => speakWords.has(w)).length;
          if (matchCount / candWords.length >= 0.75) return true;
        }
      }
    }

    // Check against recent utterances spoken by the assistant
    return this.recentBotUtterances.some((u) => {
      if (!u || lower.length < 8) return false;
      return lower === u || (lower.length > 15 && u.includes(lower) && lower.length > u.length * 0.75);
    });
  }

  /**
   * Handles user barge-in / speech cancellation immediately.
   */
  handleInterruption(interruptionText = "", reason = "command") {
    voiceDiagnostics.mark("playback_cancelled");
    this.stopSpeaking();
    if (this.interruptionCallback) {
      this.interruptionCallback({
        text: interruptionText,
        reason,
        speechGeneration: this.speechGeneration,
      });
    }
  }

  handleFinalTranscript(rawText, source = "recognition") {
    const lower = rawText.toLowerCase().trim();

    // 0. Duplicate Dispatch Protection:
    // If the exact same command was dispatched within the last 1500ms, ignore duplicate
    const now = Date.now();
    if (this.lastDispatchedCommand === lower && now - this.lastDispatchTimestamp < 1500) {
      return;
    }

    // Echo cancellation: only drop if the mic captured the bot's own output
    if (this.isAssistantEcho(lower)) {
      return;
    }

    // Interruption check: halt playback immediately and notify UI
    if (isInterruptionCommand(lower, this.isSpeaking)) {
      this.handleInterruption(rawText, "interruption_phrase");
      return;
    }

    // Substantive command while speaking: stop speech immediately
    if (this.isSpeaking) {
      this.stopSpeaking();
    }

    // Record dispatch timestamp & text
    this.lastDispatchedCommand = lower;
    this.lastDispatchTimestamp = now;

    // Check for wake-words
    let isWakeWord = false;
    let cleanCommand = lower;

    for (const wake of WAKE_WORDS) {
      if (lower.startsWith(wake)) {
        isWakeWord = true;
        cleanCommand = lower.slice(wake.length).trim().replace(/^[,.-]\s*/, "");
        break;
      } else if (lower.includes(wake)) {
        isWakeWord = true;
        const parts = lower.split(wake);
        cleanCommand = (parts[1] || "").trim().replace(/^[,.-]\s*/, "");
        break;
      }
    }

    voiceDiagnostics.mark("command_exec_start");

    if (this.commandCallback) {
      this.commandCallback({
        rawText,
        commandText: cleanCommand,
        hasWakeWord: isWakeWord,
        source,
      });
    }
  }

  async startListening() {
    // Tab in background check: DO NOT start speech recognition or mic capture when tab is hidden
    if (typeof document !== "undefined" && (document.hidden || document.visibilityState === "hidden" || this.isTabHidden)) {
      return;
    }

    if (this.audioPipeline && this.audioPipeline.isSupported() && !this.audioPipeline.isCapturing) {
      try {
        await this.audioPipeline.start();
      } catch (err) {
        console.warn("Audio pipeline start failed:", err);
      }
    }

    if (!this.recognition) {
      this.initSpeechRecognition();
      if (!this.recognition) return;
    }
    if (this.isListening) return;

    try {
      this.recognition.start();
    } catch (err) {
      if (err.name === "InvalidStateError") {
        // Recognition is already in progress or transitioning; do not override isListening
        setTimeout(() => {
          if (this.isHandsFree && !this.isListening && !this.isTabHidden && (typeof document === "undefined" || !document.hidden)) {
            try { this.recognition.start(); } catch {}
          }
        }, 350);
      } else {
        console.warn("Recognition start failed, scheduling refresh:", err);
        setTimeout(() => this.recreateRecognition(), 300);
      }
    }
  }

  stopListening(preserveHandsFree = false) {
    if (!preserveHandsFree) {
      this.isHandsFree = false;
      this.wasHandsFreeBeforeHidden = false;
    }
    if (this.audioPipeline && this.audioPipeline.isCapturing) {
      this.audioPipeline.stop();
    }
    if (!this.recognition) return;
    try {
      this.recognition.stop();
      this.isListening = false;
      this.emitState("idle");
    } catch {
      // Ignore
    }
  }

  enableHandsFree(enabled = true) {
    this.isHandsFree = enabled;
    this.wasHandsFreeBeforeHidden = enabled;
    if (enabled && !this.isListening && !this.isTabHidden && (typeof document === "undefined" || !document.hidden)) {
      this.startListening();
    }
  }

  speak(text, onComplete, fromQueue = false) {
    if (fromQueue) {
      return this.speakPhrase(text, onComplete);
    }

    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      this.speechGeneration++;
      if (onComplete) onComplete();
      return;
    }

    // Cancel active speech and advance generation counter
    this.stopSpeaking();
    const currentGen = ++this.speechGeneration;

    if (this.isMuted || !text) {
      this.isSpeaking = false;
      this.currentSpeakingText = "";
      if (onComplete) onComplete();
      return;
    }

    // Sanitize text for natural speech
    let spokenText = String(text)
      .replace(/<[^>]*>/g, "") // strip HTML tags
      .replace(/[*_#`[\]()]/g, " ") // strip markdown
      .replace(/\s+/g, " ")
      .trim();

    PRONUNCIATION_MAP.forEach(({ regex, replacement }) => {
      spokenText = spokenText.replace(regex, replacement);
    });

    if (!spokenText) {
      if (onComplete) onComplete();
      return;
    }

    this.currentSpeakingText = spokenText.toLowerCase();

    const utterance = new SpeechSynthesisUtterance(spokenText);
    if (this.selectedVoice) utterance.voice = this.selectedVoice;
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    if (!window.__nodiqUtterances) {
      window.__nodiqUtterances = new Set();
    }
    window.__nodiqUtterances.add(utterance);

    if (this.speechTimeout) clearTimeout(this.speechTimeout);
    this.speechTimeout = setTimeout(() => {
      if (this.speechGeneration !== currentGen) return;
      if (this.isSpeaking) {
        this.isSpeaking = false;
        this.currentSpeakingText = "";
        this.ignoreAudioUntil = 0;
        this.emitState(this.isListening ? "listening" : "idle");
        if (this.isHandsFree && !this.isListening) {
          this.startListening();
        }
      }
    }, Math.min(10000, Math.max(2500, spokenText.length * 60)));

    utterance.onstart = () => {
      if (this.speechGeneration !== currentGen) return;
      this.isSpeaking = true;
      voiceDiagnostics.mark("first_response_audio");
      this.recentBotUtterances.push(spokenText.toLowerCase());
      if (this.recentBotUtterances.length > 6) this.recentBotUtterances.shift();
      this.emitState("speaking");
    };

    utterance.onend = () => {
      window.__nodiqUtterances?.delete(utterance);
      if (this.speechTimeout) clearTimeout(this.speechTimeout);
      if (this.speechGeneration !== currentGen) return;

      this.isSpeaking = false;
      this.currentSpeakingText = "";
      this.ignoreAudioUntil = Date.now() + 300; // room reverb echo silence window
      this.currentUtterance = null;
      this.emitState(this.isListening ? "listening" : "idle");

      setTimeout(() => {
        if (this.isHandsFree && !this.isSpeaking && !this.isListening) {
          this.startListening();
        }
      }, 350);

      if (onComplete) onComplete();
    };

    utterance.onerror = () => {
      window.__nodiqUtterances?.delete(utterance);
      if (this.speechTimeout) clearTimeout(this.speechTimeout);
      if (this.speechGeneration !== currentGen) return;

      this.isSpeaking = false;
      this.currentSpeakingText = "";
      this.ignoreAudioUntil = Date.now() + 200;
      this.currentUtterance = null;
      this.emitState(this.isListening ? "listening" : "idle");

      setTimeout(() => {
        if (this.isHandsFree && !this.isSpeaking && !this.isListening) {
          this.startListening();
        }
      }, 300);

      if (onComplete) onComplete();
    };

    this.currentUtterance = utterance;
    try {
      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.warn("Speech synthesis dispatch error:", err);
      this.isSpeaking = false;
      this.currentSpeakingText = "";
      if (onComplete) onComplete();
    }
  }

  speakPhrase(phrase, onComplete, generation) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      if (onComplete) onComplete();
      return;
    }

    const currentGen = generation !== undefined ? generation : this.speechGeneration;
    if (this.speechGeneration !== currentGen || this.isMuted || !phrase) {
      if (onComplete) onComplete();
      return;
    }

    let spokenText = String(phrase)
      .replace(/<[^>]*>/g, "")
      .replace(/[*_#`[\]()]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    PRONUNCIATION_MAP.forEach(({ regex, replacement }) => {
      spokenText = spokenText.replace(regex, replacement);
    });

    if (!spokenText) {
      if (onComplete) onComplete();
      return;
    }

    this.currentSpeakingText = spokenText.toLowerCase();

    const utterance = new SpeechSynthesisUtterance(spokenText);
    if (this.selectedVoice) utterance.voice = this.selectedVoice;
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    if (!window.__nodiqUtterances) {
      window.__nodiqUtterances = new Set();
    }
    window.__nodiqUtterances.add(utterance);

    utterance.onstart = () => {
      if (this.speechGeneration !== currentGen) return;
      this.isSpeaking = true;
      voiceDiagnostics.mark("first_audio_start");
      this.recentBotUtterances.push(spokenText.toLowerCase());
      if (this.recentBotUtterances.length > 6) this.recentBotUtterances.shift();
      this.emitState("speaking");
    };

    const finish = () => {
      window.__nodiqUtterances?.delete(utterance);
      if (this.speechGeneration !== currentGen) return;
      this.currentSpeakingText = "";
      this.currentUtterance = null;
      if (onComplete) onComplete();
    };

    utterance.onend = finish;
    utterance.onerror = finish;

    this.currentUtterance = utterance;
    try {
      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.warn("Speech synthesis dispatch error:", err);
      if (onComplete) onComplete();
    }
  }

  stopSpeaking() {
    this.speechGeneration++;
    if (this.streamQueue) {
      this.streamQueue.cancel();
    }
    if (this.phraseSegmenter) {
      this.phraseSegmenter.reset();
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
      } catch {}
      if (window.__nodiqUtterances) window.__nodiqUtterances.clear();
    }
    if (this.speechTimeout) clearTimeout(this.speechTimeout);
    this.isSpeaking = false;
    this.currentSpeakingText = "";
    this.ignoreAudioUntil = Date.now() + 250;
    this.currentUtterance = null;
    this.emitState(this.isListening ? "listening" : "idle");
    if (this.isHandsFree && !this.isListening) {
      setTimeout(() => this.startListening(), 350);
    }
  }

  async speakStream(tokenStream, generation, onToken, onComplete) {
    const currentGen = generation || ++this.speechGeneration;
    this.streamQueue.setGeneration(currentGen);
    const segmenter = new PhraseSegmenter();

    segmenter.onPhrase((phrase) => {
      if (this.speechGeneration !== currentGen) return;
      voiceDiagnostics.mark("first_phrase");
      this.streamQueue.enqueue(phrase, currentGen);
    });

    try {
      for await (const chunk of tokenStream) {
        if (this.speechGeneration !== currentGen) {
          break;
        }

        if (chunk.type === "token" && chunk.delta) {
          voiceDiagnostics.mark("first_token");
          segmenter.push(chunk.delta);
          if (onToken) onToken(chunk.delta);
        } else if (chunk.type === "done") {
          segmenter.flush();
          if (onComplete) onComplete(chunk);
          voiceDiagnostics.mark("response_complete");
        }
      }
      segmenter.flush();
    } catch (err) {
      if (err?.name !== "AbortError") {
        console.warn("SpeechStream error:", err);
      }
    }
  }

  toggleMute() {
    this.isMuted = !this.isMuted;
    if (this.isMuted) this.stopSpeaking();
    return this.isMuted;
  }

  emitState(state) {
    if (this.stateCallback) {
      this.stateCallback(state);
    }
  }

  onTranscript(cb) {
    this.transcriptCallback = cb;
    return () => {
      if (this.transcriptCallback === cb) this.transcriptCallback = null;
    };
  }

  onCommand(cb) {
    this.commandCallback = cb;
    return () => {
      if (this.commandCallback === cb) this.commandCallback = null;
    };
  }

  onStateChange(cb) {
    this.stateCallback = cb;
    return () => {
      if (this.stateCallback === cb) this.stateCallback = null;
    };
  }

  onInterruption(cb) {
    this.interruptionCallback = cb;
    return () => {
      if (this.interruptionCallback === cb) this.interruptionCallback = null;
    };
  }

  onAudioLevel(cb) {
    this.levelCallback = cb;
    return () => {
      if (this.levelCallback === cb) this.levelCallback = null;
    };
  }

  destroy() {
    if (this.watchdogInterval) clearInterval(this.watchdogInterval);
    if (this.speechTimeout) clearTimeout(this.speechTimeout);
    if (this.interimTimer) clearTimeout(this.interimTimer);
    if (typeof document !== "undefined" && this.handleVisibilityChange) {
      document.removeEventListener("visibilitychange", this.handleVisibilityChange);
    }
    if (typeof window !== "undefined" && this.handleWindowBlur) {
      window.removeEventListener("blur", this.handleWindowBlur);
    }
    if (this.audioPipeline) {
      this.audioPipeline.dispose();
    }
    this.stopSpeaking();
    this.stopListening();
  }
}

export const voiceAgent = new VoiceAgent();
export default voiceAgent;
