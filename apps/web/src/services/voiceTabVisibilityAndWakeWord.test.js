import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import voiceAgent, { WAKE_WORDS } from "./voiceAgent";

describe("Tab Visibility & Background Audio Eavesdropping Protection", () => {
  let listeners = {};
  const originalDocument = globalThis.document;
  const originalWindow = globalThis.window;

  beforeEach(() => {
    vi.clearAllMocks();
    voiceAgent.stopSpeaking();
    voiceAgent.stopListening();
    listeners = {};

    globalThis.document = {
      hidden: false,
      visibilityState: "visible",
      addEventListener: vi.fn((event, cb) => {
        listeners[event] = listeners[event] || [];
        listeners[event].push(cb);
      }),
      removeEventListener: vi.fn((event, cb) => {
        if (listeners[event]) {
          listeners[event] = listeners[event].filter((fn) => fn !== cb);
        }
      }),
      dispatchEvent: vi.fn((event) => {
        const type = event.type || event;
        listeners[type]?.forEach((fn) => fn(event));
      }),
    };

    voiceAgent.bindVisibilityListeners();
  });

  afterEach(() => {
    voiceAgent.stopSpeaking();
    voiceAgent.stopListening();
    if (originalDocument) {
      globalThis.document = originalDocument;
    } else {
      delete globalThis.document;
    }
  });

  it("suppresses startListening when document is hidden (background tab)", async () => {
    globalThis.document.hidden = true;
    globalThis.document.visibilityState = "hidden";
    voiceAgent.isTabHidden = true;

    voiceAgent.isListening = false;
    const startSpy = vi.fn();
    voiceAgent.recognition = { start: startSpy };

    await voiceAgent.startListening();

    expect(startSpy).not.toHaveBeenCalled();
    expect(voiceAgent.isListening).toBe(false);
  });

  it("halts speech recognition and speech output immediately when visibilitychange triggers hidden", () => {
    voiceAgent.isListening = true;
    voiceAgent.isSpeaking = true;
    voiceAgent.recognition = { stop: vi.fn(), start: vi.fn() };
    const stopSpeakingSpy = vi.spyOn(voiceAgent, "stopSpeaking");

    // Simulate tab switch to background
    globalThis.document.hidden = true;
    globalThis.document.visibilityState = "hidden";
    globalThis.document.dispatchEvent({ type: "visibilitychange" });

    expect(voiceAgent.isTabHidden).toBe(true);
    expect(voiceAgent.isListening).toBe(false);
    expect(stopSpeakingSpy).toHaveBeenCalled();
  });

  it("does not allow watchdog or onend to restart recognition while tab is hidden", () => {
    globalThis.document.hidden = true;
    globalThis.document.visibilityState = "hidden";
    voiceAgent.isTabHidden = true;

    voiceAgent.isHandsFree = true;
    voiceAgent.isListening = false;
    const startListeningSpy = vi.spyOn(voiceAgent, "startListening");

    // Trigger onend
    voiceAgent.recognition?.onend?.();

    expect(startListeningSpy).not.toHaveBeenCalled();
  });

  it("drops any incoming speech recognition results when tab is hidden", () => {
    globalThis.document.hidden = true;
    globalThis.document.visibilityState = "hidden";
    voiceAgent.isTabHidden = true;

    const transcriptCb = vi.fn();
    const unsub = voiceAgent.onTranscript(transcriptCb);

    // Simulate audio result coming in while tab is in background (e.g. lecture playing in other tab)
    const mockEvent = {
      resultIndex: 0,
      results: [
        [
          {
            transcript: "today we will cover iron carbon phase diagrams",
            isFinal: true,
          },
        ],
      ],
    };
    mockEvent.results[0].isFinal = true;

    voiceAgent.recognition?.onresult?.(mockEvent);

    expect(transcriptCb).not.toHaveBeenCalled();

    unsub();
  });

  it("distinguishes intentional wake words from lecture / ambient speech", () => {
    const commandCb = vi.fn();
    const unsub = voiceAgent.onCommand(commandCb);

    // 1. Ambient lecture speech without wake word
    voiceAgent.handleFinalTranscript("in this lecture we analyze pearlite nodules");
    expect(commandCb).toHaveBeenCalledWith(
      expect.objectContaining({
        rawText: "in this lecture we analyze pearlite nodules",
        hasWakeWord: false,
      })
    );

    commandCb.mockClear();

    // 2. Intentional call with wake word 'Hey Nodiq'
    voiceAgent.handleFinalTranscript("hey nodiq run nodularity analysis");
    expect(commandCb).toHaveBeenCalledWith(
      expect.objectContaining({
        hasWakeWord: true,
        commandText: "run nodularity analysis",
      })
    );

    commandCb.mockClear();

    // 3. Intentional call with wake word 'Hi Nodiq Bot'
    voiceAgent.handleFinalTranscript("hi nodiq bot show me the dataset");
    expect(commandCb).toHaveBeenCalledWith(
      expect.objectContaining({
        hasWakeWord: true,
        commandText: "show me the dataset",
      })
    );

    unsub();
  });

  it("includes all canonical wake word patterns in WAKE_WORDS list", () => {
    expect(WAKE_WORDS).toContain("hey nodiq");
    expect(WAKE_WORDS).toContain("hi nodiq bot");
    expect(WAKE_WORDS).toContain("nodiq bot");
    expect(WAKE_WORDS).toContain("ok nodiq");
    expect(WAKE_WORDS).toContain("nodiq");
  });
});
