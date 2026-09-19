# Voce: sintesi, trascrizione, e cosa manca

> **Aggiornato il 1 agosto 2026.** Tutta la catena e' passata allo streaming, in
> entrata e in uscita. Numeri e dettagli in
> [ricerche/voce-streaming-misure.md](../../../ricerche/voce-streaming-misure.md).

## Stato attuale

**Funziona**: assistente legge risposte ad alta voce, in italiano, con voce
locale, e avatar muove bocca a tempo. Microfono trascrive **mentre
parli** e capisce da solo quando hai finito.

| | prima | adesso |
|---|---|---|
| primo suono (frase da 132 caratteri) | 5,80 s | **0,98 s** |
| primo testo dal microfono | dopo lo stop | **1,2 s mentre parli** |
| fine turno | click | **automatica, ~870 ms di silenzio** |

**Non ancora fatto** (rinviato per scelta): interrompere assistente parlandogli
sopra. Per ora microfono si silenzia mentre assistente parla (vedi
"L'eco" più sotto).

## La buona notizia: il parlato automatico c'era già

`static/js/tts-ai.js` conteneva già tutto: riproduzione automatica, spezzettamento
per frase mentre risposta arriva (con accortezze giuste — non scambia "1."
per fine frase, né iniziali puntate), soglia minima 15 caratteri, coda
seriale.

Pulsante che lo accende esisteva ma era **nascosto nel codice** con commento
*"read-aloud feature is off in this build"*, insieme a intera scheda TTS delle
impostazioni.

Quindi non c'era da costruire parlato: c'era da **fornire una voce** e
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

**Nessun buffer in mezzo.** Ogni tappa passa byte mentre arrivano: chi
raccoglieva tutto prima di consegnare (`resp.content`, `Response(content=...)`,
`await response.blob()`) e' stato riscritto. Erano quattro, insieme
trasformavano ~200 ms di primo pezzo di PocketTTS nei 2-6 secondi della frase
intera.

Odysseus sa parlare con servizio esterno in formato OpenAI (provider
`endpoint:<id>`, chiama `POST {base_url}/audio/speech`). PocketTTS invece espone
`POST /tts` con campi form. Il ponte traduce.

Dettaglio che ha semplificato le cose: **Odysseus chiede sempre formato mp3, ma
poi riconosce il tipo di file dai primi byte** — quindi si può rispondere in WAV
e funziona lo stesso, risparmiando conversione.

Il ponte è `d:\assistenteeee\voce\ponte_voce.py`, ~130 righe di FastAPI. Espone:
- `POST /v1/audio/speech` → PocketTTS
- `POST /v1/audio/transcriptions` → Parakeet (conversione a 16 kHz mono con ffmpeg)
- `GET /v1/models` → elenco fittizio, serve solo alla sonda di Odysseus
- `GET /health`

Modello di trascrizione si carica **alla prima richiesta**, non all'avvio: chi
usa solo sintesi non paga i 2GB di RAM.

## La sintesi: PocketTTS

Kyutai PocketTTS, ~100 milioni di parametri, gira su CPU.

- Avvio: `pocket-tts serve --language italian --quantize --port 8014`
- Prestazioni misurate: **2.3-3.4 secondi per frase**, modello resta caricato
  (i 6.8 secondi della prima prova erano il caricamento iniziale)
- Dichiarate: 3-4 volte più veloce del tempo reale, primo pezzo audio in ~200ms,
  234MB RAM con `--quantize` (che è pure 27% più veloce)
- Risponde già in streaming

**Voce scelta: `estelle`** (femminile). Nota tecnica: è voce **francese**
clonata sul modello italiano. Funziona (ascoltata e approvata) ma voce nativa
italiana è `giovanni`, maschile. Se pronuncia suonasse strana su qualche parola,
sappiamo dove guardare.

PocketTTS supporta anche **clonazione** da campione audio, ma è dietro
accesso condizionato su HuggingFace: serve accettare termini e autenticarsi.

### Le altre voci provate

