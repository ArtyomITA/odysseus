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
// recente (una specie di controllo di volume automatico).
const MOUTH_GAIN = 2.4;
const MOUTH_FLOOR = 0.02;
const PICCO_MINIMO = 0.035;   // sotto questo non si normalizza: e' rumore
const PICCO_DECADIMENTO = 0.995;
// A6: UN SOLO livellamento in tutta la catena.
//
// Prima erano tre in cascata: attacco/rilascio per fotogramma qui, un altro
// 0,5 per fotogramma nel renderer e uno `smoothingTimeConstant` che sui dati
// nel dominio del tempo non fa niente (MDN: media fra i frame di analisi in
// FREQUENZA). Tre ritardi sommati, tutti dipendenti dai fotogrammi al secondo.
//
// Qui resta solo questo, e in millisecondi invece che "per fotogramma": a 30
// fps un coefficiente tarato a 60 fps raddoppia il ritardo. Attacco corto
// perche' la bocca umana apre di scatto, rilascio piu' lungo perche' si chiude
// piano: e' quello che distingue un labiale da un lampeggio.
const ATTACCO_MS = 35;
const RILASCIO_MS = 100;
// Se chi produce l'audio ci alimenta da fuori (postMessage/BroadcastChannel) e
// poi smette, la bocca deve chiudersi da sola invece di restare spalancata.
const SCADENZA_LIVELLO_MS = 250;

