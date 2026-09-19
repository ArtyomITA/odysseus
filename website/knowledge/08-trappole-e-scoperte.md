# Trappole e scoperte

Cose costate tempo, e cose che hanno risparmiato lavoro. Ordinate per costo.

---

## 1. PixiJS richiede `unsafe-eval`, che la sicurezza di Odysseus vieta

**Sintomo:** avatar non compariva. Nessun errore visibile — il codice catturava
l'eccezione e nascondeva il riquadro in silenzio.

**Diagnosi:** pagina di autodiagnosi (`static/avatar-test.html` +
`static/js/avatarSelfTest.js`), eseguita in browser headless. Verdetto:

```
Current environment does not allow unsafe-eval, please use @pixi/unsafe-eval module to enable support.
```

**La ricerca diceva il contrario**, ma parlava del **Cubism Core** (pulito:
verificato in sandbox con WebAssembly disabilitato). Nessuno aveva controllato
PixiJS, che per gli shader usa `new Function`.

**Soluzione:** `@pixi/unsafe-eval` stessa versione, caricato **subito dopo**
`pixi.min.js`. Si applica da solo al caricamento (rimpiazza due metodi del
sistema shader), niente da chiamare. **Nessuna modifica alla sicurezza di
Odysseus.**

**Lezione:** un `try/catch` che nasconde l'interfaccia senza dire niente è
peggio di un crash. Ricerche da verificare componente per componente.

---

## 2. Le pagine statiche non ricevono il nonce: niente script inline

Sicurezza Odysseus: `script-src 'self' 'nonce-...'`. Nonce iniettato **solo in
`index.html`**, da funzione dedicata del backend. Pagine da `/static/`
**non lo ricevono**: ogni `<script>` inline muore in silenzio.

Colpite pagina di test e finestra widget avatar.

**Regola:** codice in file `.js` esterni, passano con `'self'`.

---

## 3. Il modello Live2D non aveva il parametro che pilotavo

**Sintomo:** avatar si muoveva (respiro, battito ciglia) ma **la bocca no**,
nemmeno con audio in corso.

**Diagnosi:** file config del modello. Gruppo labiale di `mao_pro` dichiara
**`ParamA`** (forma bocca vocale A). Pilotavo `ParamMouthOpenY`, standard negli
esempi — che questo modello **non ha**. Scrivere su parametro inesistente in
Cubism fallisce senza errore.

**Soluzione:** renderer ora **legge dal modello stesso** quali parametri usare
(`motionManager.lipSyncIds`). Vale per qualunque personaggio futuro.

---

## 4. L'analizzatore audio scavalca la scelta del dispositivo di uscita

**Sintomo:** utente sceglie cuffie, audio esce dalla cassa bluetooth.

**Causa non ovvia:** collegando l'audio a un analizzatore per il labiale, la
riproduzione **smette di passare dall'elemento audio** e passa dal motore Web
Audio, con uscita propria che ignora il dispositivo impostato sull'elemento.

Selezione funzionava: scavalcata dall'avatar stesso.

**Soluzione:** applicare dispositivo anche al motore audio, riapplicarlo al
volo quando l'utente cambia scelta.

---

## 5. Il filtro del ragionamento: un bug, due sintomi

**Sintomi:** (a) assistente **leggeva ad alta voce il ragionamento**; (b) voce
partiva **solo alla fine**, non frase per frase.

**Causa unica:** filtro che toglie il blocco ragionamento funzionava **solo su
blocchi chiusi**. Mentre la risposta arriva il blocco è ancora aperto:

- ragionamento passava e veniva letto (sintomo a);
- alla chiusura del blocco, il testo "pulito" **si accorciava di colpo**. Il
  contatore di avanzamento lettura restava più avanti del testo, e la
  condizione `plainText.length <= _streamSentencesSent` bloccava tutto per il
  resto del turno (sintomo b).

**Soluzione:** togliere anche il blocco aperto, accettare attributi nel tag
(Odysseus riscrive `<think>` come `<think time="2.4">` a fine ragionamento).

