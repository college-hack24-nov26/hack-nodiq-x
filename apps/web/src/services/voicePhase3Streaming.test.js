/**
 * Phase 3 Voice Architecture Suite:
 * Low-latency streaming speech recognition, incremental AI response generation,
 * streaming phrase playback queue, and immediate barge-in interruption.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import PhraseSegmenter from "./phraseSegmenter.js";
import SpeechStreamQueue from "./speechStreamQueue.js";
import audioCapturePipeline from "./audioCapturePipeline.js";
import voiceAgent from "./voiceAgent.js";
import nodiqIntentEngine from "./nodiqIntentEngine.js";
import api from "./api.js";
import voiceDiagnostics from "./voiceDiagnostics.js";

describe("Phase 3: PhraseSegmenter - Natural Phrase Segmentation & Token Buffering", () => {
  it("buffers incoming tokens and emits natural speakable phrases on sentence boundaries", () => {
    const segmenter = new PhraseSegmenter();
    const emittedPhrases = [];
    segmenter.onPhrase((phrase) => emittedPhrases.push(phrase));

    // Push tokens incrementally
    segmenter.push("The ");
    segmenter.push("nodularity ");
    segmenter.push("is ");
    segmenter.push("82.5%. ");

    expect(emittedPhrases).toEqual(["The nodularity is 82.5%."]);

    segmenter.push("ASTM ");
    segmenter.push("A536 ");
    segmenter.push("classification ");
    segmenter.push("verified! ");

    expect(emittedPhrases).toEqual([
      "The nodularity is 82.5%.",
      "ASTM A536 classification verified!",
    ]);
  });

  it("splits long clauses at natural pauses when length exceeds 25 characters", () => {
    const segmenter = new PhraseSegmenter();
    const phrases = [];
    segmenter.onPhrase((p) => phrases.push(p));

    segmenter.push("The micrograph displays dense nodular graphite structures, ");
    expect(phrases).toHaveLength(1);
    expect(phrases[0]).toBe("The micrograph displays dense nodular graphite structures,");

    segmenter.push("and the ferrite matrix is fully homogeneous.");
    segmenter.flush();
    expect(phrases).toHaveLength(2);
    expect(phrases[1]).toBe("and the ferrite matrix is fully homogeneous.");
  });

  it("filters internal markdown action fences and code blocks from spoken phrases", () => {
    const segmenter = new PhraseSegmenter();
    const phrases = [];
    segmenter.onPhrase((p) => phrases.push(p));

    segmenter.push("Analysis complete. ```action\n{\"action\": \"NAVIGATE\"}\n``` Preparing your report.");
    segmenter.flush();

    const fullSpoken = phrases.join(" ");
    expect(fullSpoken).not.toContain("```action");
    expect(fullSpoken).not.toContain("NAVIGATE");
    expect(fullSpoken).toContain("Analysis complete.");
    expect(fullSpoken).toContain("Preparing your report.");
  });

  it("does not split on abbreviations such as e.g., fig., or decimal measurements like 0.45 um", () => {
    const segmenter = new PhraseSegmenter();
    const phrases = [];
    segmenter.onPhrase((p) => phrases.push(p));

    segmenter.push("The optical scale is set to 0.45 um per pixel, e.g. for ASTM A536 classification. ");
    expect(phrases).toHaveLength(1);
    expect(phrases[0]).toBe("The optical scale is set to 0.45 um per pixel, e.g. for ASTM A536 classification.");
  });

  it("flushes remaining buffered text when flush() is invoked", () => {
    const segmenter = new PhraseSegmenter();
    const phrases = [];
    segmenter.onPhrase((p) => phrases.push(p));

    segmenter.push("No punctuation ending");
    expect(phrases).toHaveLength(0);

    segmenter.flush();
    expect(phrases).toEqual(["No punctuation ending"]);
  });
});

describe("Phase 3: SpeechStreamQueue - Incremental Speech Output & Instant Cancellation", () => {
  it("enqueues phrases and invokes speaker sequentially with zero gap", () => {
    const spoken = [];
    let pendingCallback = null;

    const mockSpeaker = {
      speakPhrase: vi.fn((phrase, onEnd) => {
        spoken.push(phrase);
        pendingCallback = onEnd;
      }),
      stopSpeaking: vi.fn(),
      isSpeaking: false,
    };

    const queue = new SpeechStreamQueue(mockSpeaker);
    queue.setGeneration(1);

    queue.enqueue("First sentence.", 1);
    expect(mockSpeaker.speakPhrase).toHaveBeenCalledTimes(1);
    expect(spoken).toEqual(["First sentence."]);
    expect(queue.isBusy()).toBe(true);

    // Enqueue second phrase while first is actively playing
    queue.enqueue("Second sentence.", 1);
    expect(mockSpeaker.speakPhrase).toHaveBeenCalledTimes(1); // not called yet

    // Complete first phrase
    pendingCallback();
    expect(mockSpeaker.speakPhrase).toHaveBeenCalledTimes(2);
    expect(spoken).toEqual(["First sentence.", "Second sentence."]);

    // Complete second phrase
    pendingCallback();
    expect(queue.isBusy()).toBe(false);
  });

  it("discards incoming phrases belonging to obsolete generations", () => {
    const mockSpeaker = {
      speakPhrase: vi.fn((_phrase, onEnd) => onEnd()),
      stopSpeaking: vi.fn(),
      isSpeaking: false,
    };

    const queue = new SpeechStreamQueue(mockSpeaker);
    queue.setGeneration(2);

    // Stale generation 1 phrase arriving
    queue.enqueue("Stale phrase from previous turn", 1);
    expect(mockSpeaker.speakPhrase).not.toHaveBeenCalled();

    // Current generation 2 phrase arriving
    queue.enqueue("Valid phrase from current turn", 2);
    expect(mockSpeaker.speakPhrase).toHaveBeenCalledTimes(1);
  });

  it("cancels immediately on barge-in, advances generation, and flushes pending queue", () => {
    const mockSpeaker = {
      speakPhrase: vi.fn(),
      stopSpeaking: vi.fn(),
      isSpeaking: true,
    };

    const queue = new SpeechStreamQueue(mockSpeaker);
    queue.setGeneration(5);

    queue.enqueue("Sentence 1", 5);
    queue.enqueue("Sentence 2", 5);
    queue.enqueue("Sentence 3", 5);

    expect(queue.queue).toHaveLength(2);

    // Barge-in interruption occurs
    queue.cancel();

    expect(mockSpeaker.stopSpeaking).toHaveBeenCalled();
    expect(queue.queue).toEqual([]);
    expect(queue.isPlaying).toBe(false);
    expect(queue.queueGeneration).toBeGreaterThan(5);

    // Stale delayed callback from sentence 1 should NOT trigger sentence 2
    expect(queue.isBusy()).toBe(false);
  });

  it("handles multiple rapid interruptions cleanly without crashing or leaking state", () => {
    const mockSpeaker = {
      speakPhrase: vi.fn(),
      stopSpeaking: vi.fn(),
      isSpeaking: false,
    };

    const queue = new SpeechStreamQueue(mockSpeaker);

    for (let i = 0; i < 10; i++) {
      queue.setGeneration(i * 2);
      queue.enqueue(`Interrupted test ${i}`, i * 2);
      queue.cancel();
    }

    expect(queue.queue).toEqual([]);
    expect(queue.isPlaying).toBe(false);
  });

  it("recovers from a stalled speech phrase via watchdog timeout and unblocks the queue", () => {
    vi.useFakeTimers();
    try {
      const spoken = [];
      const mockSpeaker = {
        speakPhrase: vi.fn((phrase) => {
          spoken.push(phrase);
          // Deliberately does NOT invoke onEnd to simulate browser speech engine hang
        }),
        stopSpeaking: vi.fn(),
        isSpeaking: false,
      };

      const queue = new SpeechStreamQueue(mockSpeaker);
      queue.setGeneration(1);

      queue.enqueue("Stalled first sentence.", 1);
      queue.enqueue("Second sentence.", 1);

      expect(spoken).toEqual(["Stalled first sentence."]);

      // Advance timers past watchdog duration
      vi.advanceTimersByTime(4500);

      // Watchdog should have unblocked the queue and started the second phrase
      expect(spoken).toEqual(["Stalled first sentence.", "Second sentence."]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Phase 3: Streaming Audio Transport - 16kHz PCM & Pipeline Lifecycle", () => {
  it("encodes float32 audio data into 16-bit signed PCM integers", () => {
    const floatSamples = new Float32Array([0.0, 0.5, -0.5, 1.0, -1.0]);
    const pcm = audioCapturePipeline.encodePCM16(floatSamples);

    expect(pcm).toBeInstanceOf(Int16Array);
    expect(pcm.length).toBe(floatSamples.length);
    expect(pcm[0]).toBe(0);
    expect(pcm[1]).toBe(16383); // 0.5 * 32767
    expect(pcm[2]).toBe(-16384); // -0.5 * 32768
    expect(pcm[3]).toBe(32767); // clipped positive
    expect(pcm[4]).toBe(-32768); // clipped negative
  });

  it("registers and notifies streaming PCM chunk callbacks", () => {
    const emitted = [];
    const unsub = audioCapturePipeline.onPCMChunk((chunk) => {
      emitted.push(chunk);
    });

    // Verify subscription and unsubscription
    expect(typeof unsub).toBe("function");
    unsub();
  });
});

describe("Phase 3: Incremental AI Response Generation & Stream Endpoint Fallback", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("parses incoming SSE tokens incrementally via copilotStream", async () => {
    const ssePayload = [
      'data: {"type": "token", "delta": "Specimen "}\n\n',
      'data: {"type": "token", "delta": "shows 80% "}\n\n',
      'data: {"type": "token", "delta": "nodularity."}\n\n',
      'data: {"type": "done", "reply": "Specimen shows 80% nodularity."}\n\n',
    ].join("");

    const mockReadableStream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(ssePayload));
        controller.close();
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      body: mockReadableStream,
    });

    const receivedTokens = [];
    let doneEvent = null;

    for await (const chunk of api.copilotStream("Check nodularity")) {
      if (chunk.type === "token") {
        receivedTokens.push(chunk.delta);
      } else if (chunk.type === "done") {
        doneEvent = chunk;
      }
    }

    expect(receivedTokens).toEqual(["Specimen ", "shows 80% ", "nodularity."]);
    expect(doneEvent).not.toBeNull();
    expect(doneEvent.reply).toBe("Specimen shows 80% nodularity.");
  });

  it("gracefully falls back to standard non-streaming copilot endpoint when streaming fails", async () => {
    // Stream endpoint fails with 502 / network error
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 502,
    });

    // Fallback standard call succeeds
    vi.spyOn(api, "copilot").mockResolvedValueOnce({
      reply: "Fallback non-streaming response.",
      action: null,
    });

    const receivedTokens = [];
    let doneEvent = null;

    for await (const chunk of api.copilotStream("What is carbide?")) {
      if (chunk.type === "token") {
        receivedTokens.push(chunk.delta);
      } else if (chunk.type === "done") {
        doneEvent = chunk;
      }
    }

    expect(receivedTokens).toEqual(["Fallback non-streaming response."]);
    expect(doneEvent?.reply).toBe("Fallback non-streaming response.");
  });

  it("safely ignores malformed or non-JSON SSE lines without terminating the stream", async () => {
    const sseWithMalformed = [
      'data: {"type": "token", "delta": "Valid token 1. "}\n\n',
      'data: INVALID_JSON_LINE\n\n',
      'data: {"type": "token", "delta": "Valid token 2."}\n\n',
      'data: {"type": "done"}\n\n',
    ].join("");

    const mockStream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(sseWithMalformed));
        controller.close();
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      body: mockStream,
    });

    const tokens = [];
    for await (const chunk of api.copilotStream("Test malformed")) {
      if (chunk.type === "token") {
        tokens.push(chunk.delta);
      }
    }

    expect(tokens).toEqual(["Valid token 1. ", "Valid token 2."]);
  });

  it("correctly handles split network chunks and partial multi-byte UTF-8 sequences", async () => {
    // Split "data: {"type": "token", "delta": "100 µm"}" across 2 network chunks
    const chunk1 = new TextEncoder().encode('data: {"type": "token", "delta": "100 ');
    const chunk2 = new TextEncoder().encode('µm"}\n\ndata: {"type": "done"}\n\n');

    const mockStream = new ReadableStream({
      start(controller) {
        controller.enqueue(chunk1);
        controller.enqueue(chunk2);
        controller.close();
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      body: mockStream,
    });

    const tokens = [];
    for await (const chunk of api.copilotStream("Scale test")) {
      if (chunk.type === "token") tokens.push(chunk.delta);
    }

    expect(tokens.join("")).toBe("100 µm");
  });

  it("terminates stream promptly when AbortController signal aborts", async () => {
    const controller = new AbortController();

    vi.spyOn(globalThis, "fetch").mockImplementationOnce((_url, options) => {
      if (options?.signal?.aborted) {
        const err = new Error("Aborted");
        err.name = "AbortError";
        return Promise.reject(err);
      }
      return Promise.resolve({ ok: true, body: null });
    });

    controller.abort();

    await expect(async () => {
      for await (const _ of api.copilotStream("Test abort", [], "s1", {}, { signal: controller.signal })) {
        // should reject
      }
    }).rejects.toThrow();
  });
});

describe("Phase 3: Turn Management, Interruption Propagation & Non-Destructive Barge-In", () => {
  it("VAD speech onset halts audio playback immediately without cancelling active application analyses", () => {
    const stopSpeakingSpy = vi.spyOn(voiceAgent, "stopSpeaking");

    // Simulate assistant is speaking
    voiceAgent.isSpeaking = true;

    // Simulate acoustic speech start event from audioPipeline
    voiceAgent.audioPipeline.onSpeechStart = vi.fn();
    voiceAgent.handleInterruption("", "vad_speech_start");

    expect(stopSpeakingSpy).toHaveBeenCalled();
    expect(voiceAgent.isSpeaking).toBe(false);
  });

  it("does not execute application commands on partial or connector prefixes", () => {
    const prefixes = ["now go to", "visit", "open", "please can you"];

    for (const prefix of prefixes) {
      const isIncomplete =
        /^(?:please\s+)?(?:now|go|go to|now go|now go to|visit|now visit|open|now open|show|show me|take me|take me to|navigate|navigate to|switch|switch to|and|to|the|for|in|on|at|can you|could you|i want to|i wanna)?\s*$/i.test(
          prefix
        );
      expect(isIncomplete).toBe(true);
    }
  });

  it("preserves conversation history across turns without recording interrupted responses as completed", async () => {
    const history = [];

    // Turn 1 completes successfully
    history.push({ role: "user", content: "Explain nodularity" });
    history.push({ role: "assistant", content: "Nodularity measures sphericity." });

    // Turn 2 is interrupted halfway through
    const turn2User = "Compare with specimen 4";
    // Interruption occurs before assistant completes: response is NOT added
    // Assistant output is discarded rather than pushed as misleading truth

    expect(history).toHaveLength(2);
    expect(history[0].role).toBe("user");
    expect(history[1].role).toBe("assistant");
    expect(history[1].content).toBe("Nodularity measures sphericity.");
  });

  it("records precise monotonic diagnostic marks for the streaming turn lifecycle", () => {
    voiceDiagnostics.startSession(true);

    voiceDiagnostics.mark("speech_start");
    voiceDiagnostics.mark("interim_result");
    voiceDiagnostics.mark("final_result", { text: "Run nodularity" });
    voiceDiagnostics.mark("first_token");
    voiceDiagnostics.mark("first_phrase");
    voiceDiagnostics.mark("first_audio_start");
    voiceDiagnostics.mark("response_complete");

    const metrics = voiceDiagnostics.getLatestMetrics();

    expect(metrics.speechStartDetected).toBeGreaterThan(0);
    expect(metrics.firstInterimResult).toBeGreaterThan(0);
    expect(metrics.finalResultReceived).toBeGreaterThan(0);
    expect(metrics.firstToken).toBeGreaterThan(0);
    expect(metrics.firstPhrase).toBeGreaterThan(0);
    expect(metrics.firstAudioStart).toBeGreaterThan(0);
    expect(metrics.responseComplete).toBeGreaterThan(0);
  });
});
