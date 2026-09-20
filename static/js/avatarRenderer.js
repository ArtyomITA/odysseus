// Live2D renderer — draws the avatar and applies commands from avatarCore.
//
// Pure output: it never reads the chat stream. The same module backs both the
// in-page canvas and the detached widget window; the widget just listens on the
// BroadcastChannel instead of the local core.

const MODEL_URL = '/static/live2d/mao_pro/runtime/mao_pro.model3.json';

// Espressioni di mao_pro, lette dai suoi otto file exp_*.exp3.json:
// 0 exp_01 occhi normali · 1 exp_02 occhi che sorridono · 2 exp_03 vuota
// 3 exp_04 occhi spalancati con luce · 4 exp_05 sopracciglia giu', bocca giu'
// 5 exp_06 guance rosse, sopracciglia giu' · 6 exp_07 sopracciglia su, bocca giu'
// 7 exp_08 bocca arrabbiata. Prima se ne usavano quattro su otto.
// Tutti e otto toccano ParamA/I/U/E/O con Blend Add e valore 0, quindi non
// litigano con il lipsync.
const EXPRESSION_INDEX = {
  neutral: 0, joy: 1, surprise: 3, sadness: 4,
  fear: 5, disgust: 6, smirk: 6, anger: 7,
};

// Priorita' di Cubism: 0 nessuna, 1 attesa, 2 normale, 3 forzata.
const PRIORITA_ATTESA = 1;
const PRIORITA_NORMALE = 2;
const PRIORITA_FORZATA = 3;

// Le sette animazioni del pacchetto, una per stato. Prima `STATE_MOTION` le
// mappava TUTTE su `Idle` (mtn_01) e le altre sei non partivano mai.
// Il gruppo senza nome ("") e' quello che il .model3.json dichiara con
// mtn_02, mtn_03, mtn_04, special_01, special_02, special_03 in quest'ordine.
// `talking` non lancia niente: la vita durante il parlato la danno il lipsync
// e i micro-movimenti della testa, e un'animazione nuova a meta' frase si
// vedrebbe come uno scatto.
const STATE_MOTION = {
  idle:      { gruppo: 'Idle', indice: undefined, priorita: PRIORITA_ATTESA },
  listening: { gruppo: '', indice: 0, priorita: PRIORITA_NORMALE },  // mtn_02
  thinking:  { gruppo: '', indice: 1, priorita: PRIORITA_NORMALE },  // mtn_03
  working:   { gruppo: '', indice: 2, priorita: PRIORITA_NORMALE },  // mtn_04
  reacting:  { gruppo: '', indice: null, priorita: PRIORITA_FORZATA }, // special_*
};
// Indici delle tre `special_*` nel gruppo senza nome.
const SPECIALI = [3, 4, 5];

// Le cinque vocali di mao_pro. Non sono parametri standard di Cubism (che per
// la bocca ha solo ParamMouthOpenY e ParamMouthForm), sono convenzione di
// fatto: vanno cercati sul modello, non dati per scontati.
const VOCALI = ['ParamA', 'ParamI', 'ParamU', 'ParamE', 'ParamO'];

// Micro-movimenti della testa mentre parla. Si SOMMANO al respiro e allo
// sguardo invece di sovrascriverli (beforeModelUpdate scatta dopo entrambi).
const TESTA = [
  { id: 'ParamAngleX', ampiezza: 4.5, periodo: 2300 },
  { id: 'ParamAngleY', ampiezza: 3.0, periodo: 1700 },
  { id: 'ParamAngleZ', ampiezza: 2.5, periodo: 3100 },
];
// Sguardo mentre pensa: non fisso in avanti, ma che vaga piano in alto.
const SGUARDO_PENSIERO = { ampiezza: 0.55, periodo: 4200 };

