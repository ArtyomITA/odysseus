# Trappole e scoperte

Le cose che ci sono costate tempo, e quelle che ci hanno risparmiato lavoro.
Ordinate per quanto sono state costose.

---

## 1. PixiJS richiede `unsafe-eval`, che la sicurezza di Odysseus vieta

**Sintomo:** l'avatar non compariva. Nessun errore visibile — perché il mio codice
catturava l'eccezione e nascondeva il riquadro in silenzio.

**Diagnosi:** ho scritto una pagina di autodiagnosi
(`static/avatar-test.html` + `static/js/avatarSelfTest.js`) e l'ho eseguita in un
browser headless. Verdetto:

```
Current environment does not allow unsafe-eval, please use @pixi/unsafe-eval module to enable support.
```

**La ricerca aveva detto il contrario**, ma parlava del **Cubism Core** (che
infatti è pulito: verificato eseguendolo in una sandbox con WebAssembly
disabilitato). Nessuno aveva controllato PixiJS, che per il suo sistema di shader
usa `new Function`.

**Soluzione:** `@pixi/unsafe-eval` della stessa versione, caricato **subito dopo**
`pixi.min.js`. Si applica da solo al caricamento (rimpiazza due metodi del sistema
shader), non serve chiamare niente. **Nessuna modifica alla sicurezza di Odysseus.**

**Lezione:** un `try/catch` che nasconde l'interfaccia senza dire niente è peggio
di un crash. E le ricerche vanno verificate componente per componente.

---

## 2. Le pagine statiche non ricevono il nonce: niente script inline

La sicurezza di Odysseus è `script-src 'self' 'nonce-...'`. Il nonce viene
iniettato **solo in `index.html`** da una funzione dedicata del backend. Le pagine
servite da `/static/` **non lo ricevono**, quindi ogni `<script>` scritto dentro
l'HTML muore in silenzio.

Ha colpito sia la pagina di test sia la finestra widget dell'avatar.

**Regola:** tutto il codice in file `.js` esterni, che passano con `'self'`.

---

## 3. Il modello Live2D non aveva il parametro che pilotavo

**Sintomo:** l'avatar si muoveva (respiro, battito di ciglia) ma **la bocca no**,
nemmeno mentre l'audio suonava.

**Diagnosi:** ho letto il file di configurazione del modello. Il gruppo labiale di
`mao_pro` dichiara **`ParamA`** (la forma della bocca per la vocale A). Io
pilotavo `ParamMouthOpenY`, che è quello di tutti gli esempi standard — e che
questo modello **non ha**. Scrivere su un parametro inesistente in Cubism
fallisce senza errore.

**Soluzione:** il renderer ora **legge dal modello stesso** quali parametri usare
(`motionManager.lipSyncIds`). Vale per qualunque personaggio si scarichi in futuro.

---

## 4. L'analizzatore audio scavalca la scelta del dispositivo di uscita

**Sintomo:** l'utente sceglie le cuffie, l'audio esce dalla cassa bluetooth.

**Causa non ovvia:** nel momento in cui si collega l'audio a un analizzatore per
il labiale, la riproduzione **smette di passare dall'elemento audio** e passa dal
motore Web Audio. Quel motore ha una sua uscita, che ignora completamente il
dispositivo impostato sull'elemento.

Quindi la selezione funzionava: veniva scavalcata proprio dall'avatar.

**Soluzione:** applicare il dispositivo anche al motore audio, e riapplicarlo al
volo quando l'utente cambia scelta.

---

## 5. Il filtro del ragionamento: un bug, due sintomi

**Sintomi:** (a) l'assistente **leggeva ad alta voce il ragionamento**; (b) la
voce partiva **solo alla fine**, invece che frase per frase.

**Causa unica:** il filtro che toglie il blocco di ragionamento funzionava **solo
su blocchi chiusi**. Mentre la risposta arriva il blocco è ancora aperto, quindi:

- il ragionamento passava e veniva letto (sintomo a);
- quando il blocco si chiudeva, il testo "pulito" **si accorciava di colpo**. Il
  contatore che tiene il segno di dove è arrivata la lettura restava più avanti
  del testo, e la condizione `plainText.length <= _streamSentencesSent` bloccava
  tutto per il resto del turno (sintomo b).

