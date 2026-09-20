/* Indice degli strumenti — sempre presente in Odysseus, non ingombrante.
 *
 * Tre livelli: Categoria  ->  tool grande (la nostra facciata)  ->  i comandi
 * che orchestra. Il tool grande spiega COME chiama gli altri e a cosa servono.
 * Non e' il prompt del modello: e' la mappa per l'utente. Dati da
 * /static/catalogo-facce.json (rigenerabile). Si auto-inietta: una riga in index.html.
 */
(function () {
  "use strict";
  if (window.__catalogoStrumentiCaricato) return;
  window.__catalogoStrumentiCaricato = true;

  var CSS = `
  /* Token del tema Odysseus (--bg/--fg/--panel/--border/--brand-color): il
     widget segue la skin scelta dall'utente invece di una palette sua.
     Spazio: pannello staccato dal bordo (20px), respiro interno 18px. */
  #cat-launch{position:fixed;right:20px;top:62px;z-index:9000;
    display:inline-flex;align-items:center;gap:8px;cursor:pointer;
    background:var(--panel,#111);color:var(--fg,#ddd);
    border:1px solid var(--border,#355a66);border-radius:20px;
    padding:7px 14px;font:600 12px/1 var(--font-family,'Fira Code',ui-monospace,monospace);
    box-shadow:0 4px 14px rgba(0,0,0,.35);transition:border-color .15s,box-shadow .15s}
  #cat-launch:hover{border-color:var(--brand-color,var(--red,#c678dd));
    box-shadow:0 0 18px color-mix(in srgb,var(--brand-color,var(--red,#c678dd)) 30%,transparent)}
  #cat-launch .ico{display:inline-flex;line-height:1;color:var(--brand-color,var(--red,#c678dd))}
  #cat-launch .ico svg{width:14px;height:14px}
  #cat-launch:focus-visible{outline:2px solid var(--brand-color,var(--red,#c678dd));outline-offset:2px}

  #cat-panel{position:fixed;right:20px;top:106px;z-index:9001;
    width:400px;max-width:calc(100vw - 40px);max-height:calc(100vh - 130px);
    display:none;flex-direction:column;background:var(--panel,#111);color:var(--fg,#ddd);
    border:1px solid var(--brand-color,var(--red,#c678dd));border-radius:12px;
    box-shadow:0 0 0 1px color-mix(in srgb,var(--brand-color,var(--red,#c678dd)) 25%,transparent),
      0 12px 38px rgba(0,0,0,.55);
    overflow:hidden;font:14px/1.5 var(--font-family,'Fira Code',ui-monospace,monospace)}
  #cat-panel.aperto{display:flex}

  /* Con un pannello a tutta area davanti (ShadowBroker) il pulsante restava
     sopra la mappa e ne copriva i controlli in alto a destra: si toglie di
     mezzo finche' il pannello e' aperto. */
  body.shadowbroker-active #cat-launch,
  body.shadowbroker-active #cat-panel{display:none}

  #cat-head{flex:0 0 auto;display:flex;align-items:center;gap:10px;
    padding:16px 18px 14px;border-bottom:1px solid var(--border,#355a66)}
  #cat-head .ttl{font-weight:600;font-size:.98rem;letter-spacing:.02em;color:var(--brand-color,var(--red,#c678dd))}
  #cat-head .cnt{font:600 .62rem ui-monospace,Consolas,monospace;color:color-mix(in srgb,var(--fg) 60%,transparent);
    border:1px solid var(--border,#355a66);border-radius:5px;padding:2px 7px}
  #cat-head .x{margin-left:auto;cursor:pointer;color:color-mix(in srgb,var(--fg) 60%,transparent);font-size:18px;
    line-height:1;padding:2px 6px;border-radius:5px}
  #cat-head .x:hover{color:var(--brand-color,var(--red,#c678dd))}

  #cat-search{flex:0 0 auto;margin:14px 18px 0;padding:8px 12px;background:var(--bg,#000);
    border:1px solid var(--border,#355a66);border-radius:8px;color:var(--fg,#ddd);font:inherit;font-size:.85rem;outline:none}
  #cat-search:focus{border-color:var(--brand-color,var(--red,#c678dd))}

  #cat-intro{flex:0 0 auto;margin:12px 18px 4px;padding:10px 12px;
    border:1px solid var(--border,#355a66);border-radius:8px;background:var(--bg,#000);
    color:color-mix(in srgb,var(--fg) 75%,transparent);font-size:.8rem;line-height:1.5}
  #cat-intro b{color:var(--brand-color,var(--red,#c678dd))}

  #cat-body{flex:1 1 auto;overflow-y:auto;padding:10px 18px 18px}
  #cat-body::-webkit-scrollbar{width:9px}
  #cat-body::-webkit-scrollbar-thumb{background:var(--border,#355a66);border-radius:5px}
  #cat-body::-webkit-scrollbar-track{background:transparent}

  /* livello 1: categoria */
  .cat-cat{border:1px solid var(--border,#355a66);border-radius:10px;margin:8px 0;overflow:hidden;background:var(--bg,#000)}
  .cat-cat>summary{list-style:none;cursor:pointer;display:flex;align-items:center;
    gap:10px;padding:11px 14px;font-weight:600;font-size:.88rem}
  .cat-cat>summary::-webkit-details-marker{display:none}
  .cat-cat>summary .lbl{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .cat-cat>summary .cnt{flex:0 0 auto;font:600 .62rem ui-monospace,Consolas,monospace;color:color-mix(in srgb,var(--fg) 55%,transparent)}
  .cat-cat>summary .car{flex:0 0 auto;color:var(--brand-color,var(--red,#c678dd));font-size:.72rem;transition:transform .15s}
  .cat-cat[open]>summary .car{transform:rotate(90deg)}
  .cat-cat[open]>summary{border-bottom:1px solid var(--border,#355a66)}

  /* livello 2: tool grande (facciata) */
  .cat-face{border-top:1px solid color-mix(in srgb,var(--border,#355a66) 60%,transparent);background:var(--panel,#111)}
  .cat-face:first-of-type{border-top:none}
  .cat-face>summary{list-style:none;cursor:pointer;display:flex;align-items:baseline;
    gap:8px;padding:10px 14px 10px 16px}
  .cat-face>summary::-webkit-details-marker{display:none}
  .cat-face>summary .n{flex:0 0 auto;font:700 .82rem ui-monospace,Consolas,monospace;color:var(--brand-color,var(--red,#c678dd))}
  .cat-face>summary .d{flex:1 1 auto;min-width:0;color:color-mix(in srgb,var(--fg) 85%,transparent);font-size:.82rem;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .cat-face>summary .car{flex:0 0 auto;align-self:center;color:color-mix(in srgb,var(--fg) 45%,transparent);font-size:.66rem;transition:transform .15s}
  .cat-face[open]>summary .car{transform:rotate(90deg)}
  .cat-face[open]>summary .d{white-space:normal}

  .face-body{padding:2px 14px 14px 16px}
  .face-come{color:color-mix(in srgb,var(--fg) 75%,transparent);font-size:.82rem;line-height:1.5;margin:2px 0 8px}
  .face-subttl{font:600 .6rem ui-monospace,Consolas,monospace;letter-spacing:.08em;
    text-transform:uppercase;color:color-mix(in srgb,var(--fg) 45%,transparent);margin:10px 0 6px}
  .face-es{margin:0 0 8px}
  .face-es .q{color:var(--fg,#ddd);font-size:.82rem;line-height:1.4}
  .face-es .q::before{content:"« ";color:var(--brand-color,var(--red,#c678dd))}
  .face-es .q::after{content:" »";color:var(--brand-color,var(--red,#c678dd))}
  .face-es .chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
  .face-es .chip{font:600 .66rem ui-monospace,Consolas,monospace;color:color-mix(in srgb,var(--fg) 70%,transparent);
    background:var(--bg,#000);border:1px solid var(--border,#355a66);border-radius:4px;padding:1px 6px}

  /* livello 3: sotto-tool orchestrati */
  .cat-sub{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;align-items:baseline}
  .cat-sub .sn{font:600 .76rem ui-monospace,Consolas,monospace;color:color-mix(in srgb,var(--fg) 70%,transparent);white-space:nowrap}
  .cat-sub .sd{color:color-mix(in srgb,var(--fg) 60%,transparent);font-size:.78rem}

  #cat-empty{padding:18px;color:color-mix(in srgb,var(--fg) 55%,transparent);font-size:.85rem;text-align:center}
  `;

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === "text") e.textContent = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }

  var stato = { dati: null, filtro: "" };

  function faceMatches(f, q) {
    if (f.nome.toLowerCase().indexOf(q) >= 0) return true;
    if ((f.desc || "").toLowerCase().indexOf(q) >= 0) return true;
    if ((f.come || "").toLowerCase().indexOf(q) >= 0) return true;
    if ((f.esempi || []).some(function (ex) { return (ex.q || "").toLowerCase().indexOf(q) >= 0; })) return true;
    return (f.sub || []).some(function (s) {
      return s.nome.toLowerCase().indexOf(q) >= 0 || (s.desc || "").toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderFace(f, aperta) {
    var summary = el("summary", null, [
      el("span", { class: "n", text: f.nome }),
      el("span", { class: "d", text: f.desc || "" }),
      el("span", { class: "car", text: "▸" })
    ]);
    var body = el("div", { class: "face-body" });
    if (f.come) body.appendChild(el("div", { class: "face-come", text: f.come }));
    if (f.esempi && f.esempi.length) {
      body.appendChild(el("div", { class: "face-subttl", text: "esempi — coi tool che usano" }));
      f.esempi.forEach(function (ex) {
        var chips = el("div", { class: "chips" });
        (ex.tool || []).forEach(function (t) { chips.appendChild(el("span", { class: "chip", text: t })); });
        body.appendChild(el("div", { class: "face-es" }, [
          el("div", { class: "q", text: ex.q }),
          chips
        ]));
      });
    }
    if (f.sub && f.sub.length) {
      body.appendChild(el("div", { class: "face-subttl", text: "chiama sotto — " + f.sub.length }));
      var grid = el("div", { class: "cat-sub" });
      f.sub.forEach(function (s) {
        grid.appendChild(el("span", { class: "sn", text: s.nome }));
        grid.appendChild(el("span", { class: "sd", text: s.desc || "" }));
      });
      body.appendChild(grid);
    }
    var d = el("details", { class: "cat-face" }, [summary, body]);
    if (aperta) d.setAttribute("open", "");
    return d;
  }

  function render() {
    var body = document.getElementById("cat-body");
    if (!body) return;
    body.innerHTML = "";
    if (!stato.dati) { body.appendChild(el("div", { id: "cat-empty", text: "Carico…" })); return; }
    var q = stato.filtro.trim().toLowerCase();
    var visti = 0;
    stato.dati.categorie.forEach(function (c) {
      var facce = q ? c.facce.filter(function (f) { return faceMatches(f, q); }) : c.facce;
      if (!facce.length) return;
      visti += facce.length;
      var summary = el("summary", null, [
        el("span", { class: "lbl", text: c.categoria }),
        el("span", { class: "cnt", text: String(facce.length) }),
        el("span", { class: "car", text: "▸" })
      ]);
      var cat = el("details", { class: "cat-cat" }, [summary]);
      if (q) cat.setAttribute("open", "");
      facce.forEach(function (f) { cat.appendChild(renderFace(f, !!q)); });
      body.appendChild(cat);
    });
    if (!visti) body.appendChild(el("div", { id: "cat-empty", text: "Niente per «" + q + "»" }));
  }

  function apri() {
    document.getElementById("cat-panel").classList.add("aperto");
    if (!stato.dati) carica();
    var s = document.getElementById("cat-search");
    if (s) setTimeout(function () { s.focus(); }, 30);
  }
  function chiudi() { document.getElementById("cat-panel").classList.remove("aperto"); }

  function carica() {
    fetch("/static/catalogo-facce.json", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        stato.dati = d;
        var c = document.querySelector("#cat-head .cnt");
        if (c && d.conteggi) c.textContent = d.conteggi.facce + " tool";
        var intro = document.getElementById("cat-intro");
        if (intro && d.intro) intro.innerHTML = d.intro.replace("router", "<b>router</b>");
        render();
      })
      .catch(function () {
        var b = document.getElementById("cat-body");
        if (b) b.innerHTML = '<div id="cat-empty">Catalogo non disponibile.</div>';
      });
  }

  function monta() {
    if (document.getElementById("cat-launch")) return;
    document.head.appendChild(el("style", { html: CSS }));

    // Icona in linea, non un'emoji: stesso tratto delle altre icone dell'app.
    var ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<rect x="3" y="8" width="18" height="12" rx="1.5"/><path d="M3 13h18"/>' +
      '<path d="M9 8V6a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 6v2"/></svg>';
    var launch = el("div", { id: "cat-launch", title: "Gli strumenti dell'assistente" }, [
      el("span", { class: "ico", html: ICO }),
      el("span", { text: "Strumenti" })
    ]);
    launch.addEventListener("click", function () {
      var p = document.getElementById("cat-panel");
      if (p.classList.contains("aperto")) chiudi(); else apri();
    });

    var search = el("input", { id: "cat-search", type: "text", placeholder: "cerca uno strumento…" });
    search.addEventListener("input", function () { stato.filtro = search.value; render(); });

    var head = el("div", { id: "cat-head" }, [
      el("span", { class: "ttl", text: "Strumenti" }),
      el("span", { class: "cnt", text: "…" }),
      el("span", { class: "x", text: "✕", title: "Chiudi" })
    ]);
    head.querySelector(".x").addEventListener("click", chiudi);

    var panel = el("div", { id: "cat-panel" }, [
      head, search,
      el("div", { id: "cat-intro" }),
      el("div", { id: "cat-body" })
    ]);

    document.body.appendChild(launch);
    document.body.appendChild(panel);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") chiudi(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", monta);
  } else { monta(); }
})();
