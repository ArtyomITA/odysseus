# Modifiche al core di Odysseus

Registro completo di cosa abbiamo toccato del codice originale. Serve per due
motivi: rifare le modifiche dopo un aggiornamento del repository, e capire cosa
potrebbe entrare in conflitto.

**Principio seguito:** dove esiste un punto di estensione ufficiale (skill,
preset, MCP, impostazioni) lo si usa. Il core si tocca solo quando non c'è
alternativa, e con modifiche minime.

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
`NameError: name 'Any' is not defined` alla riga 1503. È un bug del merge sul ramo
`main`. Da ricontrollare a ogni aggiornamento; varrebbe una segnalazione a monte.

### `routes/tts_routes.py` — l'endpoint bloccava tutto il server

```python
# prima
async def synthesize_speech(request: TTSRequest):
# dopo
def synthesize_speech(request: TTSRequest):
```

Il gestore era dichiarato asincrono ma dentro chiamava la rete in modo
**bloccante**. Risultato: durante ogni sintesi vocale l'intero server si
congelava. Con la lettura frase per frase attiva, succedeva di continuo.

Togliendo `async`, FastAPI sposta da sé il gestore su un thread separato. Nel file
c'è il commento che spiega perché è deliberato.

---

## A-bis. Voce in streaming (1 agosto 2026)

Quattro punti raccoglievano l'audio intero prima di passarlo, annullando lo
streaming che PocketTTS faceva già. Misure e dettaglio in
[05-voce-tts-stt.md](05-voce-tts-stt.md) e
[ricerche/voce-streaming-misure.md](../../../ricerche/voce-streaming-misure.md).

| File | Modifica |
|---|---|
| `services/tts/tts_service.py` | **nuovo** `synthesize_stream()` con `httpx.stream()`; la cache si riempie duplicando il flusso mentre passa, e si scrive solo se l'ultimo pezzo esce |
| `routes/tts_routes.py` | **nuova** rotta `GET /api/tts/stream`; il primo pezzo viene estratto per decidere il tipo di contenuto e poi reimmesso |
| `routes/stt_routes.py` | **nuovo** `WS /api/stt/stream`: inoltra il microfono al ponte e il testo indietro |
| `services/stt/stt_service.py` | riconosce il provider `stream` |
| `static/js/tts-ai.js` | `_streamUrl()`, `forSpeech()`, `_spezza()`, eventi `odysseus:tts-start/end`; `_prefetch()` ora crea l'elemento `<audio>` invece di riempire una cache di blob |
| `static/js/voiceRecorder.js` | ramo `stream`: microfono in diretta, niente `MediaRecorder` |

**Perché GET e non POST** per la sintesi: un elemento `<audio>` si può solo
puntare a una URL. Tutto ciò che si scarica a mano finisce in un Blob, e un Blob è
completo per definizione — cioè reintroduce l'attesa che si stava togliendo.
Sopra i 1.600 caratteri si torna al POST.

**Perché il microfono passa da Odysseus** invece che dritto al ponte: la CSP
dichiara `connect-src 'self'`. Inoltrare costa 50 ms ed evita di allargarla.

---

## B. Agganci per l'avatar

### `static/js/chat.js` riga ~2320 — eventi del flusso

```javascript
if (!_isBg) window.OdysseusAvatar?.handleStreamEvent(json);
```

Una riga, inserita **prima** del filtro esistente sui tipi di evento, nel
dispatcher unico degli eventi SSE. Passa ogni evento al nucleo dell'avatar, che ne
ricava lo stato (pensa / lavora / parla / fermo). Il controllo `!_isBg` esclude le
conversazioni in background.

### `static/js/chat.js` riga ~2238 — fine del flusso

```javascript
if (!_isBg) window.OdysseusAvatar?.handleStreamEnd();
```

Dentro il ramo `if (data === '[DONE]')`. Riporta l'avatar a riposo.

### `static/js/tts-ai.js` — audio verso avatar e dispositivo scelto

Due punti, perché ci sono due percorsi di riproduzione:

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

