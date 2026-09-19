// Avatar persona — writes the character preset that makes the agent tag its
// replies with emotions.
//
// The emotion block is appended automatically to whatever personality the user
// writes, so rewriting the personality never silently disables the expressions.

import { AVATAR_MODELS, currentModelId } from './avatarDock.js';

const MARKER = '<!-- avatar-emotions -->';

function emotionBlock(emotions) {
  const tags = Object.keys(emotions).map((e) => `[${e}]`).join(' ');
  return `${MARKER}
Hai un volto animato che mostra le tue emozioni. Inserisci UN tag emozione
all'inizio di ogni risposta, e cambialo durante la risposta solo se il tono cambia
davvero. Tag disponibili: ${tags}
Scrivi il tag esattamente così, fra parentesi quadre, senza spiegarlo mai
all'utente. Esempio: "[joy] Trovato! Il file era nella cartella temporanea."
Usa [neutral] quando non c'è una emozione particolare.`;
}

/** Strip any previously appended block so re-saving doesn't stack copies. */
function stripEmotionBlock(prompt) {
  const i = prompt.indexOf(MARKER);
  return (i === -1 ? prompt : prompt.slice(0, i)).trimEnd();
}

export function composePrompt(personality) {
  const model = AVATAR_MODELS[currentModelId()];
  const base = stripEmotionBlock(personality || '');
  return `${base}\n\n${emotionBlock(model.expressions)}`.trim();
}

export async function loadPersona() {
  const res = await fetch('/api/presets');
  if (!res.ok) return null;
  const presets = await res.json();
  return presets?.custom || null;
}

export async function savePersona(name, personality) {
  // The endpoint takes a JSON body (PresetUpdateRequest), not form fields.
  const res = await fetch('/api/presets/custom', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: name || 'Avatar',
      system_prompt: composePrompt(personality),
      temperature: 0.8,
      max_tokens: 0,
      enabled: true,
      inject_prefix: '',
      inject_suffix: '',
    }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`preset save failed: ${res.status} ${detail.slice(0, 200)}`);
  }
  return res.json();
}

// --- wiring ---------------------------------------------------------------

const promptEl = document.getElementById('avatar-persona-prompt');
const nameEl = document.getElementById('avatar-persona-name');
const saveEl = document.getElementById('avatar-persona-save');
const statusEl = document.getElementById('avatar-persona-status');

if (promptEl && saveEl) {
  loadPersona().then((p) => {
    if (!p) return;
    if (nameEl) nameEl.value = p.character_name || p.name || '';
    promptEl.value = stripEmotionBlock(p.system_prompt || '');
  }).catch(() => {});

  saveEl.addEventListener('click', async () => {
    if (statusEl) statusEl.textContent = 'salvo…';
    try {
      await savePersona(nameEl?.value, promptEl.value);
      if (statusEl) statusEl.textContent = 'applicata';
    } catch (e) {
      console.warn('avatar persona:', e);
      if (statusEl) statusEl.textContent = 'errore';
    }
    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 2500);
  });
}
