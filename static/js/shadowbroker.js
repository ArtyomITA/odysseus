// static/js/shadowbroker.js
//
// Vergilius: ShadowBroker as an Odysseus workspace.
//
// ShadowBroker is a separate Next.js app (localhost:3000) talking to its own
// FastAPI backend (localhost:8000). It is embedded rather than ported: it is
// ~1100 files of React + MapLibre, and rewriting the map layer inside Odysseus
// would buy nothing.
//
// Two things had to be arranged for the frame to work at all:
//   * ShadowBroker's `X-Frame-Options: DENY` / `frame-ancestors 'none'` are now
//     driven by SHADOWBROKER_FRAME_ANCESTORS (frontend/src/proxy.ts).
//   * Odysseus' CSP `frame-src 'self'` had to learn the ShadowBroker origin
//     (core/middleware.py).
//
// The panel covers the chat area only. The avatar dock is position:fixed on
// <body>, so it keeps floating above without any special handling — which is
// the whole point: the map changes, the assistant stays.

const API_BASE = window.location.origin;

let _config = null;      // {url, enabled} from /api/shadowbroker/config
let _frame = null;       // the <iframe>, created once and kept alive
let _open = false;
let _probeTimer = null;

function _els() {
  return {
    panel: document.getElementById('shadowbroker-panel'),
    body: document.getElementById('sb-panel-body'),
    status: document.getElementById('sb-panel-status'),
    closeBtn: document.getElementById('sb-panel-close'),
    externalBtn: document.getElementById('sb-open-external'),
    railBtn: document.getElementById('rail-shadowbroker'),
    toolBtn: document.getElementById('tool-shadowbroker-btn'),
  };
}

async function _loadConfig() {
  if (_config) return _config;
  try {
    const res = await fetch(`${API_BASE}/api/shadowbroker/config`, { credentials: 'same-origin' });
    if (res.ok) _config = await res.json();
  } catch (_) { /* fall through to the default below */ }
  if (!_config || !_config.url) _config = { url: 'http://127.0.0.1:3000', enabled: false };
  return _config;
}

function _setStatus(text, kind) {
  const { status } = _els();
  if (!status) return;
  status.textContent = text;
  status.className = 'sb-panel-status' + (kind ? ' sb-status-' + kind : '');
}

/**
 * Is the dashboard actually up?
 *
 * Cross-origin means we cannot read the iframe's load result, and a `fetch` to
 * localhost:3000 is blocked by Odysseus' own `connect-src 'self'`. So the probe
 * runs server-side, where neither restriction applies.
 */
async function _probe() {
  try {
    const res = await fetch(`${API_BASE}/api/shadowbroker/probe`, { credentials: 'same-origin' });
    if (!res.ok) return null;
    return await res.json();
  } catch (_) {
    return null;
  }
}

function _renderOffline(cfg) {
  const { body } = _els();
  if (!body) return;
  body.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'sb-offline';

  const title = document.createElement('div');
  title.className = 'sb-offline-title';
  title.textContent = 'ShadowBroker non risponde';
  box.appendChild(title);

  const desc = document.createElement('div');
  desc.className = 'sb-offline-desc';
  desc.textContent = `Nessuna risposta da ${cfg.url}. ShadowBroker fa parte dei profili di avvio del sistema:`;
  box.appendChild(desc);

  const pre = document.createElement('pre');
  pre.className = 'sb-offline-cmd';
  // Il sistema si avvia dal batch di regia, che accende anche ShadowBroker nei
  // profili che lo prevedono: niente comandi a mano per backend e frontend.
  pre.textContent =
    'AVVIA-VERGILIUS.bat\n'
    + 'scegli un profilo che comprende ShadowBroker (shadowbroker oppure full)';
  box.appendChild(pre);

  // ▶ lancia i due comandi qui sopra al posto dell'operatore. L'avvio è
  // detached lato server: sopravvive anche a un riavvio di Odysseus.
  const avvia = document.createElement('button');
  avvia.type = 'button';
  avvia.className = 'sb-offline-retry';
  avvia.style.marginRight = '8px';
  avvia.textContent = '▶ Avvia ShadowBroker';
  avvia.addEventListener('click', async () => {
    avvia.disabled = true;
    avvia.textContent = 'avvio in corso…';
    try {
      await fetch(`${API_BASE}/api/shadowbroker/start`, {
        method: 'POST', credentials: 'same-origin',
      });
    } catch (_) { /* si vede dal poll */ }
    // Next dev alla prima compilazione può metterci anche un minuto: si
    // sonda finché risponde, con un tetto per non girare per sempre.
    const inizio = Date.now();
    const timer = setInterval(async () => {
      const h = await _probe();
      if (h && h.frontend) {
        clearInterval(timer);
        _frame = null;
        _mount();
      } else if (Date.now() - inizio > 120000) {
        clearInterval(timer);
        avvia.disabled = false;
        avvia.textContent = '▶ Avvia ShadowBroker';
        _setStatus('avvio fallito: guarda avvio-backend.log / avvio-frontend.log', 'bad');
      } else {
        _setStatus('avvio in corso…');
      }
    }, 3000);
  });
  box.appendChild(avvia);

  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'sb-offline-retry';
  retry.textContent = 'Riprova';
  retry.addEventListener('click', () => { _frame = null; _mount(); });
  box.appendChild(retry);

  body.appendChild(box);
}

