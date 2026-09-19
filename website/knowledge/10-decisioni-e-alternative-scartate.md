# Decisioni prese e alternative scartate

Registro dei bivi, con motivo della scelta. Serve a non rifare la stessa
valutazione fra sei mesi.

---

## Il modello

**Scelto: QwenPaw-Flash-9B** (finetune agentico di Qwen3.5-9B).

| Alternativa | Perché no |
|---|---|
| Qwen3.5-9B liscio | QwenPaw è lo stesso modello già addestrato sul nostro caso d'uso |
| Qwen3.5-4B / QwenPaw-4B | più veloce, ma il 9B ci sta e regge meglio i compiti agentici |
| Gemma 4 E4B | benchmark nettamente inferiori (GPQA 58.6 contro 76.2); in compenso ha audio nativo e quantizzazioni ufficiali. Tenuto come rivale da provare per la velocità pura |
| Qwen3.6-35B-A3B (MoE) | sarebbe il "muscolo" per i compiti pesanti, ma richiede 32GB di RAM. Rimandato all'upgrade |
| prism-ml Bonsai (1-bit) | accuratezza dichiarata **contestata pubblicamente**, richiede un fork non ufficiale di llama.cpp, supporto Pascal non confermato |

**Aggiunto dopo: variante heretic**, senza rifiuti. Non predefinita: si
sceglie dal menu quando serve.

---

## La configurazione di inferenza

**Scelto: Q4_K_M + flash attention + cache q8_0 + 48K di contesto.**

| Alternativa | Perché no |
|---|---|
| Q5_K_M | qualità impercettibilmente migliore ma costringe il contesto a 8K. Escluso dai profili (il file resta) |
| Q6_K / Q8_0 | non entrano senza offload, e l'offload su modello denso è un disastro sul PCIe |
| IQ4_XS | 5.2GB invece di 5.9, ma -5/10% di velocità. Riserva se servisse spazio |
| sotto IQ4 | **vietato**: il tool calling si rompe a IQ3 |
| cache f16 | metà del contesto a parità di VRAM, senza guadagno misurabile |
| offload di livelli su CPU | modello denso: i pesi viaggerebbero sul PCIe a ogni token |

---

## L'avatar

**Scelto: tela Live2D dentro la pagina di Odysseus, con nucleo estraibile in
widget.**

| Alternativa | Perché no |
|---|---|
| Open-LLM-VTuber come app separata | **due cervelli**: ciclo, memoria e configurazione propri; non saprebbe cosa sta facendo Odysseus |
| VTube Studio pilotato da Odysseus | animazione più ricca gratis (fisica, respiro, blink già pronti) ma **finestra separata, non incorporabile in una pagina web**. Resta l'opzione se un giorno servisse vederlo mentre si gioca |
| riusare il frontend di Open-LLM-VTuber | React+Electron, non esiste come pacchetto, stato accoppiato ai loro messaggi WebSocket. Riscriverlo è più semplice che estrarlo |
| avatar VRM 3D | Open-LLM-VTuber supporta **solo Live2D**, il VRM è una richiesta aperta |
| server MCP per le animazioni | il protocollo **non ha primitive di streaming**; unico tentativo su GitHub abbandonato; 36 strumenti = migliaia di token. Sì invece per i **gesti volontari**, dove Odysseus ha già `ui_control` |

**Nota su una valutazione sbagliata:** avevo detto che la tela avrebbe avuto
animazione povera perché fisica e respiro andrebbero riscritti. Falso: il ciclo
di aggiornamento della libreria li chiama già.

---

## La voce

**Scelto: PocketTTS (voce estelle) in streaming + Nemotron-3.5 in diretta,
dietro un ponte OpenAI su porta 8013.**

### Sintesi

| Alternativa | Perché no |
|---|---|
| Edge-TTS | **qualità migliore in assoluto**, ma passa dal cloud Microsoft |
| Kokoro | ottima e gira su CPU (scoperta utile), ma PocketTTS ha latenza minore. Riserva pronta |
| Piper | il più veloce ma più robotico |
| Speaches (server unico) | non supporta PocketTTS, pensato per Docker + CUDA |
| **Qwen3-TTS** | ~1,3 GB contro i 234 MB di PocketTTS, RTF ≥ 1,3 su CPU migliori della nostra, e **nessuno streaming documentato**: perderemmo i 200 ms di primo pezzo. L'unico vantaggio è la clonazione da 3 secondi |
| **KittenTTS** (25 MB) | usato dal progetto che sta a 1,25 s solo CPU, ma **solo inglese** |

### Trascrizione

| Alternativa | Perché no |
|---|---|
| Whisper | architettura sbagliata per il tempo reale: elabora sempre 30 secondi anche se ne dici tre |
| **Parakeet a lotti** (era la scelta) | va 26× il tempo reale, ma **non produce una parola finché non premi stop**. Resta installato come riserva |
| **Silero VAD** per la fine turno | **non serve**: sherpa-onnx ce l'ha dentro e scatta a 870 ms |
| Silero VAD in TorchScript invece di ONNX | ONNX è **1,7× più veloce** su CPU (189 contro 325 µs), e nel browser TorchScript non gira |

**Ribaltata una conclusione precedente.** Qui c'era scritto: *"daemon microfono
sempre attivo: non serve, con Parakeet a 26× il metodo manda-il-file-intero
basta"*. Era vero finché si accettava di non vedere niente fino allo stop. Con
lo streaming il testo arriva a 1,2 s e il turno si chiude da solo: due cose che
il giro a lotti non può dare per costruzione.

---

## Modelli e strumenti multipli

**Scelto: llama-swap con 4 profili esposti come modelli.**

