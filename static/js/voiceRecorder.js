// static/js/voiceRecorder.js

/**
 * Voice recording with optional Speech-to-Text transcription.
 *
 * STT providers:
 *   "disabled"       — record audio as file attachment (original behavior)
 *   "browser"        — use Web Speech API for real-time transcription
 *   "stream"         — live transcription over WebSocket (/api/stt/stream)
 *   "local"          — send recording to server /api/stt/transcribe (Whisper)
 *   "endpoint:<id>"  — send recording to server /api/stt/transcribe (API)
 *
 * "stream" is a different shape from the others and does not use MediaRecorder
 * at all. The rest record a whole clip, upload it, and wait: nothing appears
 * until you press stop. The live path pushes 100 ms of audio at a time and gets
 * text back while you are still talking — and decides on its own when you have
 * finished, so the stop press becomes optional.
 */

import { AsrStreaming } from './asrStreaming.js';

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let recordingStartTime = null;
let recordingInterval = null;

// Browser STT state
let _recognition = null;
let _browserTranscript = '';

// Cached STT provider — refreshed on settings change
let _sttProvider = 'disabled';

/**
 * Fetch current STT provider from server settings
 */
async function refreshSttProvider() {
  try {
    const res = await fetch('/api/stt/stats', { credentials: 'same-origin' });
    if (res.ok) {
      const stats = await res.json();
      _sttProvider = stats.provider || 'disabled';
      // La lingua scelta nelle impostazioni va passata al riconoscitore in
      // diretta: nessuno la pubblicava, e il microfono partiva sempre in
      // italiano qualunque cosa ci fosse scritto in `stt_language`.
      if (stats.language) window.OdysseusSttLanguage = stats.language;
      // Notify the send button to update its icon
      if (window._updateSendBtnIcon) window._updateSendBtnIcon();
    }
  } catch (e) {
    console.warn('Failed to fetch STT stats:', e);
  }
}

/**
 * Format seconds as MM:SS
 */
function formatTime(seconds) {
  const mins = Math.floor(seconds / 60).toString().padStart(2, '0');
  const secs = (seconds % 60).toString().padStart(2, '0');
  return `${mins}:${secs}`;
}

/**
 * Reset UI state after recording ends
 */
function _resetRecordingUI() {
  isRecording = false;
  if (recordingInterval) {
    clearInterval(recordingInterval);
    recordingInterval = null;
  }
  // Reset send button via global callback
  const sendBtn = document.querySelector('.send-btn');
  if (sendBtn) {
    sendBtn.classList.remove('recording');
    sendBtn.dataset.mode = '';
  }
  if (window._updateSendBtnIcon) {
    setTimeout(window._updateSendBtnIcon, 50);
  }
}

/**
 * Start browser speech recognition alongside recording
 */
function startBrowserSTT() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return;

  _browserTranscript = '';
  _recognition = new SpeechRecognition();
  _recognition.continuous = true;
  _recognition.interimResults = false;
  _recognition.lang = '';

  _recognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        _browserTranscript += event.results[i][0].transcript + ' ';
      }
    }
  };

  _recognition.onerror = (e) => {
    console.warn('Browser STT error:', e.error);
  };

  _recognition.start();
}

function stopBrowserSTT() {
  if (_recognition) {
    try { _recognition.stop(); } catch (e) { /* ignore */ }
    _recognition = null;
  }
  return _browserTranscript.trim();
}

/**
 * Send audio to server for transcription
 */
async function transcribeOnServer(audioBlob) {
  const formData = new FormData();
  formData.append('file', audioBlob, 'audio.webm');

  const res = await fetch('/api/stt/transcribe', {
    method: 'POST',
    credentials: 'same-origin',
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || 'Transcription failed');
  }

  const data = await res.json();
  return data.text || '';
}

/**
 * Insert transcribed text into the chat input
 */
function insertTranscription(text, showToast) {
  if (!text) return;
  const input = document.getElementById('message');
  if (!input) return;

  const existing = input.value.trim();
  input.value = existing ? existing + ' ' + text : text;

  // Trigger auto-resize and icon update
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.focus();

  if (showToast) showToast('Transcribed');
}

// ── Live transcription (provider "stream") ──

let _live = null;
let _liveBase = '';          // what was already in the box when the mic opened
let _liveParziale = '';      // the not-yet-final text currently shown

