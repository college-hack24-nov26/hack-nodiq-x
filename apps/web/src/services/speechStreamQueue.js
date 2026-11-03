/**
 * Speech Stream Queue for Incremental Audio Playback
 *
 * Receives segmented phrases as they stream from the LLM, queues them,
 * and plays them sequentially with zero gap.
 *
 * Supports instant cancellation (barge-in):
 *  - Clears pending queue immediately
 *  - Stops active speech playback immediately
 *  - Increments monotonic generation counter to discard obsolete chunks
 *  - Self-healing watchdog timeout prevents deadlocks on speech synthesis hangs
 */

export class SpeechStreamQueue {
  constructor(speakerEngine) {
    this.speakerEngine = speakerEngine; // e.g. voiceAgent
    this.queue = [];
    this.isPlaying = false;
    this.queueGeneration = 0;
    this.currentChunk = null;
    this.stateCallbacks = [];
    this.completeCallbacks = [];
    this._cancelling = false;
    this.phraseWatchdog = null;
  }

  setGeneration(gen) {
    this.queueGeneration = gen;
    this.queue = [];
    this.isPlaying = false;
    this.currentChunk = null;
    if (this.phraseWatchdog) clearTimeout(this.phraseWatchdog);
  }

  enqueue(phrase, generation) {
    if (!phrase || typeof phrase !== "string") return;
    const clean = phrase.trim();
    if (!clean) return;

    if (generation !== undefined && generation !== this.queueGeneration) {
      // Chunk belongs to an obsolete turn generation
      return;
    }

    this.queue.push({ phrase: clean, generation: this.queueGeneration });

    if (!this.isPlaying) {
      this.playNext();
    }
  }

  playNext() {
    if (this.phraseWatchdog) {
      clearTimeout(this.phraseWatchdog);
      this.phraseWatchdog = null;
    }

    if (this.queue.length === 0) {
      this.isPlaying = false;
      this.currentChunk = null;
      this.emitState("idle");
      this.emitComplete();
      return;
    }

    this.isPlaying = true;
    this.emitState("speaking");

    const chunk = this.queue.shift();
    this.currentChunk = chunk;
    const activeGen = this.queueGeneration;

    let handled = false;
    const onPhraseEnded = () => {
      if (handled) return;
      handled = true;
      if (this.phraseWatchdog) clearTimeout(this.phraseWatchdog);
      // Callback check: only advance if still in current generation
      if (activeGen === this.queueGeneration && this.isPlaying) {
        this.playNext();
      }
    };

    // Self-healing watchdog timeout: if browser speech synthesis hangs, advance
    const timeoutMs = Math.min(12000, Math.max(3500, chunk.phrase.length * 85));
    this.phraseWatchdog = setTimeout(() => {
      if (!handled && activeGen === this.queueGeneration && this.isPlaying) {
        console.warn("SpeechStreamQueue watchdog triggered; advancing stalled phrase.");
        onPhraseEnded();
      }
    }, timeoutMs);

    if (this.speakerEngine && typeof this.speakerEngine.speakPhrase === "function") {
      this.speakerEngine.speakPhrase(chunk.phrase, onPhraseEnded, activeGen);
    } else if (this.speakerEngine && typeof this.speakerEngine.speak === "function") {
      this.speakerEngine.speak(chunk.phrase, onPhraseEnded, true);
    } else {
      // Fallback timer simulation if speech engine is mocked
      setTimeout(onPhraseEnded, 50);
    }
  }

  cancel() {
    if (this._cancelling) return;
    this._cancelling = true;
    try {
      if (this.phraseWatchdog) {
        clearTimeout(this.phraseWatchdog);
        this.phraseWatchdog = null;
      }
      this.queueGeneration++;
      this.queue = [];
      this.isPlaying = false;
      this.currentChunk = null;

      if (this.speakerEngine && typeof this.speakerEngine.stopSpeaking === "function" && this.speakerEngine.isSpeaking) {
        this.speakerEngine.stopSpeaking();
      }

      this.emitState("idle");
    } finally {
      this._cancelling = false;
    }
  }

  isBusy() {
    return this.isPlaying || this.queue.length > 0;
  }

  onStateChange(cb) {
    this.stateCallbacks.push(cb);
    return () => {
      this.stateCallbacks = this.stateCallbacks.filter((c) => c !== cb);
    };
  }

  onComplete(cb) {
    this.completeCallbacks.push(cb);
    return () => {
      this.completeCallbacks = this.completeCallbacks.filter((c) => c !== cb);
    };
  }

  emitState(state) {
    for (const cb of this.stateCallbacks) {
      try {
        cb(state);
      } catch (err) {
        console.warn("SpeechStreamQueue state callback error:", err);
      }
    }
  }

  emitComplete() {
    for (const cb of this.completeCallbacks) {
      try {
        cb();
      } catch (err) {
        console.warn("SpeechStreamQueue complete callback error:", err);
      }
    }
  }
}

export default SpeechStreamQueue;
