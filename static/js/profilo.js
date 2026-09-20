/* Profilo di avvio → cosa compare, e la BARRA MODALITA' in alto.
 *
 * Il boot (porta 7001) avvia Odysseus con ODYSSEUS_STARTUP_PROFILE; Odysseus
 * lo espone in /api/startup-profile-status (pubblico). Qui:
 *   1) si nascondono i toggle che il profilo non permette
 *        vergilius-chat → niente Intelligence/Financial/Voce (ShadowBroker non c'e')
 *        vergilius-lite → niente Voce
 *   2) si monta in alto, nella chat-top-bar, una barra di chip cliccabili con
 *      le modalita' disponibili (Intelligence · Financial · Computer · Browser):
 *      stato a colpo d'occhio e cambio con un click. I chip riusano le funzioni
 *      gia' esistenti (OdysseusShadowBroker.impostaModo/impostaFinancial,
 *      OdysseusVista) — nessuna logica duplicata. Il menu "More" (Rename,
 *      Compact, PDF…) resta dov'era, non e' lui la modalita'.
 * Un toggle nascosto viene anche spento in localStorage, altrimenti la chat
 * manderebbe osint_mode=true a un ShadowBroker che non esiste.
 * Si auto-inietta: una riga in index.html.
 */
(function () {
  "use strict";
  if (window.__profiloCaricato) return;
  window.__profiloCaricato = true;
  var API = (window.API_BASE || '');

  var NASCONDI = {
    'vergilius-chat': ['overflow-osint-btn', 'overflow-financial-btn', 'overflow-automappa-btn', 'rail-shadowbroker', 'tool-shadowbroker-btn', 'overflow-tts-btn'],
    'vergilius-lite': ['overflow-tts-btn'],
    'full': [],
    'shadowbroker': [],
  };
  var SPEGNI_PREF = {
    'overflow-osint-btn': 'odysseus.osint.mode',
    'overflow-financial-btn': 'odysseus.financial.mode',
  };

  // ── barra modalita' ────────────────────────────────────────────────────
  var CSS = '\
  #modo-bar{display:inline-flex;align-items:center;gap:6px;margin-right:14px;vertical-align:middle}\
  #modo-bar .mchip{display:inline-flex;align-items:center;gap:6px;cursor:pointer;user-select:none;\
    font:600 11px/1 var(--font-family,inherit);letter-spacing:.02em;padding:5px 10px;border-radius:14px;\
    color:color-mix(in srgb,var(--fg) 70%,transparent);background:transparent;\
    border:1px solid color-mix(in srgb,var(--border,#355a66) 80%,transparent);transition:all .15s}\
  #modo-bar .mchip:hover{border-color:var(--brand-color,var(--red,#c678dd));color:var(--fg)}\
  #modo-bar .mchip[aria-pressed="true"]{color:var(--bg,#0b0f14);border-color:var(--brand-color,var(--red,#c678dd));\
    background:var(--brand-color,var(--red,#c678dd));box-shadow:0 0 0 1px var(--brand-color,var(--red,#c678dd))}\
  #modo-bar .mchip[aria-pressed="true"]:hover{color:var(--bg,#0b0f14)}\
  #modo-bar .mchip[aria-pressed="false"]{border-style:dashed}\
  #modo-bar .mchip .dot{width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.3}\
  #modo-bar .mchip[aria-pressed="true"] .dot{opacity:1;box-shadow:0 0 6px currentColor}\
  #modo-bar .mchip:focus-visible{outline:2px solid var(--brand-color,var(--red,#c678dd));outline-offset:2px}\
  #modo-bar .mchip.hid{display:none}\
  #modo-bar .msep{width:1px;height:14px;background:color-mix(in srgb,var(--border,#355a66) 70%,transparent);margin:0 2px}\
  #modo-bar .mmod{font:600 11px/1 var(--font-family,inherit);color:color-mix(in srgb,var(--fg) 55%,transparent);padding:0 4px}';

  var CHIP = [
    { id: 'intelligence', label: 'Intelligence', needs: 'overflow-osint-btn',
      on: function () { return !!(window.OdysseusShadowBroker && window.OdysseusShadowBroker.modoAttivo()); },
      toggle: function () { var sb = window.OdysseusShadowBroker; if (sb) sb.impostaModo(!sb.modoAttivo()); } },
    { id: 'financial', label: 'Financial', needs: 'overflow-financial-btn',
      on: function () { return !!(window.OdysseusShadowBroker && window.OdysseusShadowBroker.financialAttivo()); },
      toggle: function () { var sb = window.OdysseusShadowBroker; if (sb) sb.impostaFinancial(!sb.financialAttivo(), true); } },
    { id: 'computer', label: 'Computer', needs: 'overflow-computer-btn', vista: true,
      on: function () { return !!(window.OdysseusVista && window.OdysseusVista.computer()); },
      toggle: function () { var b = document.getElementById('overflow-computer-btn'); if (b) b.click(); } },
    { id: 'browser', label: 'Browser', needs: 'overflow-browser-btn', vista: true,
      on: function () { return !!(window.OdysseusVista && window.OdysseusVista.browser()); },
      toggle: function () { var b = document.getElementById('overflow-browser-btn'); if (b) b.click(); } },
  ];

  function _nascosto(id) {
    var el = document.getElementById(id);
    return !el || el.getAttribute('data-profilo-nascosto');
  }

  // Modalita' "in primo piano": la piu' specifica fra quelle accese. Serve al
  // filo colorato in testa alla chat e al bordo del composer (blocco
  // "identita Vergilius" in coda a style.css): un colore solo, mai cinque.
  var ORDINE_MODO = { intelligence: 'intelligence', financial: 'financial',
                      computer: 'controllo', browser: 'controllo' };

  function aggiornaBarra() {
    var bar = document.getElementById('modo-bar'); if (!bar) return;
    var vista = !!(window.OdysseusVista && window.OdysseusVista.attiva());
    var inPrimoPiano = '';
    CHIP.forEach(function (c) {
      var el = bar.querySelector('[data-modo="' + c.id + '"]'); if (!el) return;
      var nascosto = _nascosto(c.needs) || (c.vista && !vista);
      var acceso = !nascosto && c.on();
      el.classList.toggle('hid', !!nascosto);
      el.classList.toggle('on', acceso);
      // Lo stato non si legge piu' solo dall'opacita': riempimento pieno se
      // acceso, bordo tratteggiato se spento, e aria-pressed per chi legge
      // con la tastiera o con uno screen reader.
      // Si scrive SOLO se il valore cambia: questa funzione gira anche a
      // riposo ogni 1,5 s e riscriveva gli attributi ogni giro (rumore per
      // chi osserva il DOM, e un clic poteva restare sotto una risincronia).
      var premuto = acceso ? 'true' : 'false';
      if (el.getAttribute('aria-pressed') !== premuto) el.setAttribute('aria-pressed', premuto);
      var titolo = (acceso ? 'Acceso' : 'Spento') + ', ' + c.label + ': clic per cambiare';
      if (el.title !== titolo) el.title = titolo;
      if (acceso && !inPrimoPiano) inPrimoPiano = ORDINE_MODO[c.id] || '';
    });
    // Vista non ha un chip suo (e' un interruttore del modello): se nessuna
    // modalita' e' accesa ma gli occhi ci sono, il filo lo dice lo stesso.
    if (!inPrimoPiano && vista) inPrimoPiano = 'vista';
    try {
      var de = document.documentElement;
      if (inPrimoPiano) {
        if (de.getAttribute('data-modo-attivo') !== inPrimoPiano) de.setAttribute('data-modo-attivo', inPrimoPiano);
      } else if (de.hasAttribute('data-modo-attivo')) {
        de.removeAttribute('data-modo-attivo');
      }
    } catch (_) {}
    var mod = bar.querySelector('.mmod');
    if (mod) {
      var l = document.getElementById('model-picker-label');
      var nome = (l && (l.title || l.textContent) || '').trim().split('/').pop();
      var etichetta = nome ? nome + (vista ? ' 👁' : '') : '';
      if (mod.textContent !== etichetta) mod.textContent = etichetta;
    }
  }

  function montaBarra() {
    if (document.getElementById('modo-bar')) return;
    var meta = document.querySelector('.chat-meta-overlay'); if (!meta) return;
    var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
    var bar = document.createElement('span'); bar.id = 'modo-bar';
    CHIP.forEach(function (c) {
      var ch = document.createElement('span'); ch.className = 'mchip hid'; ch.setAttribute('data-modo', c.id);
      ch.setAttribute('role', 'button');
      ch.setAttribute('tabindex', '0');
      ch.setAttribute('aria-pressed', 'false');
      ch.innerHTML = '<span class="dot"></span><span></span>';
      ch.querySelector('span:last-child').textContent = c.label;
      ch.title = 'Attiva/disattiva ' + c.label;
      // Ogni clic conta: si aggiorna subito dallo stato reale, senza
      // aspettare il giro dell'intervallo (i clic ravvicinati si perdevano).
      var premi = function (e) {
        e.preventDefault(); e.stopPropagation();
        c.toggle();
        aggiornaBarra();
        setTimeout(aggiornaBarra, 0);
      };
      ch.addEventListener('click', premi);
      ch.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') premi(e);
      });
      bar.appendChild(ch);
    });
    var sep = document.createElement('span'); sep.className = 'msep'; bar.appendChild(sep);
    var mod = document.createElement('span'); mod.className = 'mmod'; bar.appendChild(mod);
    meta.insertBefore(bar, meta.firstChild);
    aggiornaBarra();
    document.addEventListener('overflow-state-change', aggiornaBarra);
    document.addEventListener('odysseus:model-picked', function () { setTimeout(aggiornaBarra, 0); });
    document.addEventListener('odysseus:model-caps', aggiornaBarra);
    var l = document.getElementById('model-picker-label');
    if (l && window.MutationObserver) new MutationObserver(aggiornaBarra).observe(l, { attributes: true, childList: true, characterData: true, subtree: true });
    // localStorage cambiato da un'altra scheda o dal menu "+"
    window.addEventListener('storage', aggiornaBarra);
    setInterval(aggiornaBarra, 1500);
  }

  // ── selettore di PROFILO in alto (ShadowBroker / Chat / Lite / Full) ───
  var PROFILI = [
    { id: 'shadowbroker',   nome: 'ShadowBroker',   desc: 'solo intelligence, niente modello' },
    { id: 'vergilius-chat', nome: 'Vergilius Chat', desc: 'chat completa, senza ShadowBroker' },
    { id: 'vergilius-lite', nome: 'Vergilius Lite', desc: 'chat + ShadowBroker' },
    { id: 'full',           nome: 'Full',           desc: 'tutto: voce e Avatar 2D' },
  ];
  var CSS_P = '\
  #prof-wrap{position:relative;display:inline-block;margin-right:10px;vertical-align:middle}\
  #prof-btn{display:inline-flex;align-items:center;gap:7px;cursor:pointer;user-select:none;\
    font:600 12px/1 var(--font-family,inherit);letter-spacing:.02em;padding:6px 12px;border-radius:16px;\
    color:var(--brand-color,var(--red,#c678dd));background:color-mix(in srgb,var(--brand-color,var(--red,#c678dd)) 10%,transparent);\
    border:1px solid var(--brand-color,var(--red,#c678dd))}\
  #prof-btn:hover{background:color-mix(in srgb,var(--brand-color,var(--red,#c678dd)) 18%,transparent)}\
  #prof-btn .car{font-size:10px;opacity:.8}\
  #prof-menu{position:absolute;left:0;top:calc(100% + 6px);z-index:9600;min-width:260px;display:none;\
    background:var(--panel,#111);border:1px solid var(--brand-color,var(--red,#c678dd));border-radius:10px;\
    box-shadow:0 12px 34px rgba(0,0,0,.55);padding:6px;font:var(--font-family,inherit)}\
  #prof-menu.on{display:block}\
  #prof-menu .pi{display:flex;flex-direction:column;gap:2px;padding:9px 11px;border-radius:7px;cursor:pointer;color:var(--fg)}\
  #prof-menu .pi:hover{background:color-mix(in srgb,var(--brand-color,var(--red,#c678dd)) 12%,transparent)}\
  #prof-menu .pi.cur{color:var(--brand-color,var(--red,#c678dd))}\
  #prof-menu .pi .pn{font-weight:600;font-size:12px}\
  #prof-menu .pi .pd{font-size:10.5px;opacity:.65}\
  #prof-menu .pi.cur .pn::after{content:"  ● attivo";font-weight:400;font-size:10px;opacity:.8}\
  #prof-menu .pnote{padding:8px 11px 4px;font-size:10px;opacity:.55;border-top:1px solid color-mix(in srgb,var(--border,#355a66) 70%,transparent);margin-top:4px}';

  function montaProfilo() {
    if (document.getElementById('prof-wrap')) return;
    var meta = document.querySelector('.chat-meta-overlay'); if (!meta) return;
    var st = document.createElement('style'); st.textContent = CSS_P; document.head.appendChild(st);
    var wrap = document.createElement('span'); wrap.id = 'prof-wrap';
    var btn = document.createElement('span'); btn.id = 'prof-btn'; btn.title = 'Cambia profilo di avvio';
    btn.innerHTML = '<span class="pnome">Vergilius</span><span class="car">▾</span>';
    var menu = document.createElement('div'); menu.id = 'prof-menu';
    PROFILI.forEach(function (p) {
      var it = document.createElement('div'); it.className = 'pi'; it.setAttribute('data-prof', p.id);
      it.innerHTML = '<span class="pn"></span><span class="pd"></span>';
      it.querySelector('.pn').textContent = p.nome; it.querySelector('.pd').textContent = p.desc;
      it.addEventListener('click', function (e) { e.stopPropagation(); cambiaProfilo(p.id); });
      menu.appendChild(it);
    });
    var note = document.createElement('div'); note.className = 'pnote';
    note.textContent = 'Il cambio spegne/avvia i servizi e riavvia la shell: il loader ti riporta qui.';
    menu.appendChild(note);
    wrap.appendChild(btn); wrap.appendChild(menu);
    meta.insertBefore(wrap, meta.firstChild);
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var apri = !menu.classList.contains('on');
      menu.classList.toggle('on', apri);
      btn.setAttribute('aria-expanded', apri ? 'true' : 'false');
    });
    document.addEventListener('click', function () {
      menu.classList.remove('on');
      btn.setAttribute('aria-expanded', 'false');
    });
    // Escape chiude PRIMA il menu a tendina: e' lo strato piu' in alto.
    // In cattura e con stopImmediatePropagation, cosi' non arriva anche
    // all'arbitro che chiuderebbe una finestra sotto.
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || !menu.classList.contains('on')) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      menu.classList.remove('on');
      btn.setAttribute('aria-expanded', 'false');
      try { btn.focus(); } catch (_) {}
    }, true);
    btn.setAttribute('role', 'button');
    btn.setAttribute('tabindex', '0');
    btn.setAttribute('aria-expanded', 'false');
  }

  function aggiornaProfilo(profilo) {
    var p = PROFILI.filter(function (x) { return x.id === profilo; })[0];
    var btn = document.querySelector('#prof-btn .pnome'); if (btn) btn.textContent = p ? p.nome : 'Vergilius';
    var items = document.querySelectorAll('#prof-menu .pi');
    Array.prototype.forEach.call(items, function (it) { it.classList.toggle('cur', it.getAttribute('data-prof') === profilo); });
  }

  function cambiaProfilo(nuovo) {
    if (nuovo === window.__profiloAvvio) return;
    var menu = document.getElementById('prof-menu'); if (menu) menu.classList.remove('on');
    fetch(API + '/api/boot/profile', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile: nuovo }) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || r.status); return j; }); })
      .then(function () {
        // il boot riavvia Odysseus: la pagina del boot mostra il loader e poi
        // riporta alla destinazione (questa shell, o ShadowBroker).
        window.location.href = 'http://127.0.0.1:7001/';
      })
      .catch(function (e) {
        try { window.uiModule && window.uiModule.showToast && window.uiModule.showToast('Cambio profilo non riuscito: ' + e.message); } catch (_) {}
      });
  }

  // ── profilo ────────────────────────────────────────────────────────────
  function applica(profilo) {
    aggiornaProfilo(profilo);
    var lista = NASCONDI[profilo] || [];
    lista.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) { el.style.display = 'none'; el.setAttribute('data-profilo-nascosto', profilo); }
      var pref = SPEGNI_PREF[id];
      if (pref) { try { localStorage.setItem(pref, '0'); } catch (_) {} }
    });
    try { document.documentElement.setAttribute('data-profilo', profilo); } catch (_) {}
    window.__profiloAvvio = profilo;
    try { document.dispatchEvent(new CustomEvent('overflow-state-change')); } catch (_) {}
    aggiornaBarra();
  }

  function carica() {
    montaProfilo();
    montaBarra();
    fetch(API + '/api/startup-profile-status', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s && s.profile) applica(String(s.profile)); })
      .catch(function () {});
  }

  window.OdysseusProfilo = { get: function () { return window.__profiloAvvio || ''; }, applica: applica, aggiorna: aggiornaBarra };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', carica);
  else carica();
})();
