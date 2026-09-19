# Voce: sintesi, trascrizione, e cosa manca

> **Aggiornato il 1 agosto 2026.** Tutta la catena e' passata allo streaming, in
> entrata e in uscita. Numeri e dettagli in
> [ricerche/voce-streaming-misure.md](../../../ricerche/voce-streaming-misure.md).

## Stato attuale

**Funziona**: l'assistente legge le risposte ad alta voce, in italiano, con voce
locale, e l'avatar muove la bocca a tempo. Il microfono trascrive **mentre
parli** e capisce da solo quando hai finito.

| | prima | adesso |
|---|---|---|
| primo suono (frase da 132 caratteri) | 5,80 s | **0,98 s** |
| primo testo dal microfono | dopo lo stop | **1,2 s mentre parli** |
| fine turno | click | **automatica, ~870 ms di silenzio** |

**Non ancora fatto** (rinviato per scelta): interrompere l'assistente parlandogli
sopra. Per ora il microfono si silenzia mentre l'assistente parla (vedi
"L'eco" piu' sotto).

## La buona notizia: il parlato automatico c'era già

`static/js/tts-ai.js` conteneva già tutto: riproduzione automatica, spezzettamento
per frase mentre la risposta arriva (con le accortezze giuste — non scambia "1."
per fine frase, né le iniziali puntate), soglia minima di 15 caratteri, coda
seriale.

Il pulsante che lo accende esisteva ma era **nascosto nel codice** con il commento
*"read-aloud feature is off in this build"*, insieme all'intera scheda TTS delle
impostazioni.

Quindi non c'era da costruire il parlato: c'era da **fornire una voce** e
**scoprire l'interruttore**.

## L'architettura della voce

```
USCITA (sintesi)
Odysseus  ──chiede in formato OpenAI──►  ponte voce :8013 ──►  PocketTTS :8014
   │                                                              (streaming)
   └── GET /api/tts/stream ──►  <audio> riproduce mentre scarica

ENTRATA (trascrizione in diretta)
browser AudioWorklet 16 kHz  ──WebSocket──►  Odysseus /api/stt/stream
                                                   │ (tramite)
                                                   ▼
                             ponte :8013 /v1/audio/stream ──► Nemotron-3.5
                                                              (sherpa-onnx, CPU)

ENTRATA (giro vecchio, ancora installato come riserva)
file audio intero  ──►  ponte :8013  ──►  ffmpeg  ──►  Parakeet
```

**Nessun buffer in mezzo.** Ogni tappa passa i byte mentre arrivano: chi
raccoglieva tutto prima di consegnare (`resp.content`, `Response(content=...)`,
`await response.blob()`) e' stato riscritto. Erano quattro, e insieme
trasformavano i ~200 ms di primo pezzo di PocketTTS nei 2-6 secondi della frase
intera.

Odysseus sa parlare con un servizio esterno in formato OpenAI (provider
`endpoint:<id>`, chiama `POST {base_url}/audio/speech`). PocketTTS invece espone
`POST /tts` con campi form. Il ponte traduce.

Dettaglio che ha semplificato le cose: **Odysseus chiede sempre formato mp3, ma
poi riconosce il tipo di file dai primi byte** — quindi si può rispondere in WAV
e funziona lo stesso, risparmiando una conversione.

Il ponte è `d:\assistenteeee\voce\ponte_voce.py`, ~130 righe di FastAPI. Espone:
- `POST /v1/audio/speech` → PocketTTS
- `POST /v1/audio/transcriptions` → Parakeet (conversione a 16 kHz mono con ffmpeg)
- `GET /v1/models` → elenco fittizio, serve solo alla sonda di Odysseus
- `GET /health`

Il modello di trascrizione si carica **alla prima richiesta**, non all'avvio: chi
usa solo la sintesi non paga i 2GB di RAM.

## La sintesi: PocketTTS

Kyutai PocketTTS, ~100 milioni di parametri, gira su CPU.

- Avvio: `pocket-tts serve --language italian --quantize --port 8014`
- Prestazioni misurate: **2.3-3.4 secondi per frase**, il modello resta caricato
  (i 6.8 secondi della prima prova erano il caricamento iniziale)
- Dichiarate: 3-4 volte più veloce del tempo reale, primo pezzo di audio in ~200ms,
  234MB di RAM con `--quantize` (che è pure il 27% più veloce)
- Risponde già in streaming

**Voce scelta: `estelle`** (femminile). Nota tecnica: è una voce **francese**
clonata sul modello italiano. Funziona (ascoltata e approvata) ma la voce nativa
italiana è `giovanni`, maschile. Se la pronuncia suonasse strana su qualche parola,
sappiamo dove guardare.