**Soluzione:** togliere anche il blocco aperto, e accettare gli attributi nel tag
(Odysseus riscrive `<think>` come `<think time="2.4">` a fine ragionamento).

---

## 6. L'aggancio del labiale era sul percorso sbagliato

Avevo collegato l'audio all'avatar solo nel metodo di riproduzione singola, che in
pratica **non viene mai usato**. Sia il pulsante di lettura sia il parlato
automatico passano dalla **coda**.

Una riga, ma finché non l'ho trovata l'avatar non muoveva mai la bocca.

---

## 7. L'endpoint di sintesi bloccava l'intero server

`POST /api/tts/synthesize` era dichiarato `async` ma dentro chiamava la rete in
modo **bloccante**: congelava tutto Odysseus per la durata di ogni sintesi. Con la
lettura frase per frase, di continuo.

Corretto togliendo `async` (FastAPI sposta i gestori sincroni su un thread).

---

## 8. Odysseus non partiva: import mancante nel loro codice

`NameError: name 'Any' is not defined`. Bug del merge sul ramo `main`: usano `Any`
senza importarlo. Una riga.

---

## 9. Il formato delle skill: invisibili senza errore

Le SKILL.md in formato Claude hanno solo `name` e `description` nel frontmatter.
Odysseus richiede anche **`status: published` e `category`**, altrimenti la skill
non compare — **senza dare errore**.

---

## 10. L'endpoint dei preset voleva JSON, non un form

`POST /api/presets/custom` accetta un corpo JSON (modello Pydantic). Mandandogli
un form multipart risponde errore. Le altre API di Odysseus (endpoint dei modelli,
server MCP) usano invece i form: non c'è coerenza, va guardato caso per caso.

---

## 11. Il parlato saltava pezzi di risposta: tre difetti sovrapposti

Sintomo riferito: la risposta a schermo era
*"Ciao! Sono pronto\n\nSto già aspettando per provare le funzionalità che hai in
mente. Fammi sapere quando sei pronto e possiamo iniziare!"*, ma la voce ha detto
solo un frammento.

Tre bug distinti in `static/js/tts-ai.js` e `static/js/chat.js`, tutti nella
stessa direzione: **perdita silenziosa di testo**.

### 11a. Unità di misura diverse per lo stesso contatore — la causa principale

`_streamSentencesSent` è un **offset in caratteri sul testo dell'intero turno**.
Ma le due estremità gli davano stringhe diverse:

```
chat.js:2605   streamingUpdate(roundText)     <- azzerato a OGNI giro dell'agente
chat.js:3679   streamingEnd(accumulated)      <- l'intero messaggio, mai azzerato
```

Dal secondo giro in poi l'offset punta **oltre** la fine del nuovo `roundText`,
quindi `plainText.length <= this._streamSentencesSent` fa uscire subito: quel giro
non viene mai pronunciato. Poi `streamingEnd` taglia `accumulated` a un offset
calcolato su un'altra stringa, e ne esce un pezzo qualunque.

Riprodotto con due giri (`Ciao! Sono pronto.` + il resto):

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

Il taglio a metà parola (`"à che hai in mente"`) è la firma di questo bug.

Correzione: `streamingUpdate(accumulated)`.

### 11b. Le frasi sotto i 15 caratteri sparivano

```js
if (sentence.length < 15) { advancedChars += sentence.length + 1; continue; }
```

La frase corta **avanzava il contatore senza essere mai messa in coda**. Un saluto
come `"Ciao!"` (5 caratteri) veniva consumato e mai detto. Nessun log.

Verificato sul testo reale: `parole perse: Ciao!`.

Correzione: le frasi corte non si buttano, si **incollano alla successiva**. Se
restano corte a fine turno, `streamingEnd` le pronuncia comunque (prima aveva la
stessa soglia `>= 15`, quindi una risposta che finiva con una frase breve perdeva
la chiusura).

### 11c. Il contatore andava a deriva sui capoversi