async function _mount() {
  const cfg = await _loadConfig();
  const { body } = _els();
  if (!body) return;

  // Already mounted — the iframe survives close/reopen on purpose.
  if (_frame && _frame.isConnected) {
    _setStatus('collegato', 'ok');
    return;
  }

  _setStatus('connessione…');
  body.innerHTML = '';

  const health = await _probe();
  if (!health || !health.frontend) {
    _setStatus('non raggiungibile', 'bad');
    _renderOffline(cfg);
    return;
  }

  const frame = document.createElement('iframe');
  frame.className = 'sb-frame';
  frame.src = cfg.url;
  frame.title = 'ShadowBroker';
  // No `sandbox` attribute: the dashboard needs same-origin storage, workers,
  // and WebGL, and sandboxing it to a null origin breaks MapLibre outright.
  // The trust boundary here is that both apps are ours on loopback.
  frame.setAttribute('allow', 'fullscreen; clipboard-read; clipboard-write');
  frame.addEventListener('load', () => {
    if (!health.backend) {
      // La sonda dice "non ancora": il backend puo' essere solo lento ad
      // alzarsi. Finche' non c'e' una seconda risposta negativa si dice che
      // si sta verificando, non che e' giu'.
      _setStatus('verifico il backend…');
      _probe().then((h2) => {
        if (!_open) return;
        if (h2 && h2.backend) _setStatus('carico la mappa…');
        else _setStatus('mappa attiva, backend giù', 'warn');
      });
      return;
    }
    // `load` scatta quando arriva il documento, ma MapLibre ci mette altri
    // 15-20 secondi a scaricare le tessere e a disegnare i 45 livelli. Senza
    // dirlo, il pannello sembra bloccato su un rettangolo nero.
    _setStatus('carico la mappa…');
    setTimeout(() => {
      if (_open) _setStatus('collegato', 'ok');
    }, 18000);
  });
  body.appendChild(frame);
  _frame = frame;
}

// ── modalità Intelligence ────────────────────────────────────────────────
// Restringe la dotazione del modello ai soli dieci strumenti OSINT. Non è un
// risparmio di token (~1.100 in tutto): impedisce a un 9B di rispondere con
// una ricerca web o con PowerShell alla domanda "cosa succede in Ucraina".
//
// Interruttore esplicito e non solo legato al pannello: si può volere
// l'intelligence senza la mappa davanti, e soprattutto si deve **vedere**
// quando è attiva.

const PREF_MODO = 'odysseus.osint.mode';

export function modoAttivo() {
  // Il pannello aperto la implica; l'interruttore la tiene accesa da sola.
  return _open || localStorage.getItem(PREF_MODO) === '1';
}

// Il selettore del modello vive nella barra di composizione: quando lo spazio
// di lavoro ShadowBroker la copre va nascosto, e riacceso alla chiusura.
// `updateModelPicker` decide da solo cosa mostrare; qui basta risvegliarlo.
function _aggiornaSelettoreModello() {
  try {
    const sm = window.sessionModule;
    if (sm && typeof sm.updateModelPicker === 'function') sm.updateModelPicker();
  } catch (_) {}
}


function _aggiornaPulsante() {
  const b = document.getElementById('overflow-osint-btn');
  if (!b) return;
  const on = modoAttivo();
  b.classList.toggle('active', on);
  b.title = on
    ? 'Modalità Intelligence attiva: solo strumenti OSINT (niente ricerca web, niente shell)'
    : 'Attiva la modalità Intelligence: il modello interroga ShadowBroker invece del web';
}