**Trappola in cui siamo caduti:** avevamo agganciato solo il primo percorso, che
in pratica non viene mai usato. Il pulsante di lettura e il parlato automatico
passano entrambi dalla coda.

### `static/js/tts-ai.js` — `extractPlainText`, il filtro del ragionamento

```javascript
let cleaned = content
    .replace(/<think(?:ing)?\b[^>]*>[\s\S]*?<\/think(?:ing)?>/gi, '')
    .replace(/<think(?:ing)?\b[^>]*>[\s\S]*$/i, '');
```

Due cambiamenti rispetto all'originale:
1. `\b[^>]*` per accettare gli attributi: Odysseus riscrive il tag come
   `<think time="2.4">` a fine ragionamento, e il vecchio filtro non lo matchava.
2. La seconda `replace` toglie il blocco **ancora aperto**.

Questa seconda riga risolve **due bug in uno** (vedi
[08-trappole-e-scoperte.md](08-trappole-e-scoperte.md)).

### `static/js/voiceRecorder.js` — microfono scelto

```javascript
navigator.mediaDevices.getUserMedia(
  window.OdysseusAudioDevices?.micConstraints() || { audio: true })
```

Onora il microfono selezionato nelle impostazioni; ripiega sul predefinito.

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
2. **Cinque tag script** (librerie Live2D + nostri moduli). L'ordine conta:
   Cubism Core, PixiJS, **la toppa unsafe-eval**, la libreria Live2D, poi i moduli.
3. **Due schede nel pannello Aspetto**: "Dispositivi audio" (microfono, uscita,
   pulsante rileva) e "Live2D avatar" (interruttore, scelta modello, personalità).
4. **Pulsante voce riabilitato**: era
   `<button id="overflow-tts-btn" hidden style="display:none">` con il commento
   *"read-aloud feature is off in this build"*. Tolti `hidden` e lo stile,
   rinominato "Voce".

### `static/style.css`

Blocco in fondo per il riquadro dell'avatar: posizione fissa, trascinabile
(`cursor: grab`, `touch-action: none`), barra dei pulsanti che appare al
passaggio del mouse, maniglia di ridimensionamento nell'angolo, nascosto sotto i
900px di larghezza.

Secondo blocco: `.model-loading-*` (overlay di caricamento del modello) e
`.model-blind-badge` (pastiglia "senza vista").

---

## C-bis. Caricamento dei modelli e rilevamento della vista

Dettaglio completo e misure in
[12-caricamento-modelli-e-vista.md](12-caricamento-modelli-e-vista.md).

### `src/chat_helpers.py` — `model_supports_vision()`

Consulta llama-swap **prima** dell'euristica sul nome, con lo stesso schema già
usato per LM Studio. Senza questo, `qwenpaw-vista` e `heretic-vista` risultavano
ciechi (nessuna parola chiave nel nome) e Odysseus **toglieva l'immagine dalla
richiesta** pur avendo il proiettore caricato.

### `src/agent_loop.py` — `_drop_image_only_tools()`

Nuova funzione più una riga di chiamata subito dopo `_expand_browser_mcp_tools`.
Toglie `Screenshot` e `browser_take_screenshot` quando llama.cpp dichiara
`modalities.vision = false`. Confronto sul nome nudo, perché il nome qualificato
MCP contiene l'identificativo del server (da noi un UUID). Filtra **solo** su un
no esplicito.

### `routes/model_routes.py` — due rotte nuove

`GET /api/model-runtime/status` e `POST /api/model-runtime/warmup`, più
`_resolve_known_endpoint()` che accetta solo endpoint già configurati (l'URL
arriva dal browser: prenderlo per buono sarebbe una falla SSRF).

### `static/js/modelPicker.js`

Un import e `_warmupPicked(m)` sulle due uscite riuscite di `_pick()`.

---

## C-ter. ShadowBroker: pannello, strumenti, modalità dedicata

Dettaglio in [13](13-shadowbroker-dentro-odysseus.md) (collegamento),
[14](14-agente-osint.md) (orchestrazione), [15](15-shadowbroker-come-funziona.md) (dati).