`advancedChars += sentence.length + 1` presume **esattamente un** carattere di
separazione. Con un capoverso (`"\n\n"`) ne consuma due e ne conta uno: la regione
successiva parte un carattere troppo indietro, e il pezzo si ripete.

Correzione: si contano i caratteri **grezzi** effettivamente consumati
(`chunk.length`, spazi inclusi), non quelli della frase ripulita.

### Nota su "premuto stop"

`stop()` mette `_streamActive = false`. Se il modello sta ancora scrivendo, tutti
gli aggiornamenti successivi e `streamingEnd` escono subito: **il resto del turno
non viene più letto**. È il comportamento voluto (stop vuol dire stop), e il
pulsante di riascolto sul messaggio finito rilegge tutto da capo — ma vale la pena
saperlo, perché sembra un bug.

---

## 12. ShadowBroker: i difetti che mentono in silenzio

Elenco completo in [15-shadowbroker-come-funziona.md](15-shadowbroker-come-funziona.md).
Qui i tre che producono **risposte sbagliate senza dare errore** — i peggiori.

### 12a. Il raggio si chiama `radius`, gli altri nomi vengono ignorati

```
radius_km=50     -> applica 500 miglia
radius_miles=50  -> applica 500 miglia
radius=50        -> applica 50 miglia
```

"Notizie entro 50 km da Kyiv" restituiva **Mosca e Varsavia**. Nessun avviso: il
nome sconosciuto viene buttato e si ricade sul predefinito.

### 12b. `brief_area` mescola locale e mondiale

`nearby` è davvero vicino. `context_layers` sono i primi N **globali senza
filtro**. Chiedendo la zona di Kyiv, i terremoti erano in Filippine, Indonesia e
Cina. Un modello che legge quel blocco dice che c'è stato un 5.1 vicino a Kyiv.

### 12c. Più processi in LISTEN sulla stessa porta

`main.py` avvia uvicorn con reload, che genera figli via
`multiprocessing.spawn`. Uccidendo il padre il figlio resta in ascolto, e
**Windows permette a più processi di restare in LISTEN sulla stessa porta**.

Conseguenza reale: **le prime misure sono andate al processo vecchio senza
nessun segnale**, e per un'ora GT è sembrato spento mentre in realtà stavo
parlando con un backend che non aveva mai letto la variabile.

Per riavviare bisogna uccidere anche i figli `multiprocessing.spawn`.

### 12d. Il mio filtro dei titoli cancellava le notizie

La prima versione toglieva gli spazi prima di controllare se un titolo fosse un
identificativo. Così "Russia Pounds Kyiv With Missiles" diventava una stringa
alfanumerica di 28 caratteri e finiva fra gli scarti. **Il filtro cancellava
proprio le notizie che doveva salvare.** Trovato misurando, non rileggendo.

Regola che ne deriva: un filtro che scarta va sempre provato su ciò che deve
**tenere**, non solo su ciò che deve buttare.

---

## 13. Quattro strati che annullavano lo streaming di sotto

PocketTTS trasmetteva **già** in streaming: `StreamingResponse`, intestazione WAV
con `nframes` a un miliardo apposta per essere letta prima che il file esista, e
nessun pre-buffer. La documentazione lo diceva pure: *"primo pezzo in ~200 ms"*.

Quel vantaggio non arrivava mai al browser. Veniva annullato **quattro volte**:

```
voce/ponte_voce.py          await client.post(...)  ->  resp.content
services/tts/tts_service.py httpx.post(...)
routes/tts_routes.py        Response(content=audio_data)
static/js/tts-ai.js         await response.blob()
```

Ognuno preso da solo sembra innocuo — è il modo normale di fare una richiesta
HTTP. Il costo era **5,80 secondi invece di 0,98** su una frase da 132 caratteri.

**Lezione:** quando un componente a monte dichiara una latenza molto migliore di
quella che si osserva, il colpevole non è quasi mai lui. Va misurato **ogni
salto**, non solo i capi della catena (`scripts/misura_voce_primo_suono.py` fa
esattamente questo).

### 13a. `\p{Emoji_Component}` contiene le cifre 0-9

Scritto un filtro per togliere le emoji dal testo da pronunciare. La classe
Unicode che sembra giusta per prendere "tutti i pezzi delle emoji" **include le
cifre e il cancelletto**, perché servono a comporre i tasti tipo `1️⃣`.