export function impostaModo(on) {
  try { localStorage.setItem(PREF_MODO, on ? '1' : '0'); } catch (_) {}
  _aggiornaPulsante();
  try {
    if (window.uiModule?.showToast) {
      window.uiModule.showToast(on ? 'Intelligence: solo strumenti OSINT' : 'Intelligence disattivata');
    }
  } catch (_) {}
}

// ── profilo Financial ────────────────────────────────────────────────────
// Sottoinsieme di Intelligence, non un'aggiunta: **sette** strumenti invece di
// tredici. Con i dieci OSINT davanti, alla domanda "come sta la difesa" un 9B
// chiama `osint_militare` — che parla di aerei, non di titoli. Misurato: da
// 6/10 a 10/10 di scelte corrette restringendo il profilo e riscrivendo le
// regole (scripts/prova_modello_finanza.py).
//
// Tiene mappa, notizie e testo perché senza non potrebbe né mostrare né
// incrociare: "questa commessa dove sta" e "che notizie la spiegano" sono
// esattamente le domande per cui esiste.

const PREF_FIN = 'odysseus.financial.mode';

export function financialAttivo() {
  return localStorage.getItem(PREF_FIN) === '1';
}

function _aggiornaPulsanteFin() {
  const b = document.getElementById('overflow-financial-btn');
  if (!b) return;
  const on = financialAttivo();
  b.classList.toggle('active', on);
  b.title = on
    ? 'Profilo Financial attivo: mercati, appalti federali, insider, piu\' mappa e notizie'
    : 'Attiva il profilo Financial: sotto Intelligence, ristretto ai dati economici';
}

/**
 * Accende/spegne il profilo Financial.
 *
 * `daUtente` distingue il passaggio spento→acceso deciso dall'utente (chip o
 * voce di menu) da un allineamento interno: solo il primo apre il popup di
 * configurazione e imposta il preset della mappa. Prima il popup viveva nel
 * gestore del menu "+", quindi il chip in alto lo accendeva in silenzio e
 * all'avvio compariva da solo sopra la chat.
 */
export function impostaFinancial(on, daUtente) {
  const prima = financialAttivo();
  const intelPrima = localStorage.getItem(PREF_MODO) === '1';
  try {
    localStorage.setItem(PREF_FIN, on ? '1' : '0');
    // Financial vive dentro Intelligence: accenderlo da solo lascerebbe il
    // modello senza l'escalation ad agente, e in chat gli strumenti non
    // esistono proprio — risponderebbe inventando invece di leggere i dati.
    if (on) localStorage.setItem(PREF_MODO, '1');
  } catch (_) {}
  _aggiornaPulsante();
  _aggiornaPulsanteFin();
  try {
    if (window.uiModule?.showToast) {
      // L'accoppiamento con Intelligence e' dichiarato, non nascosto: se
      // accendendo Financial si accende anche Intelligence, lo si dice.
      const traino = on && !intelPrima;
      window.uiModule.showToast(
        on ? ('Financial: mercati, appalti, insider' + (traino ? ' (accende anche Intelligence)' : ''))
           : 'Financial disattivato');
    }
  } catch (_) {}
  // Solo il passaggio spento→acceso voluto dall'utente apre il popup e
  // imposta la mappa: mai all'avvio, mai su un riallineamento interno.
  if (daUtente && on && !prima) {
    _presetMappaFinanziario();
    mostraConfigFinancial();
  }
}

export function isOpen() {
  return _open;
}

export async function open() {
  const { panel, railBtn } = _els();
  if (!panel) return;
  _open = true;
  panel.classList.remove('hidden');
  document.body.classList.add('shadowbroker-active');
  if (railBtn) railBtn.classList.add('rail-active');
  _aggiornaPulsante();
  _aggiornaSelettoreModello();
  await _mount();
  // Cheap liveness ticker while the panel is visible; stopped on close so a
  // backgrounded workspace costs nothing.
  if (_probeTimer) clearInterval(_probeTimer);
  // Uno stato incerto non si annuncia come guasto: serve una seconda sonda
  // negativa di fila prima di scrivere "giù".
  let _negativi = 0;
  _probeTimer = setInterval(async () => {
    const h = await _probe();
    const giu = !h || !h.frontend;
    const senzaBackend = !giu && !h.backend;
    if (!giu && !senzaBackend) { _negativi = 0; _setStatus('collegato', 'ok'); return; }
    _negativi += 1;
    if (_negativi < 2) { _setStatus('verifico…'); return; }
    _setStatus(giu ? 'non raggiungibile' : 'mappa attiva, backend giù', giu ? 'bad' : 'warn');
  }, 15000);
}