---

## 6. L'aggancio del labiale era sul percorso sbagliato

Audio collegato all'avatar solo nel metodo di riproduzione singola, **mai
usato**. Sia pulsante di lettura sia parlato automatico passano dalla **coda**.

Una riga, ma finché non trovata l'avatar non muoveva mai la bocca.

---

## 7. L'endpoint di sintesi bloccava l'intero server

`POST /api/tts/synthesize` dichiarato `async` ma dentro chiamava la rete in
modo **bloccante**: congelava tutto Odysseus per la durata di ogni sintesi. Con
lettura frase per frase, di continuo.

Corretto togliendo `async` (FastAPI sposta i gestori sincroni su un thread).

---

## 8. Odysseus non partiva: import mancante nel loro codice

`NameError: name 'Any' is not defined`. Bug del merge su `main`: usano `Any`
senza importarlo. Una riga.

---

## 9. Il formato delle skill: invisibili senza errore

SKILL.md formato Claude hanno solo `name` e `description` nel frontmatter.
Odysseus richiede anche **`status: published` e `category`**, altrimenti la
skill non compare — **senza errore**.

---

## 10. L'endpoint dei preset voleva JSON, non un form

`POST /api/presets/custom` accetta corpo JSON (modello Pydantic). Form
multipart risponde errore. Altre API Odysseus (endpoint modelli, server MCP)
usano invece form: nessuna coerenza, va guardato caso per caso.

---

## 11. Il parlato saltava pezzi di risposta: tre difetti sovrapposti

Sintomo: risposta a schermo era
*"Ciao! Sono pronto\n\nSto già aspettando per provare le funzionalità che hai in
mente. Fammi sapere quando sei pronto e possiamo iniziare!"*, voce ha detto solo
un frammento.

Tre bug distinti in `static/js/tts-ai.js` e `static/js/chat.js`, stessa
direzione: **perdita silenziosa di testo**.

### 11a. Unità di misura diverse per lo stesso contatore — la causa principale

`_streamSentencesSent` è **offset in caratteri sul testo dell'intero turno**.
Le due estremità gli davano stringhe diverse:

```
chat.js:2605   streamingUpdate(roundText)     <- azzerato a OGNI giro dell'agente
chat.js:3679   streamingEnd(accumulated)      <- l'intero messaggio, mai azzerato
```

Dal secondo giro l'offset punta **oltre** la fine del nuovo `roundText`, quindi
`plainText.length <= this._streamSentencesSent` esce subito: quel giro non
viene mai pronunciato. Poi `streamingEnd` taglia `accumulated` a offset
calcolato su altra stringa, ne esce un pezzo qualunque.

Riprodotto con due giri (`Ciao! Sono pronto.` + resto):

```
PRIMA: "Ciao! Sono pronto."
       "per provare le funzionalità che hai in mente."
       "à che hai in mente. Fammi sapere quando sei pronto e possiamo iniziare!"
       perse: "Sto già aspettando"   ripetizioni: sì

DOPO:  "Ciao! Sono pronto."
       "Sto già aspettando per provare le funzionalità che hai in mente."
       "Fammi sapere quando sei pronto e possiamo iniziare!"
       perse: nessuna                ripetizioni: no
```

Taglio a metà parola (`"à che hai in mente"`) è la firma del bug.

Correzione: `streamingUpdate(accumulated)`.

### 11b. Le frasi sotto i 15 caratteri sparivano

```js
if (sentence.length < 15) { advancedChars += sentence.length + 1; continue; }
```

Frase corta **avanzava il contatore senza essere mai messa in coda**. Saluto
`"Ciao!"` (5 caratteri) consumato e mai detto. Nessun log.

Verificato sul testo reale: `parole perse: Ciao!`.

Correzione: frasi corte non si buttano, si **incollano alla successiva**. Se
restano corte a fine turno, `streamingEnd` le pronuncia comunque (prima stessa
soglia `>= 15`: risposta finita con frase breve perdeva la chiusura).

