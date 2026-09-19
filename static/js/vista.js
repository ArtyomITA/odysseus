/* Vista — gli occhi di Vergilius (Holo VLM locale, CPU).
 *
 * La vista si sceglie DAI MODELLI: `ling-vista` nel picker = Ling + Holo. Il
 * loader e' quello del picker (modelLoading.js aspetta anche `occhi_pronti`),
 * l'avvio/stop di Holo lo fa il server nel warmup (model_routes.py).
 *
 * Qui: due toggle nel menu "+" — Computer (Windows-MCP + occhi sullo schermo)
 * e Browser (Playwright MCP isolato) — visibili solo con un modello -vista.
 * Stato in localStorage; i flag viaggiano nel FormData della chat (chat.js).
 * Si auto-inietta: una riga in index.html.
 */
(function () {
  "use strict";
  if (window.__vistaCaricata) return;
  window.__vistaCaricata = true;

  var PREF_PC = 'odysseus.vista.computer';
  var PREF_BR = 'odysseus.vista.browser';

  function modelloCorrente() {
    var l = document.getElementById('model-picker-label');
    return (l && (l.title || l.textContent) || '').trim().toLowerCase();
  }
  function attiva() {
    var m = modelloCorrente().split('/').pop();
    return m.indexOf('ling') === 0 && /-vista$/.test(m);
  }
  function computer() { try { return attiva() && localStorage.getItem(PREF_PC) === '1'; } catch (_) { return false; } }
  function browser()  { try { return attiva() && localStorage.getItem(PREF_BR) === '1'; } catch (_) { return false; } }

  function _toast(msg) {
    try { window.uiModule && window.uiModule.showToast && window.uiModule.showToast(msg); } catch (_) {}
  }

  function _aggiorna() {
    var on = attiva();
    var bp = document.getElementById('overflow-computer-btn');
    var bb = document.getElementById('overflow-browser-btn');
    [bp, bb].forEach(function (b) { if (b) b.style.display = on ? '' : 'none'; });
    if (bp) {
      bp.classList.toggle('active', computer());
      bp.title = computer() ? 'Computer attivo: il modello guarda lo schermo e agisce via Windows-MCP'
                            : 'Attiva Computer: controllo del PC con gli occhi (Holo) + Windows-MCP';
    }
    if (bb) {
      bb.classList.toggle('active', browser());
      bb.title = browser() ? 'Browser attivo: sessione Chromium dedicata (Playwright), isolata dal tuo Chrome'
                           : 'Attiva Browser: apre una sessione Chromium dedicata controllata dal modello';
    }
    try { document.dispatchEvent(new CustomEvent('overflow-state-change')); } catch (_) {}
  }

  function _toggle(pref, nome) {
    var on = (localStorage.getItem(pref) === '1');
    try { localStorage.setItem(pref, on ? '0' : '1'); } catch (_) {}
    _aggiorna();
    _toast(nome + (on ? ' disattivato' : ' attivo'));
  }

  function monta() {
    var bp = document.getElementById('overflow-computer-btn');
    var bb = document.getElementById('overflow-browser-btn');
    if (bp) bp.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); _toggle(PREF_PC, 'Computer'); });
    if (bb) bb.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); _toggle(PREF_BR, 'Browser'); });
    _aggiorna();
    // Il modello puo' cambiare in qualunque momento: riallinea i toggle.
    document.addEventListener('odysseus:model-picked', function () { setTimeout(_aggiorna, 0); });
    document.addEventListener('odysseus:model-caps', _aggiorna);
    var l = document.getElementById('model-picker-label');
    if (l && window.MutationObserver) {
      new MutationObserver(_aggiorna).observe(l, { attributes: true, childList: true, characterData: true, subtree: true });
    }
  }

  window.OdysseusVista = { attiva: attiva, computer: computer, browser: browser };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', monta);
  else monta();
})();