export function close() {
  const { panel, railBtn } = _els();
  if (!panel) return;
  _open = false;
  panel.classList.add('hidden');
  document.body.classList.remove('shadowbroker-active');
  if (railBtn) railBtn.classList.remove('rail-active');
  _aggiornaPulsante();
  _aggiornaSelettoreModello();
  if (_probeTimer) { clearInterval(_probeTimer); _probeTimer = null; }
  // The iframe stays in the DOM: reloading it would re-warm MapLibre tiles and
  // restart the telemetry poll from zero every single time.
}

export function toggle() {
  return _open ? close() : open();
}

/**
 * Accende sulla mappa i livelli del profilo finanziario.
 *
 * Passa dalla rotta di Odysseus e non dal cruscotto: il browser non ha una
 * connessione diretta a ShadowBroker, e la politica di sicurezza dichiara
 * `connect-src 'self'`. Fallisce in silenzio di proposito — se la mappa non
 * c'è, il profilo deve funzionare lo stesso.
 */
async function _presetMappaFinanziario() {
  try {
    await fetch('/api/shadowbroker/preset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ preset: 'financial' }),
    });
  } catch (_) { /* mappa assente: il profilo resta valido */ }
}

// ── popup di configurazione Financial ────────────────────────────────────
// Compare quando l'UTENTE accende il profilo (chip in alto o voce del menu
// "+"), mai da solo al caricamento: le scelte riguardano il budget di chiamate
// Finnhub condiviso e vanno riviste consapevolmente. Riusa le classi
// .modal/.confirm-btn come styledConfirm(), zero markup in index.html.

// Col backend ShadowBroker spento queste due chiamate restavano appese per
// decine di secondi: il popup compariva 20 s dopo il clic, sopra qualunque
// cosa l'utente stesse facendo. Con un tetto di 2,5 s si apre subito, al
// massimo con i valori predefiniti.
function _fetchBreve(url, ms) {
  const ctrl = new AbortController();
  const t = setTimeout(() => { try { ctrl.abort(); } catch (_) {} }, ms || 2500);
  return fetch(url, { credentials: 'same-origin', signal: ctrl.signal })
    .finally(() => clearTimeout(t));
}

async function _configAttuale() {
  try {
    const r = await _fetchBreve('/api/shadowbroker/financial-config');
    const j = await r.json();
    const c = j && (j.config || j);
    return {
      preset: c && c.preset === 'broad' ? 'broad' : 'core',
      deep_news: !!(c && c.deep_news),
      realtime: !!(c && c.realtime),
    };
  } catch (_) {
    return { preset: 'core', deep_news: false, realtime: false };
  }
}

async function _regoleProfilo() {
  try {
    const r = await _fetchBreve('/api/shadowbroker/rules?profile=financial', 4000);
    const j = await r.json();
    return (j && j.rules) || '';
  } catch (_) { return ''; }
}