### 11c. Il contatore andava a deriva sui capoversi

`advancedChars += sentence.length + 1` presume **esattamente un** carattere di
separazione. Con capoverso (`"\n\n"`) ne consuma due e ne conta uno: regione
successiva parte un carattere troppo indietro, pezzo si ripete.

Correzione: si contano caratteri **grezzi** effettivamente consumati
(`chunk.length`, spazi inclusi), non quelli della frase ripulita.

### Nota su "premuto stop"

`stop()` mette `_streamActive = false`. Se il modello scrive ancora, tutti gli
aggiornamenti successivi e `streamingEnd` escono subito: **resto del turno non
letto**. Comportamento voluto (stop vuol dire stop), pulsante di riascolto sul
messaggio finito rilegge tutto da capo — ma sembra un bug, va saputo.

---

## 12. ShadowBroker: i difetti che mentono in silenzio

Elenco completo in [15-shadowbroker-come-funziona.md](15-shadowbroker-come-funziona.md).
Qui i tre che producono **risposte sbagliate senza errore** — i peggiori.

### 12a. Il raggio si chiama `radius`, gli altri nomi vengono ignorati

```
radius_km=50     -> applica 500 miglia
radius_miles=50  -> applica 500 miglia
radius=50        -> applica 50 miglia
```

"Notizie entro 50 km da Kyiv" restituiva **Mosca e Varsavia**. Nessun avviso:
nome sconosciuto buttato, ricade sul predefinito.

### 12b. `brief_area` mescola locale e mondiale

`nearby` è davvero vicino. `context_layers` sono i primi N **globali senza
filtro**. Chiedendo zona di Kyiv, terremoti in Filippine, Indonesia, Cina.
Modello che legge quel blocco dice 5.1 vicino a Kyiv.

### 12c. Più processi in LISTEN sulla stessa porta

`main.py` avvia uvicorn con reload, genera figli via `multiprocessing.spawn`.
Uccidendo il padre il figlio resta in ascolto, e **Windows permette a più
processi di restare in LISTEN sulla stessa porta**.

Conseguenza reale: **prime misure andate al processo vecchio senza segnale**,
per un'ora GT sembrava spento mentre in realtà parlavo con backend che non
aveva mai letto la variabile.

Per riavviare vanno uccisi anche i figli `multiprocessing.spawn`.

### 12d. Il mio filtro dei titoli cancellava le notizie

Prima versione toglieva spazi prima di controllare se titolo fosse
identificativo. "Russia Pounds Kyiv With Missiles" diventava stringa
alfanumerica di 28 caratteri, finiva fra gli scarti. **Filtro cancellava
proprio le notizie da salvare.** Trovato misurando, non rileggendo.

Regola: filtro che scarta va sempre provato su ciò che deve **tenere**, non
solo su ciò che deve buttare.

---

## 13. Quattro strati che annullavano lo streaming di sotto

PocketTTS trasmetteva **già** in streaming: `StreamingResponse`, intestazione
WAV con `nframes` a un miliardo apposta per essere letta prima che il file
esista, nessun pre-buffer. Documentazione: *"primo pezzo in ~200 ms"*.

Vantaggio non arrivava mai al browser. Annullato **quattro volte**:

```
voce/ponte_voce.py          await client.post(...)  ->  resp.content
services/tts/tts_service.py httpx.post(...)
routes/tts_routes.py        Response(content=audio_data)
static/js/tts-ai.js         await response.blob()
```

Ognuno preso da solo sembra innocuo — modo normale di fare richiesta HTTP.
Costo: **5,80 secondi invece di 0,98** su frase da 132 caratteri.

**Lezione:** quando un componente a monte dichiara latenza molto migliore di
quella osservata, colpevole quasi mai lui. Va misurato **ogni salto**, non solo
i capi della catena (`scripts/misura_voce_primo_suono.py` fa esattamente
questo).

### 13a. `\p{Emoji_Component}` contiene le cifre 0-9

