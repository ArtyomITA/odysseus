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
//
// Il guadagno fisso non bastava: l'RMS di una frase sintetizzata sta fra 0.02 e
// 0.10 a seconda della voce e del volume, cioe' fra il 5% e il 24% di apertura.
// Sullo schermo e' una bocca che non si muove. Qui si normalizza sul picco
// recente (una specie di controllo di volume automatico) e si tiene un attacco
// rapido con un rilascio lento: e' quello che fa sembrare un labiale un labiale
// e non un lampeggio.
const MOUTH_GAIN = 2.4;
const MOUTH_FLOOR = 0.02;
const PICCO_MINIMO = 0.035;   // sotto questo non si normalizza: e' rumore
const PICCO_DECADIMENTO = 0.995;
const ATTACCO = 0.6;          // quanto in fretta la bocca si apre
const RILASCIO = 0.18;        // quanto lentamente si richiude
// Se chi produce l'audio ci alimenta da fuori (postMessage/BroadcastChannel) e
// poi smette, la bocca deve chiudersi da sola invece di restare spalancata.
const SCADENZA_LIVELLO_MS = 250;

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
    this._picco = PICCO_MINIMO;
    this._livello = 0;          // valore fornito da fuori, 0..1
    this._livelloAl = 0;        // quando e' arrivato
    this._levigato = 0;
    try {
      this._channel = new BroadcastChannel(CHANNEL);
    } catch {
      this._channel = null; // older browsers: in-page only, widget won't sync
    }
    // Chi riproduce l'audio puo' stare in un altro documento (finestra staccata,
    // iframe): li' non c'e' nessun elemento da intercettare, quindi accettiamo
    // anche il solo livello, gia' misurato da chi ce l'ha in mano.
    try {
      this._channel?.addEventListener('message', (e) => {
        if (e.data?.command === 'mouth-level') this.pushLivello(e.data.value);
      });
    } catch { /* niente canale: resta il percorso in-pagina */ }
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
      const ctx = this._contesto();
      // A media element can only be tapped once; reuse the node on replays.
      if (!audioEl._avatarAnalyser) {
        // Intercettare l'elemento gli toglie l'uscita di suo: da qui in poi si
        // sente solo attraverso il grafo. Se qualcosa va storto a meta' bisogna
        // ricollegarlo, altrimenti l'assistente diventa muto — che e' peggio di
        // una bocca ferma.
        const sorgente = ctx.createMediaElementSource(audioEl);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.35;
        sorgente.connect(analyser);
        analyser.connect(ctx.destination);
        audioEl._avatarSource = sorgente;
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
      // Solo l'elemento ancora agganciato puo' spegnere la bocca. Tra una frase
      // e l'altra il player mette in pausa quella vecchia e subito dopo attacca
      // la nuova, ma l'evento 'pause' arriva DOPO: senza questa guardia la
      // frase 1 spegneva l'analizzatore della frase 2 e da li' in poi la bocca
      // restava ferma per tutto il resto della risposta.
      if (this._analyser && this._analyser !== audioEl._avatarAnalyser) return;
      this._untrack();
      this.setState('idle');
      audioEl.removeEventListener('ended', stop);
      audioEl.removeEventListener('pause', stop);
    };
    audioEl.addEventListener('ended', stop);
    audioEl.addEventListener('pause', stop);
  }

  /**
   * Stesso lavoro di `attachAudio`, ma partendo da un nodo Web Audio gia' vivo.
   *
   * E' la via da preferire quando chi riproduce ha gia' il suo AudioContext:
   * `createMediaElementSource` puo' essere chiamato una volta sola per elemento,
   * e su un elemento gia' agganciato da qualcun altro fallisce. Un nodo si
   * dirama quante volte si vuole.
   */
  attachNode(nodo, ctx) {
    if (!nodo) return;
    try {
      const contesto = ctx || nodo.context || this._contesto();
      const analyser = contesto.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.35;
      nodo.connect(analyser);   // derivazione: non tocca il percorso di ascolto
      this._analyser = analyser;
    } catch (e) {
      console.warn('avatar: node tap failed', e);
      return;
    }
    this.setState('talking');
    this._track();
  }

  /**
   * Ampiezza gia' misurata da fuori, 0..1 (RMS del pezzo appena suonato).
   *
   * Serve a chi l'audio ce l'ha in un altro documento o in un worklet: manda il
   * numero e basta, alla curva e al livellamento pensiamo qui. Se smette di
   * arrivare per SCADENZA_LIVELLO_MS la bocca si chiude da sola.
   */
  pushLivello(valore) {
    const v = Number(valore);
    if (!isFinite(v)) return;
    this._livello = Math.max(0, v);
    this._livelloAl = performance.now();
    this.setState('talking');
    this._track();
  }

  _contesto() {
    if (!this._audioCtx) {
      this._audioCtx = new AudioContext();
      // Tapping the element routes playback through Web Audio, which bypasses
      // the element's own setSinkId — the chosen output has to be set here.
      window.OdysseusAudioDevices?.applyToContext(this._audioCtx);
    }
    // Senza un gesto recente il contesto nasce sospeso: nessun suono e nessun
    // campione, quindi bocca ferma. `resume()` va richiesto ogni volta.
    if (this._audioCtx.state === 'suspended') this._audioCtx.resume();
    return this._audioCtx;
  }

  _track() {
    if (this._rafId) return;
    let buf = null;
    const tick = () => {
      let grezzo = null;

      if (this._analyser) {
        if (!buf || buf.length !== this._analyser.fftSize) {
          buf = new Float32Array(this._analyser.fftSize);
        }
        this._analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const s of buf) sum += s * s;
        grezzo = Math.sqrt(sum / buf.length);
      } else if (performance.now() - this._livelloAl < SCADENZA_LIVELLO_MS) {
        grezzo = this._livello;
      }

      if (grezzo === null) { this._untrack(); return; }

      // Controllo di volume automatico: il picco recente diventa "bocca
      // spalancata", cosi' una voce piano apre quanto una voce forte.
      this._picco = Math.max(grezzo, this._picco * PICCO_DECADIMENTO, PICCO_MINIMO);
      const bersaglio = Math.min(1, (grezzo / this._picco) * (MOUTH_GAIN / 2.4));

      const k = bersaglio > this._levigato ? ATTACCO : RILASCIO;
      this._levigato += (bersaglio - this._levigato) * k;
      this._setMouth(this._levigato);

      this._rafId = requestAnimationFrame(tick);
    };
    this._rafId = requestAnimationFrame(tick);
  }

  _untrack() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._rafId = null;
    this._analyser = null;
    this._levigato = 0;
    this._picco = PICCO_MINIMO;
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
