// iOS Safari Optimized Audio Engine with Real-Time Barge-In Support
class AudioEngine {
  constructor() {
    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.processorNode = null;
    this.isPlaying = false;
    this.isRecording = false;
    this.activeSource = null;
    this.bargeInThreshold = 0.04; // Microphone energy threshold for barge-in detection
    this.onAudioChunk = null; // Callback for outgoing mic PCM chunks
    this.onBargeIn = null; // Callback triggered when user interrupts
    this.onSpeechEnd = null; // Callback when assistant finishes reading
  }

  // Mandatory for iOS Safari: Call on direct user gesture
  async unlock() {
    if (!this.audioContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioCtx({ sampleRate: 16000 });
    }
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }
    console.log('[AudioEngine] AudioContext unlocked, state:', this.audioContext.state);
  }

  async startRecording(onChunkCallback, onBargeInCallback) {
    await this.unlock();
    this.onAudioChunk = onChunkCallback;
    this.onBargeIn = onBargeInCallback;

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 16000,
          channelCount: 1
        }
      });

      this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
      // ScriptProcessor for wide browser compatibility on iOS Safari
      this.processorNode = this.audioContext.createScriptProcessor(2048, 1, 1);

      this.processorNode.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        
        // 1. Check volume energy for Barge-In Interruption
        let sumSquares = 0;
        for (let i = 0; i < inputData.length; i++) {
          sumSquares += inputData[i] * inputData[i];
        }
        const rms = Math.sqrt(sumSquares / inputData.length);

        // If assistant is currently speaking and user talks, trigger instant barge-in!
        if (this.isPlaying && rms > this.bargeInThreshold) {
          console.log('[AudioEngine] Barge-in detected! RMS:', rms.toFixed(4));
          this.stopPlayback();
          if (this.onBargeIn) this.onBargeIn();
        }

        // 2. Convert to 16-bit PCM for Gemini Live WebSocket
        const pcm16 = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          let s = Math.max(-1, Math.min(1, inputData[i]));
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        if (this.onAudioChunk) {
          this.onAudioChunk(pcm16.buffer);
        }
      };

      this.sourceNode.connect(this.processorNode);
      this.processorNode.connect(this.audioContext.destination);
      this.isRecording = true;
      console.log('[AudioEngine] Microphone recording started');
    } catch (err) {
      console.error('[AudioEngine] Microphone permission or init error:', err);
      throw err;
    }
  }

  stopRecording() {
    if (this.processorNode) {
      this.processorNode.disconnect();
      this.processorNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    this.isRecording = false;
    console.log('[AudioEngine] Microphone recording stopped');
  }

  // Instant interruption cutoff: stops active playback immediately
  stopPlayback() {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (this.activeSource) {
      try {
        this.activeSource.stop();
        this.activeSource.disconnect();
      } catch (e) {}
      this.activeSource = null;
    }
    this.isPlaying = false;
    console.log('[AudioEngine] Playback silenced instantly (Barge-in / Stop)');
  }

  // Play natural speech aloud (using Web Speech API or raw PCM buffer)
  speakText(text, onEnded) {
    this.stopPlayback();
    this.isPlaying = true;

    if (!('speechSynthesis' in window)) {
      console.warn('[AudioEngine] speechSynthesis not supported');
      this.isPlaying = false;
      if (onEnded) onEnded();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    
    // Choose high quality English voice if available on iOS
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(v => v.lang.startsWith('en') && (v.name.includes('Samantha') || v.name.includes('Daniel') || v.name.includes('Siri')));
    if (preferredVoice) utterance.voice = preferredVoice;

    utterance.onend = () => {
      this.isPlaying = false;
      if (onEnded) onEnded();
    };

    utterance.onerror = (e) => {
      console.error('[AudioEngine] Speech error:', e);
      this.isPlaying = false;
      if (onEnded) onEnded();
    };

    window.speechSynthesis.speak(utterance);
  }
}

window.AudioEngine = AudioEngine;