Tutti i campioni sono in `d:\assistenteeee\voice-samples\`.

| Motore | Voci italiane | Giudizio |
|---|---|---|
| **PocketTTS** | giovanni (M), alba/estelle (F) | scelto |
| Kokoro (ONNX) | if_sara (F), im_nicola (M) | buona qualità, **non serve CUDA**: gira a metà tempo reale su CPU |
| Piper | paola (F), riccardo (M) | il più veloce, più robotico |
| Edge-TTS | Elsa, Isabella, Diego, Giuseppe | **qualità migliore in assoluto**, ma passa dal cloud Microsoft |

Scoperta utile: **Kokoro non ha bisogno di CUDA**. Odysseus lo supporta solo in
modalità GPU, ma via ONNX gira benissimo su CPU. Alternativa pronta se PocketTTS
deludesse.

### Il taglio del testo prima della sintesi

Tre tagli, in `tts-ai.js`:

1. **fine frase**, con trappole note (`1.` di elenco, `A.` di iniziale)
2. **virgola / punto e virgola / due punti**, solo se seguono almeno **25
   caratteri** — sguardo in avanti evita tagliare su un mozzicone
3. **taglio duro a 180 caratteri**

Il terzo esiste per difetto scoperto nei log: *"Chunk has 182 tokens (max 50),
generation may skip words"*. **PocketTTS salta parole oltre ~50 token, in
silenzio.** Elenchi puntati e paragrafi lunghi ne erano vittima.

### Il filtro per la voce

`AITTSManager.forSpeech()` toglie emoji e caratteri di parentesi (contenuto
resta) prima della sintesi.

Sta **subito prima di sintetizzare** e non dentro `extractPlainText()`, per
motivo preciso: contatore di scorrimento dello streaming indicizza dentro
quella stringa, e filtro lì può farla **accorciare** a metà flusso — parentesi
ancora aperta al confine del pezzo sopravvive a un aggiornamento e
sparisce al successivo. E' lo stesso modo di rompersi già visto con `<think>`.

Trappola Unicode: `\p{Emoji_Component}` **contiene le cifre 0-9**. Usarla
avrebbe tolto tutti i numeri dalle risposte.

Prove: `tests/prova_tts_spezzettamento.mjs`, 16 casi.

## La trascrizione in diretta: Nemotron-3.5 (predefinita)

`nvidia/nemotron-3.5-asr-streaming-0.6b` confezionato per **sherpa-onnx**,
variante **320 ms int8**, in `d:\assistenteeee\asr-models\`.

- **40 lingue-locali**, italiano dichiarato per flusso con `set_option("language")`
- ~680 MB su disco e in RAM, **zero VRAM**
- **RTF 0,5** con 2 thread: elabora doppio della velocità con cui parli
- caricato **all'avvio** del ponte, non alla prima frase (sono ~5 s)

**La fine turno e' dentro sherpa-onnx** (`enable_endpoint_detection`), non serve
un rilevatore di voce a parte:

| `rule2_min_trailing_silence` | scatta dopo l'ultima parola |
|---|---|
| 0,5 s (in uso) | **~870 ms** |
| 0,8 s | 1.100 ms |

Configurabile da variabili d'ambiente: `ASR_MODELLO`, `ASR_LINGUA`, `ASR_THREAD`,
`ASR_SILENZIO`.

**Perche' passa da Odysseus** invece che dritto al ponte: CSP dichiara
`connect-src 'self'`, quindi browser non aprirebbe WebSocket verso :8013.
Il tramite costa 50 ms ed evita allargare CSP.

Il **worklet sta in un file suo** (`static/js/asrWorklet.js`) e non in blob
URL, perché `script-src 'self'` rifiuterebbe `addModule()` su blob.

## La trascrizione a lotti: Parakeet (riserva)

**Whisper è architettura sbagliata** per tempo reale: elabora sempre finestre
da 30 secondi riempite di silenzio, quindi in streaming paghi tutto ogni volta. E
`large-v3-turbo` non aiuta, perché alleggerisce solo parte finale.

Scelta: **Parakeet TDT v3 di NVIDIA** — 25 lingue, errore su italiano del 3%,
~2GB RAM, su CPU a 8 core va **26 volte più veloce del tempo reale**. Tre
secondi di parlato si trascrivono in circa 115 millisecondi.

Installato con `pip install onnx-asr[cpu,hub]`, nativo su Windows.

Resta installato e funzionante come riserva: per tornarci basta rimettere
`stt_provider` a `endpoint:<id>` (`STT_PROVIDER=endpoint:... python
configura_odysseus.py`).

**La conclusione che c'era qui prima — "non serve un servizio microfono sempre
attivo" — non regge più.** Era vera finché si accettava di non vedere una
parola fino allo stop. Con riconoscitore in streaming testo arriva a 1,2 s
e turno si chiude da solo: sono due cose che giro a lotti non può dare,
per costruzione.

## Selezione dei dispositivi audio

Odysseus **non aveva** alcun modo di scegliere microfono o uscita: usava sempre
predefinito di sistema. Aggiunta in Impostazioni → Aspetto, scheda "Dispositivi
audio".

Due avvertenze oneste:
- Nomi dei dispositivi restano vuoti finché non si concede una volta accesso al
  microfono (regola dei browser). Pulsante "Rileva dispositivi" serve a sbloccarli.
- Scelta dell'**uscita** funziona su Chrome ed Edge, **non su Firefox**, che non
  lo permette. Lì si usa quella di sistema, e interfaccia lo dice.

**Trappola non ovvia risolta:** nel momento in cui audio viene collegato
all'analizzatore per labiale dell'avatar, riproduzione **smette di passare
dall'elemento audio** e passa dal motore Web Audio, che ha sua uscita e ignora
dispositivo scelto sull'elemento. Va applicato anche al motore audio.

## Configurazione (il pannello è morto)

Scheda TTS in `index.html` è nascosta di proposito e codice della
trascrizione punta a elementi che non esistono. Impostazioni esistono e
funzionano, ma **vanno scritte via API o direttamente nel file**.

Lo fa `d:\assistenteeee\voce\configura_odysseus.py`:
- registra endpoint del ponte nel database (usando modelli di Odysseus, così
  campi restano coerenti)
- scrive in `data/settings.json`: `tts_enabled`, `tts_provider: endpoint:<id>`,
  `tts_voice: estelle`, `stt_provider`, `stt_language: it`

Due modelli del ponte (`pocket-tts`, `parakeet`) comparivano nel menu dei modelli
insieme a QwenPaw, perché Odysseus accetta solo due tipi di endpoint (llm e
immagini) e non ha categoria per voce. Risolto usando campo
`hidden_models` dell'endpoint, che li nasconde dal selettore **senza disabilitarli**
(servizio vocale chiama endpoint per identificativo, non passa dal menu).

## Cosa manca: l'interruzione

Rinviata per scelta dell'utente, ma ricerca è fatta. Piano è in
[ricerche/voce-architettura.md](../../ricerche/voce-architettura.md),
[ricerche/eco-microfono-aec.md](../../ricerche/eco-microfono-aec.md) e
[ricerche/interruzione-testo-non-detto.md](../../ricerche/interruzione-testo-non-detto.md).

I tre problemi difficili, in sintesi:

**1. L'eco.** Senza cuffie assistente sente propria voce e si interrompe da
solo. Attivare cancellazione d'eco del browser **non basta**: Chrome non "sente"
audio riprodotto dalla pagina stessa, cancella solo quello che arriva da
videochiamata. Rimedio documentato è far passare voce attraverso
connessione WebRTC che pagina apre verso sé stessa (~30ms di costo).

*Fatto nel frattempo:* interruttore di sicurezza c'è. `tts-ai.js` emette
`odysseus:tts-start` e `odysseus:tts-end`, e `voiceRecorder.js` silenzia
microfono nel mezzo. Eventi sono emessi attorno **all'intera coda** e non per
frase: per frase microfono si riaprirebbe in ogni pausa, cioè proprio quando
casse stanno ancora suonando.

**2. llama.cpp non annulla davvero.** Bug noto (issue #24496): chiudere
connessione **non libera lo slot**, modello continua a generare fino alla fine.
Turno successivo parte in ritardo. Si mitiga con limite basso di token e
istruzione a rispondere breve in modalità voce.

**3. Cosa fare del testo generato ma non pronunciato.** Se salvi in cronologia
tutta la risposta, assistente crede di averti detto cose che non hai sentito. La
soluzione elegante (Pipecat) è far viaggiare testo **nella stessa coda
dell'audio**: quello che non esce dalle casse non entra in cronologia. Nel nostro
caso, dove TTS lavora frase per frase, basta tenere traccia di quali frasi sono
uscite davvero e tagliare lì il messaggio salvato.

Regola per far scattare interruzione: **servono almeno N parole, ma solo mentre
assistente parla; se sta zitto basta una parola.** Evita che colpo di tosse
tronchi la risposta.
