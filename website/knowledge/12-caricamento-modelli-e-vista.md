# Caricamento dei modelli e gestione della vista

Aggiunto il 1 agosto 2026. Risponde a due domande poste esplicitamente:
*"quando cambio modello dal dropdown deve esserci un loading"* e *"quando sto
senza vista non devo avere l'opzione di screenshot"*.

---

## 1. Cosa succede davvero quando cambi modello

Nel menu di Odysseus ci sono quattro voci, ma **non sono quattro modelli**:
sono quattro **profili di llama-swap** su un solo indirizzo (`127.0.0.1:8012`).

| Voce nel menu | GGUF | Proiettore visivo | Contesto |
|---|---|---|---|
| QwenPaw 9B | Q4_K_M | no | 48K |
| QwenPaw 9B (vista) | **lo stesso Q4_K_M** | mmproj Q8_0 su RAM | 32K |
| QwenPaw 9B heretic | heretic Q4_K_M | no | 48K |
| QwenPaw 9B heretic (vista) | **lo stesso heretic** | mmproj BF16 su RAM | 32K |

Le due righe "vista" caricano **gli stessi pesi** delle righe sopra. Cambia
solo il proiettore e, di conseguenza, il contesto (il proiettore mangia VRAM
anche stando su RAM di sistema).

### Risposta alla domanda "serve anche per la vista?"

**Sì, è esattamente la stessa cosa.** Nessun interruttore vista sì/no sullo
stesso processo: `--mmproj` è argomento della riga di comando di
`llama-server`, deciso all'avvio. Passare da `qwenpaw` a `qwenpaw-vista`
significa che llama-swap **spegne un processo e ne accende un altro**, come
passare a `heretic`. Stesso tempo, stesso caricamento, stesso spinner.

Misurato: **~50 secondi a freddo**, pochi secondi se il file è già in cache
disco.

---

## 2. Le API di llama-swap che rendono possibile lo spinner

Scoperte provando sul server acceso, non documentate nel materiale precedente:

```
GET /running
  {"running":[{"model":"qwenpaw","state":"starting", ...}]}
  lo stato passa a "ready" quando il server risponde

GET /v1/models
  ogni voce ha "status":{"value":"unloaded"}
  serve perché /running elenca SOLO i processi accesi: senza questo, un
  profilo mai avviato è indistinguibile da un endpoint morto

GET /upstream/{modello}/{percorso}
  proxy verso il llama-server, MA LO ACCENDE PRIMA se è spento
  è quindi il modo più economico di far partire un caricamento:
  /upstream/{modello}/health non costa nessuna valutazione di prompt

POST /api/models/unload/{modello}
  spegne un profilo
```

**La chiamata resta aperta per tutta la durata del caricamento.** Per questo il
backend la lancia su thread separato e non la aspetta.

---

## 3. Come l'abbiamo implementato

### Backend

**`src/llamaswap.py`** (nuovo). Tre livelli di cache, perché le tre
informazioni cambiano a ritmi diversi:

| Cosa | Durata cache | Perché |
|---|---|---|
| "questo endpoint è llama-swap?" | 5 minuti | non cambia mai in pratica |
| stato di caricamento | 2 secondi | cambia da solo (scadenza ttl, altri client) |
| `modalities` da `/props` | 24 ore | è una proprietà del GGUF, fissa |

Funzione chiave: `swap_base()` toglie il suffisso `/v1` dall'URL salvato in
Odysseus, perché `/running` e `/upstream` stanno **un livello sopra** l'API
OpenAI.

`props()` **non** fa partire un caricamento di proposito: chiedere le capacità
non deve mai buttare fuori il modello con cui stai parlando.

**`routes/model_routes.py`** (due rotte nuove):

```
GET  /api/model-runtime/status?endpoint_url=&model=
     -> {"swap":true,"state":"ready","vision":false,"context_tokens":49152}
POST /api/model-runtime/warmup  {"endpoint_url":..., "model":...}
     -> {"swap":true,"state":"starting"}   e torna subito
```

