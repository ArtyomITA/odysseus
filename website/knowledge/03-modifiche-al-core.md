# Modifiche al core di Odysseus

Registro completo di cosa abbiamo toccato del codice originale. Serve per due
motivi: rifare modifiche dopo aggiornamento del repository, e capire cosa
potrebbe entrare in conflitto.

**Principio seguito:** dove esiste punto di estensione ufficiale (skill,
preset, MCP, impostazioni) lo si usa. Core si tocca solo quando non c'è
alternativa, con modifiche minime.

---

## A. Correzioni di bug loro

### `src/agent_loop.py` riga 15 — import mancante

```python
# prima
from typing import AsyncGenerator, List, Dict, Optional, Set
# dopo
from typing import Any, AsyncGenerator, List, Dict, Optional, Set
```

**Senza questa riga Odysseus non parte.** Errore:
`NameError: name 'Any' is not defined` alla riga 1503. Bug del merge sul ramo
`main`. Da ricontrollare a ogni aggiornamento; varrebbe segnalazione a monte.

### `routes/tts_routes.py` — l'endpoint bloccava tutto il server

```python
# prima
async def synthesize_speech(request: TTSRequest):
# dopo
def synthesize_speech(request: TTSRequest):
```

Gestore dichiarato asincrono ma dentro chiamava rete in modo
**bloccante**. Risultato: durante ogni sintesi vocale intero server si
congelava. Con lettura frase per frase attiva, succedeva di continuo.

Togliendo `async`, FastAPI sposta da sé gestore su thread separato. Nel file
c'è commento che spiega perché è deliberato.

---

## A-bis. Voce in streaming (1 agosto 2026)

Quattro punti raccoglievano audio intero prima di passarlo, annullando
streaming che PocketTTS faceva già. Misure e dettaglio in
[05-voce-tts-stt.md](05-voce-tts-stt.md) e
[ricerche/voce-streaming-misure.md](../../../ricerche/voce-streaming-misure.md).

| File | Modifica |
|---|---|
| `services/tts/tts_service.py` | **nuovo** `synthesize_stream()` con `httpx.stream()`; cache si riempie duplicando flusso mentre passa, si scrive solo se ultimo pezzo esce |
| `routes/tts_routes.py` | **nuova** rotta `GET /api/tts/stream`; primo pezzo estratto per decidere tipo contenuto poi reimmesso |
| `routes/stt_routes.py` | **nuovo** `WS /api/stt/stream`: inoltra microfono al ponte e testo indietro |
| `services/stt/stt_service.py` | riconosce provider `stream` |
| `static/js/tts-ai.js` | `_streamUrl()`, `forSpeech()`, `_spezza()`, eventi `odysseus:tts-start/end`; `_prefetch()` ora crea elemento `<audio>` invece di riempire cache di blob |
| `static/js/voiceRecorder.js` | ramo `stream`: microfono in diretta, niente `MediaRecorder` |

**Perché GET e non POST** per sintesi: elemento `<audio>` si può solo
puntare a URL. Tutto ciò che si scarica a mano finisce in Blob, e Blob è
completo per definizione — cioè reintroduce attesa che si stava togliendo.
Sopra 1.600 caratteri si torna al POST.

**Perché microfono passa da Odysseus** invece che dritto al ponte: CSP
dichiara `connect-src 'self'`. Inoltrare costa 50 ms ed evita allargarla.

---

## B. Agganci per l'avatar

### `static/js/chat.js` riga ~2320 — eventi del flusso

```javascript
if (!_isBg) window.OdysseusAvatar?.handleStreamEvent(json);
```

Una riga, inserita **prima** del filtro esistente sui tipi evento, nel
dispatcher unico degli eventi SSE. Passa ogni evento a nucleo avatar, che ne
ricava stato (pensa / lavora / parla / fermo). Controllo `!_isBg` esclude
conversazioni in background.

### `static/js/chat.js` riga ~2238 — fine del flusso

```javascript
if (!_isBg) window.OdysseusAvatar?.handleStreamEnd();
```

Dentro ramo `if (data === '[DONE]')`. Riporta avatar a riposo.

### `static/js/tts-ai.js` — audio verso avatar e dispositivo scelto

Due punti, perché ci sono due percorsi riproduzione:

