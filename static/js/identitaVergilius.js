/* Identita' Vergilius — il segno di famiglia degli strumenti e le tessere del
 * benvenuto. Piano di design: D:\vergilius-lab\design\01-identita-vergilius.md
 *
 * Tre cose, tutte piccole:
 *   1) ogni scheda di strumento nella chat (.agent-thread-node) riceve
 *      data-fam="intelligence|financial|vista|browser|pc" e un'icona in linea:
 *      il colore e il segno li mette il CSS (blocco "identita Vergilius" in
 *      coda a style.css). Qui si guarda solo il NOME dello strumento.
 *   2) il benvenuto mostra sei tessere, una per famiglia, con un esempio che
 *      RIEMPIE il campo di scrittura (non invia mai).
 *   3) una capacita' che il profilo di avvio corrente non offre appare spenta,
 *      col perche'. Lo stato vero viene da /api/startup-profile-status.
 *
 * Niente animazioni infinite, niente sfocature, nessun timer a riposo:
 * l'osservatore si sveglia solo quando la chat cambia.
 * Si auto-inietta: una riga in index.html.
 */
(function () {
  "use strict";
  if (window.__identitaVergilius) return;
  window.__identitaVergilius = true;

  // ── icone: stesso tratto (2), stessa griglia (24), nessuna emoji ─────────
  var I = {
    intelligence: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17M3.5 12h17"/><path d="M12 3.5c3 3 3 14 0 17c-3-3-3-14 0-17z"/>',
    financial:    '<path d="M3.5 18.5h17"/><path d="M6 15V9M11 15V5M16 15v-7M21 15v-4"/>',
    vista:        '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.6"/>',
    browser:      '<rect x="3" y="4.5" width="18" height="15" rx="1.5"/><path d="M3 9h18"/><path d="M6 6.7h.01M8.6 6.7h.01"/>',
    pc:           '<rect x="3" y="4.5" width="18" height="11.5" rx="1.5"/><path d="M8 20h8M12 16v4"/>',
    voce:         '<rect x="9" y="3" width="6" height="10" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>',
    neutro:       '<path d="M4 6.5h16M4 12h16M4 17.5h10"/>',
  };
  function svg(fam) {
    return '<svg class="segno-fam" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (I[fam] || I.neutro) + '</svg>';
  }

  // ── nome dello strumento -> famiglia ────────────────────────────────────
  function famiglia(nome) {
    var n = String(nome || '').trim();
    if (!n) return 'neutro';
    if (/^osint_/i.test(n)) return 'intelligence';
    if (/^fin_/i.test(n) || /^calcola$/i.test(n) || /^financial_rag$/i.test(n)) return 'financial';
    if (/^vista_/i.test(n)) return 'vista';
    if (/^browser_/i.test(n)) return 'browser';
    // Windows-MCP arriva con nomi tipo "Click-Tool", "Powershell-Tool".
    if (/-Tool$/.test(n) || /^(bash|python|powershell|ui_control)$/i.test(n)) return 'pc';
    return 'neutro';
  }

  // ── 1) segno di famiglia sulle schede di strumento ──────────────────────
  // Il segno si rimette ogni volta che manca: mentre lo strumento gira la
  // chat riscrive l'innerHTML della scheda (chat.js) e il nome provvisorio
  // ("Writing") diventa quello vero. Il guardiano e' l'icona, non data-fam.
  function segnaNodo(nodo) {
    var t = nodo && nodo.querySelector('.agent-thread-tool');
    if (!t || t.querySelector('.segno-fam')) return;
    var fam = famiglia(t.textContent);
    nodo.dataset.fam = fam;
    t.insertAdjacentHTML('afterbegin', svg(fam));
  }
  function segnaTutto(radice) {
    var nodi = (radice || document).querySelectorAll('.agent-thread-node');
    for (var i = 0; i < nodi.length; i++) segnaNodo(nodi[i]);
  }
  function osservaChat() {
    var box = document.getElementById('chat-history');
    if (!box || !window.MutationObserver) return;
    segnaTutto(box);
    // Si sveglia solo quando la chat cambia davvero; il lavoro e' un
    // querySelectorAll sui nodi non ancora marcati.
    new MutationObserver(function () { segnaTutto(box); })
      .observe(box, { childList: true, subtree: true });
  }

  // ── 2-3) tessere del benvenuto ──────────────────────────────────────────
  // `serve`: profili in cui la capacita' NON c'e', col motivo da mostrare.
  var TESSERE = [
    { fam: 'intelligence', ttl: 'Intelligence', modo: 'intelligence',
      riga: 'Voli, navi, notizie, SIGINT e SAR su una mappa viva.',
      es: 'Che cosa vola adesso sopra il Mar Nero?',
      spento: { 'vergilius-chat': 'ShadowBroker non e\' avviato nel profilo Vergilius Chat.' } },
    { fam: 'financial', ttl: 'Financial', modo: 'financial',
      riga: 'Quotazioni, notizie di borsa, appalti, insider, calcolo esatto.',
      es: 'Come ha chiuso NVDA questa settimana, e perche\'?',
      spento: { 'vergilius-chat': 'ShadowBroker non e\' avviato nel profilo Vergilius Chat.' } },
    { fam: 'vista', ttl: 'Vista', modo: 'vista',
      riga: 'Guarda lo schermo o un\'immagine con un modello visivo.',
      es: 'Guarda lo schermo e dimmi che finestra ho davanti.' },
    { fam: 'pc', ttl: 'Controllo PC e browser', modo: 'controllo',
      riga: 'Apre finestre, preme, scrive, naviga: il PC lo usa lui.',
      es: 'Apri il Blocco note e scrivici la lista della spesa.' },
    { fam: 'voce', ttl: 'Voce e avatar', modo: 'voce',
      riga: 'Ti ascolta e risponde a voce, con un volto 2D.',
      es: 'Parliamo a voce: presentati in tre frasi.',
      spento: { 'vergilius-chat': 'La voce vive solo nel profilo Full.',
                'vergilius-lite': 'La voce vive solo nel profilo Full.',
                'shadowbroker':   'La voce vive solo nel profilo Full.' } },
    { fam: 'neutro', ttl: 'Memoria e documenti', modo: '',
      riga: 'Ricorda, legge i tuoi file, cerca sul web e cita le fonti.',
      es: 'Che cosa mi ero segnato sul disco D la settimana scorsa?' },
  ];

  function riempiComposer(testo) {
    var ta = document.getElementById('message');
    if (!ta) return;
    ta.value = testo;
    try { ta.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
    try { ta.focus(); ta.setSelectionRange(testo.length, testo.length); } catch (_) {}
  }

  function montaTessere(profilo) {
    var ws = document.getElementById('welcome-screen');
    if (!ws || document.getElementById('ver-skill')) return;
    var griglia = document.createElement('div');
    griglia.id = 'ver-skill';
    griglia.setAttribute('aria-label', 'Che cosa sa fare Vergilius');

    TESSERE.forEach(function (t) {
      var motivo = t.spento && t.spento[profilo];
      var card = document.createElement(motivo ? 'div' : 'button');
      if (!motivo) card.type = 'button';
      card.className = 'ver-tess' + (motivo ? ' spenta' : '');
      card.setAttribute('data-fam', t.fam);
      if (t.modo) card.setAttribute('data-modo', t.modo);
      card.innerHTML =
        '<span class="vt-top">' + svg(t.fam) + '<span class="vt-ttl"></span></span>' +
        '<span class="vt-riga"></span>' +
        '<span class="vt-es"></span>';
      card.querySelector('.vt-ttl').textContent = t.ttl;
      card.querySelector('.vt-riga').textContent = t.riga;
      card.querySelector('.vt-es').textContent = motivo ? motivo : t.es;
      if (motivo) {
        card.title = t.ttl + ' non disponibile: ' + motivo;
      } else {
        card.title = 'Mette l\'esempio nel campo di scrittura (non lo manda)';
        card.addEventListener('click', function () { riempiComposer(t.es); });
      }
      griglia.appendChild(card);
    });

    // Sotto al sottotitolo, sopra al tasto Nobody: le tessere sono il contenuto
    // principale del benvenuto, non un'appendice.
    var dopo = document.getElementById('welcome-tip') || document.getElementById('welcome-sub');
    if (dopo && dopo.parentNode === ws) ws.insertBefore(griglia, dopo.nextSibling);
    else ws.appendChild(griglia);
  }

  function carica() {
    osservaChat();
    fetch((window.API_BASE || '') + '/api/startup-profile-status',
          { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { montaTessere(s && s.profile ? String(s.profile) : 'full'); })
      .catch(function () { montaTessere('full'); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', carica);
  else carica();
})();