| File | Modifica |
|---|---|
| `core/middleware.py` | `_shadowbroker_frame_src()`: la CSP impara l'origine del cruscotto (entrambe le forme, `127.0.0.1` e `localhost`, che per un browser sono origini diverse) |
| `routes/chat_routes.py` | flag `osint_mode`: col pannello aperto restringe la dotazione ai soli strumenti OSINT |
| `src/tool_schemas.py` | in fondo, estende `FUNCTION_TOOL_SCHEMAS` con i dieci schemi OSINT |
| `src/agent_tools/__init__.py` | registra gli handler OSINT e i loro tag; import protetto — ShadowBroker è opzionale |
| `static/js/chat.js` | manda `osint_mode=true` quando il pannello è aperto |
| `static/js/tts-ai.js` | `_prefetch()`: sintetizza il blocco N+1 mentre suona il blocco N |
| `static/index.html` | pulsante barra, voce Strumenti, contenitore del pannello |
| `static/style.css` | blocco `.sb-*` |

---

## D. File nuovi (nessun conflitto con gli aggiornamenti)

### Moduli Python

| File | Ruolo |
|---|---|
| `src/llamaswap.py` | stato di caricamento dei profili, lettura di `/props`, avvio di un profilo |
| `src/shadowbroker/client.py` | HTTP con backoff, batch, comandi vietati, `radius` corretto |
| `src/shadowbroker/store.py` | magazzino per layer, identificativi stabili, schede intere |
| `src/shadowbroker/sagome.py` | che campi tenere per ogni layer |
| `src/shadowbroker/geo.py` | distanze vere, nomi dei posti, 60+ luoghi noti |
| `src/shadowbroker/testo.py` | recupero articoli, titoli marcati non cancellati |
| `src/shadowbroker/briefing.py` | **i cinque briefing precalcolati** |
| `src/shadowbroker/entita.py` | composizione annidata delle schede entità |
| `src/shadowbroker/schemi.py` | i dieci schemi degli strumenti |
| `src/agent_tools/shadowbroker_tools.py` | i dieci handler |
| `routes/shadowbroker_routes.py` | scoperta e sonda di vitalità del cruscotto |

### Moduli JavaScript

| File | Ruolo |
|---|---|
| `static/js/avatarCore.js` | macchina a stati, lettura tag emozione, analisi audio per il labiale |
| `static/js/avatarRenderer.js` | disegna il Live2D, applica i comandi |
| `static/js/avatarDock.js` | riquadro in pagina, trascinamento, scelta modello, stacco widget |
| `static/js/avatarPersona.js` | compone e salva il preset personalità + emozioni |
| `static/js/avatarWidget.js` | punto d'ingresso della finestra staccata |
| `static/js/avatarSelfTest.js` | diagnostica della catena Live2D |
| `static/js/audioDevices.js` | scelta microfono e uscita audio |
| `static/js/modelLoading.js` | overlay di caricamento del modello, capacità del profilo, pastiglia "senza vista" |
| `static/js/shadowbroker.js` | pannello ShadowBroker: apri, chiudi, sonda, iframe tenuto vivo |
| `static/js/shadowbrokerBoot.js` | aggancia i pulsanti senza effetti collaterali sull'import |
| `static/js/asrStreaming.js` | microfono in diretta: WebSocket, silenziamento durante il parlato |
| `static/js/asrWorklet.js` | preleva il microfono a pezzi da 100 ms, gia' in PCM 16 bit |

### Fuori dal repository (`d:\assistenteeee\voce\`)

| File | Ruolo |
|---|---|
| `asr_streaming.py` | **nuovo** — carica Nemotron-3.5 una volta sola, una `Sessione` per microfono aperto |
| `ponte_voce.py` | `WS /v1/audio/stream`, sintesi in streaming, riscaldamento del modello all'avvio |

### Prove