```javascript
// in play() — riproduzione singola
this.currentAudio = new Audio(audioUrl);
window.OdysseusAudioDevices?.applyOutputDevice(this.currentAudio);
window.OdysseusAvatar?.attachAudio(this.currentAudio);

// in _playQueueItem() — la coda, usata da pulsante e lettura automatica
const audio = new Audio(audioUrl);
window.OdysseusAudioDevices?.applyOutputDevice(audio);
window.OdysseusAvatar?.attachAudio(audio);
```

**Trappola in cui siamo caduti:** avevamo agganciato solo primo percorso, che
in pratica non viene mai usato. Pulsante di lettura e parlato automatico
passano entrambi dalla coda.

### `static/js/tts-ai.js` — `extractPlainText`, il filtro del ragionamento

```javascript
let cleaned = content
    .replace(/<think(?:ing)?\b[^>]*>[\s\S]*?<\/think(?:ing)?>/gi, '')
    .replace(/<think(?:ing)?\b[^>]*>[\s\S]*$/i, '');
```

Due cambiamenti rispetto originale:
1. `\b[^>]*` per accettare attributi: Odysseus riscrive tag come
   `<think time="2.4">` a fine ragionamento, vecchio filtro non lo matchava.
2. Seconda `replace` toglie blocco **ancora aperto**.

Questa seconda riga risolve **due bug in uno** (vedi
[08-trappole-e-scoperte.md](08-trappole-e-scoperte.md)).

### `static/js/voiceRecorder.js` — microfono scelto

```javascript
navigator.mediaDevices.getUserMedia(
  window.OdysseusAudioDevices?.micConstraints() || { audio: true })
```

Onora microfono selezionato nelle impostazioni; ripiega su predefinito.

---

## C. Interfaccia

### `static/index.html`

1. **Riquadro dell'avatar** prima del blocco degli script:
   ```html
   <div id="avatar-dock" hidden>
     <canvas id="avatar-canvas"></canvas>
     <div id="avatar-dock-bar">…</div>
     <div id="avatar-resize"></div>
   </div>
   ```
2. **Cinque tag script** (librerie Live2D + nostri moduli). Ordine conta:
   Cubism Core, PixiJS, **toppa unsafe-eval**, libreria Live2D, poi moduli.
3. **Due schede nel pannello Aspetto**: "Dispositivi audio" (microfono, uscita,
   pulsante rileva) e "Live2D avatar" (interruttore, scelta modello, personalità).
4. **Pulsante voce riabilitato**: era
   `<button id="overflow-tts-btn" hidden style="display:none">` con commento
   *"read-aloud feature is off in this build"*. Tolti `hidden` e stile,
   rinominato "Voce".

### `static/style.css`

Blocco in fondo per riquadro avatar: posizione fissa, trascinabile
(`cursor: grab`, `touch-action: none`), barra pulsanti che appare al
passaggio mouse, maniglia ridimensionamento nell'angolo, nascosto sotto
900px di larghezza.

Secondo blocco: `.model-loading-*` (overlay caricamento modello) e
`.model-blind-badge` (pastiglia "senza vista").

---

## C-bis. Caricamento dei modelli e rilevamento della vista

Dettaglio completo e misure in
[12-caricamento-modelli-e-vista.md](12-caricamento-modelli-e-vista.md).

### `src/chat_helpers.py` — `model_supports_vision()`

Consulta llama-swap **prima** dell'euristica sul nome, con schema già
usato per LM Studio. Senza questo, `qwenpaw-vista` e `heretic-vista` risultavano
ciechi (nessuna parola chiave nel nome) e Odysseus **toglieva immagine dalla
richiesta** pur avendo proiettore caricato.

### `src/agent_loop.py` — `_drop_image_only_tools()`

Nuova funzione più riga di chiamata subito dopo `_expand_browser_mcp_tools`.
Toglie `Screenshot` e `browser_take_screenshot` quando llama.cpp dichiara
`modalities.vision = false`. Confronto su nome nudo, perché nome qualificato
MCP contiene identificativo del server (da noi UUID). Filtra **solo** su
no esplicito.

### `routes/model_routes.py` — due rotte nuove

