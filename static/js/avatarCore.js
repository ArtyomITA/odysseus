// Avatar core — turns agent lifecycle into renderer-agnostic commands.
//
// Knows nothing about how the avatar is drawn. It watches the chat stream,
// derives a state, extracts emotion tags, and analyses TTS audio, then emits
// commands that any renderer (in-page canvas, widget window, VTube Studio
// adapter) can consume.
//
// Event names match the upstream Agent Avatar proposal (odysseus #4184) so a
// future merge composes instead of conflicting.

const CHANNEL = 'odysseus-avatar';

// Canonical emotions of the bundled mao_pro model, with Italian aliases so the
// agent can tag replies in either language.
const EMOTIONS = {
  neutral: 'neutral', neutro: 'neutral', calmo: 'neutral',
  joy: 'joy', gioia: 'joy', felice: 'joy', felicita: 'joy',
  anger: 'anger', rabbia: 'anger', arrabbiato: 'anger',
  sadness: 'sadness', tristezza: 'sadness', triste: 'sadness',
  surprise: 'surprise', sorpresa: 'surprise', sorpreso: 'surprise',
  fear: 'fear', paura: 'fear',
  disgust: 'disgust', disgusto: 'disgust',
  smirk: 'smirk', ghigno: 'smirk', sarcasmo: 'smirk',
};

const TAG_RE = /\[([a-zA-Zàèéìòù]+)\]/g;

// Mouth curve. The renderer library floors an open mouth at 0.4, which reads as
// flapping; we drive the parameter ourselves from the raw RMS instead.
const MOUTH_GAIN = 2.4;
const MOUTH_FLOOR = 0.02;

class AvatarCore extends EventTarget {
  constructor() {
    super();
    this.state = 'idle';
    this.emotion = 'neutral';
    this.mouth = 0;
    this._audioCtx = null;
    this._analyser = null;
    this._rafId = null;
    this._pending = '';
    try {
      this._channel = new BroadcastChannel(CHANNEL);
    } catch {
      this._channel = null; // older browsers: in-page only, widget won't sync
    }
  }

  // --- outbound -----------------------------------------------------------

  _emit(command, detail) {
    const payload = { command, ...detail };
    this.dispatchEvent(new CustomEvent('command', { detail: payload }));
    if (this._channel) this._channel.postMessage(payload);
  }

  setState(state) {
    if (state === this.state) return;
    this.state = state;
    document.documentElement.dataset.avatarState = state;
    document.querySelectorAll('.role-agent-avatar').forEach((el) => {
      el.classList.toggle('is-speaking', state === 'talking');
    });
    this._emit('state', { state });
  }

  setEmotion(emotion) {
    const name = EMOTIONS[String(emotion).toLowerCase()];
    if (!name || name === this.emotion) return;
    this.emotion = name;
    document.dispatchEvent(new CustomEvent('avatar-emotion', { detail: { emotion: name } }));
    this._emit('emotion', { emotion: name });
  }

  _setMouth(value) {
    const v = value < MOUTH_FLOOR ? 0 : Math.min(1, value);
    if (Math.abs(v - this.mouth) < 0.01) return;
    this.mouth = v;
    document.documentElement.style.setProperty('--speak-intensity', v.toFixed(2));
    this._emit('mouth', { value: v });
  }

  // --- inbound: chat stream ----------------------------------------------

  /** Feed every parsed SSE payload from the chat stream. */
  handleStreamEvent(json) {
    if (!json) return;
    if (json.thinking === true) {
      this.setState('thinking');
      return;
    }
    if (typeof json.delta === 'string') {
      this.setState('talking');
      this._scanForEmotion(json.delta);
      return;
    }
    switch (json.type) {
      case 'tool_start':
      case 'tool_progress':
      case 'tool_output':
        this.setState('working');
        break;
      case 'agent_step':
        this.setState('thinking');
        break;
      case 'metrics':
        this.setState('idle');
        break;
    }
  }

  /** Stream is over (DONE or aborted). */
  handleStreamEnd() {
    this.setState('idle');
  }

  // Tags can straddle chunk boundaries, so keep a small tail buffer.
  _scanForEmotion(chunk) {
    const text = this._pending + chunk;
    let last = null;
    let m;
    TAG_RE.lastIndex = 0;
    while ((m = TAG_RE.exec(text)) !== null) last = m[1];
    if (last) this.setEmotion(last);
    const cut = text.lastIndexOf('[');
    this._pending = cut >= 0 && text.length - cut < 24 ? text.slice(cut) : '';
  }

  // --- inbound: TTS audio -------------------------------------------------

  /**
   * Drive the mouth from a playing audio element. Called by the TTS layer;
   * also re-emitted as `avatar-speak` for upstream compatibility.
   */
  attachAudio(audioEl) {
    if (!audioEl) return;
    document.dispatchEvent(new CustomEvent('avatar-speak', { detail: { audio: audioEl } }));
    try {
      if (!this._audioCtx) {
        this._audioCtx = new AudioContext();
        // Tapping the element routes playback through Web Audio, which bypasses
        // the element's own setSinkId — the chosen output has to be set here.
        window.OdysseusAudioDevices?.applyToContext(this._audioCtx);
      }
      if (this._audioCtx.state === 'suspended') this._audioCtx.resume();
      // A media element can only be tapped once; reuse the node on replays.
      if (!audioEl._avatarSource) {
        audioEl._avatarSource = this._audioCtx.createMediaElementSource(audioEl);
        const analyser = this._audioCtx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.7;
        audioEl._avatarSource.connect(analyser);
        analyser.connect(this._audioCtx.destination);
        audioEl._avatarAnalyser = analyser;
      }
      this._analyser = audioEl._avatarAnalyser;
    } catch (e) {
      console.warn('avatar: audio tap failed', e);
      return;
    }
    this.setState('talking');
    this._track();
    const stop = () => {
      this._untrack();
      this.setState('idle');
      audioEl.removeEventListener('ended', stop);
      audioEl.removeEventListener('pause', stop);
    };
    audioEl.addEventListener('ended', stop);
    audioEl.addEventListener('pause', stop);
  }

  _track() {
    if (this._rafId) return;
    const buf = new Float32Array(this._analyser.fftSize);
    const tick = () => {
      if (!this._analyser) return;
      this._analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const s of buf) sum += s * s;
      this._setMouth(Math.sqrt(sum / buf.length) * MOUTH_GAIN);
      this._rafId = requestAnimationFrame(tick);
    };
    this._rafId = requestAnimationFrame(tick);
  }

  _untrack() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._rafId = null;
    this._analyser = null;
    this._setMouth(0);
  }

  /** Emotion keywords to advertise in the system prompt. */
  static promptHint() {
    const names = [...new Set(Object.values(EMOTIONS))];
    return names.map((n) => `[${n}]`).join(', ');
  }
}

export const avatarCore = new AvatarCore();
export { AvatarCore, EMOTIONS };

// Reachable from non-module scripts (chat.js is a classic script).
window.OdysseusAvatar = avatarCore;