Filtro scritto per togliere emoji dal testo da pronunciare. Classe Unicode che
sembra giusta per "tutti i pezzi delle emoji" **include cifre e cancelletto**,
servono a comporre tasti tipo `1️⃣`.

Usarla avrebbe tolto **tutti i numeri dalle risposte** — su assistente OSINT,
esattamente i dati. Preso da prova scritta apposta, non rileggendo.

Si usano `\p{Extended_Pictographic}`, `\p{Emoji_Modifier}`,
`\p{Regional_Indicator}` e selettori di variazione espliciti.

### 13b. Il filtro non può stare dove sembra naturale

Posto ovvio per ripulire il testo era `extractPlainText()`. Sbagliato: il
contatore di scorrimento streaming **indicizza dentro quella stringa**, filtro
lì può farla accorciare a metà flusso.

Parentesi ancora aperta al confine del pezzo (`"...la mappa (vedi"`) sopravvive
a un aggiornamento e sparisce al successivo. Contatore slitta, frase riletta o
persa.

**Stesso guasto del punto 5**, causa diversa. Rimedio: filtrare subito prima di
sintetizzare, scostamenti calcolati su testo intatto.

### 13c. PocketTTS salta parole oltre 50 token, in silenzio

Trovato nei log, non da sintomo:

```
Chunk has 182 tokens (max 50), generation may skip words: 'report - Tradurre tra italiano...'
Maximum generation length reached without EOS
```

Elenchi puntati e paragrafi lunghi perdevano pezzi. **Quarto** difetto della
voce, indipendente dai tre del punto 11 — quelli erano JavaScript, questo il
motore. Rimedio: taglio duro a 180 caratteri.

**Lezione:** log dei componenti terze parti vanno letti anche senza sintomo
aperto. Questo stava lì da giorni.

---

## 14. TorchScript "3x più veloce" non voleva dire più veloce di ONNX

Silero VAD v5 annuncia *"3x faster"*. Sembra buon motivo per abbandonare ONNX.

Il 3x confronta **v5-TorchScript con v4-TorchScript**. Stessa tabella, stessa
macchina:

```
v5 ONNX          189 us per pezzo
v5 TorchScript   325 us per pezzo
```

**ONNX 1,7 volte più veloce.** Frase esatta del progetto: *"TorchScript ora è
veloce quanto ONNX"* — ha recuperato, non superato.

**Lezione:** "N volte più veloce" senza termine di paragone scritto accanto non
è un numero, è un titolo.

---

## 15. La prova a orario libero misurava sé stessa

Prima versione di `prova_ws_trascrizione.py` diceva fine turno a **1.638 ms**
dopo l'ultima parola. Valore vero: **870 ms**.

Difetto: dormiva 100 ms *dopo* ogni invio. Sommando tempo di decodifica (~50
ms), ogni pezzo partiva sempre più in ritardo del precedente, a fine 8 secondi
la prova era indietro di quasi un secondo rispetto a microfono vero — che
consegna ogni 100 ms **a prescindere** da quanto ci mette chi ascolta.

Rimedio: orario assoluto (`t0 + n * 0.1`), non `sleep` incrementale.

**Lezione:** prova che simula tempo reale deve rispettare tabella di marcia
fissa, altrimenti misura somma di sé stessa e del sistema.

---

# Le scoperte che ci hanno risparmiato lavoro

## A. Odysseus aveva già il parlato automatico

Riproduzione automatica, spezzettamento per frase mentre risposta arriva, coda
seriale: tutto già scritto. Pulsante **nascosto nel codice** con commento
*"read-aloud feature is off in this build"*.

Non c'era da costruire: da fornire voce e scoprire l'interruttore.

## B. Odysseus ha già il selezionatore semantico degli strumenti

`src/tool_index.py`: indice a embedding, recupera primi k strumenti per
rilevanza, **indicizza anche quelli MCP**. Non dobbiamo costruire il router.

## C. Odysseus aveva già risolto il problema della cache

