// Diagnostics for the Live2D stack. Loaded by /static/avatar-test.html.
// External file because static pages get a CSP without an inline nonce.

const log = document.getElementById('log');
const say = (t) => { const li = document.createElement('li'); li.textContent = t; log.appendChild(li); };

window.addEventListener('error', (e) => say('WINDOW ERROR: ' + e.message));

say('cubism core: ' + (typeof window.Live2DCubismCore));
say('PIXI: ' + (typeof window.PIXI));
say('PIXI version: ' + (window.PIXI?.VERSION || 'n/a'));
say('PIXI.live2d: ' + (typeof window.PIXI?.live2d));
say('Live2DModel: ' + (typeof window.PIXI?.live2d?.Live2DModel));

try {
  const app = new PIXI.Application({ view: document.getElementById('c'), backgroundAlpha: 0 });
  say('PIXI.Application: ok');

  const model = await PIXI.live2d.Live2DModel.from(
    '/static/live2d/mao_pro/runtime/mao_pro.model3.json',
    { ticker: PIXI.Ticker.shared, autoInteract: false });
  say('model loaded: ok');
  say('originalWidth=' + model.internalModel.originalWidth + ' originalHeight=' + model.internalModel.originalHeight);

  app.stage.addChild(model);
  model.anchor.set(0.5, 0.5);
  model.position.set(150, 200);
  model.scale.set(0.12);
  say('stage children: ' + app.stage.children.length);
  say('scaled size: ' + Math.round(model.width) + 'x' + Math.round(model.height));

  const settings = model.internalModel.settings;
  say('expressions: ' + (settings.expressions?.length ?? 'n/a'));
  say('motion groups: ' + Object.keys(settings.motions || {}).join(',') || 'none');

  model.internalModel.on('beforeModelUpdate', () => {
    model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', 0.5);
  });
  say('beforeModelUpdate hook: ok');

  say('ESITO: TUTTO OK');
} catch (e) {
  say('ERRORE: ' + (e && e.message ? e.message : String(e)));
  if (e && e.stack) say('STACK: ' + e.stack.split('\n').slice(0, 3).join(' | '));
}
