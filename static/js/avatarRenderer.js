// Live2D renderer — draws the avatar and applies commands from avatarCore.
//
// Pure output: it never reads the chat stream. The same module backs both the
// in-page canvas and the detached widget window; the widget just listens on the
// BroadcastChannel instead of the local core.

const MODEL_URL = '/static/live2d/mao_pro/runtime/mao_pro.model3.json';

// mao_pro expression indices, from the model's own emotionMap.
const EXPRESSION_INDEX = {
  neutral: 0, fear: 1, sadness: 1, anger: 2, disgust: 2,
  joy: 3, smirk: 3, surprise: 3,
};

// Motion groups the model ships with; picked per state when available.
const STATE_MOTION = {
  idle: 'Idle',
  thinking: 'Idle',
  working: 'Idle',
  talking: 'Idle',
};

export class AvatarRenderer {
  constructor(canvas, { modelUrl = MODEL_URL, scale = 0.22, expressions = EXPRESSION_INDEX } = {}) {
    this.canvas = canvas;
    this.modelUrl = modelUrl;
    this.scale = scale;
    this.expressions = expressions;
    this.model = null;
    this.mouth = 0;
    this._mouthTarget = 0;
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

    // Mouth parameters are per-model — mao_pro drives `ParamA`, not the
    // `ParamMouthOpenY` most examples hardcode. Read them off the model's own
    // LipSync group so any downloaded character works.
    this.mouthIds = this.model.internalModel.motionManager?.lipSyncIds?.length
      ? [...this.model.internalModel.motionManager.lipSyncIds]
      : ['ParamMouthOpenY'];

    this.app.stage.addChild(this.model);
    this._layout();
    // Riferimento tenuto da parte: senza, ogni accensione dell'avatar lascia un
    // ascoltatore attaccato a un modello distrutto, e al primo ridimensionamento
    // della finestra la console si riempie di errori.
    this._suRidimensiona = () => this._layout();
    window.addEventListener('resize', this._suRidimensiona);

    // beforeModelUpdate is the only hook that survives: parameters written on a
    // plain ticker get overwritten by the model's own update pass.
    this.model.internalModel.on('beforeModelUpdate', () => {
      this.mouth += (this._mouthTarget - this.mouth) * 0.5; // smooth the jitter
      const core = this.model.internalModel.coreModel;
      for (const id of this.mouthIds) core.setParameterValueById(id, this.mouth);
    });

    return this;
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
        break;
      }
      case 'mouth':
        this._mouthTarget = cmd.value;
        break;
      case 'state':
        this._applyState(cmd.state);
        break;
    }
  }

  _applyState(state) {
    this.canvas.dataset.state = state;
    const group = STATE_MOTION[state];
    if (group && state !== 'talking') {
      // Idle priority: never cut off a running motion.
      this.model.motion(group, undefined, 1);
    }
    if (state === 'idle') this._mouthTarget = 0;
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
    if (this._core && this._applica) this._core.removeEventListener('command', this._applica);
    try { this._canale?.close(); } catch { /* gia' chiuso */ }
    try { this.model?.destroy({ children: true, texture: true, baseTexture: true }); } catch { /* gia' distrutto */ }
    try { this.app?.destroy(false, { children: true, texture: true, baseTexture: true }); } catch { /* gia' distrutto */ }
    this.model = null;
    this.app = null;
  }
}
