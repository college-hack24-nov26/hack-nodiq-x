/**
 * Audio Capture & Voice Activity Detection (VAD) Pipeline
 *
 * Utilizes `navigator.mediaDevices.getUserMedia()` with browser-managed WebRTC
 * DSP processing:
 *  - echoCancellation: true (hardware/software acoustic echo cancellation)
 *  - noiseSuppression: true
 *  - autoGainControl: true
 *
 * Performs real-time frequency-weighted spectral and energy analysis to detect
 * speech onset (barge-in) and end-of-turn silence without requiring cloud round-trips
 * or heavy external model downloads.
 */

import voiceDiagnostics from "./voiceDiagnostics";

export const VAD_DEFAULTS = {
  fftSize: 512,
  sampleRate: 16000,
  analysisIntervalMs: 25,
  voiceBandMinHz: 300,
  voiceBandMaxHz: 3400,
  energyThresholdRatio: 2.2, // Multiplier over dynamic ambient noise floor
  minEnergyThreshold: 0.018, // Absolute energy floor to reject dead silence / micro-clicks
  minSpeechFrames: 3, // ~75ms confirmation window to reject transient impulse noise
  silenceHangoverFrames: 30, // ~750ms of silence before declaring speech ended
};

export class AudioCapturePipeline {
  constructor(config = {}) {
    this.config = { ...VAD_DEFAULTS, ...config };

    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.analyserNode = null;

    this.isCapturing = false;
    this.isSpeechActive = false;
    this.permissionState = "prompt"; // prompt | granted | denied | unsupported

    // Dynamic noise floor tracking & frame counters
    this.ambientFloor = 0.012;
    this.consecutiveSpeechFrames = 0;
    this.consecutiveSilenceFrames = 0;
    this.analysisTimer = null;

    // Callbacks
    this.speechStartCallback = null;
    this.speechEndCallback = null;
    this.levelCallback = null;
    this.errorCallback = null;
    this.pcmChunkCallbacks = [];

    // Frequency bin bounds for speech bandpass
    this.binStart = 0;
    this.binEnd = 0;
  }

  isSupported() {
    const hasMedia =
      typeof navigator !== "undefined" &&
      !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    const hasAudioCtx =
      typeof AudioContext !== "undefined" ||
      (typeof window !== "undefined" && (!!window.AudioContext || !!window.webkitAudioContext));
    return hasMedia && hasAudioCtx;
  }