export class AvatarRenderer {
  constructor(canvas, { modelUrl = MODEL_URL, scale = 0.22, expressions = EXPRESSION_INDEX } = {}) {
    this.canvas = canvas;
    this.modelUrl = modelUrl;
    this.scale = scale;
    this.expressions = expressions;
    this.model = null;
    this.mouth = 0;
    // A6: niente secondo livellamento qui. Il valore arriva gia' livigato da
    // avatarCore (un solo attacco/rilascio, in millisecondi reali) e gia'
    // spostato indietro del ritardo di uscita. Rilevigarlo qui aggiungeva un
    // ritardo dipendente dai fotogrammi al secondo che nessuno aveva tarato.
    this._vocali = null;
    this._stato = 'idle';
    this._puntatore = { x: 0, y: 0, visto: false };
    this._reagisceFinoA = 0;
  }

  async init() {
    const { Live2DModel } = PIXI.live2d;
    this.app = new PIXI.Application({
      view: this.canvas,
      backgroundAlpha: 0,
      resizeTo: this.canvas.parentElement || undefined,
      antialias: true,
      autoStart: true,
    });

    this.model = await Live2DModel.from(this.modelUrl, {
      ticker: PIXI.Ticker.shared,
      autoInteract: false, // don't steal clicks from the chat UI
    });

    // We own the mouth: the library's own lipsync floors it at 0.4, which reads
    // as flapping rather than speech.
    this.model.internalModel.lipSync = false;

    // Parametri della bocca. mao_pro dichiara nel gruppo LipSync il solo
    // `ParamA`, ma espone tutte e cinque le vocali: il gruppo e' il default
    // del SDK, non un vincolo. Si cercano le cinque a nome, provando a
    // scrivere e rileggere: in Cubism un id inesistente non lancia nessun
    // errore, restituisce sempre lo stesso valore, ed e' l'unico modo per
    // accorgersene. Il vecchio ripiego `['ParamMouthOpenY']` scriveva su un
    // parametro che su questo modello NON esiste.
    this.mouthIds = this._trovaParametriBocca();

    this.app.stage.addChild(this.model);
    this._layout();
    // Riferimento tenuto da parte: senza, ogni accensione dell'avatar lascia un
    // ascoltatore attaccato a un modello distrutto, e al primo ridimensionamento
    // della finestra la console si riempie di errori.
    this._suRidimensiona = () => this._layout();
    window.addEventListener('resize', this._suRidimensiona);

    // beforeModelUpdate is the only hook that survives: parameters written on a
    // plain ticker get overwritten by the model's own update pass. Scatta DOPO
    // animazioni, espressione, battito ciglia, sguardo e respiro: qui `set`
    // sovrascrive, `add` si somma. La bocca sovrascrive (le animazioni
    // muovono anche loro le vocali), la testa si somma al respiro.
    this.model.internalModel.on('beforeModelUpdate', () => {
      const core = this.model.internalModel.coreModel;
      const ora = performance.now();
      this._scriviBocca(core);
      this._scriviTesta(core, ora);
    });

    this._collegaSguardo();
    return this;
  }

  /** Le cinque vocali se il modello le ha davvero, altrimenti il gruppo LipSync. */
  _trovaParametriBocca() {
    const core = this.model.internalModel.coreModel;
    // Quanti parametri dichiara il modello, PRIMA di cercarne uno. Serve
    // perche' su Cubism 5.1 un id sconosciuto non da' errore e non torna -1:
    // viene aggiunto in coda, con un indice pari al conteggio di partenza.
    // E' anche il motivo per cui il vecchio ripiego `ParamMouthOpenY` sembrava
    // funzionare mentre la bocca restava ferma.
    let dichiarati = 0;
    try { dichiarati = core.getParameterCount(); } catch (_) { dichiarati = 0; }
    const scrivibile = (id) => {
      try {
        if (dichiarati > 0 && typeof core.getParameterIndex === 'function') {
          const i = core.getParameterIndex(id);
          return i >= 0 && i < dichiarati;
        }
        const prima = core.getParameterValueById(id);
        core.setParameterValueById(id, 0.73);
        const dopo = core.getParameterValueById(id);
        core.setParameterValueById(id, prima);
        return Math.abs(dopo - 0.73) < 0.01;
      } catch (_) { return false; }
    };
    const trovate = VOCALI.filter(scrivibile);
    if (trovate.length >= 3) return trovate;
    const gruppo = this.model.internalModel.motionManager?.lipSyncIds || [];
    return gruppo.length ? [...gruppo] : [];
  }

