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

  // I parametri della bocca sono per modello: mao_pro muove `ParamA`, non il
  // `ParamMouthOpenY` che copiano tutti gli esempi. Provarlo a nome fisso vuol
  // dire scrivere su un parametro che non esiste e dire "tutto ok" — che e' il
  // motivo per cui questa pagina passava mentre la bocca restava ferma. Si
  // legge il gruppo LipSync del modello, esattamente come fa avatarRenderer.js.
  const core = model.internalModel.coreModel;
  const idsBocca = model.internalModel.motionManager?.lipSyncIds?.length
    ? [...model.internalModel.motionManager.lipSyncIds]
    : [];
  say('parametri bocca (gruppo LipSync): ' + (idsBocca.join(',') || 'NESSUNO'));

  if (idsBocca.length === 0) {
    throw new Error('il modello non dichiara un gruppo LipSync: nessun parametro da muovere');
  }

  // Prova onesta: si scrive un valore e si rilegge. Un id inesistente in
  // Cubism non lancia nessun errore, restituisce semplicemente sempre lo stesso
  // valore — ed e' l'unico modo per accorgersene.
  for (const id of idsBocca) {
    const prima = core.getParameterValueById(id);
    core.setParameterValueById(id, 0.9);
    const dopo = core.getParameterValueById(id);
    if (!(Math.abs(dopo - 0.9) < 0.01)) {
      throw new Error(`il parametro ${id} non cambia (letto ${dopo} dopo aver scritto 0.9)`);
    }
    core.setParameterValueById(id, prima);
    say(`parametro ${id}: scrivibile (ok)`);
  }

  model.internalModel.on('beforeModelUpdate', () => {
    for (const id of idsBocca) core.setParameterValueById(id, 0.5);
  });
  say('beforeModelUpdate hook: ok (usa ' + idsBocca.join(',') + ')');

  say('ESITO: TUTTO OK');
} catch (e) {
  say('ERRORE: ' + (e && e.message ? e.message : String(e)));
  if (e && e.stack) say('STACK: ' + e.stack.split('\n').slice(0, 3).join(' | '));
}