PocketTTS supporta anche la **clonazione** da un campione audio, ma è dietro un
accesso condizionato su HuggingFace: serve accettare i termini e autenticarsi.

### Le altre voci provate

Tutti i campioni sono in `d:\assistenteeee\voice-samples\`.

| Motore | Voci italiane | Giudizio |
|---|---|---|
| **PocketTTS** | giovanni (M), alba/estelle (F) | scelto |
| Kokoro (ONNX) | if_sara (F), im_nicola (M) | buona qualità, **non serve CUDA**: gira a metà del tempo reale su CPU |
| Piper | paola (F), riccardo (M) | il più veloce, più robotico |
| Edge-TTS | Elsa, Isabella, Diego, Giuseppe | **qualità migliore in assoluto**, ma passa dal cloud Microsoft |

Scoperta utile: **Kokoro non ha bisogno di CUDA**. Odysseus lo supporta solo in
modalità GPU, ma via ONNX gira benissimo su CPU. Alternativa pronta se PocketTTS
deludesse.

### Il taglio del testo prima della sintesi

Tre tagli, in `tts-ai.js`:

1. **fine frase**, con le trappole note (`1.` di elenco, `A.` di iniziale)
2. **virgola / punto e virgola / due punti**, ma solo se seguono almeno **25
   caratteri** — lo sguardo in avanti evita di tagliare su un mozzicone
3. **taglio duro a 180 caratteri**

Il terzo esiste per un difetto scoperto nei log: *"Chunk has 182 tokens (max 50),
generation may skip words"*. **PocketTTS salta parole oltre ~50 token, in
silenzio.** Gli elenchi puntati e i paragrafi lunghi ne erano vittima.

### Il filtro per la voce

`AITTSManager.forSpeech()` toglie emoji e caratteri di parentesi (il contenuto
resta) prima della sintesi.

Sta **subito prima di sintetizzare** e non dentro `extractPlainText()`, per un
motivo preciso: il contatore di scorrimento dello streaming indicizza dentro
quella stringa, e un filtro li' puo' farla **accorciare** a meta' flusso — una
parentesi ancora aperta al confine del pezzo sopravvive a un aggiornamento e
sparisce al successivo. E' lo stesso modo di rompersi gia' visto con `<think>`.

Trappola Unicode: `\p{Emoji_Component}` **contiene le cifre 0-9**. Usarla
avrebbe tolto tutti i numeri dalle risposte.

Prove: `tests/prova_tts_spezzettamento.mjs`, 16 casi.

## La trascrizione in diretta: Nemotron-3.5 (predefinita)

`nvidia/nemotron-3.5-asr-streaming-0.6b` confezionato per **sherpa-onnx**,
variante **320 ms int8**, in `d:\assistenteeee\asr-models\`.

- **40 lingue-locali**, italiano dichiarato per flusso con `set_option("language")`
- ~680 MB su disco e in RAM, **zero VRAM**
- **RTF 0,5** con 2 thread: elabora il doppio della velocita' con cui parli
- caricato **all'avvio** del ponte, non alla prima frase (sono ~5 s)

**La fine turno e' dentro sherpa-onnx** (`enable_endpoint_detection`), non serve
un rilevatore di voce a parte:

| `rule2_min_trailing_silence` | scatta dopo l'ultima parola |
|---|---|
| 0,5 s (in uso) | **~870 ms** |
| 0,8 s | 1.100 ms |

Configurabile da variabili d'ambiente: `ASR_MODELLO`, `ASR_LINGUA`, `ASR_THREAD`,
`ASR_SILENZIO`.

**Perche' passa da Odysseus** invece che dritto al ponte: la CSP dichiara
`connect-src 'self'`, quindi il browser non aprirebbe una WebSocket verso :8013.
Il tramite costa 50 ms e evita di allargare la CSP.

Il **worklet sta in un file suo** (`static/js/asrWorklet.js`) e non in una blob
URL, perche' `script-src 'self'` rifiuterebbe `addModule()` su una blob.

## La trascrizione a lotti: Parakeet (riserva)

**Whisper è l'architettura sbagliata** per il tempo reale: elabora sempre finestre
da 30 secondi riempite di silenzio, quindi in streaming paghi tutto ogni volta. E
`large-v3-turbo` non aiuta, perché alleggerisce solo la parte finale.

Scelta: **Parakeet TDT v3 di NVIDIA** — 25 lingue, errore sull'italiano del 3%,
~2GB di RAM, e su CPU a 8 core va **26 volte più veloce del tempo reale**. Tre
secondi di parlato si trascrivono in circa 115 millisecondi.

Installato con `pip install onnx-asr[cpu,hub]`, nativo su Windows.

Resta installato e funzionante come riserva: per tornarci basta rimettere
`stt_provider` a `endpoint:<id>` (`STT_PROVIDER=endpoint:... python
configura_odysseus.py`).

**La conclusione che c'era qui prima — "non serve un servizio microfono sempre
attivo" — non regge piu'.** Era vera finche' si accettava di non vedere una
parola fino allo stop. Con il riconoscitore in streaming il testo arriva a 1,2 s
e il turno si chiude da solo: sono due cose che il giro a lotti non puo' dare,
per costruzione.

## Selezione dei dispositivi audio

Odysseus **non aveva** alcun modo di scegliere microfono o uscita: usava sempre il
predefinito di sistema. Aggiunta in Impostazioni → Aspetto, scheda "Dispositivi
audio".

Due avvertenze oneste:
- I nomi dei dispositivi restano vuoti finché non si concede una volta l'accesso al
  microfono (regola dei browser). Il pulsante "Rileva dispositivi" serve a sbloccarli.
- La scelta dell'**uscita** funziona su Chrome ed Edge, **non su Firefox**, che non
  lo permette. Lì si usa quella di sistema, e l'interfaccia lo dice.

**Trappola non ovvia risolta:** nel momento in cui l'audio viene collegato
all'analizzatore per il labiale dell'avatar, la riproduzione **smette di passare
dall'elemento audio** e passa dal motore Web Audio, che ha una sua uscita e ignora
il dispositivo scelto sull'elemento. Va applicato anche al motore audio.

## Configurazione (il pannello è morto)

La scheda TTS in `index.html` è nascosta di proposito e il codice della
trascrizione punta a elementi che non esistono. Le impostazioni esistono e
funzionano, ma **vanno scritte via API o direttamente nel file**.

Lo fa `d:\assistenteeee\voce\configura_odysseus.py`:
- registra l'endpoint del ponte nel database (usando i modelli di Odysseus, così i
  campi restano coerenti)
- scrive in `data/settings.json`: `tts_enabled`, `tts_provider: endpoint:<id>`,
  `tts_voice: estelle`, `stt_provider`, `stt_language: it`

I due modelli del ponte (`pocket-tts`, `parakeet`) comparivano nel menu dei modelli
insieme a QwenPaw, perché Odysseus accetta solo due tipi di endpoint (llm e
immagini) e non ha una categoria per la voce. Risolto usando il campo
`hidden_models` dell'endpoint, che li nasconde dal selettore **senza disabilitarli**
(il servizio vocale chiama l'endpoint per identificativo, non passa dal menu).

## Cosa manca: l'interruzione

Rinviata per scelta dell'utente, ma la ricerca è fatta. Il piano è in
[ricerche/voce-architettura.md](../../ricerche/voce-architettura.md),
[ricerche/eco-microfono-aec.md](../../ricerche/eco-microfono-aec.md) e
[ricerche/interruzione-testo-non-detto.md](../../ricerche/interruzione-testo-non-detto.md).

I tre problemi difficili, in sintesi:

**1. L'eco.** Senza cuffie l'assistente sente la propria voce e si interrompe da
solo. Attivare la cancellazione d'eco del browser **non basta**: Chrome non "sente"
l'audio riprodotto dalla pagina stessa, cancella solo quello che arriva da una
videochiamata. Il rimedio documentato è far passare la voce attraverso una
connessione WebRTC che la pagina apre verso sé stessa (~30ms di costo).

*Fatto nel frattempo:* l'interruttore di sicurezza c'e'. `tts-ai.js` emette
`odysseus:tts-start` e `odysseus:tts-end`, e `voiceRecorder.js` silenzia il
microfono nel mezzo. Gli eventi sono emessi attorno **all'intera coda** e non per
frase: per frase il microfono si riaprirebbe in ogni pausa, cioe' proprio quando
le casse stanno ancora suonando.

**2. llama.cpp non annulla davvero.** Bug noto (issue #24496): chiudere la
connessione **non libera lo slot**, il modello continua a generare fino alla fine.
Il turno successivo parte in ritardo. Si mitiga con un limite basso di token e
un'istruzione a rispondere breve in modalità voce.

**3. Cosa fare del testo generato ma non pronunciato.** Se salvi in cronologia
tutta la risposta, l'assistente crede di averti detto cose che non hai sentito. La
soluzione elegante (Pipecat) è far viaggiare il testo **nella stessa coda
dell'audio**: quello che non esce dalle casse non entra in cronologia. Nel nostro
caso, dove il TTS lavora frase per frase, basta tenere traccia di quali frasi sono
uscite davvero e tagliare lì il messaggio salvato.

Regola per far scattare l'interruzione: **servono almeno N parole, ma solo mentre
l'assistente parla; se sta zitto basta una parola.** Evita che un colpo di tosse
tronchi la risposta.