`GET /api/model-runtime/status` e `POST /api/model-runtime/warmup`, più
`_resolve_known_endpoint()` che accetta solo endpoint già configurati (URL
arriva dal browser: prenderlo per buono sarebbe falla SSRF).

### `static/js/modelPicker.js`

Un import e `_warmupPicked(m)` sulle due uscite riuscite di `_pick()`.

---

## C-ter. ShadowBroker: pannello, strumenti, modalità dedicata

Dettaglio in [13](13-shadowbroker-dentro-odysseus.md) (collegamento),
[14](14-agente-osint.md) (orchestrazione), [15](15-shadowbroker-come-funziona.md) (dati).

| File | Modifica |
|---|---|
| `core/middleware.py` | `_shadowbroker_frame_src()`: CSP impara origine cruscotto (entrambe forme, `127.0.0.1` e `localhost`, per browser origini diverse) |
| `routes/chat_routes.py` | flag `osint_mode`: col pannello aperto restringe dotazione ai soli strumenti OSINT |
| `src/tool_schemas.py` | in fondo, estende `FUNCTION_TOOL_SCHEMAS` con dieci schemi OSINT |
| `src/agent_tools/__init__.py` | registra handler OSINT e loro tag; import protetto — ShadowBroker è opzionale |
| `static/js/chat.js` | manda `osint_mode=true` quando pannello è aperto |
| `static/js/tts-ai.js` | `_prefetch()`: sintetizza blocco N+1 mentre suona blocco N |
| `static/index.html` | pulsante barra, voce Strumenti, contenitore pannello |
| `static/style.css` | blocco `.sb-*` |

---

## D. File nuovi (nessun conflitto con gli aggiornamenti)

### Moduli Python

| File | Ruolo |
|---|---|
| `src/llamaswap.py` | stato caricamento profili, lettura `/props`, avvio profilo |
| `src/shadowbroker/client.py` | HTTP con backoff, batch, comandi vietati, `radius` corretto |
| `src/shadowbroker/store.py` | magazzino per layer, identificativi stabili, schede intere |
| `src/shadowbroker/sagome.py` | che campi tenere per ogni layer |
| `src/shadowbroker/geo.py` | distanze vere, nomi posti, 60+ luoghi noti |
| `src/shadowbroker/testo.py` | recupero articoli, titoli marcati non cancellati |
| `src/shadowbroker/briefing.py` | **i cinque briefing precalcolati** |
| `src/shadowbroker/entita.py` | composizione annidata schede entità |
| `src/shadowbroker/schemi.py` | dieci schemi degli strumenti |
| `src/agent_tools/shadowbroker_tools.py` | dieci handler |
| `routes/shadowbroker_routes.py` | scoperta e sonda vitalità cruscotto |

### Moduli JavaScript

| File | Ruolo |
|---|---|
| `static/js/avatarCore.js` | macchina a stati, lettura tag emozione, analisi audio per labiale |
| `static/js/avatarRenderer.js` | disegna Live2D, applica comandi |
| `static/js/avatarDock.js` | riquadro in pagina, trascinamento, scelta modello, stacco widget |
| `static/js/avatarPersona.js` | compone e salva preset personalità + emozioni |
| `static/js/avatarWidget.js` | punto ingresso finestra staccata |
| `static/js/avatarSelfTest.js` | diagnostica catena Live2D |
| `static/js/audioDevices.js` | scelta microfono e uscita audio |
| `static/js/modelLoading.js` | overlay caricamento modello, capacità profilo, pastiglia "senza vista" |
| `static/js/shadowbroker.js` | pannello ShadowBroker: apri, chiudi, sonda, iframe tenuto vivo |
| `static/js/shadowbrokerBoot.js` | aggancia pulsanti senza effetti collaterali sull'import |
| `static/js/asrStreaming.js` | microfono in diretta: WebSocket, silenziamento durante parlato |
| `static/js/asrWorklet.js` | preleva microfono a pezzi da 100 ms, già in PCM 16 bit |

### Fuori dal repository (`d:\assistenteeee\voce\`)

| File | Ruolo |
|---|---|
| `asr_streaming.py` | **nuovo** — carica Nemotron-3.5 una volta sola, una `Sessione` per microfono aperto |
| `ponte_voce.py` | `WS /v1/audio/stream`, sintesi in streaming, riscaldamento modello all'avvio |

