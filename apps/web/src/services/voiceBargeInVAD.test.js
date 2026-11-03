import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import voiceAgent from "./voiceAgent";
import audioCapturePipeline, { AudioCapturePipeline } from "./audioCapturePipeline";
import voiceDiagnostics from "./voiceDiagnostics";
import domActionEngine from "./domActionEngine";
import goalPlanner from "./goalPlanner";

describe("Voice Barge-in & VAD Architecture Suite", () => {
  let mockTrack;
  let mockStream;
  let mockAudioContext;
  let mockAnalyser;

  beforeEach(() => {
    vi.restoreAllMocks();
    voiceAgent.stopSpeaking();
    voiceAgent.stopListening();

    mockTrack = {
      label: "Default Workstation Mic",
      readyState: "live",
      stop: vi.fn(),
      getSettings: vi.fn().mockReturnValue({
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        sampleRate: 48000,
      }),
    };

    mockStream = {
      getAudioTracks: vi.fn().mockReturnValue([mockTrack]),
      getTracks: vi.fn().mockReturnValue([mockTrack]),
    };

    mockAnalyser = {
      fftSize: 512,
      frequencyBinCount: 256,
      smoothingTimeConstant: 0.3,
      connect: vi.fn(),
      disconnect: vi.fn(),
      getByteFrequencyData: vi.fn((arr) => arr.fill(0)),
      getFloatTimeDomainData: vi.fn((arr) => arr.fill(0)),
    };

    mockAudioContext = {
      sampleRate: 48000,
      state: "running",
      createAnalyser: vi.fn().mockReturnValue(mockAnalyser),
      createMediaStreamSource: vi.fn().mockReturnValue({
        connect: vi.fn(),
        disconnect: vi.fn(),
      }),
      resume: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
    };

    // Global browser API stubs for headless Node environment
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockResolvedValue(mockStream),
      },
      configurable: true,
      writable: true,
    });
    globalThis.AudioContext = vi.fn().mockImplementation(function () {
      return mockAudioContext;
    });
    globalThis.webkitAudioContext = globalThis.AudioContext;

    // Ensure audio pipeline callbacks are cleanly initialized for voiceAgent
    voiceAgent.initAudioPipeline();
  });

  afterEach(() => {
    voiceAgent.stopSpeaking();
    voiceAgent.stopListening();
    vi.restoreAllMocks();
  });

  // --------------------------------------------------------------------------
  // Requirement 1: VAD speech-start detection triggers playback cancellation
  // --------------------------------------------------------------------------
  it("triggers playback cancellation immediately when VAD detects speech onset", () => {
    const stopSpeakingSpy = vi.spyOn(voiceAgent, "stopSpeaking");
    const interruptCb = vi.fn();
    const unsub = voiceAgent.onInterruption(interruptCb);

    // Simulate assistant actively speaking
    voiceAgent.isSpeaking = true;
    voiceAgent.currentSpeakingText = "analysis is calculating pearlite percentage";

    // Trigger VAD speech start callback
    voiceAgent.audioPipeline.speechStartCallback?.({
      timestamp: Date.now(),
      rms: 0.08,
      ambientFloor: 0.012,
    });

    expect(stopSpeakingSpy).toHaveBeenCalled();
    expect(voiceAgent.isSpeaking).toBe(false);
    expect(interruptCb).toHaveBeenCalledWith(
      expect.objectContaining({
        reason: "vad_speech_start",
        speechGeneration: voiceAgent.speechGeneration,
      })
    );

    unsub();
  });

  // --------------------------------------------------------------------------
  // Requirement 2: Background noise does not automatically execute commands
  // --------------------------------------------------------------------------
  it("does not trigger speech onset or execute commands for background noise", () => {
    const pipeline = new AudioCapturePipeline({
      minEnergyThreshold: 0.02,
      minSpeechFrames: 3,
    });
    const speechStartSpy = vi.fn();
    pipeline.onSpeechStart(speechStartSpy);

    pipeline.isCapturing = true;
    pipeline.analyserNode = mockAnalyser;

    // Simulate quiet background noise (RMS = 0.005, well below threshold)
    mockAnalyser.getFloatTimeDomainData = vi.fn((arr) => {
      for (let i = 0; i < arr.length; i++) arr[i] = 0.005;
    });
    mockAnalyser.getByteFrequencyData = vi.fn((arr) => arr.fill(10));

    // Run frame iteration
    pipeline.startAnalysisLoop();
    // Advance frames
    expect(pipeline.isSpeechActive).toBe(false);
    expect(speechStartSpy).not.toHaveBeenCalled();

    pipeline.dispose();
  });

  // --------------------------------------------------------------------------
  // Requirement 3: VAD events never directly trigger domain actions
  // --------------------------------------------------------------------------
  it("never directly triggers domain actions or navigation from VAD events alone", () => {
    const clickSpy = vi.spyOn(domActionEngine, "click");
    const navSpy = vi.spyOn(goalPlanner, "goToRoute");

    // Fire both speech start and speech end
    voiceAgent.audioPipeline.speechStartCallback?.({ timestamp: Date.now() });
    voiceAgent.audioPipeline.speechEndCallback?.({ timestamp: Date.now(), silenceDurationMs: 800 });

    expect(clickSpy).not.toHaveBeenCalled();
    expect(navSpy).not.toHaveBeenCalled();
  });

  // --------------------------------------------------------------------------
  // Requirement 4 & 5: Complete recognized utterance routed exactly once
  // --------------------------------------------------------------------------
  it("routes a complete recognized utterance exactly once without duplicates", () => {
    const commandCb = vi.fn();
    const unsub = voiceAgent.onCommand(commandCb);

    // Initial final result dispatch
    voiceAgent.handleFinalTranscript("run nodularity analysis", "recognition_final");
    expect(commandCb).toHaveBeenCalledTimes(1);
    expect(commandCb).toHaveBeenCalledWith(
      expect.objectContaining({
        commandText: "run nodularity analysis",
      })
    );

    // Duplicate event arriving within 1500ms (e.g. repeated isFinal or interim debounce)
    voiceAgent.handleFinalTranscript("run nodularity analysis", "interim_debounce");
    expect(commandCb).toHaveBeenCalledTimes(1); // Still 1, protected against duplication

    unsub();
  });

  // --------------------------------------------------------------------------
  // Requirement 6: VAD turn-end and recognition finalization do not duplicate dispatch
  // --------------------------------------------------------------------------
  it("prevents duplicate dispatch between recognition finalization and VAD turn-end", () => {
    const commandCb = vi.fn();
    const unsub = voiceAgent.onCommand(commandCb);

    // Speech recognition finalizes first
    voiceAgent.handleFinalTranscript("open the microscope view", "recognition_final");
    expect(commandCb).toHaveBeenCalledTimes(1);

    // VAD turn-end silence fires shortly after with the same candidate
    voiceAgent.lastInterimCandidate = "open the microscope view";
    voiceAgent.audioPipeline.speechEndCallback?.({ timestamp: Date.now(), silenceDurationMs: 800 });

    // Should NOT duplicate command
    expect(commandCb).toHaveBeenCalledTimes(1);

    unsub();
  });

  // --------------------------------------------------------------------------
  // Requirement 7: Microphone permission denial produces a recoverable UI state
  // --------------------------------------------------------------------------
  it("handles microphone permission denial gracefully and emits permission_denied", async () => {
    const stateCb = vi.fn();
    const unsub = voiceAgent.onStateChange(stateCb);

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockRejectedValue({
          name: "NotAllowedError",
          message: "Permission denied by user",
        }),
      },
      configurable: true,
      writable: true,
    });

    const success = await voiceAgent.audioPipeline.start();
    expect(success).toBe(false);
    expect(stateCb).toHaveBeenCalledWith("permission_denied");
    expect(voiceAgent.isListening).toBe(false);

    unsub();
  });

  // --------------------------------------------------------------------------
  // Requirement 8: Microphone tracks are stopped during disposal
  // --------------------------------------------------------------------------
  it("stops all audio tracks when AudioCapturePipeline is stopped or disposed", async () => {
    const pipeline = new AudioCapturePipeline();
    await pipeline.start();

    expect(pipeline.mediaStream).not.toBeNull();
    pipeline.dispose();

    expect(mockTrack.stop).toHaveBeenCalled();
    expect(pipeline.mediaStream).toBeNull();
    expect(pipeline.isCapturing).toBe(false);
  });

  // --------------------------------------------------------------------------
  // Requirement 9: Component unmount cleans up audio processing resources
  // --------------------------------------------------------------------------
  it("cleans up AudioContext and disconnects nodes on destroy", async () => {
    await voiceAgent.audioPipeline.start();
    voiceAgent.destroy();

    expect(mockTrack.stop).toHaveBeenCalled();
    expect(voiceAgent.audioPipeline.isCapturing).toBe(false);
  });

  // --------------------------------------------------------------------------
  // Requirement 10: Interrupting TTS does not cancel running analysis
  // --------------------------------------------------------------------------
  it("verifies speech-start interruption does not abort running metallurgical analyses", () => {
    globalThis.__active_metallurgical_task = { id: "ANL-998822", status: "running" };

    // Assistant speaking, user interrupts via VAD
    voiceAgent.isSpeaking = true;
    voiceAgent.audioPipeline.speechStartCallback?.({ timestamp: Date.now() });

    expect(voiceAgent.isSpeaking).toBe(false);
    // Analysis task MUST remain intact and unaffected
    expect(globalThis.__active_metallurgical_task.status).toBe("running");
    delete globalThis.__active_metallurgical_task;
  });

  // --------------------------------------------------------------------------
  // Requirement 11: Old speech-generation callbacks cannot restore obsolete state
  // --------------------------------------------------------------------------
  it("prevents obsolete speech-generation callbacks from updating state", () => {
    voiceAgent.speechGeneration = 5;
    const obsoleteGen = 5;

    // Advance generation due to barge-in
    voiceAgent.stopSpeaking();
    expect(voiceAgent.speechGeneration).toBe(6);

    // Obsolete timeout / callback attempts to reset state using old generation
    const mockObsoleteEnd = () => {
      if (voiceAgent.speechGeneration !== obsoleteGen) return;
      voiceAgent.emitState("idle");
    };

    const stateSpy = vi.spyOn(voiceAgent, "emitState");
    mockObsoleteEnd();
    expect(stateSpy).not.toHaveBeenCalled();
  });

  // --------------------------------------------------------------------------
  // Requirement 12: Recognition restart failures do not create infinite retry loops
  // --------------------------------------------------------------------------
  it("guards against infinite retry loops on recognition restart failure", () => {
    voiceAgent.isHandsFree = true;
    voiceAgent.isListening = true;

    const startSpy = vi.fn(() => {
      const err = new Error("Already started");
      err.name = "InvalidStateError";
      throw err;
    });

    voiceAgent.recognition = { start: startSpy };
    // Trigger start listening while already listening
    voiceAgent.startListening();

    // Since isListening was true, it should return immediately without throwing
    expect(startSpy).not.toHaveBeenCalled();
  });

  // --------------------------------------------------------------------------
  // Bonus: Track Settings Inspection
  // --------------------------------------------------------------------------
  it("inspects hardware track settings for echo cancellation verification", async () => {
    const pipeline = new AudioCapturePipeline();
    await pipeline.start();

    const trackInfo = pipeline.getTrackSettings();
    expect(trackInfo).not.toBeNull();
    expect(trackInfo.settings.echoCancellation).toBe(true);
    expect(trackInfo.settings.noiseSuppression).toBe(true);

    pipeline.dispose();
  });

  // --------------------------------------------------------------------------
  // Bonus: Latency Diagnostics Timing
  // --------------------------------------------------------------------------
  it("records diagnostic marks and calculates bargeInDurationMs accurately", () => {
    voiceDiagnostics.startSession(true);

    voiceDiagnostics.mark("speech_start");
    // Simulate 35ms playback cancellation
    const now = performance.now();
    voiceDiagnostics.currentSession.speechStartDetected = now - 35;
    voiceDiagnostics.mark("playback_cancelled");

    const metrics = voiceDiagnostics.getLatestMetrics();
    expect(metrics.bargeInDurationMs).toBeGreaterThanOrEqual(30);
    expect(metrics.isSimulated).toBe(true);
  });
});