| Alternativa | Perché no |
|---|---|
| llama-server diretto | un modello alla volta, cambio solo da riga di comando |
| due istanze contemporanee | non c'è VRAM per due modelli |
| profili solo negli script | funziona, ma non si sceglie dall'interfaccia |

Prezzo accettato: **10-50 secondi per cambio profilo**.

---

## Ricerca web

**Confermato: DuckDuckGo (`ddgs`), con Tavily come riserva consigliata.**

| Alternativa | Perché no |
|---|---|
| SearXNG | su Windows **non supportato** dagli autori; la versione portable è ferma a maggio 2025 (parser rotti); WSL/Docker costerebbero 1-2GB di RAM |
| istanza pubblica di SearXNG | la maggior parte disabilita l'interfaccia JSON; e manderesti tutte le ricerche a un operatore sconosciuto |
| Brave Search API | piano gratuito **chiuso a febbraio 2026**, ora addebita senza tetto |
| Whoogle | **archiviato**, Google ha chiuso le pagine senza JavaScript |

Motivo decisivo: `ddgs` nel 2026 **non è più solo DuckDuckGo**, è già un
aggregatore multi-motore. Il vantaggio principale di SearXNG ce l'abbiamo già.

---

## Navigazione web dell'agente

**Scelto (da installare): Playwright MCP con capacità visive disattivate.**

| Alternativa | Perché no |
|---|---|
| agent-browser (Vercel) | il più economico in token, ma bug Windows aperti — uno manda in stallo la CLI quando PowerShell cattura l'output, e Odysseus lo fa. **Riguardare fra tre mesi** |
| lightpanda | nessuna build Windows, e **non renderizza** (niente CSS/layout) |
| pinchtab | Windows "best effort" dichiarato, e non è MCP nativo |
| chrome-devtools-mcp | 18.000 token di sole descrizioni = 37% del contesto |

---

## Compressione del contesto

**Scartato: Headroom.** Confermato dopo una seconda valutazione, con misure.

> **Il motivo scritto qui prima era sbagliato.** Diceva *"il loro guadagno è
> economico e noi non paghiamo niente"*. Falso per il nostro caso: il vincolo è
> il **contesto**, non il costo. La conclusione regge lo stesso, per due motivi
> migliori, entrambi misurati.

**Primo: sui nostri briefing il tetto è il 14%.** Headroom comprime la *forma*
(chiavi ripetute, array uniformi); noi comprimiamo già il *senso* (scegliamo
cosa merita di essere detto). Il grasso è tolto, non con la stessa tecnica.

```
gdelt grezzo, 1553 eventi   584.819 token
briefing filtrato, 9 eventi     515 token     1 a 1135
poi Headroom sopra             ~440 token     1 a 1329
```

Il secondo passaggio è rumore rispetto al primo. Risparmio reale: 1.117 token,
il **2,3% del contesto**.

**Secondo: comprimere a ogni turno costerebbe 32 volte un turno normale.**
Misurato su questa macchina con 22K di contesto:

```
prefisso identico     1,57 s di prefill    21.543 token riusati dalla cache
prefisso cambiato    50,57 s                    0 token riusati
```

Risultato peggiore: **tornando a un prefisso già visto, la cache non c'era
più**. llama-server ha uno slot solo, un turno divergente avvelena anche i
successivi. Il loro `CacheAligner` è pensato per la cache **dei fornitori**, un
altro meccanismo — che copra anche la corrispondenza di prefisso di llama.cpp
non è dichiarato da nessuna parte.

Dettaglio in
[ricerche/headroom-per-shadowbroker.md](../../../ricerche/headroom-per-shadowbroker.md)
e [ricerche/cache-kv-e-compattazione.md](../../../ricerche/cache-kv-e-compattazione.md).

Restano validi anche i motivi originali:

- riscrive i prompt, e Odysseus ha un impianto delicato (contenuto non fidato
  incapsulato, tag emozione, schemi JSON) che si romperebbe in modo subdolo;
- un 9B soffre il testo compresso molto più di un modello grande;
- metà delle funzioni non si applicano (regolano parametri di OpenAI e
  Anthropic che llama.cpp non ha);
- il recupero degli originali costa **un altro strumento** nel contesto;
- il compressore usa un suo modello, che girerebbe sulla CPU già occupata.

La sua funzione più interessante (avvisare quando contenuto volatile invalida
la cache) **Odysseus l'ha già risolta** spostando la data fuori dal messaggio
di sistema.

Alternative migliori per lo stesso obiettivo: ridurre gli strumenti esposti, il
piano R3 per le skill, e configurare bene Playwright.

---

## Cose rinviate per scelta

| Cosa | Stato |
|---|---|
| Interruzione mentre l'assistente parla | l'interruttore di sicurezza c'è (microfono muto durante il parlato); manca l'anti-eco WebRTC che permetterebbe di parlargli sopra davvero |
| Clonazione della voce da campione | **bloccata da un permesso, non dal codice**: i pesi con encoder sono dietro i termini di `kyutai/pocket-tts` su HuggingFace. Campione pronto in `voice-samples/campione_nuovo_24k.wav` |
| Playwright MCP | configurazione decisa, installazione da fare |
| Sfoltimento degli strumenti di Windows-MCP | flag decisi, da applicare e misurare |
| Speculative decoding (MTP) | drafter individuato, +20-30% potenziale |
| Modalità headless (display su iGPU) | recupererebbe ~1.1GB di VRAM |
| Piano R3 (embedding + recupero skill) | è la risposta giusta al problema dell'indice skill |
| Upgrade RAM 16 → 32GB | sbloccherebbe seconda istanza e modelli MoE grandi |
