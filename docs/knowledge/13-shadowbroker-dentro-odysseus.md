# ShadowBroker dentro Odysseus

1 agosto 2026. Analisi completa della piattaforma in
[ricerche/shadowbroker-analisi-e-integrazione.md](../../../ricerche/shadowbroker-analisi-e-integrazione.md).
Qui c'è solo **come l'abbiamo attaccato a Odysseus**.

---

## La scelta: incorporare, non riscrivere

ShadowBroker è ~1100 file di React + MapLibre + FastAPI. Riscrivere il
livello mappa dentro Odysseus non comprerebbe niente e costerebbe mesi.

Quindi: **resta un'applicazione separata**, incorporata in un iframe che copre
l'area della chat. Tre servizi indipendenti che si parlano su loopback.

```
Odysseus        127.0.0.1:7000    <- l'iframe sta qui dentro
ShadowBroker UI 127.0.0.1:3000    <- Next.js
ShadowBroker API 127.0.0.1:8000   <- FastAPI, 60+ feed
```

**L'avatar resta.** Il riquadro dell'avatar è `position: fixed` sul `<body>`,
mentre il pannello è `position: absolute` dentro `<main>`. Galleggia sopra la
mappa senza una riga di codice dedicata — esattamente l'effetto voluto: cambia
la finestra centrale, l'assistente no.

---

## Il muro: due intestazioni di sicurezza, una per lato

Al primo tentativo l'iframe restava bianco. Due blocchi indipendenti.

### Lato ShadowBroker — rifiutava di farsi incorporare

```
X-Frame-Options: DENY
Content-Security-Policy: ... frame-ancestors 'none'
```

`X-Frame-Options` **non sa esprimere una lista di origini**: la variante
`ALLOW-FROM` è stata rimossa da tutti i browser attuali, restano solo
`DENY`/`SAMEORIGIN`. E quando ci sono entrambe le intestazioni, in alcuni
motori vince quella vecchia.

Soluzione: quando è configurata una lista, **si toglie `X-Frame-Options`** e
si lascia decidere a `frame-ancestors`, sostituto moderno che la lista la
accetta.

| File | Modifica |
|---|---|
| `frontend/next.config.ts` | `X-Frame-Options` emesso solo se `SHADOWBROKER_FRAME_ANCESTORS` è vuota |
| `frontend/src/proxy.ts` | `frame-ancestors 'none'` → il valore della variabile, se c'è |

Non impostata = comportamento originale intatto (`DENY` + `'none'`).

```powershell
$env:SHADOWBROKER_FRAME_ANCESTORS = "'self' http://localhost:7000 http://127.0.0.1:7000"
```

**Mai `*` qui.** `frame-ancestors` è l'unica cosa tra quel cruscotto e una
sovrapposizione di clickjacking, e dentro l'iframe sono raggiungibili le rotte
che si fidano dell'operatore locale.

### Lato Odysseus — vietava di incorporare

`core/middleware.py` aveva `frame-src 'self'`. Aggiunta `_shadowbroker_frame_src()`:
legge `SHADOWBROKER_URL` dall'ambiente e aggiunge **solo quell'origine**, in
entrambe le forme:

```
frame-src 'self' http://127.0.0.1:3000 http://localhost:3000
```

`127.0.0.1` e `localhost` sono **origini diverse** per un browser, e quale
finisce nell'iframe dipende da come sei arrivato su Odysseus. Metterle
entrambe evita un blocco che si manifesterebbe solo a volte.

Nient'altro è stato allentato: `script-src`, `connect-src` e `frame-ancestors`
restano identici.

---

## I pezzi aggiunti

### Backend — `routes/shadowbroker_routes.py` (nuovo)

Due rotte. Nessuna delle due fa da proxy ai dati: il browser parla con
ShadowBroker direttamente.

```
GET /api/shadowbroker/config  -> {"url": ..., "api": ..., "enabled": true}
GET /api/shadowbroker/probe   -> {"frontend": bool, "backend": bool, "detail": ...}
```

**Perché la sonda sta sul server e non nel browser.** Due motivi che si
sommano:

1. La CSP di Odysseus è `connect-src 'self'` — la pagina **non può** fare
   fetch verso `localhost:3000`.
2. Il risultato del caricamento di un iframe cross-origin **non è leggibile**:
   un cruscotto morto e uno lento sono indistinguibili.

Sul server nessuno dei due limiti esiste. Così il pannello scrive "non
raggiungibile" invece di mostrare un rettangolo bianco per sempre.

I due stati sono riportati **separati** di proposito: la mappa può disegnare
benissimo mentre il FastAPI dietro è giù, e il pannello lo dice.

Registrata in `app.py` subito dopo le rotte dei modelli.

### Frontend

| File | Ruolo |
|---|---|
| `static/js/shadowbroker.js` | superficie pura: `open()`, `close()`, `toggle()`, `isOpen()` |
| `static/js/shadowbrokerBoot.js` | aggancia i pulsanti — separato apposta, così importare il modulo non ha effetti collaterali |
| `static/index.html` | pulsante nella barra, voce in Strumenti, contenitore `#shadowbroker-panel` |
| `static/style.css` | blocco `.sb-*` in fondo |

**L'iframe si crea una volta sola e non viene mai smontato.** Chiudere il
pannello lo nasconde e basta: ricaricarlo rifarebbe scaldare le tessere di
MapLibre e ripartire da zero il polling della telemetria, ogni singola volta.

**Niente attributo `sandbox`.** Il cruscotto ha bisogno di storage
same-origin, worker e WebGL; isolarlo su un'origine nulla rompe MapLibre di
netto. Il confine di fiducia qui è che entrambe le applicazioni sono nostre,
su loopback.

