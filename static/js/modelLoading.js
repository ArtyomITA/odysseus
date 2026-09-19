// static/js/modelLoading.js
//
// Vergilius: model-swap loading overlay.
//
// Every local profile is served by one llama-swap on 127.0.0.1:8012. Picking a
// different entry in the dropdown makes llama-swap kill the running
// llama-server and start another one — 30-60 seconds from cold on the 1080,
// during which the endpoint accepts requests but answers nothing. Odysseus had
// no signal for that, so the first message after a switch just sat there.
//
// This module drives the two backend routes added for it:
//   POST /api/model-runtime/warmup  -> starts the load, returns immediately
//   GET  /api/model-runtime/status  -> {swap, state, vision, context_tokens}
//
// Endpoints that aren't llama-swap answer {swap:false} and no overlay is shown.
//
// Side effect worth knowing about: once a profile reports ready, llama.cpp's
// own /props tells us whether an mmproj is loaded. That verdict is cached
// here, broadcast as `odysseus:model-caps`, and drives the "senza vista" badge
// below. The backend gates the screenshot tools off the same fact
// (_drop_image_only_tools in agent_loop.py) — the badge only explains it.

import spinnerModule from './spinner.js';

const POLL_MS = 700;
// A cold 9B off a spinning disk is ~50s; 5 minutes is "something is wrong",
// not "be patient". The overlay stays dismissible the whole time.
const TIMEOUT_MS = 300000;
// Long enough that a fast warm swap doesn't produce an overlay flash.
const SHOW_AFTER_MS = 350;

const _caps = new Map();      // modelId -> {vision, context_tokens}
let _overlay = null;
let _activeToken = 0;

/** Last known capabilities for a model, or null when never probed. */
export function getCaps(modelId) {
  return _caps.get(modelId) || null;
}

/** Capabilities of whatever the chatbox is pointing at right now. */
export function getCurrentCaps() {
  return _caps.get(_currentModelId()) || null;
}

function _currentModelId() {
  try {
    const label = document.getElementById('model-picker-label');
    return (label && label.title) || '';
  } catch (_) {
    return '';
  }
}

function _publish(modelId, status) {
  if (!modelId || !status || status.vision === null || status.vision === undefined) return;
  const caps = {
    vision: !!status.vision,
    context_tokens: status.context_tokens || null,
  };
  _caps.set(modelId, caps);
  try {
    window.__odysseusModelCaps = Object.fromEntries(_caps);
    document.dispatchEvent(new CustomEvent('odysseus:model-caps', {
      detail: { model: modelId, ...caps },
    }));
  } catch (_) {}
}

// ── Overlay ──────────────────────────────────────────────────────────────

function _buildOverlay(displayName) {
  const overlay = document.createElement('div');
  overlay.className = 'model-loading-overlay';
  overlay.setAttribute('role', 'status');
  overlay.setAttribute('aria-live', 'polite');

  const panel = document.createElement('div');
  panel.className = 'model-loading-panel';

  const spin = spinnerModule.createWhirlpool(44);
  panel.appendChild(spin.element);

  const title = document.createElement('div');
  title.className = 'model-loading-title';
  title.textContent = 'Carico ' + displayName;
  panel.appendChild(title);

  const sub = document.createElement('div');
  sub.className = 'model-loading-sub';
  sub.textContent = 'llama-swap sta avviando il server…';
  panel.appendChild(sub);

  const elapsed = document.createElement('div');
  elapsed.className = 'model-loading-elapsed';
  elapsed.textContent = '0s';
  panel.appendChild(elapsed);

  const dismiss = document.createElement('button');
  dismiss.type = 'button';
  dismiss.className = 'model-loading-dismiss';
  dismiss.textContent = 'Nascondi';
  // Escape hatch, not a cancel: hiding the overlay must not abort the load,
  // otherwise the next message would hit a half-started server.
  dismiss.title = 'Il caricamento continua in background';
  panel.appendChild(dismiss);

  overlay.appendChild(panel);
  return { overlay, sub, elapsed, dismiss, spin };
}

function _closeOverlay() {
  if (!_overlay) return;
  try { _overlay.spin.destroy(); } catch (_) {}
  try { clearInterval(_overlay.timer); } catch (_) {}
  try { document.removeEventListener('keydown', _overlay.onKey); } catch (_) {}
  _overlay.overlay.remove();
  _overlay = null;
}

function _openOverlay(displayName, startedAt) {
  _closeOverlay();
  const parts = _buildOverlay(displayName);
  parts.dismiss.addEventListener('click', _closeOverlay);
  parts.onKey = (e) => { if (e.key === 'Escape') _closeOverlay(); };
  document.addEventListener('keydown', parts.onKey);
  parts.timer = setInterval(() => {
    const s = Math.round((Date.now() - startedAt) / 1000);
    parts.elapsed.textContent = s + 's';
    // The 1080 loads a Q4 9B in roughly 50s; past that, say so rather than
    // letting the user wonder whether it hung.
    if (s === 75) {
      parts.sub.textContent = 'Più lento del solito — il modello sta ancora caricando.';
    }
  }, 1000);
  _overlay = parts;
  document.body.appendChild(parts.overlay);
}

// ── Public entry point ───────────────────────────────────────────────────

/**
 * Warm up a model and block visually until it is ready.
 *
 * Never rejects: a failure here must not stop the user from chatting, it just
 * means they wait through the first message like before.
 *
 * @param {{url: string, mid: string, display?: string}} m
 * @returns {Promise<{swap: boolean, state: string, vision: (boolean|null)}>}
 */