| File | Cosa verifica |
|---|---|
| `tests/prova_tts_spezzettamento.mjs` | 16 casi: filtro emoji/parentesi, i tre tagli, il contatore che non slitta |
| `scripts/prova_asr_streaming.py` | RTF e ritardo per pezzo del riconoscitore |
| `scripts/prova_asr_finiturno.py` | quando scatta la fine turno, per tre soglie |
| `scripts/prova_ws_trascrizione.py` | la catena WebSocket, a orario fisso come un microfono vero |
| `scripts/prova_relay_stt.py` | il tramite di Odysseus, montato senza autenticazione su porta usa e getta |
| `scripts/misura_voce_primo_suono.py` | tempo al **primo** byte di audio nei tre punti della catena |

### Modifiche dentro ShadowBroker (repo separato)

| File | Modifica |
|---|---|
| `backend/services/openclaw_channel.py` | `VIEW_COMMANDS` + `map_focus`, `set_layers`, `highlight` |
| `frontend/src/hooks/useAgentActions.ts` | due azioni nuove, polling 3000ms → 700ms |
| `frontend/src/lib/agentLayerMap.ts` | **nuovo** — traduce i nomi dei layer nei tasti dell'interfaccia |
| `frontend/src/app/page.tsx` | stato delle evidenziazioni, ripristino dei livelli dell'operatore |
| `frontend/src/components/MaplibreViewer.tsx` | livello evidenziazioni; `flyTo` ora rispetta lo zoom (era fisso a 8) |
| `frontend/src/types/dashboard.ts` | tipo della prop `agentHighlights` |
| `frontend/next.config.ts` + `src/proxy.ts` | `frame-ancestors` da variabile d'ambiente, `X-Frame-Options` tolto quando serve |

### Pagine e stili

- `static/avatar.html` — finestra widget staccabile
- `static/avatar-widget.css` — stile della finestra
- `static/avatar-test.html` — pagina di autodiagnosi

### Librerie (`static/lib/`)

| File | Origine | Nota |
|---|---|---|
| `live2dcubismcore.min.js` | cubism.live2d.com | **da servire immutato**, licenza proprietaria |
| `pixi.min.js` | PixiJS 7.4.2 | |
| `pixi-unsafe-eval.min.js` | @pixi/unsafe-eval 7.4.2 | **indispensabile**, vedi trappole |
| `live2d-cubism4.min.js` | pixi-live2d-display-lipsyncpatch 0.5.0-ls-8 | variante con labiale |

### Risorse

- `static/live2d/mao_pro/` — il modello Live2D (Niziiro Mao, licenza Free Material)

---

## E. Dati e configurazione (non è codice, ma va ricordato)

- `data/settings.json` — modelli per ruolo, voce, trascrizione, ricerca
- `data/presets.json` — la personalità (slot `custom`)
- `data/skills/` — 13 skill installate in 4 categorie
- `data/app.db` — endpoint dei modelli e server MCP registrati

Vedi [09-configurazione.md](09-configurazione.md) per il dettaglio delle chiavi.

---

## Riassunto per l'aggiornamento

Se un giorno si aggiorna Odysseus da monte, l'ordine di lavoro è:

1. **Ricontrollare l'import `Any`** in `agent_loop.py`: se il bug è ancora lì,
   riapplicare.
2. **Riapplicare le 5 righe** di aggancio (2 in `chat.js`, 2 in `tts-ai.js`, 1 in
   `voiceRecorder.js`) e il filtro `extractPlainText`.
3. **Ricontrollare `tts_routes.py`**: se hanno corretto il blocco loro, lasciare
   stare. Ma la rotta `GET /stream` e `synthesize_stream()` vanno riapplicate
   comunque: sono nostre, non correzioni loro.
3-bis. **Rimettere il ramo `stream`** in `voiceRecorder.js` e `stt_service.py`, e
   la rotta WebSocket in `stt_routes.py`. Senza, il microfono ricade sul giro a
   lotti: funziona, ma torna a non dire una parola fino allo stop.
4. **Reinserire i blocchi HTML e CSS.**
5. I file nuovi non danno conflitti.

Nessuna modifica tocca la logica dell'agente, la sicurezza o il database: sono
tutte al livello di presentazione o correzioni puntuali.