### Prove

| File | Cosa verifica |
|---|---|
| `tests/prova_tts_spezzettamento.mjs` | 16 casi: filtro emoji/parentesi, i tre tagli, contatore che non slitta |
| `scripts/prova_asr_streaming.py` | RTF e ritardo per pezzo del riconoscitore |
| `scripts/prova_asr_finiturno.py` | quando scatta fine turno, per tre soglie |
| `scripts/prova_ws_trascrizione.py` | catena WebSocket, a orario fisso come microfono vero |
| `scripts/prova_relay_stt.py` | tramite di Odysseus, montato senza autenticazione su porta usa e getta |
| `scripts/misura_voce_primo_suono.py` | tempo al **primo** byte di audio nei tre punti della catena |

### Modifiche dentro ShadowBroker (repo separato)

| File | Modifica |
|---|---|
| `backend/services/openclaw_channel.py` | `VIEW_COMMANDS` + `map_focus`, `set_layers`, `highlight` |
| `frontend/src/hooks/useAgentActions.ts` | due azioni nuove, polling 3000ms → 700ms |
| `frontend/src/lib/agentLayerMap.ts` | **nuovo** — traduce nomi layer nei tasti dell'interfaccia |
| `frontend/src/app/page.tsx` | stato evidenziazioni, ripristino livelli dell'operatore |
| `frontend/src/components/MaplibreViewer.tsx` | livello evidenziazioni; `flyTo` ora rispetta zoom (era fisso a 8) |
| `frontend/src/types/dashboard.ts` | tipo della prop `agentHighlights` |
| `frontend/next.config.ts` + `src/proxy.ts` | `frame-ancestors` da variabile d'ambiente, `X-Frame-Options` tolto quando serve |

### Pagine e stili

- `static/avatar.html` — finestra widget staccabile
- `static/avatar-widget.css` — stile finestra
- `static/avatar-test.html` — pagina di autodiagnosi

### Librerie (`static/lib/`)

| File | Origine | Nota |
|---|---|---|
| `live2dcubismcore.min.js` | cubism.live2d.com | **da servire immutato**, licenza proprietaria |
| `pixi.min.js` | PixiJS 7.4.2 | |
| `pixi-unsafe-eval.min.js` | @pixi/unsafe-eval 7.4.2 | **indispensabile**, vedi trappole |
| `live2d-cubism4.min.js` | pixi-live2d-display-lipsyncpatch 0.5.0-ls-8 | variante con labiale |

### Risorse

- `static/live2d/mao_pro/` — modello Live2D (Niziiro Mao, licenza Free Material)

---

## E. Dati e configurazione (non è codice, ma va ricordato)

- `data/settings.json` — modelli per ruolo, voce, trascrizione, ricerca
- `data/presets.json` — la personalità (slot `custom`)
- `data/skills/` — 13 skill installate in 4 categorie
- `data/app.db` — endpoint dei modelli e server MCP registrati

Vedi [09-configurazione.md](09-configurazione.md) per dettaglio delle chiavi.

---

## Riassunto per l'aggiornamento

Se un giorno si aggiorna Odysseus da monte, ordine di lavoro è:

1. **Ricontrollare import `Any`** in `agent_loop.py`: se bug è ancora lì,
   riapplicare.
2. **Riapplicare 5 righe** di aggancio (2 in `chat.js`, 2 in `tts-ai.js`, 1 in
   `voiceRecorder.js`) e filtro `extractPlainText`.
3. **Ricontrollare `tts_routes.py`**: se hanno corretto blocco loro, lasciare
   stare. Ma rotta `GET /stream` e `synthesize_stream()` vanno riapplicate
   comunque: sono nostre, non correzioni loro.
3-bis. **Rimettere ramo `stream`** in `voiceRecorder.js` e `stt_service.py`, e
   rotta WebSocket in `stt_routes.py`. Senza, microfono ricade sul giro a
   lotti: funziona, ma torna a non dire parola fino allo stop.
4. **Reinserire blocchi HTML e CSS.**
5. File nuovi non danno conflitti.

Nessuna modifica tocca logica dell'agente, sicurezza o database: sono
tutte a livello di presentazione o correzioni puntuali.