export async function mostraConfigFinancial() {
  // Un solo popup alla volta.
  document.getElementById('fin-config-overlay')?.remove();

  const cfg = await _configAttuale();

  const overlay = document.createElement('div');
  overlay.id = 'fin-config-overlay';
  overlay.className = 'modal';

  const riga = (input, titolo, spiega) => (
    `<label style="display:flex;gap:10px;align-items:flex-start;margin:10px 0;cursor:pointer;">
       ${input}
       <span><strong>${titolo}</strong><br>
       <span style="opacity:.75;font-size:.85em;">${spiega}</span></span>
     </label>`);

  overlay.innerHTML =
    // `aria-labelledby` lega la finestra al suo titolo: senza, chi legge con
    // uno screen reader entra in un dialogo senza nome. La trappola del fuoco
    // di ui.js si attiva gia' con `aria-modal="true"`.
    '<div class="modal-content" role="dialog" aria-modal="true" aria-labelledby="fin-config-titolo" style="max-width:480px;">' +
      '<div class="modal-header"><h4 id="fin-config-titolo">Profilo Financial</h4></div>' +
      '<div class="modal-body" style="max-height:60vh;overflow-y:auto;">' +
        '<div style="opacity:.8;font-size:.9em;margin-bottom:6px;">' +
          'Queste scelte pesano sul budget Finnhub (60 chiamate/min, condiviso ' +
          'con lo sweep dei prezzi). Questa finestra si riapre ogni volta che ' +
          'accendi il profilo Financial.</div>' +
        riga(`<input type="radio" name="fin-preset" value="core" ${cfg.preset === 'core' ? 'checked' : ''}>`,
             'Titoli: Core (25)',
             'difesa + big tech + cripto, prezzi aggiornati ogni minuto') +
        riga(`<input type="radio" name="fin-preset" value="broad" ${cfg.preset === 'broad' ? 'checked' : ''}>`,
             'Titoli: Broad (60)',
             'aggiunge banche, energia, industriali, farmaceutici; prezzi ogni 2 minuti') +
        riga(`<input type="checkbox" id="fin-deep" ${cfg.deep_news ? 'checked' : ''}>`,
             'Deep news',
             "notizie su 30 titoli con finestra di 7 giorni invece di 13 titoli su 3: piu' contesto, stesso giro da 10 minuti") +
        riga(`<input type="checkbox" id="fin-rt" ${cfg.realtime ? 'checked' : ''}>`,
             'Sottoinsieme in tempo quasi reale',
             '10 titoli chiave riquotati ogni 30 secondi (monitoraggio serrato, non esecuzione ordini)') +
        '<details style="margin-top:12px;">' +
          '<summary style="cursor:pointer;opacity:.85;">Regole attive del profilo (quelle vere, come le riceve il modello)</summary>' +
          '<pre id="fin-config-rules" style="white-space:pre-wrap;font-size:.78em;opacity:.8;margin-top:8px;max-height:220px;overflow-y:auto;">carico…</pre>' +
        '</details>' +
      '</div>' +
      '<div class="modal-footer">' +
        // data-action="close": e' l'aggancio con cui l'arbitro di Escape in
        // ui.js chiude lo strato piu' in alto. Cosi' Escape equivale ad Annulla
        // senza aggiungere un secondo gestore di tastiera.
        '<button id="fin-config-cancel" data-action="close" class="confirm-btn confirm-btn-secondary">Annulla</button>' +
        '<button id="fin-config-ok" class="confirm-btn confirm-btn-primary">Applica</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(overlay);

  // Le regole arrivano dopo: il popup non deve aspettare la rete.
  _regoleProfilo().then((t) => {
    const pre = document.getElementById('fin-config-rules');
    if (pre) pre.textContent = t || 'regole non disponibili';
  });

  // Trascinabile dalla testata: il popup sta sopra alla chat e deve potersi
  // togliere di mezzo senza chiuderlo.
  const scatola = overlay.querySelector('.modal-content');
  const testata = overlay.querySelector('.modal-header');
  if (scatola && testata) {
    testata.style.cursor = 'grab';
    let sx = 0, sy = 0, px = 0, py = 0, presa = false;
    testata.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      presa = true;
      sx = e.clientX; sy = e.clientY;
      const r = scatola.getBoundingClientRect();
      px = r.left; py = r.top;
      scatola.style.position = 'fixed';
      scatola.style.margin = '0';
      scatola.style.left = px + 'px';
      scatola.style.top = py + 'px';
      testata.style.cursor = 'grabbing';
      try { testata.setPointerCapture(e.pointerId); } catch (_) {}
    });
    testata.addEventListener('pointermove', (e) => {
      if (!presa) return;
      scatola.style.left = (px + e.clientX - sx) + 'px';
      scatola.style.top = Math.max(0, py + e.clientY - sy) + 'px';
    });
    const molla = () => { presa = false; testata.style.cursor = 'grab'; };
    testata.addEventListener('pointerup', molla);
    testata.addEventListener('pointercancel', molla);
  }

  // `.modal` nasce con pointer-events:none (il velo non deve rubare clic):
  // qui pero' il velo SERVE, perche' il clic fuori equivale ad Annulla. Lo
  // riattiva solo questo popup, e solo finche' e' aperto.
  overlay.style.pointerEvents = 'auto';

  const chiamante = document.activeElement;
  const chiudi = () => {
    overlay.remove();
    // Il fuoco torna a chi ha aperto il popup.
    try { if (chiamante && chiamante.isConnected) chiamante.focus(); } catch (_) {}
  };
  overlay.addEventListener('click', (e) => { if (e.target === overlay) chiudi(); });
  // Il fuoco entra nel popup: senza, Tab continuava a girare nella pagina
  // dietro al velo.
  setTimeout(() => {
    try { document.getElementById('fin-config-ok')?.focus(); } catch (_) {}
  }, 30);
  document.getElementById('fin-config-cancel')?.addEventListener('click', chiudi);
  document.getElementById('fin-config-ok')?.addEventListener('click', async () => {
    const preset = overlay.querySelector('input[name="fin-preset"]:checked')?.value || 'core';
    const corpo = {
      preset,
      deep_news: !!document.getElementById('fin-deep')?.checked,
      realtime: !!document.getElementById('fin-rt')?.checked,
    };
    chiudi();
    try {
      const r = await fetch('/api/shadowbroker/financial-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(corpo),
      });
      const j = await r.json().catch(() => null);
      const ok = r.ok && !(j && j.ok === false);
      window.uiModule?.showToast?.(ok
        ? `Financial: ${preset === 'broad' ? '60 titoli' : '25 titoli'}`
          + (corpo.deep_news ? ' + deep news' : '')
          + (corpo.realtime ? ' + realtime' : '')
        : 'Config non salvata: backend ShadowBroker giù?');
    } catch (_) {
      window.uiModule?.showToast?.('Config non salvata: backend ShadowBroker giù?');
    }
  });
}