// Invio automatico a fine turno. Il ponte decide da solo quando hai finito di
// parlare (`fine_turno`): era esattamente per questo, ma il testo restava nella
// casella in attesa di un click. Quel click e' il pezzo piu' lento di tutto il
// giro della voce — leggere, spostare il mouse, premere — e vanifica i 900 ms
// che il riconoscitore si e' sudato. Si spegne con
// `localStorage['odysseus.stt.autoinvio'] = '0'`.
const PREF_AUTOINVIO = 'odysseus.stt.autoinvio';

function _autoinvioAcceso() {
  return localStorage.getItem(PREF_AUTOINVIO) !== '0';
}

/** Manda quello che c'e' nella casella, come farebbe il pulsante. */
function _inviaOra() {
  const form = document.getElementById('chat-form');
  if (!form) return;
  if (form.requestSubmit) form.requestSubmit();
  else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
}

/**
 * Paints the box as base + confirmed turns + current partial.
 *
 * Rebuilt from scratch each time rather than appended: the partial keeps being
 * revised as the recogniser hears more ("come mi tru" → "come mi truccavo"),
 * so appending would leave every intermediate guess behind.
 */
function _dipingi(input) {
  const pezzi = [_liveBase, _liveParziale].filter(s => s && s.trim());
  input.value = pezzi.join(' ');
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function startLiveTranscription(showToast, showError) {
  const input = document.getElementById('message');
  if (!input) return;

  _liveBase = input.value.trim();
  _liveParziale = '';

  _live = new AsrStreaming({
    lingua: (window.OdysseusSttLanguage || 'it'),
    onParziale: (testo) => {
      _liveParziale = testo;
      _dipingi(input);
    },
    onTurno: (testo) => {
      // Turn closed by silence. It becomes part of the base, so the next turn
      // is appended after it instead of replacing it.
      _liveBase = [_liveBase, testo].filter(s => s && s.trim()).join(' ');
      _liveParziale = '';
      _dipingi(input);
      input.focus();
      if (_autoinvioAcceso()) {
        const daMandare = _liveBase;
        // La casella riparte vuota: il turno successivo non deve rimandare la
        // frase appena spedita.
        _liveBase = '';
        if (daMandare.trim()) _inviaOra();
      }
    },
    onErrore: (msg) => {
      if (showError) showError('Trascrizione: ' + msg);
      stopLiveTranscription();
    },
  });

  isRecording = true;
  recordingStartTime = new Date();
  _live.avvia().then(() => {
    if (showToast) showToast('Microfono acceso — parla pure');
  });

  // While the assistant speaks, the microphone would pick it up from the
  // speakers and transcribe the assistant's own words. Browser echo
  // cancellation does not cover audio played by the page itself, so the mic is
  // gated on the TTS state instead.
  window.addEventListener('odysseus:tts-start', _mutoOn);
  window.addEventListener('odysseus:tts-end', _mutoOff);
  _segnalaMicrofono('mic-start');
}

function _mutoOn() { _live?.silenzia(true); }
function _mutoOff() { _live?.silenzia(false); }

/**
 * Il microfono in diretta e' aperto o chiuso.
 *
 * Serve a due cose: l'avatar entra nello stato "ascolta" invece di restare
 * immobile, e il turno inviato si dichiara vocale (ragionamento corto). Non e'
 * lo stesso di `tts-start`/`tts-end`, che dicono solo se il microfono e'
 * zittito mentre l'assistente parla.
 */
function _segnalaMicrofono(nome) {
  try { window.dispatchEvent(new CustomEvent('odysseus:' + nome)); } catch (_) {}
}

/** La conversazione a voce e' in corso (microfono in diretta acceso). */
export function conversazioneVocaleAttiva() {
  return !!_live;
}

function stopLiveTranscription() {
  window.removeEventListener('odysseus:tts-start', _mutoOn);
  window.removeEventListener('odysseus:tts-end', _mutoOff);
  if (_live) {
    _live.ferma();
    _live = null;
  }
  _liveBase = '';
  _liveParziale = '';
  _segnalaMicrofono('mic-end');
  _resetRecordingUI();
}

/**
 * Start voice recording
 */
export function startRecording(onFileCreated, showToast, showError) {
  // The live path never touches MediaRecorder: there is no clip to record and
  // no file to upload.
  if (_sttProvider === 'stream') {
    return startLiveTranscription(showToast, showError);
  }

  // Check for secure context (getUserMedia requires HTTPS or localhost)
  if (!window.isSecureContext) {
    if (showError) showError('Microphone requires HTTPS. Use a reverse proxy with SSL or access via localhost.');
    _resetRecordingUI();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (showError) showError('Microphone not supported in this browser.');
    _resetRecordingUI();
    return;
  }

  audioChunks = [];

  // Honour the microphone chosen in Settings; falls back to the system default.
  navigator.mediaDevices.getUserMedia(
    window.OdysseusAudioDevices?.micConstraints() || { audio: true })
    .then(stream => {
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

      mediaRecorder.ondataavailable = event => {
        if (event.data.size > 0) {
          audioChunks.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(track => track.stop());

        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const provider = _sttProvider;

        if (provider === 'browser') {
          const transcript = stopBrowserSTT();
          if (transcript) {
            insertTranscription(transcript, showToast);
          } else {
            if (showToast) showToast('No speech detected');
            const audioFile = new File([audioBlob], `voice-message-${Date.now()}.webm`, { type: 'audio/webm' });
            if (onFileCreated) onFileCreated(audioFile);
          }
        } else if (provider === 'local' || provider.startsWith('endpoint:')) {
          // Show "Transcribing..." feedback
          if (showToast) showToast('Transcribing...', 5000);
          try {
            const transcript = await transcribeOnServer(audioBlob);
            if (transcript) {
              insertTranscription(transcript, showToast);
            } else {
              if (showToast) showToast('No speech detected');
            }
          } catch (e) {
            console.error('STT transcription error:', e);
            if (showError) showError('Transcription failed: ' + e.message);
            // Fallback: attach as file
            const audioFile = new File([audioBlob], `voice-message-${Date.now()}.webm`, { type: 'audio/webm' });
            if (onFileCreated) onFileCreated(audioFile);
          }
        } else {
          // STT disabled — attach audio file
          const audioFile = new File([audioBlob], `voice-message-${Date.now()}.webm`, { type: 'audio/webm' });
          if (onFileCreated) onFileCreated(audioFile);
        }

        _resetRecordingUI();
      };

      mediaRecorder.start();
      isRecording = true;
      recordingStartTime = new Date();

      // Start browser STT if that's the provider
      if (_sttProvider === 'browser') {
        startBrowserSTT();
      }

      if (showToast) {
        showToast('Recording...');
      }
    })
    .catch(error => {
      console.error('Microphone access error:', error);
      if (showError) {
        if (error.name === 'NotAllowedError') {
          showError('Microphone access denied. Check browser permissions.');
        } else if (error.name === 'NotFoundError') {
          showError('No microphone found.');
        } else {
          showError('Microphone error: ' + error.message);
        }
      }
      _resetRecordingUI();
    });
}

/**
 * Stop voice recording
 */
export function stopRecording() {
  if (_live) {
    // Close the turn in flight before tearing down, so a sentence that was
    // still being spoken when the button was pressed is not thrown away.
    _live.concludi();
    setTimeout(stopLiveTranscription, 300);
    return;
  }
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop();
    // isRecording will be set to false in _resetRecordingUI called from onstop
  } else {
    _resetRecordingUI();
  }
}

/**
 * Check if currently recording
 */
export function getIsRecording() {
  return isRecording;
}

/**
 * Initialize recording state
 */
export function init() {
  isRecording = false;
  refreshSttProvider();
}

const voiceRecorderModule = {
  startRecording,
  stopRecording,
  getIsRecording,
  init,
  refreshSttProvider,
  conversazioneVocaleAttiva,
  get _sttProvider() { return _sttProvider; },
  set _sttProvider(v) { _sttProvider = v; },
};

// settings.js e' un modulo a parte e cercava `window.voiceRecorderModule` per
// aggiornare il fornitore appena lo cambi. Nessuno lo pubblicava: cambiare
// fornitore nelle impostazioni non aveva effetto fino al ricaricamento della
// pagina (sceglievi "in diretta" e il microfono continuava a registrare un file).
window.voiceRecorderModule = voiceRecorderModule;

export default voiceRecorderModule;