  /**
   * Initializes microphone capture with WebRTC acoustic echo cancellation.
   */
  async start() {
    if (this.isCapturing) return true;
    if (typeof document !== "undefined" && (document.hidden || document.visibilityState === "hidden")) {
      return false;
    }
    if (!this.isSupported()) {
      this.permissionState = "unsupported";
      this.emitError(new Error("Audio capture / getUserMedia is not supported in this browser environment."));
      return false;
    }

    voiceDiagnostics.mark("mic_init_start");

    try {
      // 1. Request microphone with explicit AEC, AGC, and noise suppression
      const constraints = {
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
        video: false,
      };

      this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
      this.permissionState = "granted";

      // 2. Initialize Web Audio Context & Analyser Node
      const AudioCtx =
        (typeof AudioContext !== "undefined" ? AudioContext : null) ||
        (typeof window !== "undefined" && (window.AudioContext || window.webkitAudioContext));
      this.audioContext = new AudioCtx();
      if (this.audioContext.state === "suspended") {
        try {
          await this.audioContext.resume();
        } catch {}
      }

      this.analyserNode = this.audioContext.createAnalyser();
      this.analyserNode.fftSize = this.config.fftSize;
      this.analyserNode.smoothingTimeConstant = 0.3;

      this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.sourceNode.connect(this.analyserNode);

      // 3. Compute speech bandpass bin indices
      const nyquist = this.audioContext.sampleRate / 2;
      const binCount = this.analyserNode.frequencyBinCount;
      this.binStart = Math.max(0, Math.floor((this.config.voiceBandMinHz / nyquist) * binCount));
      this.binEnd = Math.min(binCount - 1, Math.ceil((this.config.voiceBandMaxHz / nyquist) * binCount));

      this.isCapturing = true;
      this.isSpeechActive = false;
      this.consecutiveSpeechFrames = 0;
      this.consecutiveSilenceFrames = 0;
      this.ambientFloor = 0.012;

      voiceDiagnostics.mark("mic_init_complete");

      // 4. Start analysis loop
      this.startAnalysisLoop();
      return true;
    } catch (err) {
      console.warn("AudioCapturePipeline start error:", err);
      if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
        this.permissionState = "denied";
      } else {
        this.permissionState = "error";
      }
      this.stop();
      this.emitError(err);
      return false;
    }
  }

  /**
   * Returns current hardware track settings (e.g. echoCancellation status)
   */
  getTrackSettings() {
    if (!this.mediaStream) return null;
    const track = this.mediaStream.getAudioTracks()[0];
    if (!track) return null;
    return {
      label: track.label || "Microphone",
      readyState: track.readyState,
      settings: typeof track.getSettings === "function" ? track.getSettings() : {},
    };
  }

  startAnalysisLoop() {
    if (this.analysisTimer) clearInterval(this.analysisTimer);

    const freqData = new Uint8Array(this.analyserNode.frequencyBinCount);
    const timeData = new Float32Array(this.analyserNode.fftSize);

    this.analysisTimer = setInterval(() => {
      if (!this.isCapturing || !this.analyserNode) return;
      if (typeof document !== "undefined" && (document.hidden || document.visibilityState === "hidden")) return;

      this.analyserNode.getByteFrequencyData(freqData);
      this.analyserNode.getFloatTimeDomainData(timeData);

      // Compute RMS Energy
      let sumSquares = 0;
      for (let i = 0; i < timeData.length; i++) {
        sumSquares += timeData[i] * timeData[i];
      }
      const rms = Math.sqrt(sumSquares / timeData.length);

      // Compute Speech Band Ratio (energy concentrated in human voice range 300Hz-3400Hz)
      let voiceBandSum = 0;
      let totalBandSum = 0;
      for (let i = 0; i < freqData.length; i++) {
        const val = freqData[i];
        totalBandSum += val;
        if (i >= this.binStart && i <= this.binEnd) {
          voiceBandSum += val;
        }
      }
      const voiceRatio = totalBandSum > 0 ? voiceBandSum / totalBandSum : 0;

      // Emit audio level for UI visualizer
      const normalizedLevel = Math.min(1, Math.max(0, rms * 8));
      if (this.levelCallback) {
        this.levelCallback(normalizedLevel);
      }

      // Emit PCM chunk for streaming transports if listeners registered
      if (this.pcmChunkCallbacks.length > 0) {
        const pcmChunk = this.encodePCM16(timeData);
        for (const cb of this.pcmChunkCallbacks) {
          try {
            cb(pcmChunk);
          } catch {}
        }
      }

      // Check if current frame qualifies as speech
      const effectiveThreshold = Math.max(
        this.config.minEnergyThreshold,
        this.ambientFloor * this.config.energyThresholdRatio
      );

      // Speech frame conditions:
      // 1. RMS exceeds effective threshold
      // 2. Sufficient energy is concentrated in human speech band (> 35% of spectrum)
      const isSpeechFrame = rms > effectiveThreshold && voiceRatio > 0.35;

      if (isSpeechFrame) {
        this.consecutiveSpeechFrames++;
        this.consecutiveSilenceFrames = 0;

        if (!this.isSpeechActive && this.consecutiveSpeechFrames >= this.config.minSpeechFrames) {
          // Speech Onset Confirmed!
          this.isSpeechActive = true;
          voiceDiagnostics.mark("speech_start");
          if (this.speechStartCallback) {
            this.speechStartCallback({
              timestamp: Date.now(),
              rms,
              ambientFloor: this.ambientFloor,
            });
          }
        }
      } else {
        this.consecutiveSilenceFrames++;
        this.consecutiveSpeechFrames = 0;

        // Adapt ambient noise floor during confirmed silence periods (leaky integrator)
        if (!this.isSpeechActive) {
          this.ambientFloor = this.ambientFloor * 0.96 + rms * 0.04;
        }

        if (this.isSpeechActive && this.consecutiveSilenceFrames >= this.config.silenceHangoverFrames) {
          // Speech End Confirmed!
          this.isSpeechActive = false;
          voiceDiagnostics.mark("turn_end");
          if (this.speechEndCallback) {
            this.speechEndCallback({
              timestamp: Date.now(),
              silenceDurationMs: this.consecutiveSilenceFrames * this.config.analysisIntervalMs,
            });
          }
        }
      }
    }, this.config.analysisIntervalMs);
  }

  /**
   * Stops active capture and releases hardware tracks immediately.
   */
  stop() {
    this.isCapturing = false;
    this.isSpeechActive = false;
    this.consecutiveSpeechFrames = 0;
    this.consecutiveSilenceFrames = 0;

    if (this.analysisTimer) {
      clearInterval(this.analysisTimer);
      this.analysisTimer = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => {
        try {
          track.stop();
        } catch {}
      });
      this.mediaStream = null;
    }

    if (this.sourceNode) {
      try {
        this.sourceNode.disconnect();
      } catch {}
      this.sourceNode = null;
    }

    if (this.analyserNode) {
      try {
        this.analyserNode.disconnect();
      } catch {}
      this.analyserNode = null;
    }

    if (this.audioContext && this.audioContext.state !== "closed") {
      try {
        this.audioContext.close();
      } catch {}
      this.audioContext = null;
    }
  }

  dispose() {
    this.stop();
    this.speechStartCallback = null;
    this.speechEndCallback = null;
    this.levelCallback = null;
    this.errorCallback = null;
  }

  encodePCM16(floatData) {
    if (!floatData) return new Int16Array(0);
    const pcm = new Int16Array(floatData.length);
    for (let i = 0; i < floatData.length; i++) {
      const s = Math.max(-1, Math.min(1, floatData[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return pcm;
  }

  onPCMChunk(cb) {
    this.pcmChunkCallbacks.push(cb);
    return () => {
      this.pcmChunkCallbacks = this.pcmChunkCallbacks.filter((c) => c !== cb);
    };
  }

  onSpeechStart(cb) {
    this.speechStartCallback = cb;
    return () => {
      if (this.speechStartCallback === cb) this.speechStartCallback = null;
    };
  }

  onSpeechEnd(cb) {
    this.speechEndCallback = cb;
    return () => {
      if (this.speechEndCallback === cb) this.speechEndCallback = null;
    };
  }

  onLevel(cb) {
    this.levelCallback = cb;
    return () => {
      if (this.levelCallback === cb) this.levelCallback = null;
    };
  }

  onError(cb) {
    this.errorCallback = cb;
    return () => {
      if (this.errorCallback === cb) this.errorCallback = null;
    };
  }

  emitError(err) {
    if (this.errorCallback) {
      this.errorCallback(err);
    }
  }
}

export const audioCapturePipeline = new AudioCapturePipeline();
export default audioCapturePipeline;