// ── la mappa che si apre da sola ─────────────────────────────────────────
// Il segnale NON e' il testo dell'utente: "passo da Odessa in aereo" non e'
// una richiesta di mappa, e un riconoscitore di frasi geografiche sbaglia in
// entrambi i versi. Il segnale e' il fatto compiuto: il modello ha appena
// mosso o segnato la vista con `osint_mappa`. Allora il pannello si apre una
// volta sola nel turno, cosi' l'utente VEDE cio' che e' appena successo.
//
// Solo eventi vivi del turno (`vergilius:strumento-esito`, emesso da
// chat.js): rileggendo una conversazione vecchia non si apre niente.

const PREF_AUTO = 'odysseus.osint.automappa';

// Azioni che muovono o segnano la vista. Fuori restano `note` (che elenca e
// basta), `ripristina` e `cancella_nota`: non c'e' niente di nuovo da vedere.
const _AZIONI_VISTA = new Set([
  'centra', 'focus', 'vola', 'evidenzia', 'highlight',
  'livelli', 'layers', 'mostra_solo', 'preset', 'profilo', 'nota', 'annota',
]);

let _apertaInQuestoTurno = false;

export function automappaAttiva() {
  // Predefinita ACCESA: vale finche' non la si spegne esplicitamente.
  return localStorage.getItem(PREF_AUTO) !== '0';
}

function _aggiornaPulsanteAuto() {
  const b = document.getElementById('overflow-automappa-btn');
  if (!b) return;
  const on = automappaAttiva();
  b.classList.toggle('active', on);
  b.title = on
    ? 'La mappa si apre da sola quando il modello la usa davvero'
    : 'La mappa non si apre da sola: la apri tu dalla barra';
}

export function impostaAutomappa(on) {
  try { localStorage.setItem(PREF_AUTO, on ? '1' : '0'); } catch (_) {}
  _aggiornaPulsanteAuto();
  try {
    window.uiModule?.showToast?.(on
      ? 'La mappa si aprirà da sola quando il modello la usa'
      : 'La mappa non si aprirà più da sola');
  } catch (_) {}
}

function _profiloSenzaShadowBroker() {
  // profilo.js marca cosi' i comandi che il profilo di avvio non prevede.
  const b = document.getElementById('rail-shadowbroker');
  return !b || !!b.getAttribute('data-profilo-nascosto');
}

function _luogoDa(dati, argomenti) {
  const v = dati && dati.luogo_verificato;
  if (typeof v === 'string' && v.trim()) return v.split(',')[0].trim();
  for (const k of ['luogo', 'nome', 'preset', 'testo']) {
    const x = argomenti && argomenti[k];
    if (typeof x === 'string' && x.trim()) return x.trim();
  }
  if (dati && dati.azione === 'evidenzia') return `${dati.quanti || 0} punti`;
  if (dati && dati.azione) return String(dati.azione);
  return 'vista aggiornata';
}