// --- A7: bocca a vocali ----------------------------------------------------
//
// L'RMS ha UNA dimensione: quanto e' forte. La bocca ne ha almeno due
// (apertura e forma), quindi "AAA", "III" e "UUU" a pari volume davano la
// stessa immagine. mao_pro espone gia' ParamA/I/U/E/O: si stima la forma dallo
// spettro e si pilotano tutti e cinque.
//
// Le cinque vocali stanno su un arco: dal grave arrotondato (U) all'acuto
// stirato (I). La posizione sull'arco e' il centroide spettrale delle quattro
// bande; il peso si spartisce fra le due vocali adiacenti, cosi' la somma dei
// cinque parametri vale sempre l'apertura e la bocca non si "gonfia".
const VOCALI = [
  { id: 'ParamU', posizione: 0.0, guadagno: 0.70 },
  { id: 'ParamO', posizione: 0.8, guadagno: 0.90 },
  { id: 'ParamA', posizione: 1.7, guadagno: 1.00 },
  { id: 'ParamE', posizione: 2.4, guadagno: 0.90 },
  { id: 'ParamI', posizione: 3.0, guadagno: 0.72 },
];
// Estremi delle quattro bande, in Hz. Seguono grosso modo F1 e F2:
// 0-500 (voce e F1 chiusa), 500-1000 (F1 aperta, A), 1000-2200 (F2, E/O),
// 2200-4500 (F2 alta e fricative, I).
const BANDE_HZ = [[80, 500], [500, 1000], [1000, 2200], [2200, 4500]];
const FFT = 1024;   // 512 bin, ~47 Hz per bin a 48 kHz: basta e costa poco
// Ritardo di uscita: quanto la bocca deve stare INDIETRO rispetto all'analisi.
// Leva per tarare a mano (cuffie Bluetooth: ~170 ms).
const CHIAVE_RITARDO = 'odysseus.avatar.ritardoBocca';
const RITARDO_MAX_MS = 400;   // oltre, e' quasi certo un valore sbagliato del driver
const MEMORIA = 48;           // fotogrammi di storia: ~0,8 s a 60 fps

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
    this._forma = 1.7;          // posizione sull'arco delle vocali (A di riposo)
    this._ultimoTick = 0;
    this._bufSpettro = null;
    this._bufOnda = null;
    // Storia (tempo, apertura, forma) per la compensazione del ritardo: la
    // bocca legge il campione che si SENTE adesso, non quello appena
    // analizzato. Preallocata: nessuna allocazione per fotogramma.
    this._storia = new Float32Array(MEMORIA * 3);
    this._storiaN = 0;
    this._vocali = { ParamA: 0, ParamI: 0, ParamU: 0, ParamE: 0, ParamO: 0 };
    // Diagnostica per le misure in pagina (scarto bocca-suono, costo per
    // fotogramma). Solo lettura: nessuno la usa per decidere.
    this.diag = { ritardoMs: 0, costoMs: 0, fps: 0, livelloGrezzo: 0, forma: 0 };
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
    this._ascoltaMicrofono();
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

  /**
   * Apertura e forma della bocca.
   *
   * `apertura` e' quanto e' aperta (0..1), `forma` dove cade sull'arco delle
   * vocali (0 = U arrotondata, 3 = I stirata). I cinque parametri li calcola
   * qui una volta sola, cosi' il renderer in pagina e quello nella finestra
   * staccata ricevono gli stessi numeri.
   */
  _setMouth(apertura, forma) {
    const v = apertura < MOUTH_FLOOR ? 0 : Math.min(1, apertura);
    const f = typeof forma === 'number' && isFinite(forma) ? forma : this._forma;
    const vocali = this._vocali;
    if (v === 0) {
      // Silenzio e pause fra i pezzi: bocca CHIUSA, tutti e cinque a zero.
      for (const n of VOCALI) vocali[n.id] = 0;
    } else {
      // Peso spartito fra le due vocali adiacenti sull'arco. Somma = apertura.
      let sotto = 0;
      while (sotto < VOCALI.length - 2 && VOCALI[sotto + 1].posizione < f) sotto++;
      const a = VOCALI[sotto];
      const b = VOCALI[sotto + 1];
      const t = Math.max(0, Math.min(1, (f - a.posizione) / (b.posizione - a.posizione)));
      for (const n of VOCALI) vocali[n.id] = 0;
      vocali[a.id] = v * (1 - t) * a.guadagno;
      vocali[b.id] = v * t * b.guadagno;
    }
    // La soglia vale sull'apertura: la forma puo' cambiare a volume costante
    // (da "aaa" a "iii") e quel cambio si deve vedere.
    if (Math.abs(v - this.mouth) < 0.01 && Math.abs(f - this._forma) < 0.05) return;
    this.mouth = v;
    this._forma = f;
    document.documentElement.style.setProperty('--speak-intensity', v.toFixed(2));
    this._emit('mouth', { value: v, forma: f, vocali: { ...vocali } });
  }

  /**
   * Di quanto la bocca deve stare indietro rispetto all'analisi, in secondi.
   *
   * `AudioContext.currentTime` e' il tempo del GRAFO, non dell'altoparlante:
   * l'analizzatore legge in anticipo di `baseLatency + outputLatency`. Se si
   * disegna subito, la bocca e' avanti al suono. I due valori vanno riletti a
   * ogni fotogramma: `outputLatency` cambia durante la vita del contesto e
   * certi driver lo riportano sbagliato, da cui il tetto.
   *
   * Leva: localStorage['odysseus.avatar.ritardoBocca'] in millisecondi.
   * Vuota o 'auto' = automatico. Serve per le cuffie Bluetooth (~170 ms), che
   * il browser non sempre dichiara.
   */
  _ritardoUscita() {
    try {
      const manuale = localStorage.getItem(CHIAVE_RITARDO);
      if (manuale && manuale !== 'auto') {
        const ms = Number(manuale);
        if (isFinite(ms) && ms >= 0) return Math.min(ms, 2000) / 1000;
      }
    } catch (_) { /* archivio non accessibile: resta l'automatico */ }
    const ctx = this._audioCtx;
    if (!ctx) return 0;
    const base = Number(ctx.baseLatency) || 0;
    const uscita = Number(ctx.outputLatency) || 0;
    return Math.min(base + uscita, RITARDO_MAX_MS / 1000);
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
      // Testo che arriva NON vuol dire suono che esce. Con la voce accesa la
      // sintesi arriva secondi dopo: fino ad allora il personaggio sta ancora
      // pensando, e "parla" lo dice l'audio in riproduzione (`attachAudio`).
      // Senza voce, invece, il testo che scorre E' il parlato.
      this.setState(this._voceAttesa() ? 'thinking' : 'talking');
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
    // Se la voce sta ancora parlando, il turno non e' finito per l'avatar:
    // chiudere qui spegnerebbe la bocca a meta' frase.
    if (this._rafId) return;
    this.setState(this._microfonoAperto ? 'listening' : 'idle');
  }

  /** La risposta di questo turno verra' letta ad alta voce? */
  _voceAttesa() {
    try {
      const t = window.aiTTSManager;
      return !!(t && t.available && t.autoPlay);
    } catch (_) { return false; }
  }

  /**
   * Stato di ascolto: il microfono in diretta e' aperto.
   *
   * Gli eventi li emette voiceRecorder quando accende e spegne la
   * trascrizione in diretta. Non e' lo stesso di `tts-start`/`tts-end`, che
   * dicono solo se il microfono e' zittito mentre l'assistente parla.
   */
  _ascoltaMicrofono() {
    this._microfonoAperto = false;
    const apri = () => {
      this._microfonoAperto = true;
      if (this.state === 'idle') this.setState('listening');
    };
    const chiudi = () => {
      this._microfonoAperto = false;
      if (this.state === 'listening') this.setState('idle');
    };
    try {
      window.addEventListener('odysseus:mic-start', apri);
      window.addEventListener('odysseus:mic-end', chiudi);
    } catch (_) { /* ambiente senza window: resta senza stato di ascolto */ }
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
        // FFT piccola: 512 bin bastano per quattro bande, e il costo cresce
        // con la finestra. `smoothingTimeConstant` resta a 0: il livellamento
        // e' uno solo ed e' piu' avanti (A6). Lasciato com'era, avrebbe anche
        // sporcato la forma delle vocali mediando fra fonemi diversi.
        analyser.fftSize = FFT;
        analyser.smoothingTimeConstant = 0;
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
      this.setState(this._microfonoAperto ? 'listening' : 'idle');
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
      analyser.fftSize = FFT;
      analyser.smoothingTimeConstant = 0;
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

  /**
   * Posizione sull'arco delle vocali, dallo spettro appena letto.
   *
   * Quattro somme di bande e un centroide: qualche microsecondo, nessuna
   * allocazione. Non riconosce i fonemi, distingue le FORME: grave e
   * concentrato in basso = arrotondata, F1 alta = aperta, energia in alto =
   * stirata. E' il compromesso che costa meno e batte l'RMS di netto.
   */
  _formaDaSpettro(analyser) {
    if (!this._bufSpettro || this._bufSpettro.length !== analyser.frequencyBinCount) {
      this._bufSpettro = new Uint8Array(analyser.frequencyBinCount);
    }
    const spettro = this._bufSpettro;
    analyser.getByteFrequencyData(spettro);
    const perBin = (analyser.context.sampleRate || 48000) / analyser.fftSize;
    let totale = 0;
    let pesato = 0;
    for (let b = 0; b < BANDE_HZ.length; b++) {
      const da = Math.max(1, Math.floor(BANDE_HZ[b][0] / perBin));
      const a = Math.min(spettro.length - 1, Math.ceil(BANDE_HZ[b][1] / perBin));
      let somma = 0;
      for (let i = da; i <= a; i++) somma += spettro[i];
      somma /= (a - da + 1);   // media, non somma: bande di larghezza diversa
      totale += somma;
      pesato += somma * b;
    }
    if (totale < 1) return this._forma;
    return pesato / totale;   // 0..3, gia' la scala dell'arco
  }

  _track() {
    if (this._rafId) return;
    this._ultimoTick = 0;
    let fotogrammi = 0;
    let daQuando = performance.now();
    const tick = () => {
      const t0 = performance.now();
      let grezzo = null;
      let forma = this._forma;

      if (this._analyser) {
        const n = this._analyser.fftSize;
        if (!this._bufOnda || this._bufOnda.length !== n) this._bufOnda = new Float32Array(n);
        const onda = this._bufOnda;
        this._analyser.getFloatTimeDomainData(onda);
        let sum = 0;
        for (let i = 0; i < n; i++) sum += onda[i] * onda[i];
        grezzo = Math.sqrt(sum / n);
        if (grezzo > MOUTH_FLOOR) forma = this._formaDaSpettro(this._analyser);
      } else if (t0 - this._livelloAl < SCADENZA_LIVELLO_MS) {
        // Livello gia' misurato da fuori (finestra staccata, voce del
        // browser): c'e' solo l'ampiezza, quindi la forma resta sulla A.
        grezzo = this._livello;
        forma = VOCALI[2].posizione;
      }

      if (grezzo === null) { this._untrack(); return; }

      // Controllo di volume automatico: il picco recente diventa "bocca
      // spalancata", cosi' una voce piano apre quanto una voce forte.
      this._picco = Math.max(grezzo, this._picco * PICCO_DECADIMENTO, PICCO_MINIMO);
      const bersaglio = Math.min(1, (grezzo / this._picco) * (MOUTH_GAIN / 2.4));

      // Unico livellamento, in millisecondi reali: a 30 fps il coefficiente si
      // adatta da solo invece di raddoppiare il ritardo.
      const dt = this._ultimoTick ? Math.min(100, t0 - this._ultimoTick) : 16;
      this._ultimoTick = t0;
      const tau = bersaglio > this._levigato ? ATTACCO_MS : RILASCIO_MS;
      const k = 1 - Math.exp(-dt / tau);
      this._levigato += (bersaglio - this._levigato) * k;

      // A5: si scrive nella storia quello che il GRAFO ha appena elaborato, e
      // si disegna quello che l'ORECCHIO sente adesso, cioe' il campione di
      // `ritardo` fa. Senza, la bocca e' avanti al suono di 20-50 ms sulle
      // casse integrate e di ~170 ms sulle cuffie Bluetooth.
      // Dal ritardo si toglie quello che il livellamento gia' introduce da se'
      // (la risposta al gradino arriva a meta' in ~un ATTACCO_MS): sommarli
      // porterebbe la bocca INDIETRO rispetto al suono invece che a filo.
      // Misurato su questa macchina: 52 ms di uscita meno 35 di attacco = 17.
      const ritardo = Math.max(0, this._ritardoUscita() * 1000 - ATTACCO_MS);
      const slot = (this._storiaN % MEMORIA) * 3;
      this._storia[slot] = t0;
      this._storia[slot + 1] = this._levigato;
      this._storia[slot + 2] = forma;
      this._storiaN++;
      const [aperturaUdita, formaUdita] = this._leggiStoria(t0 - ritardo);
      this._setMouth(aperturaUdita, formaUdita);

      fotogrammi++;
      if (t0 - daQuando >= 1000) {
        this.diag.fps = Math.round((fotogrammi * 1000) / (t0 - daQuando));
        fotogrammi = 0;
        daQuando = t0;
      }
      this.diag.ritardoMs = ritardo;
      this.diag.livelloGrezzo = grezzo;
      this.diag.forma = formaUdita;
      this.diag.costoMs = this.diag.costoMs * 0.9 + (performance.now() - t0) * 0.1;

      this._rafId = requestAnimationFrame(tick);
    };
    this._rafId = requestAnimationFrame(tick);
  }

  /** Campione piu' vicino a `quando` nella storia. Ricerca lineare su 48 voci. */
  _leggiStoria(quando) {
    const quanti = Math.min(this._storiaN, MEMORIA);
    if (quanti === 0) return [this._levigato, this._forma];
    let migliore = -1;
    let scarto = Infinity;
    for (let i = 0; i < quanti; i++) {
      const s = i * 3;
      const d = Math.abs(this._storia[s] - quando);
      if (d < scarto) { scarto = d; migliore = s; }
    }
    return [this._storia[migliore + 1], this._storia[migliore + 2]];
  }

  _untrack() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._rafId = null;
    this._analyser = null;
    this._levigato = 0;
    this._picco = PICCO_MINIMO;
    this._storiaN = 0;
    this._ultimoTick = 0;
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