export async function warmup(m) {
  const token = ++_activeToken;
  const modelId = (m && m.mid) || '';
  const url = (m && m.url) || '';
  const display = (m && m.display) || modelId;
  const fallback = { swap: false, state: '', vision: null };
  if (!modelId || !url) return fallback;

  let started;
  try {
    const res = await fetch('/api/model-runtime/warmup', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint_url: url, model: modelId }),
    });
    if (!res.ok) return fallback;
    started = await res.json();
  } catch (_) {
    return fallback;
  }
  // Not a swapping endpoint (cloud API, plain llama-server, Ollama): nothing
  // loads, nothing to wait for.
  if (!started || !started.swap) return fallback;

  const startedAt = Date.now();
  let shown = false;
  const statusUrl = `/api/model-runtime/status?endpoint_url=${encodeURIComponent(url)}&model=${encodeURIComponent(modelId)}`;

  while (Date.now() - startedAt < TIMEOUT_MS) {
    // A newer pick superseded this one — drop out silently so two overlays
    // never fight over the screen.
    if (token !== _activeToken) return fallback;

    let status = null;
    try {
      const res = await fetch(statusUrl, { credentials: 'same-origin' });
      if (res.ok) status = await res.json();
    } catch (_) { /* transient; keep polling */ }

    if (status && status.state === 'ready') {
      // Vergilius: ling-vista = Ling + occhi esterni (Holo su CPU). Il loader
      // resta aperto finche' anche gli occhi rispondono: il primo prefill di
      // Holo paga 10-19s di init encoder, meglio qui che al primo messaggio.
      if (status.vista_esterna && !status.occhi_pronti) {
        if (!shown) { shown = true; _openOverlay(display + ' + occhi (Holo)', startedAt); }
        _publish(modelId, status);  // badge "vista" subito, non solo a occhi pronti
        await new Promise(r => setTimeout(r, POLL_MS));
        continue;
      }
      if (token === _activeToken) _closeOverlay();
      _publish(modelId, status);
      return status;
    }
    if (status && status.swap === false) {
      if (token === _activeToken) _closeOverlay();
      return fallback;
    }
    // ling-vista in caricamento: il badge "vista" e' gia' corretto ora.
    if (status && status.vista_esterna) _publish(modelId, status);

    if (!shown && Date.now() - startedAt > SHOW_AFTER_MS) {
      shown = true;
      _openOverlay(display, startedAt);
    }
    await new Promise(r => setTimeout(r, POLL_MS));
  }

  if (token === _activeToken) _closeOverlay();
  return { swap: true, state: 'timeout', vision: null };
}

/**
 * Read capabilities without triggering a load — used on page boot so the UI
 * starts out correct for whatever model is already up.
 */
export async function refreshCaps(url, modelId) {
  if (!url || !modelId) return null;
  try {
    const res = await fetch(
      `/api/model-runtime/status?endpoint_url=${encodeURIComponent(url)}&model=${encodeURIComponent(modelId)}`,
      { credentials: 'same-origin' },
    );
    if (!res.ok) return null;
    const status = await res.json();
    _publish(modelId, status);
    return status;
  } catch (_) {
    return null;
  }
}

// ── "senza vista" badge ──────────────────────────────────────────────────
// qwenpaw and qwenpaw-vista are the same weights; only the loaded mmproj
// differs. Without a marker in the header there is nothing on screen telling
// the user why the model just stopped being able to look at things.

function _syncBadge() {
  const label = document.getElementById('model-picker-label');
  if (!label) return;
  const caps = _caps.get(label.title || '');
  const existing = label.parentElement
    ? label.parentElement.querySelector('.model-blind-badge')
    : null;
  // Unknown capabilities (cloud model, profile never loaded) claim nothing.
  if (!caps || caps.vision) {
    if (existing) existing.remove();
    return;
  }
  // Vergilius: vista esterna (ling-vista): gli occhi sono Holo, non un mmproj.
  // Badge positivo "vista" con lo stesso stile del "senza vista".
  const esterna = !!caps.vista_esterna;
  if (existing && existing.dataset.kind === (esterna ? 'vista' : 'cieco')) return;
  if (existing) existing.remove();
  const badge = document.createElement('span');
  badge.className = 'model-blind-badge' + (esterna ? ' model-vista-badge' : '');
  badge.dataset.kind = esterna ? 'vista' : 'cieco';
  badge.textContent = esterna ? 'vista' : 'senza vista';
  badge.title = esterna
    ? 'Occhi attivi (Holo su CPU): il modello guarda lo schermo, legge immagini e video, controlla PC e browser.'
    : 'Nessun proiettore visivo caricato: gli strumenti di screenshot '
      + 'non vengono offerti al modello. Scegli il profilo "(vista)" per attivarli.';
  label.insertAdjacentElement('afterend', badge);
}

try {
  document.addEventListener('odysseus:model-caps', _syncBadge);
  document.addEventListener('odysseus:model-picked', () => setTimeout(_syncBadge, 0));
  // Boot: the model already loaded in llama-swap decides the initial state.
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
      const label = document.getElementById('model-picker-label');
      const mid = label && label.title;
      if (!mid) return;
      let url = '';
      try {
        const dc = window.__odysseusDefaultChat
          || JSON.parse(localStorage.getItem('odysseus-default-chat-cache') || 'null');
        url = (dc && dc.endpoint_url) || '';
      } catch (_) {}
      if (url) refreshCaps(url, mid).then(_syncBadge);
    }, 1500);
  });
} catch (_) {}

const modelLoadingModule = { warmup, refreshCaps, getCaps, getCurrentCaps };
try { window.OdysseusModelLoading = modelLoadingModule; } catch (_) {}
export default modelLoadingModule;
