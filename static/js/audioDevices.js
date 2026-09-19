// Audio device picker — lets the user choose which microphone to record from and
// which output the assistant speaks through. Odysseus ships neither.
//
// Choices are per-browser (localStorage). The output device is applied with
// setSinkId(), which Chromium supports and Firefox does not; there we degrade to
// the system default rather than failing.

const PREF_IN = 'odysseus.audio.input';
const PREF_OUT = 'odysseus.audio.output';

export function inputDeviceId() {
  return localStorage.getItem(PREF_IN) || '';
}

export function outputDeviceId() {
  return localStorage.getItem(PREF_OUT) || '';
}

/** Constraints for getUserMedia honouring the chosen microphone. */
export function micConstraints(extra = {}) {
  const id = inputDeviceId();
  return {
    audio: {
      ...(id ? { deviceId: { exact: id } } : {}),
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      ...extra,
    },
  };
}

/** Route one audio element to the chosen output. Safe to call unconditionally. */
export async function applyOutputDevice(audioEl) {
  const id = outputDeviceId();
  if (!id || !audioEl || typeof audioEl.setSinkId !== 'function') return;
  try {
    await audioEl.setSinkId(id);
  } catch (e) {
    console.warn('audio: cannot route to chosen output', e);
  }
}

// Anything tapped by an AnalyserNode (the avatar lip-sync) plays through the
// AudioContext, not the element, so the element's sinkId no longer applies.
const _contexts = new Set();

export async function applyToContext(ctx) {
  if (!ctx) return;
  _contexts.add(ctx);
  const id = outputDeviceId();
  if (!id || typeof ctx.setSinkId !== 'function') return;
  try {
    await ctx.setSinkId(id);
  } catch (e) {
    console.warn('audio: cannot route audio graph to chosen output', e);
  }
}

// Labels are blank until the user has granted mic permission at least once.
async function listDevices() {
  if (!navigator.mediaDevices?.enumerateDevices) return { inputs: [], outputs: [] };
  const devices = await navigator.mediaDevices.enumerateDevices();
  return {
    inputs: devices.filter((d) => d.kind === 'audioinput'),
    outputs: devices.filter((d) => d.kind === 'audiooutput'),
  };
}

function fill(select, devices, saved, fallbackLabel) {
  select.innerHTML = '';
  const auto = document.createElement('option');
  auto.value = '';
  auto.textContent = 'Predefinito di sistema';
  select.appendChild(auto);
  devices.forEach((d, i) => {
    const opt = document.createElement('option');
    opt.value = d.deviceId;
    opt.textContent = d.label || `${fallbackLabel} ${i + 1}`;
    select.appendChild(opt);
  });
  select.value = devices.some((d) => d.deviceId === saved) ? saved : '';
}

async function refresh() {
  const inSel = document.getElementById('audio-input-select');
  const outSel = document.getElementById('audio-output-select');
  if (!inSel || !outSel) return;
  const { inputs, outputs } = await listDevices();
  fill(inSel, inputs, inputDeviceId(), 'Microfono');
  fill(outSel, outputs, outputDeviceId(), 'Uscita');

  const note = document.getElementById('audio-devices-note');
  if (note) {
    const noLabels = inputs.length && !inputs[0].label;
    const noSink = typeof HTMLMediaElement === 'undefined'
      || !('setSinkId' in HTMLMediaElement.prototype);
    note.textContent = noLabels
      ? 'Consenti l\'accesso al microfono una volta per vedere i nomi dei dispositivi.'
      : noSink
        ? 'Questo browser non permette di scegliere l\'uscita audio: verrà usata quella di sistema.'
        : '';
  }
}

// --- wiring ---------------------------------------------------------------

const inSel = document.getElementById('audio-input-select');
const outSel = document.getElementById('audio-output-select');

if (inSel && outSel) {
  inSel.addEventListener('change', () => localStorage.setItem(PREF_IN, inSel.value));
  outSel.addEventListener('change', async () => {
    localStorage.setItem(PREF_OUT, outSel.value);
    // Give immediate feedback: re-route whatever is playing right now, and any
    // audio graph already built (the avatar's).
    document.querySelectorAll('audio').forEach((el) => applyOutputDevice(el));
    _contexts.forEach((ctx) => applyToContext(ctx));
  });

  document.getElementById('audio-devices-refresh')?.addEventListener('click', async () => {
    // Asking for the mic once unlocks the device labels.
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      s.getTracks().forEach((t) => t.stop());
    } catch { /* permission denied: labels stay blank */ }
    refresh();
  });

  navigator.mediaDevices?.addEventListener?.('devicechange', refresh);
  refresh();
}

window.OdysseusAudioDevices = {
  micConstraints, applyOutputDevice, applyToContext, inputDeviceId, outputDeviceId,
};