Usarla avrebbe tolto **tutti i numeri dalle risposte** — cioè, su un assistente
OSINT, esattamente i dati. Preso da una prova scritta apposta, non rileggendo.

Si usano `\p{Extended_Pictographic}`, `\p{Emoji_Modifier}`,
`\p{Regional_Indicator}` e i selettori di variazione espliciti.

### 13b. Il filtro non può stare dove sembra naturale

Il posto ovvio per ripulire il testo era `extractPlainText()`. Sbagliato: il
contatore di scorrimento dello streaming **indicizza dentro quella stringa**, e un
filtro lì può farla accorciare a metà flusso.

Una parentesi ancora aperta quando cade il confine del pezzo (`"...la mappa
(vedi"`) sopravvive a un aggiornamento e sparisce al successivo. Il contatore
slitta e una frase viene riletta o persa.

È **lo stesso guasto del punto 5**, con una causa diversa. Rimedio: filtrare
subito prima di sintetizzare, così gli scostamenti si calcolano su testo intatto.

### 13c. PocketTTS salta parole oltre 50 token, in silenzio

Trovato nei suoi log, non da un sintomo:

```
Chunk has 182 tokens (max 50), generation may skip words: 'report - Tradurre tra italiano...'
Maximum generation length reached without EOS
```

Elenchi puntati e paragrafi lunghi perdevano pezzi. È un **quarto** difetto della
voce, indipendente dai tre del punto 11 — quelli erano JavaScript, questo è il
motore. Rimedio: taglio duro a 180 caratteri.

**Lezione:** i log dei componenti di terze parti vanno letti anche quando non
c'è nessun sintomo aperto. Questo stava lì da giorni.

---

## 14. TorchScript "3x più veloce" non voleva dire più veloce di ONNX

Silero VAD v5 annuncia *"3x faster"*. Sembra un buon motivo per abbandonare ONNX.

Il 3x confronta **v5-TorchScript con v4-TorchScript**. Nella stessa tabella, sulla
stessa macchina:

```
v5 ONNX          189 us per pezzo
v5 TorchScript   325 us per pezzo
```

**ONNX è 1,7 volte più veloce.** La frase esatta del progetto è *"TorchScript ora
è veloce quanto ONNX"* — ha recuperato, non superato.

**Lezione:** un "N volte più veloce" senza il termine di paragone scritto accanto
non è un numero, è un titolo.

---

## 15. La prova a orario libero misurava sé stessa

La prima versione di `prova_ws_trascrizione.py` diceva che la fine turno scattava
**1.638 ms** dopo l'ultima parola. Il valore vero è **870 ms**.

Il difetto: dormiva 100 ms *dopo* ogni invio. Sommando il tempo di decodifica
(~50 ms), ogni pezzo partiva sempre più in ritardo del precedente, e alla fine
degli 8 secondi la prova era indietro di quasi un secondo rispetto a un microfono
vero — che consegna ogni 100 ms **a prescindere** da quanto ci mette chi ascolta.

Rimedio: orario assoluto (`t0 + n * 0.1`), non `sleep` incrementale.

**Lezione:** una prova che simula il tempo reale deve rispettare una tabella di
marcia fissa, altrimenti misura la somma di sé stessa e del sistema.

---

# Le scoperte che ci hanno risparmiato lavoro

## A. Odysseus aveva già il parlato automatico

Riproduzione automatica, spezzettamento per frase mentre la risposta arriva, coda
seriale: tutto già scritto. Il pulsante era **nascosto nel codice** con il
commento *"read-aloud feature is off in this build"*.

Non c'era da costruire: c'era da fornire una voce e scoprire l'interruttore.

## B. Odysseus ha già il selezionatore semantico degli strumenti

`src/tool_index.py`: indice a embedding che recupera i primi k strumenti per
rilevanza e **indicizza anche quelli MCP**. Non dobbiamo costruire il router.

## C. Odysseus aveva già risolto il problema della cache