  /**
   * Bocca: apertura E forma. Se avatarCore manda le cinque vocali si scrivono
   * quelle; se manda solo il livello (finestra staccata alimentata dal solo
   * `mouth-level`, voce del browser) si apre la sola A.
   */
  _scriviBocca(core) {
    const v = this._vocali;
    for (const id of this.mouthIds) {
      let valore = 0;
      if (v && typeof v[id] === 'number') valore = v[id];
      else if (!v && id === 'ParamA') valore = this.mouth;
      else if (!v && this.mouthIds.length === 1) valore = this.mouth;
      core.setParameterValueById(id, Math.max(0, Math.min(1, valore)));
    }
  }

  /**
   * Micro-movimenti della testa mentre parla, guidati dall'energia dell'audio.
   *
   * Tre seni di periodo diverso (quindi mai un ciclo riconoscibile) scalati
   * sull'apertura della bocca: zitta, la testa e' ferma e resta il solo
   * respiro. Mentre pensa, invece, lo sguardo vaga: fermo immobile sembra
   * bloccato, ed e' proprio il momento in cui l'attesa si sente.
   */
  _scriviTesta(core, ora) {
    const somma = (id, v) => {
      try { core.addParameterValueById(id, v); }
      catch (_) { /* nucleo senza add: si rinuncia al micro-movimento */ }
    };
    if (this._stato === 'talking' && this.mouth > 0.02) {
      for (const m of TESTA) {
        somma(m.id, Math.sin((ora / m.periodo) * Math.PI * 2) * m.ampiezza * this.mouth);
      }
      return;
    }
    if (this._stato === 'thinking' || this._stato === 'working') {
      const f = Math.sin((ora / SGUARDO_PENSIERO.periodo) * Math.PI * 2);
      somma('ParamEyeBallX', f * SGUARDO_PENSIERO.ampiezza);
      somma('ParamEyeBallY', 0.35 + Math.abs(f) * 0.2);   // sguardo verso l'alto
      somma('ParamAngleZ', f * 3);
    }
  }

  /**
   * Sguardo che segue il puntatore, in modo discreto.
   *
   * `autoInteract: false` spegne anche `autoFocus`, quindi finora lo sguardo
   * era fermo. Si riaccende solo il focus, a mano: gli ascoltatori di tap e
   * di trascinamento della libreria restano spenti, cosi' l'avatar non ruba
   * i clic alla chat. `model.focus()` usa solo la DIREZIONE del puntatore
   * (atan2), cioe' guarderebbe sempre al massimo: si scrive invece nel
   * `focusController`, che rispetta anche l'intensita'.
   */
  _collegaSguardo() {
    this._suPuntatore = (e) => {
      this._puntatore.x = e.clientX;
      this._puntatore.y = e.clientY;
      this._puntatore.visto = true;
      this._aggiornaSguardo();
    };
    window.addEventListener('pointermove', this._suPuntatore, { passive: true });
  }

  _aggiornaSguardo() {
    const fc = this.model?.internalModel?.focusController;
    if (!fc || !this._puntatore.visto) return;
    const r = this.canvas.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height * 0.35;   // gli occhi stanno in alto nel riquadro
    // Meta' schermo = sguardo al massimo, e comunque non oltre 0,75: un
    // pupillone che insegue il mouse fino agli angoli e' inquietante.
    const nx = (this._puntatore.x - cx) / (window.innerWidth / 2);
    const ny = (this._puntatore.y - cy) / (window.innerHeight / 2);
    const taglia = (v) => Math.max(-0.75, Math.min(0.75, v));
    // L'asse Y del controller e' verso l'ALTO, quello dello schermo verso il
    // basso: senza il meno l'avatar guarda dalla parte opposta.
    fc.focus(taglia(nx), taglia(-ny));
  }

  /** Re-fit after the dock is dragged or resized. */
  resize() {
    this.app?.resize();
    this._layout();
  }