Commento esplicito nel loro codice: data e ora **non** va messa nel messaggio
di sistema perché cambia ogni minuto e backend locali come llama.cpp calcolano
cache byte per byte — la invaliderebbe a ogni richiesta. Spostata apposta.

Esattamente il problema che il "CacheAligner" di Headroom si limita a
**segnalare**. Già coperto.

## D. `hidden_models`: nascondere modelli dal menu senza disabilitarli

Campo dell'endpoint. Serviva perché i due modelli del ponte vocale comparivano
insieme a QwenPaw (Odysseus accetta solo endpoint tipo "llm" o "immagini",
nessuna categoria voce). Nascosti dal menu, servizio vocale continua a
funzionare perché chiama endpoint per identificativo.

## E. Il proiettore visivo può stare sulla RAM

`--no-mmproj-offload` di llama.cpp. Suggerito dalla scheda del modello heretic
ma vale per tutti: **libera ~900MB di VRAM** con penalità prestazioni minima.
Effetto pratico: con vista attiva il contesto può restare a 32K invece di
scendere a 16K.

## F. La flash attention su Pascal funziona

Era il rischio numero uno del piano. Non solo funziona: **+10% velocità**. E
sblocca cache compressa, il vero premio (contesto raddoppiato).

## G. Kokoro non ha bisogno di CUDA

Odysseus lo supporta solo in modalità GPU, ma via ONNX gira a metà del tempo
reale su CPU, con voci italiane. Alternativa pronta se PocketTTS deludesse.

## H-bis. sherpa-onnx sa già quando hai finito di parlare

Piano prevedeva Silero VAD nel browser per capire fine turno. Non serve:
sherpa-onnx ha `enable_endpoint_detection` con tre regole, misurato scatta a
**870 ms** dall'ultima parola con `rule2_min_trailing_silence=0.5`.

Un modello in meno da servire, un file in meno nella pagina, una configurazione
in meno da sbagliare. Rilevatore voce resterebbe utile solo per interruzione
mentre assistente parla — per ora basta un interruttore.

## H-ter. Le voci del catalogo PocketTTS non passano dalla clonazione

Repo si chiama letteralmente `pocket-tts-without-voice-cloning`: contiene
**embedding già calcolati** di 26 voci, per ogni lingua. Nessun encoder, nessun
accesso condizionato.

Ecco perché `estelle` funziona e clonare un campione no: clonazione ha bisogno
dell'encoder, nel repo condizionato `kyutai/pocket-tts`. Per l'italiano **26
voci** disponibili, di cui solo tre scaricate.

## I. `Snapshot(use_dom=True)` legge il Chrome già autenticato

Windows-MCP estrae il DOM tramite API di accessibilità, non protocollo di
debug. Può leggere il browser con sessioni già aperte, senza aprire porte di
debug.

---

# Contro-verifiche: cose che si dicono in giro e non sono vere

- **"Uno screenshot costa 50.000 token"** — non compare in nessun paper. Misura
  vera ~4.000 per screenshot desktop. Vero divoratore: albero UI **non
  filtrato**, 20.000-80.000.
- **"Più contesto è sempre meglio"** — falso per modelli piccoli: guadagnano
  8-17.5 punti i modelli grandi, **perdono da 1 a 18.8 punti** quelli piccoli.
  Comprimere albero al 22% ha **migliorato** accuratezza di 5 punti.
- **"Le raccolte hanno 1000+ skill pronte"** — la più citata è indice di link in
  README. Skill vere quasi tutte di argomento aziendale.
- **"SearXNG dà risultati migliori"** — forse, ma `ddgs` nel 2026 **non è più
  solo DuckDuckGo**: già aggregatore multi-motore. E raschiano entrambi gli
  stessi motori dallo stesso IP di casa.
- **"Brave Search API ha un piano gratuito"** — **chiuso a febbraio 2026**. Ora
  addebita la carta oltre i 5$ di credito, senza tetto.
- **`WEBUI_CUSTOM_JS` per iniettare codice in Open WebUI** — variabile **non
  esiste**, malgrado i blog la citino.
