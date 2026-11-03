/**
 * Voice Diagnostics & Latency Instrumentation for Nodiq-X Voice Intelligence
 * Records precise timestamps for voice events without storing raw audio, secrets,
 * or specimen data.
 */

class VoiceDiagnostics {
  constructor() {
    this.isEnabled =
      typeof window !== "undefined" &&
      (window.__NODIQ_VOICE_DEBUG__ === true ||
        window.location?.hostname === "localhost" ||
        window.location?.hostname === "127.0.0.1");

    this.currentSession = this.createEmptySession();
    this.history = [];
    this.maxHistory = 20;
  }

  createEmptySession() {
    return {
      sessionId: `voice-${Date.now()}`,
      micInitStart: null,
      micInitComplete: null,
      speechStartDetected: null,
      playbackCancelled: null,
      bargeInDurationMs: null,
      firstInterimResult: null,
      finalResultReceived: null,
      turnEndDetected: null,
      turnEndDurationMs: null,
      commandExecutionStart: null,
      firstResponseText: null,
      firstResponseAudio: null,
      totalResponseLatencyMs: null,
      commandText: null,
      isSimulated: false,
    };
  }

  startSession(isSimulated = false) {
    this.currentSession = this.createEmptySession();
    this.currentSession.isSimulated = isSimulated;
  }

  mark(event, payload = {}) {
    const now = typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
    const session = this.currentSession;

    switch (event) {
      case "mic_init_start":
        session.micInitStart = now;
        break;
      case "mic_init_complete":
        session.micInitComplete = now;
        break;
      case "speech_start":
        session.speechStartDetected = now;
        break;
      case "playback_cancelled":
        session.playbackCancelled = now;
        if (session.speechStartDetected) {
          session.bargeInDurationMs = Math.round(session.playbackCancelled - session.speechStartDetected);
        }
        break;
      case "interim_result":
        if (!session.firstInterimResult) {
          session.firstInterimResult = now;
        }
        break;
      case "final_result":
        session.finalResultReceived = now;
        if (payload.text) {
          // Never log sensitive data or full specimens, just character length and command summary
          session.commandLength = payload.text.length;
        }
        break;
      case "turn_end":
        session.turnEndDetected = now;
        if (session.speechStartDetected) {
          session.turnDurationMs = Math.round(now - session.speechStartDetected);
        }
        break;
      case "command_exec_start":
        session.commandExecutionStart = now;
        break;
      case "first_token":
        if (!session.firstToken) {
          session.firstToken = now;
          const baseline = session.turnEndDetected || session.finalResultReceived || session.commandExecutionStart;
          if (baseline) {
            session.endOfTurnFirstTextMs = Math.round(now - baseline);
          }
        }
        break;
      case "first_phrase":
        if (!session.firstPhrase) {
          session.firstPhrase = now;
        }
        break;
      case "first_audio_chunk":
        if (!session.firstAudioChunk) {
          session.firstAudioChunk = now;
        }
        break;
      case "first_audio_start":
      case "first_response_audio":
        if (!session.firstResponseAudio) {
          session.firstResponseAudio = now;
          session.firstAudioStart = now;
          const baseline = session.turnEndDetected || session.finalResultReceived || session.commandExecutionStart;
          if (baseline) {
            session.endOfTurnFirstAudioMs = Math.round(now - baseline);
            session.totalResponseLatencyMs = session.endOfTurnFirstAudioMs;
          }
        }
        break;
      case "first_response_text":
        session.firstResponseText = now;
        break;
      case "response_complete":
        session.responseComplete = now;
        const baseline = session.turnEndDetected || session.finalResultReceived || session.commandExecutionStart;
        if (baseline) {
          session.totalStreamDurationMs = Math.round(now - baseline);
        }
        this.archiveSession();
        break;
      default:
        break;
    }

    if (this.isEnabled) {
      // Diagnostic log restricted to dev/debug mode
      // console.debug(`[VoiceDiagnostics] ${event}`, { latencyMs: session.bargeInDurationMs || session.totalResponseLatencyMs });
    }
  }

  archiveSession() {
    this.history.push({ ...this.currentSession });
    if (this.history.length > this.maxHistory) {
      this.history.shift();
    }
  }

  getLatestMetrics() {
    return { ...this.currentSession };
  }

  getHistory() {
    return [...this.history];
  }

  reset() {
    this.currentSession = this.createEmptySession();
    this.history = [];
  }
}

export const voiceDiagnostics = new VoiceDiagnostics();
export default voiceDiagnostics;
