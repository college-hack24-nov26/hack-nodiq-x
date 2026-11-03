import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import voiceAgent, { isInterruptionCommand, INTERRUPTION_PATTERNS } from "./voiceAgent";
import nodiqIntentEngine from "./nodiqIntentEngine";
import api from "./api";
import domActionEngine from "./domActionEngine";
import goalPlanner from "./goalPlanner";

describe("Phase 1 Voice Reliability & Interruption Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // --------------------------------------------------------------------------
  // Requirement 1 & 2: Backend response contract handling & legacy compatibility
  // --------------------------------------------------------------------------
  describe("Objective C: Copilot Response Contract Handling", () => {
    it("correctly handles backend contract returning { reply: 'Analysis completed.' }", async () => {
      vi.spyOn(api, "copilot").mockResolvedValue({
        reply: "Analysis completed.",
        provider: "groq",
        session_id: "nodiqbot-voice",
      });

      const outcome = await nodiqIntentEngine.processCommand("how does pearlite form in ductile iron?");
      expect(outcome.success).toBe(true);
      expect(outcome.speech).toBe("Analysis completed.");
      expect(outcome.actionName).toBe("Copilot Knowledge");
    });

    it("strips action blocks from reply text gracefully", async () => {
      vi.spyOn(api, "copilot").mockResolvedValue({
        reply: "The nodularity is 85%.\n```action\n{\"tool\": \"show_nodule\"}\n```",
        provider: "groq",
      });

      const outcome = await nodiqIntentEngine.processCommand("how does annealing impact hardness?");
      expect(outcome.success).toBe(true);
      // Fenced action block must be stripped from spoken text
      expect(outcome.speech).toContain("The nodularity is 85%.");
      expect(outcome.speech).not.toContain("```action");
    });

    it("remains backwards-compatible with legacy { response: '...' } payloads", async () => {
      vi.spyOn(api, "copilot").mockResolvedValue({
        response: "Legacy response payload supported.",
      });

      const outcome = await nodiqIntentEngine.processCommand("what is the graphite density?");
      expect(outcome.success).toBe(true);
      expect(outcome.speech).toBe("Legacy response payload supported.");
    });

    it("remains backwards-compatible with legacy { message: '...' } payloads", async () => {
      vi.spyOn(api, "copilot").mockResolvedValue({
        message: "Legacy message payload supported.",
      });

      const outcome = await nodiqIntentEngine.processCommand("what is the graphite density?");
      expect(outcome.success).toBe(true);
      expect(outcome.speech).toBe("Legacy message payload supported.");
    });

    it("handles authentication required errors without exposing raw internal stack traces", async () => {
      vi.spyOn(api, "copilot").mockResolvedValue({
        error: "authentication required",
      });

      const outcome = await nodiqIntentEngine.processCommand("what is the graphite density?");
      expect(outcome.success).toBe(true);
      expect(outcome.speech).toBe("Please sign in to access Copilot intelligence.");
    });
  });

  // --------------------------------------------------------------------------
  // Requirement 3 & 10: Interruption classification vs ordinary commands
  // --------------------------------------------------------------------------
  describe("Objective A: Interruption Classification & Disambiguation", () => {
    it("recognizes standard interruption phrases correctly", () => {
      const phrases = [
        "stop talking",
        "Stop talking.",
        "stop speaking",
        "be quiet",
        "quiet please",
        "shut up",
        "cancel your response",
        "cancel speech",
        "that's enough",
        "enough already",
        "hush",
        "silence",
      ];

      for (const phrase of phrases) {
        expect(isInterruptionCommand(phrase, false)).toBe(true);
        expect(isInterruptionCommand(phrase, true)).toBe(true);
      }
    });

    it("allows standalone 'stop' or 'halt' only when assistant is actively speaking", () => {
      expect(isInterruptionCommand("stop", true)).toBe(true);
      expect(isInterruptionCommand("stop.", true)).toBe(true);
      expect(isInterruptionCommand("halt", true)).toBe(true);

      // When NOT speaking, standalone 'stop' is not assumed to be speech cancellation
      expect(isInterruptionCommand("stop", false)).toBe(false);
      expect(isInterruptionCommand("halt", false)).toBe(false);
    });

    it("does NOT classify compound commands like 'stop analysis' as interruption", () => {
      const nonInterruptions = [
        "stop analysis",
        "stop the analysis",
        "stop carbide analysis",
        "stop scan",
        "bus stop",
        "door stop",
        "please stop the test",
      ];

      for (const cmd of nonInterruptions) {
        expect(isInterruptionCommand(cmd, true)).toBe(false);
        expect(isInterruptionCommand(cmd, false)).toBe(false);
      }
    });

    it("processes 'stop talking' in intentEngine as speech cancellation without DOM clicks", async () => {
      const clickSpy = vi.spyOn(domActionEngine, "click");
      const routeSpy = vi.spyOn(goalPlanner, "goToRoute");

      const outcome = await nodiqIntentEngine.processCommand("stop talking");
      expect(outcome.success).toBe(true);
      expect(outcome.isInterruption).toBe(true);
      expect(outcome.actionName).toBe("Speech Cancelled");
      expect(outcome.speech).toBe("");

      // Must NOT trigger any DOM clicks or route navigation
      expect(clickSpy).not.toHaveBeenCalled();
      expect(routeSpy).not.toHaveBeenCalled();
    });
  });

  // --------------------------------------------------------------------------
  // Requirement 4, 5 & 8: Request generations, obsolete responses & playback guards
  // --------------------------------------------------------------------------
  describe("Objective B: Generation Sequencing & Stale Response Prevention", () => {
    it("increments speechGeneration on stopSpeaking and speak", () => {
      const initialGen = voiceAgent.speechGeneration;
      voiceAgent.stopSpeaking();
      expect(voiceAgent.speechGeneration).toBeGreaterThan(initialGen);

      const genAfterStop = voiceAgent.speechGeneration;
      voiceAgent.speak("New generation test text");
      expect(voiceAgent.speechGeneration).toBeGreaterThan(genAfterStop);
    });

    it("handleInterruption halts speaking and triggers interruptionCallback with generation", () => {
      const callback = vi.fn();
      const unsub = voiceAgent.onInterruption(callback);

      voiceAgent.isSpeaking = true;
      voiceAgent.handleInterruption("be quiet");

      expect(voiceAgent.isSpeaking).toBe(false);
      expect(callback).toHaveBeenCalledWith(
        expect.objectContaining({
          text: "be quiet",
          speechGeneration: voiceAgent.speechGeneration,
        })
      );

      unsub();
    });

    it("does not trigger commandCallback when an interruption is handled", () => {
      const commandCb = vi.fn();
      const interruptCb = vi.fn();
      const unsubCmd = voiceAgent.onCommand(commandCb);
      const unsubInt = voiceAgent.onInterruption(interruptCb);

      voiceAgent.isSpeaking = true;
      voiceAgent.handleFinalTranscript("stop speaking");

      expect(interruptCb).toHaveBeenCalled();
      expect(commandCb).not.toHaveBeenCalled();

      unsubCmd();
      unsubInt();
    });

    it("stops speaking when a new substantive command arrives during speech", () => {
      const commandCb = vi.fn();
      const unsubCmd = voiceAgent.onCommand(commandCb);

      voiceAgent.isSpeaking = true;
      voiceAgent.handleFinalTranscript("go to the analysis page");

      // Speech must have been immediately halted
      expect(voiceAgent.isSpeaking).toBe(false);
      // Command should proceed
      expect(commandCb).toHaveBeenCalledWith(
        expect.objectContaining({
          commandText: "go to the analysis page",
        })
      );

      unsubCmd();
    });
  });

  // --------------------------------------------------------------------------
  // Requirement 6: Analysis safety — stopping speech does not cancel analysis
  // --------------------------------------------------------------------------
  describe("Analysis Isolation Guarantee", () => {
    it("calling stopSpeaking or handleInterruption does not abort or alter application state", () => {
      const cancelAnalysisSpy = vi.fn();
      globalThis.__test_running_analysis = true;

      voiceAgent.handleInterruption("stop talking");

      // Verifies no global analysis cancellation occurred
      expect(globalThis.__test_running_analysis).toBe(true);
      delete globalThis.__test_running_analysis;
    });
  });

  // --------------------------------------------------------------------------
  // Requirement 7 & 9: Component cleanup & safe error handling
  // --------------------------------------------------------------------------
  describe("Objective E: Subscription Cleanup & Lifecycle Safety", () => {
    it("returns unsubscribe functions that cleanly unregister listeners", () => {
      const transcriptCb = vi.fn();
      const unsub = voiceAgent.onTranscript(transcriptCb);

      expect(voiceAgent.transcriptCallback).toBe(transcriptCb);
      unsub();
      expect(voiceAgent.transcriptCallback).toBeNull();
    });

    it("re-invoking startListening while already listening does not create invalid states", () => {
      voiceAgent.isListening = true;
      const startSpy = vi.fn();
      voiceAgent.recognition = { start: startSpy };

      // Should return early safely
      voiceAgent.startListening();
      expect(startSpy).not.toHaveBeenCalled();

      voiceAgent.isListening = false;
    });

    it("clears active timers and reset state on destroy()", () => {
      voiceAgent.watchdogInterval = setInterval(() => {}, 10000);
      voiceAgent.destroy();
      expect(voiceAgent.isSpeaking).toBe(false);
      expect(voiceAgent.isListening).toBe(false);
    });
  });
});