// La ripetizione alla cieca del centramento non vive piu' qui.
//
// C'era: l'iframe appena nato chiedeva le azioni con `after=-1` e riceveva
// **solo** il cursore corrente, quindi il `map_focus` partito mentre l'iframe
// non esisteva era perso; si rimandava lo stesso comando 25 s dopo il `load`
// sperando che intanto la mappa fosse pronta. Erano 25 s di attesa per una
// cosa che l'utente vedeva comunque, e valeva solo per `centra`.
//
// Ora il recupero lo fa la vista stessa, dove il problema e' nato:
//  - `shadowbroker/backend/routers/ai_intel.py`, `wait_agent_actions`:
//    con `replay_recent=<secondi>` una vista appena nata riceve i comandi di
//    vista recenti (l'ultimo per tipo: `fly_to`, `set_layers`, `highlight`);
//  - `shadowbroker/frontend/src/hooks/useAgentActions.ts`: la prima chiamata
//    chiede quei 90 s;
//  - `shadowbroker/frontend/src/components/MaplibreViewer.tsx`: l'effetto del
//    volo dipende anche da `mapReady`, quindi un comando arrivato prima che
//    la mappa esistesse viene eseguito appena esiste.
//
// Vale quindi per TUTTI i comandi di vista, non solo per `centra`.
// `POST /api/shadowbroker/focus` resta come comando manuale di riparazione,
// ma nessuno lo chiama piu' da solo.

async function _daStrumento(ev) {
  const d = (ev && ev.detail) || {};
  if (String(d.tool || '') !== 'osint_mappa') return;
  // Solo le chiamate RIUSCITE: un errore non ha mosso niente da mostrare.
  if (d.codice != null && d.codice !== 0) return;
  let dati = null;
  try { dati = JSON.parse(String(d.esito || '')); } catch (_) { return; }
  if (!dati || typeof dati !== 'object') return;
  if (!_AZIONI_VISTA.has(String(dati.azione || '').toLowerCase())) return;
  if (!automappaAttiva()) return;
  if (_apertaInQuestoTurno) return;
  if (_open) {
    // Gia' aperto: la vista si sposta da sola, non si riapre niente. Il
    // permesso del turno si consuma lo stesso, cosi' chiudendolo a mano a
    // meta' turno non riparte da capo alla chiamata successiva.
    _apertaInQuestoTurno = true;
    return;
  }
  if (_profiloSenzaShadowBroker()) return;
  // Cruscotto spento: non si apre niente e non si fa rumore.
  const salute = await _probe();
  if (!salute || !salute.frontend) return;
  // Il pannello copre l'area della chat, barra di composizione compresa: se
  // l'utente sta scrivendo gli si toglierebbe il testo da sotto le dita.
  const att = document.activeElement;
  if (att && att.id === 'message' && String(att.value || '').trim()) return;

  _apertaInQuestoTurno = true;
  await open();

  let argomenti = null;
  try { argomenti = JSON.parse(String(d.argomenti || '')); } catch (_) {}
  try {
    window.uiModule?.showToast?.(`Mappa aperta: ${_luogoDa(dati, argomenti)}`, {
      duration: 7000, action: 'Chiudi', onAction: () => close(),
    });
  } catch (_) {}
}

