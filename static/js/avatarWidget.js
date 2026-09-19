// Entry point for the detached widget window (/static/avatar.html).
// External file because static pages get a CSP without an inline nonce.

import { AvatarRenderer } from './avatarRenderer.js';

const MODELS = {
  mao_pro: {
    url: '/static/live2d/mao_pro/runtime/mao_pro.model3.json',
    expressions: { neutral: 0, fear: 1, sadness: 1, anger: 2, disgust: 2, joy: 3, smirk: 3, surprise: 3 },
  },
};

const hint = document.getElementById('hint');
const modelId = localStorage.getItem('odysseus.avatar.model') || 'mao_pro';
const model = MODELS[modelId] || MODELS.mao_pro;

try {
  const renderer = await new AvatarRenderer(document.getElementById('live2d'), {
    modelUrl: model.url,
    expressions: model.expressions,
    scale: 0.3,
  }).init();
  renderer.bind(null); // detached: follow the BroadcastChannel
} catch (e) {
  if (hint) { hint.textContent = 'avatar non caricato: ' + e.message; hint.classList.add('show'); }
  throw e;
}

// The widget only receives while an Odysseus tab is open in this browser.
let seen = false;
new BroadcastChannel('odysseus-avatar')
  .addEventListener('message', () => { seen = true; hint?.classList.remove('show'); });
setTimeout(() => { if (!seen) hint?.classList.add('show'); }, 4000);