**Nota di sicurezza.** L'URL arriva dal browser, quindi **non va mai chiamato
così com'è**: sarebbe una falla SSRF (il server andrebbe a bussare a
qualunque indirizzo raggiungibile dalla macchina). `_resolve_known_endpoint()`
accetta solo URL che corrispondono a un endpoint **già configurato e
abilitato**, visibile a chi chiede, e usa poi l'URL preso dal database.

Chi non è llama-swap riceve `{"swap": false}` e l'interfaccia non mostra nulla.

### Frontend

**`static/js/modelLoading.js`** (nuovo):

- chiama `warmup`, poi interroga `status` ogni **700 ms**
- overlay compare solo dopo **350 ms**: uno scambio a caldo non deve produrre
  un lampo di spinner
- spinner **whirlpool nativo** di Odysseus (`spinner.createWhirlpool(44)`),
  stesse variabili CSS del resto (`--bg`, `--border`, `--fg`)
- contatore secondi; a 75 secondi il sottotitolo diventa "più lento del
  solito", perché a quel punto la domanda dell'utente è "si è bloccato?"
- bottone **Nascondi**, non Annulla: chiudere l'overlay **non ferma** il
  caricamento, altrimenti il messaggio successivo troverebbe un server a metà
- `token` progressivo: se cambi modello due volte di fila, il primo giro esce
  in silenzio invece di litigare per lo schermo col secondo

Aggancio in `modelPicker.js`, funzione `_pick()`, su **entrambe** le uscite
riuscite (chat non ancora creata / sessione esistente). Volutamente **non
aspettato**: menu resta reattivo, llama-swap accoda comunque una richiesta
che arriva a caricamento in corso.

CSS in fondo a `static/style.css` (`.model-loading-*`).

---

## 4. Il bug della vista che abbiamo trovato per strada

Odysseus decide se un modello vede le immagini con `is_vision_model()` in
`src/chat_helpers.py`, e lo fa **guardando il nome**: cerca sottostringhe come
`vision`, `vl`, `llava`, `gemma3`.

I nostri profili si chiamano `qwenpaw-vista` e `heretic-vista`. **Nessuna
parola chiave corrisponde.** Conseguenza: anche con il proiettore caricato,
Odysseus considerava il modello cieco, **toglieva l'immagine dalla richiesta**
e la mandava a un "modello vista" separato configurato in Impostazioni — che
da noi non esiste, quindi il risultato era il testo
`[No vision model configured — set one in Settings → Vision]`.

**Il mmproj c'era e non veniva usato.**

### Correzione

`model_supports_vision()` ora consulta llama-swap **prima** dell'euristica sul
nome, con lo stesso schema già presente per LM Studio:

```
llama-swap /props  ->  modalities.vision   (verità: c'è o non c'è il mmproj)
LM Studio          ->  capabilities.vision
altrimenti         ->  euristica sul nome  (invariata)
```

`supports_vision()` torna `None`, non `False`, quando non sa: un endpoint che
non è llama-swap si comporta esattamente come prima.

Verificato dal vivo, con i quattro profili caricati uno alla volta:

```
qwenpaw        ready  vision=False  ctx=49152
qwenpaw-vista  ready  vision=True   ctx=32768
heretic-vista  ready  vision=True   ctx=32768
```

`model_supports_vision('qwenpaw-vista')` prima tornava `False`, ora `True`.

**Attenzione al caso "non caricato".** `supports_vision()` torna `None`, mai
`False`, per un profilo spento: `qwenpaw-vista` ha il proiettore che il suo
processo sia acceso o no. Il primo tentativo di implementazione usava
`model_supports_vision()`, che ricade sull'euristica del nome e rispondeva
`False` per **tutti** i nostri profili — avrebbe tolto gli strumenti anche al
profilo con la vista. Il filtro degli strumenti chiama quindi `supports_vision()`
direttamente e agisce solo su un `False` esplicito.

Quando invece c'è **davvero un'immagine allegata**, `model_supports_vision()`
passa `load=True`: il profilo sta comunque per essere avviato dalla richiesta
in uscita, quindi l'attesa è la stessa attesa, solo anticipata abbastanza da
instradare l'immagine invece di buttarla via.