export function init() {
  const { railBtn, toolBtn, closeBtn, externalBtn } = _els();
  const modoBtn = document.getElementById('overflow-osint-btn');
  if (modoBtn) {
    modoBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      // Col pannello aperto la modalità è già implicita: spegnerla lì
      // confonderebbe. Si chiude il pannello, e la modalità segue.
      if (_open) { close(); impostaModo(false); return; }
      impostaModo(localStorage.getItem(PREF_MODO) !== '1');
    });
    _aggiornaPulsante();
  }
  const finBtn = document.getElementById('overflow-financial-btn');
  if (finBtn) {
    finBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      // Accendendolo si imposta anche la mappa sul preset finanziario e si
      // apre il popup: lo fa impostaFinancial, cosi' chip e voce di menu si
      // comportano allo stesso modo.
      impostaFinancial(!financialAttivo(), true);
    });
    _aggiornaPulsanteFin();
  }
  // Interruttore "Apri la mappa da sola": vive accanto a Intelligence e
  // Financial nel menu "+", perché è della stessa famiglia.
  const autoBtn = document.getElementById('overflow-automappa-btn');
  if (autoBtn) {
    autoBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      impostaAutomappa(!automappaAttiva());
    });
  }
  _aggiornaPulsanteAuto();
  window.addEventListener('vergilius:strumento-esito', _daStrumento);
  // Inizio di un turno nuovo: torna buono il permesso di aprirsi una volta.
  window.addEventListener('odysseus:chat-busy-change', (e) => {
    if (e && e.detail && e.detail.active) _apertaInQuestoTurno = false;
  });
  // Nessun popup all'avvio: compariva da solo anche sopra una risposta in
  // corso e, essendo un velo a tutto schermo, si prendeva il primo clic
  // destinato ad altro (il pannello ShadowBroker ci finiva sotto).
  if (railBtn) railBtn.addEventListener('click', toggle);
  if (toolBtn) toolBtn.addEventListener('click', () => {
    open();
    // Match the other tool-list entries, which collapse the panel on pick.
    try { document.getElementById('tools-panel')?.classList.add('hidden'); } catch (_) {}
  });
  if (closeBtn) closeBtn.addEventListener('click', close);
  if (externalBtn) externalBtn.addEventListener('click', async () => {
    const cfg = await _loadConfig();
    window.open(cfg.url, 'shadowbroker', 'width=1600,height=950');
  });
  // Escape chiude il pannello solo se e' davvero lo strato piu' in alto:
  //  - il fuoco e' dentro l'iframe → il tasto appartiene a ShadowBroker, e
  //    chiudere tutto il pannello per un suo popup e' una perdita di lavoro;
  //  - c'e' una modale aperta sopra → la chiude il suo gestore (ui.js), qui
  //    non si fa niente.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !_open || e.defaultPrevented) return;
    const att = document.activeElement;
    if (att && att.tagName === 'IFRAME') return;
    const modaleSopra = [...document.querySelectorAll('body > .modal')].some(
      (m) => !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none');
    if (modaleSopra) return;
    close();
  });

  // ⏻ nella barra utente: spegne TUTTO lo stack (llama, voce, ShadowBroker,
  // ChromaDB e Odysseus stesso). Vive qui perché questo è il modulo-colla di
  // Vergilius, e la rotta sta accanto alle altre in shadowbroker_routes.py.
  const spegniBtn = document.getElementById('user-bar-spegni');
  if (spegniBtn) {
    spegniBtn.addEventListener('click', async () => {
      const conferma = window.styledConfirm
        ? await window.styledConfirm(
            'Spegne tutti i servizi di Vergilius: modello, voce, ShadowBroker, '
            + 'memoria e questa stessa pagina. Per riaccendere: scripts\\avvia-tutto.ps1.',
            { title: 'Spegnere Vergilius?', confirmText: 'Spegni', cancelText: 'Annulla', danger: true })
        : window.confirm('Spegnere tutti i servizi di Vergilius?');
      if (!conferma) return;
      spegniBtn.disabled = true;
      let esito = null;
      try {
        const r = await fetch(`${API_BASE}/api/vergilius/spegni`, {
          method: 'POST', credentials: 'same-origin',
        });
        esito = await r.json();
      } catch (_) { /* se muore prima di rispondere, e' comunque spento */ }
      if (esito && esito.ok === false) {
        spegniBtn.disabled = false;
        if (window.showToast) window.showToast(`Spegnimento fallito: ${esito.detail || '?'}`);
        return;
      }
      // Da qui in poi il server non esiste piu': si copre la pagina, senza
      // dipendere da niente che debba ancora rispondere.
      const velo = document.createElement('div');
      velo.style.cssText = 'position:fixed;inset:0;z-index:99999;display:flex;'
        + 'flex-direction:column;align-items:center;justify-content:center;gap:12px;'
        + 'background:#0b0f14;color:#9fb8b8;font-family:monospace;font-size:15px;';
      velo.innerHTML = '<div style="font-size:34px">⏻</div>'
        + '<div>Vergilius spento.</div>'
        + '<div style="opacity:.6">Per riaccendere: scripts\\avvia-tutto.ps1</div>';
      document.body.appendChild(velo);
    });
  }
}

const shadowbrokerModule = {
  init, open, close, toggle, isOpen,
  modoAttivo, impostaModo,
  financialAttivo, impostaFinancial, mostraConfigFinancial,
  automappaAttiva, impostaAutomappa,
};
try { window.OdysseusShadowBroker = shadowbrokerModule; } catch (_) {}
export default shadowbrokerModule;
