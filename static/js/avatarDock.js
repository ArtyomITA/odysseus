// Avatar dock — mounts the renderer in the page, wires the Settings toggle,
// and handles detaching into a standalone widget window.
//
// Preferences are per-browser (localStorage): the avatar is a client-side
// presentation choice, not server state.

import { avatarCore } from './avatarCore.js';
import { AvatarRenderer } from './avatarRenderer.js';

const PREF_ENABLED = 'odysseus.avatar.enabled';
const PREF_MODEL = 'odysseus.avatar.model';
const PREF_POS = 'odysseus.avatar.pos';
const PREF_SIZE = 'odysseus.avatar.size';

// Models available under /static/live2d/. Add an entry to ship another one.
export const AVATAR_MODELS = {
  mao_pro: {
    label: 'Mao (Niziiro Mao)',
    url: '/static/live2d/mao_pro/runtime/mao_pro.model3.json',
    // Expression indices as declared by the model's own emotionMap.
    expressions: { neutral: 0, fear: 1, sadness: 1, anger: 2, disgust: 2, joy: 3, smirk: 3, surprise: 3 },
  },
};

let renderer = null;

const dock = document.getElementById('avatar-dock');
const canvas = document.getElementById('avatar-canvas');
const toggle = document.getElementById('avatar-enabled-toggle');
const modelSelect = document.getElementById('avatar-model-select');

export function currentModelId() {
  const saved = localStorage.getItem(PREF_MODEL);
  return AVATAR_MODELS[saved] ? saved : Object.keys(AVATAR_MODELS)[0];
}

export function isAvatarEnabled() {
  return localStorage.getItem(PREF_ENABLED) === '1';
}

async function mount() {
  if (renderer || !canvas) return;
  const model = AVATAR_MODELS[currentModelId()];
  dock.hidden = false;
  try {
    renderer = await new AvatarRenderer(canvas, {
      modelUrl: model.url,
      expressions: model.expressions,
    }).init();
    renderer.bind(avatarCore);
  } catch (e) {
    console.warn('avatar: renderer failed to start', e);
    dock.hidden = true;
    renderer = null;
    return false;
  }
  return true;
}

function unmount() {
  if (dock) dock.hidden = true;
  if (renderer?.app) renderer.app.destroy(false, { children: true });
  renderer = null;
}

export async function setAvatarEnabled(on) {
  localStorage.setItem(PREF_ENABLED, on ? '1' : '0');
  if (toggle) toggle.checked = on;
  if (on) await mount(); else unmount();
}

export async function setAvatarModel(id) {
  if (!AVATAR_MODELS[id]) return;
  localStorage.setItem(PREF_MODEL, id);
  if (renderer) { unmount(); await mount(); }
}

// --- wiring ---------------------------------------------------------------

if (modelSelect) {
  modelSelect.innerHTML = '';
  for (const [id, m] of Object.entries(AVATAR_MODELS)) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = m.label;
    modelSelect.appendChild(opt);
  }
  modelSelect.value = currentModelId();
  modelSelect.addEventListener('change', () => setAvatarModel(modelSelect.value));
}

if (toggle) {
  toggle.checked = isAvatarEnabled();
  toggle.addEventListener('change', () => setAvatarEnabled(toggle.checked));
}

// --- drag & resize --------------------------------------------------------

function clampIntoView(left, top, w, h) {
  const margin = 8;
  return {
    left: Math.min(Math.max(margin, left), window.innerWidth - w - margin),
    top: Math.min(Math.max(margin, top), window.innerHeight - h - margin),
  };
}

function applyGeometry() {
  if (!dock) return;
  const size = JSON.parse(localStorage.getItem(PREF_SIZE) || 'null');
  if (size) {
    dock.style.width = size.w + 'px';
    dock.style.height = size.h + 'px';
  }
  const pos = JSON.parse(localStorage.getItem(PREF_POS) || 'null');
  if (!pos) return;
  const { left, top } = clampIntoView(pos.left, pos.top, dock.offsetWidth, dock.offsetHeight);
  dock.style.left = left + 'px';
  dock.style.top = top + 'px';
  dock.style.right = 'auto';
  dock.style.bottom = 'auto';
}

function initDrag() {
  if (!dock) return;
  let startX = 0, startY = 0, startLeft = 0, startTop = 0, dragging = false;

  dock.addEventListener('pointerdown', (e) => {
    if (e.target.closest('#avatar-dock-bar') || e.target.closest('#avatar-resize')) return;
    const r = dock.getBoundingClientRect();
    startX = e.clientX; startY = e.clientY; startLeft = r.left; startTop = r.top;
    dragging = true;
    dock.setPointerCapture(e.pointerId);
    dock.classList.add('dragging');
  });

  dock.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const { left, top } = clampIntoView(
      startLeft + e.clientX - startX, startTop + e.clientY - startY,
      dock.offsetWidth, dock.offsetHeight);
    dock.style.left = left + 'px';
    dock.style.top = top + 'px';
    dock.style.right = 'auto';
    dock.style.bottom = 'auto';
  });

  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    dock.classList.remove('dragging');
    try { dock.releasePointerCapture(e.pointerId); } catch {}
    const r = dock.getBoundingClientRect();
    localStorage.setItem(PREF_POS, JSON.stringify({ left: r.left, top: r.top }));
  };
  dock.addEventListener('pointerup', end);
  dock.addEventListener('pointercancel', end);

  // Corner handle resizes; the renderer re-fits on the resize event.
  const handle = document.getElementById('avatar-resize');
  let rs = null;
  handle?.addEventListener('pointerdown', (e) => {
    e.stopPropagation();
    rs = { x: e.clientX, y: e.clientY, w: dock.offsetWidth, h: dock.offsetHeight };
    handle.setPointerCapture(e.pointerId);
  });
  handle?.addEventListener('pointermove', (e) => {
    if (!rs) return;
    const w = Math.max(140, Math.min(700, rs.w + (e.clientX - rs.x)));
    const h = Math.max(180, Math.min(900, rs.h + (e.clientY - rs.y)));
    dock.style.width = w + 'px';
    dock.style.height = h + 'px';
    renderer?.resize();
  });
  handle?.addEventListener('pointerup', (e) => {
    if (!rs) return;
    rs = null;
    try { handle.releasePointerCapture(e.pointerId); } catch {}
    localStorage.setItem(PREF_SIZE, JSON.stringify({ w: dock.offsetWidth, h: dock.offsetHeight }));
    renderer?.resize();
  });

  // Keep it on screen when the window changes size.
  window.addEventListener('resize', () => applyGeometry());
}

applyGeometry();
initDrag();

document.getElementById('avatar-detach')?.addEventListener('click', () => {
  // The widget listens on the same BroadcastChannel, so both stay in sync.
  const w = window.open('/static/avatar.html', 'odysseus-avatar',
    'width=360,height=520,menubar=no,toolbar=no,location=no,status=no');
  if (w) unmount();
});

document.getElementById('avatar-close')?.addEventListener('click', () => setAvatarEnabled(false));

if (isAvatarEnabled()) mount();

window.OdysseusAvatarDock = { setAvatarEnabled, setAvatarModel, isAvatarEnabled, AVATAR_MODELS };