C'è un commento esplicito nel loro codice: la data e ora **non** va messa nel
messaggio di sistema perché cambia ogni minuto e i backend locali come llama.cpp
calcolano la cache byte per byte — la invaliderebbe a ogni richiesta. L'hanno
spostata apposta.

È esattamente il problema che il "CacheAligner" di Headroom si limita a
**segnalare**. Già coperto.

## D. `hidden_models`: nascondere modelli dal menu senza disabilitarli

Campo dell'endpoint. Serviva perché i due modelli del ponte vocale comparivano
insieme a QwenPaw (Odysseus accetta solo endpoint di tipo "llm" o "immagini", non
ha una categoria per la voce). Nascosti dal menu, il servizio vocale continua a
funzionare perché chiama l'endpoint per identificativo.

## E. Il proiettore visivo può stare sulla RAM

`--no-mmproj-offload` di llama.cpp. Suggerito dalla scheda del modello heretic ma
vale per tutti: **libera ~900MB di VRAM** con una penalità di prestazioni minima.
Effetto pratico: con la vista attiva il contesto può restare a 32K invece di
scendere a 16K.

## F. La flash attention su Pascal funziona

Era il rischio numero uno del piano. Non solo funziona: **+10% di velocità**. E
sblocca la cache compressa, che è il vero premio (contesto raddoppiato).

## G. Kokoro non ha bisogno di CUDA

Odysseus lo supporta solo in modalità GPU, ma via ONNX gira a metà del tempo reale
su CPU, con voci italiane. Alternativa pronta se PocketTTS deludesse.

## H-bis. sherpa-onnx sa già quando hai finito di parlare

Il piano prevedeva Silero VAD nel browser per capire la fine turno. Non serve:
sherpa-onnx ha `enable_endpoint_detection` con tre regole, e misurato scatta a
**870 ms** dall'ultima parola con `rule2_min_trailing_silence=0.5`.

Un modello in meno da servire, un file in meno nella pagina, una configurazione in
meno da sbagliare. Il rilevatore di voce resterebbe utile solo per l'interruzione
mentre l'assistente parla — e lì per ora basta un interruttore.

## H-ter. Le voci del catalogo PocketTTS non passano dalla clonazione

Il repo si chiama letteralmente `pocket-tts-without-voice-cloning`: contiene gli
**embedding già calcolati** di 26 voci, per ogni lingua. Nessun encoder, nessun
accesso condizionato.

Ecco perché `estelle` funziona e clonare un campione no: la clonazione ha bisogno
dell'encoder, che sta nel repo condizionato `kyutai/pocket-tts`. Per l'italiano ci
sono **26 voci** disponibili, di cui solo tre scaricate.

## I. `Snapshot(use_dom=True)` legge il Chrome già autenticato

Windows-MCP estrae il DOM tramite le API di accessibilità, non tramite il
protocollo di debug. Può quindi leggere il tuo browser con le tue sessioni aperte,
senza aprire porte di debug.

---

# Contro-verifiche: cose che si dicono in giro e non sono vere

- **"Uno screenshot costa 50.000 token"** — non compare in nessun paper. La misura
  vera è ~4.000 per uno screenshot desktop. Il vero divoratore è l'albero UI **non
  filtrato**: 20.000-80.000.
- **"Più contesto è sempre meglio"** — falso per i modelli piccoli: guadagnano
  8-17.5 punti i modelli grandi, **perdono da 1 a 18.8 punti** quelli piccoli.
  Comprimere l'albero al 22% ha **migliorato** l'accuratezza di 5 punti.
- **"Le raccolte hanno 1000+ skill pronte"** — quella più citata è un indice di
  link in un README. Le skill vere sono quasi tutte di argomento aziendale.
- **"SearXNG dà risultati migliori"** — forse, ma `ddgs` nel 2026 **non è più solo
  DuckDuckGo**: è già un aggregatore multi-motore. E raschiano entrambi gli stessi
  motori dallo stesso IP di casa.
- **"Brave Search API ha un piano gratuito"** — **chiuso a febbraio 2026**. Ora
  addebita la carta oltre i 5$ di credito, senza tetto.
- **`WEBUI_CUSTOM_JS` per iniettare codice in Open WebUI** — quella variabile
  **non esiste**, malgrado i blog la citino.