---

## `local` / `remote` non c'entra niente con un LLM

Nel pannello AI Intel di ShadowBroker c'è un interruttore `Local | Remote`. È
**dove gira l'agente**, non che modello usa:

| Modo | Significato |
|---|---|
| **Local** | l'agente è sulla stessa macchina → `http://localhost:8000`, **nessuna firma HMAC** |
| **Remote** | l'agente è altrove → indirizzo onion via Tor + HMAC obbligatorio |

**ShadowBroker non contiene nessun LLM.** Il loro README lo dice
esplicitamente: *"ShadowBroker does not bundle an LLM, an agent runtime, or
model weights — it provides the surface; you bring the agent."*

Quel pannello, in pratica, **genera un blocco di testo** (`buildSnippet` in
`AIIntelPanel.tsx`) fatto di variabili d'ambiente più un lungo prompt
operativo, da incollare nel proprio agente. Vale la pena riusarlo: è un
prompt di sistema già scritto e ben tarato, con le regole su quali comandi
preferire.

**Conseguenza per noi:** stando sulla stessa macchina, `local` è la scelta
giusta e **tutta la parte HMAC si salta**. Il collegamento si riduce a:

```
POST http://127.0.0.1:8000/api/ai/channel/command
     {"cmd": "search_news", "args": {"query": "conflict"}}
```

Verificato dal vivo: risposta piena, nessuna intestazione di firma.

---

## Quello che manca ancora (e non è impossibile)

L'agente **oggi** non può spegnere i layer né evidenziare una singola entità.
Non perché la mappa non sappia farlo — MapLibre ha `setFilter` e la visibilità
per layer — ma perché **nessun comando dell'agente è cablato a quei
controlli**.

Tutto il controllo mappa passa da un file di 80 righe
(`frontend/src/hooks/useAgentActions.ts`) che interroga
`GET /api/ai/agent-actions` ogni 3 secondi e gestisce **due sole azioni**:

```
show_image   <- da show_satellite / show_sentinel
fly_to       <- da sar_focus_aoi soltanto
```

Da aggiungere, in ordine:

| Comando nuovo | Azione | Effetto |
|---|---|---|
| `map_focus(lat, lng, zoom)` | `fly_to` | zoom su un punto qualsiasi, senza AOI |
| `set_layers(on[], off[])` | `set_layers` | **spegne tutto tranne quello di cui si sta parlando** |
| `highlight(ids[], layer)` | `highlight` | `setFilter` di MapLibre sulle sole entità citate |

Stima: ~60 righe di backend, ~80 di frontend, più il cablaggio degli stati che
`WorldviewLeftPanel.tsx` già espone.

Da fare anche: portare il polling da 3 s a ~700 ms, o agganciarsi allo stream
SSE che il backend già pubblica (`layer_changed`, `alert`, `task`). Altrimenti
la mappa reagisce fino a 3 secondi dopo che l'avatar ha finito di parlare.

---

## Cose scoperte installando, che il loro README non dice

**Il proxy AIS è Node.js e le sue dipendenze non vengono mai installate.**
`backend/package.json` esiste (dipende da `ws`) ma il dev setup non dice di
lanciare `npm install` dentro `backend/`. Senza:

```
WARNING:services.ais_stream: AIS proxy stderr: Error: Cannot find module 'ws'
```

e il layer navi resta a 11 (solo le portaerei) anche con la chiave AIS
valida. Dopo `cd backend && npm install`: **9.990 navi**.

**`ships` nel riepilogo conta solo le portaerei.** Le navi AIS stanno in un
contatore separato. Vedere `ships: 11` con la chiave configurata non è un
errore.

**Il download di Tor fallisce con 404** su entrambe le versioni tentate.
Serve solo a InfoNet, che non useremo. Non blocca nulla.

---

## Configurazione, tutta insieme

```powershell
# ShadowBroker — cruscotto
$env:SHADOWBROKER_FRAME_ANCESTORS = "'self' http://localhost:7000 http://127.0.0.1:7000"
cd d:\assistenteeee\shadowbroker\frontend ; npm run dev:frontend

# ShadowBroker — dati
cd d:\assistenteeee\shadowbroker\backend ; venv\Scripts\python.exe main.py

# Odysseus (opzionali: i predefiniti sono già questi)
# $env:SHADOWBROKER_URL     = "http://127.0.0.1:3000"
# $env:SHADOWBROKER_API_URL = "http://127.0.0.1:8000"
cd d:\assistenteeee\odysseus ; venv\Scripts\python.exe app.py
```

Chiavi in `shadowbroker/backend/.env` — **file ignorato da git**, riga 14 del
`.gitignore`. Configurate: OpenSky (voli globali) e aisstream (navi).

`OPENCLAW_ACCESS_TIER=restricted`: sola lettura. Va portato a `full` quando
vorremo che il modello disegni sulla mappa (`place_pin`, `place_analysis_zone`).

---

## Stato

Verificato strutturalmente:

```
frame-src 'self' http://127.0.0.1:3000 http://localhost:3000        (Odysseus)
frame-ancestors 'self' http://localhost:7000 http://127.0.0.1:7000  (ShadowBroker)
X-Frame-Options                                                      assente
/api/shadowbroker/config  401 senza sessione   -> gate attivo
/api/shadowbroker/probe   401 senza sessione   -> gate attivo
/static/js/shadowbroker.js 200
```

**Non ancora provato nel browser da un utente autenticato.** Il pannello va
aperto e guardato.