---

## 4-bis. Il guasto trovato per strada: due mmproj da 0 byte

Provando a caricare `qwenpaw-vista` per verificare il rilevamento:

```
[WARN] group: starting qwenpaw-vista failed: upstream command exited prematurely
E gguf_init_from_reader: failed to read magic
E clip_init: failed to load model '.../QwenPaw-Flash-9B.mmproj-Q8_0.gguf'
```

```
QwenPaw-Flash-9B.mmproj-Q8_0.gguf         0 byte
QwenPaw-Flash-9B.mmproj-f16.gguf          0 byte
mmproj-heretic-BF16.gguf            921 MB   (buono)
```

I due proiettori di QwenPaw erano **file vuoti**, residuo di un download
fallito del 23 luglio. `qwenpaw-vista` non era mai partito, e nessuno se n'era
accorto perché fino a oggi nessuna parte del sistema tentava di caricarlo.

Riscaricato da `mradermacher/QwenPaw-Flash-9B-GGUF` (repo **statico**, non
`i1`: i proiettori non stanno nel repo imatrix) con aria2:

```
595 MB, magic 47475546 = "GGUF"
carica in 56 s, vision=True, 32K di contesto, 6991 MiB / 8192 MiB di VRAM
```

Il file `mmproj-f16.gguf` resta cancellato: usiamo il Q8_0, e comunque sta su
RAM di sistema (`--no-mmproj-offload`).

**Morale:** un download fallito lascia un file da 0 byte che sembra presente
in `ls`. Il controllo giusto sono i **primi 4 byte**, che per un GGUF valido
sono `47 47 55 46`.

---

## 5. Senza vista: via gli strumenti di screenshot

`src/agent_loop.py`, funzione `_drop_image_only_tools()`, applicata dopo tutta
la selezione degli strumenti (subito dopo `_expand_browser_mcp_tools`).

Strumenti tolti quando il profilo attivo non ha proiettore:

- `Screenshot` (Windows-MCP)
- `browser_take_screenshot` (Playwright MCP)

Il confronto è sul **nome nudo** (`nome.rsplit("__", 1)[-1]`) perché i nomi
qualificati MCP contengono l'identificativo del server, che da noi è un UUID
generato all'installazione (`mcp__075fe6c2__Screenshot`): scriverlo a mano si
romperebbe alla prima reinstallazione.

**Filtra solo su un no certo.** Se la capacità è sconosciuta — endpoint non
llama-swap, profilo non ancora caricato — gli strumenti restano tutti. Un
dubbio non deve accecare il modello.

Cosa **non** viene tolto, di proposito:

- `Snapshot` di Windows-MCP: legge l'albero di accessibilità, è **testo**, ed
  è anche più economico di una foto
- `browser_snapshot` / `browser_find`: leggono il DOM, sempre testo
- la vista lato modello: il mmproj resta nei profili `*-vista`, intatto

Nell'interfaccia compare una pastiglia **"senza vista"** accanto al nome del
modello (`.model-blind-badge`), con la spiegazione nel suggerimento al
passaggio del mouse. Compare **solo** quando la capacità è nota e negativa: mai
su un modello di cui non sappiamo nulla.

---

## 6. Cosa resta aperto

- La pastiglia si aggiorna quando cambi modello o al caricamento pagina. Se
  llama-swap fa scadere il profilo per conto suo (ttl 3600) l'interfaccia non
  se ne accorge finché non ricarichi. Ininfluente: le capacità del profilo non
  cambiano, solo il suo stato.
- Il pulsante di allegato immagine **non** è disabilitato sui profili ciechi.
  Volutamente: Odysseus ha comunque la via del "modello vista separato", che
  un domani potremmo configurare puntandolo su `qwenpaw-vista`. Sarebbe la
  soluzione elegante — descrivere l'immagine con il profilo vista senza
  scaricare quello con cui stai chattando. **Da valutare**, vedi
  [11-stato-e-da-fare.md](11-stato-e-da-fare.md).
- L'overlay non è stato ancora provato dall'utente nel browser.