  // Frame the upper body: these models are full-height (mao_pro is 5800x8400),
  // so fitting the whole figure into a small dock leaves a face a few pixels tall.
  _layout() {
    if (!this.model || !this.app?.screen) return;
    const { width, height } = this.app.screen;
    const im = this.model.internalModel;
    this.model.anchor.set(0.5, 0.0);
    this.model.position.set(width / 2, -height * 0.12);
    this.model.scale.set((width / im.originalWidth) * (this.scale / 0.22) * 2.6);
  }

  /** Apply one command emitted by avatarCore. */
  apply(cmd) {
    if (!this.model) return;
    switch (cmd.command) {
      case 'emotion': {
        const idx = this.expressions[cmd.emotion];
        if (idx !== undefined) this.model.expression(idx);
        // Il tag emozione ora si VEDE invece di sentirsi: forSpeech lo toglie
        // dal parlato, e qui diventa espressione piu' un lampo di reazione.
        if (cmd.emotion && cmd.emotion !== 'neutral' && this._stato !== 'talking') {
          this.reagisci();
        }
        break;
      }
      case 'mouth':
        this.mouth = cmd.value;
        this._vocali = cmd.vocali || null;
        break;
      case 'state':
        this._applyState(cmd.state);
        break;
    }
  }

  _applyState(state) {
    if (state === this._stato) return;
    // Una reazione in corso non si interrompe: e' un lampo di un secondo e
    // mezzo, e lasciarla tagliare dal primo `idle` che passa la rende invisibile.
    if (performance.now() < this._reagisceFinoA && state !== 'talking') return;
    this._stato = state;
    this.canvas.dataset.state = state;
    if (state === 'idle' || state === 'talking') {
      if (state === 'idle') { this.mouth = 0; this._vocali = null; }
      // Ritorno morbido all'attesa: priorita' bassa, quindi non taglia
      // l'animazione in corso e la dissolvenza di mtn_01 (1 s) fa il resto.
      if (state === 'idle') this._lancia(STATE_MOTION.idle);
      return;
    }
    const scelta = STATE_MOTION[state];
    if (scelta) this._lancia(scelta);
  }

  _lancia(scelta) {
    if (!scelta || !this.model) return;
    let indice = scelta.indice;
    if (indice === null) indice = SPECIALI[Math.floor(Math.random() * SPECIALI.length)];
    try {
      // Le promesse di `motion()` sono rifiutate quando la priorita' non passa:
      // e' il caso normale, non un errore da mostrare in console.
      Promise.resolve(this.model.motion(scelta.gruppo, indice, scelta.priorita))
        .catch(() => {});
    } catch (_) { /* gruppo assente nel modello: si resta su quella in corso */ }
  }

  /** Lampo di reazione: un'animazione speciale, poi ritorno da solo allo stato. */
  reagisci() {
    if (!this.model) return;
    this._reagisceFinoA = performance.now() + 1500;
    this.canvas.dataset.state = 'reacting';
    this._lancia(STATE_MOTION.reacting);
  }

  /** Follow a core instance (in-page) or the BroadcastChannel (widget). */
  bind(core) {
    this._applica = (e) => this.apply(e.detail);
    if (core) {
      this._core = core;
      core.addEventListener('command', this._applica);
      return this;
    }
    this._canale = new BroadcastChannel('odysseus-avatar');
    this._canale.onmessage = (e) => this.apply(e.data);
    return this;
  }

  /**
   * Smonta tutto. La texture di mao_pro e' 4096x4096: lasciarla in giro a ogni
   * accensione/spegnimento dell'avatar vuol dire ~67 MB di memoria video per
   * giro, e il contesto WebGL che prima o poi si perde.
   */
  destroy() {
    if (this._suRidimensiona) window.removeEventListener('resize', this._suRidimensiona);
    if (this._suPuntatore) window.removeEventListener('pointermove', this._suPuntatore);
    if (this._core && this._applica) this._core.removeEventListener('command', this._applica);
    try { this._canale?.close(); } catch { /* gia' chiuso */ }
    try { this.model?.destroy({ children: true, texture: true, baseTexture: true }); } catch { /* gia' distrutto */ }
    try { this.app?.destroy(false, { children: true, texture: true, baseTexture: true }); } catch { /* gia' distrutto */ }
    this.model = null;
    this.app = null;
  }
}
