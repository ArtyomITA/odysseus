# Stato attuale e cose da fare

Aggiornato al 1 agosto 2026.

## Cosa funziona

| Componente | Stato | Note |
|---|---|---|
| Odysseus nativo su Windows | ✅ | porta 7000, venv Python 3.13 |
| llama-swap con 4 profili | ✅ | selezionabili dal menu modelli |
| QwenPaw 9B, 48K contesto | ✅ | 23-27 tok/s misurati |
| Variante heretic | ✅ | scaricata, non predefinita |
| Vista (proiettore su RAM) | ✅ | profili `*-vista`, 32K contesto |
| ChromaDB nativo | ✅ | memoria vettoriale e RAG |
| Windows-MCP | ✅ | 13 strumenti (sfoltiti da 20), connesso |
| Playwright MCP | ✅ | 24 strumenti browser |
| Ricerca web (DuckDuckGo) | ✅ | |
| 13 skill installate | ✅ | 4 categorie |
| Avatar Live2D | ✅ | stati, emozioni, labiale, trascinabile, staccabile |
| Sintesi vocale italiana | ✅ | PocketTTS voce estelle |
| **Sintesi in streaming** | ✅ | primo suono a **0,98 s** invece di 5,80 s; 95 pezzi progressivi |
| **Taglio sotto-frase** | ✅ | virgola + 25 caratteri di sguardo; taglio duro a 180 (PocketTTS saltava parole) |
| **Filtro emoji e parentesi** | ✅ | prima della sintesi, non negli offset; 16 prove verdi |
| Voce con precaricamento | ✅ | blocco N+1 sintetizzato mentre suona N: niente pause |
| Selezione dispositivi audio | ✅ | aggiunta da noi, non c'era |
| **Trascrizione in diretta** | ✅ | Nemotron-3.5 su CPU, testo a **1,2 s mentre parli**, RTF 0,5, zero VRAM |
| **Fine turno automatica** | ✅ | ~870 ms di silenzio; il pulsante non serve più |
| **Microfono muto mentre parla** | ✅ | eventi `odysseus:tts-start/end` |
| Trascrizione a lotti (Parakeet) | ✅ | resta installata come riserva |
| Overlay caricamento modello | ✅ | spinner mentre llama-swap scambia profilo |
| **ShadowBroker nativo** | ✅ | :3000 + :8000, niente Docker, chiavi OpenSky e AIS configurate |
| **Pannello nell'interfaccia** | ✅ | icona globo nella barra; l'avatar resta sopra |
| **10 strumenti OSINT** | ✅ | briefing precalcolati, 1.019 token medi |
| **Controllo mappa** | ✅ | `map_focus`, `set_layers`, `highlight`; polling 700ms |
| **Modalità OSINT dedicata** | ✅ | pannello aperto = solo strumenti OSINT |
| GT Strategic Risk Analytics | ✅ | acceso, 1.641 regioni |

## Da testare (mai provato dall'utente in browser)

- Scelta del modello dal menu, e cambio di profilo
- Vista: caricare un'immagine e chiedere cosa c'è
- Avatar con emozioni: serve applicare una personalità e **ricaricare**
- Voce: menu `+` → Voce, poi scrivere qualcosa
- **Mappa che reagisce**: chiedere "cosa succede in Ucraina" col pannello
  aperto, vedere se si centra e filtra da sola
- **Evidenziazioni**: anelli arancioni sulle entità citate, svaniscono dopo
  120 secondi
- **Voce senza pause** sulle risposte lunghe
- **Microfono in diretta**: premere Voce e parlare — testo deve comparire
  mentre parli, fermarsi da solo quando taci

### Già provato, e i risultati

| Prova | Esito |
|---|---|
| `scripts/prova_osint.py` | **48 controlli, 0 rotti**; massimo 2.311 token (4,7% del contesto) |
| `scripts/prova_modello_osint.py` | **12/12** strumenti scelti giusti da QwenPaw, media 5,7 s |
| Giro completo domanda → strumento → risposta | funziona, risposta in italiano ordinata per gravità |
| `tests/prova_tts_spezzettamento.mjs` | **16/16**: filtro, i tre tagli, il contatore che non slitta |
| `scripts/prova_asr_streaming.py` | RTF **0,501** a 2 thread, primo testo a 0,76 s |
| `scripts/prova_asr_finiturno.py` | fine turno a **870 ms** con soglia 0,5 s |
| `scripts/prova_ws_trascrizione.py` | catena completa: primo testo 1,17 s |
| `scripts/prova_relay_stt.py` | il tramite di Odysseus costa **50 ms** |
| `scripts/misura_voce_primo_suono.py` | primo byte **0,62 s** dal ponte (era l'ultimo, a 5,79 s) |
| `scripts/misura_cache_kv.py` | prefisso cambiato = **32×** un turno normale |

## Da fare, in ordine di valore

### 1. Sfoltire gli strumenti e misurare

Prima di aggiungere altro, **misurare quanto costa davvero una fotografia
dell'interfaccia** sulla nostra macchina. Poi:

```
--exclude-tools "Registry,Notification,MultiSelect,MultiEdit,Move,DisplayInventory,Process"
WINDOWS_MCP_MAX_TREE_ELEMENTS=180
```

Obiettivo: restare sotto **3.500 token per osservazione**. Sotto quella soglia
la ricerca dice che l'accuratezza **migliora**, non peggiora.

### 2. Installare Playwright MCP configurato bene

```powershell
npm i -g @playwright/mcp@latest
npx playwright install chromium
```

E cambiare la registrazione in `src/builtin_mcp.py` da `--headless --caps vision` a:
```
--headless --isolated --snapshot-mode none --output-mode file --image-responses omit
```

Poi tre righe di instradamento nel prompt di sistema: quale strumento per
quale compito.

### 3. Il ciclo vocale: quel che resta

Fatto: streaming in entrata e in uscita, fine turno automatica, microfono muto
mentre l'assistente parla. Resta:

- **Anti-eco vero**: loopback WebRTC, per poter parlargli **sopra** invece di
  aspettare che finisca. Oggi il microfono è muto durante il parlato, quindi
  l'interruzione non è possibile per costruzione
- Troncamento del messaggio salvato a quello effettivamente pronunciato
- Regola di interruzione: parlato confermato, non il primo rumore; soglia più
  alta mentre l'assistente parla
- **La voce dal campione**, appena l'accesso HuggingFace è sbloccato

Nota sul limite di sotto: `llama.cpp` **non annulla davvero** (issue #24496).
Chiudere la connessione non libera lo slot, il turno dopo parte in ritardo. Si
mitiga con un tetto basso ai token in modalità voce, non si risolve.

### 4. Il benchmark personale

Il piano originale lo prevedeva, mai fatto: **30-50 richieste reali** con
risposte di riferimento, per misurare ogni modifica invece di andare a
sensazione. Metriche: percentuale chiamate strumenti ben formate, correttezza
del compito, token al secondo, tempo alla prima risposta, VRAM di picco.

Senza questo, ogni ottimizzazione futura è a occhio.

### 5. Il piano R3 (embedding + recupero skill)

Oggi l'indice di **tutte** le skill entra in ogni prompt. Con l'embedding su
CPU (costo VRAM zero) si iniettano solo quelle rilevanti.

### 6. Cose minori ma utili

- Implementare il "sampling" MCP instradandolo sul modello locale: sbloccherebbe
  il riassunto delle pagine nello strumento `Scrape`
- Ramo `avatar` nel tool `ui_control` per i gesti a richiesta
- Speculative decoding (drafter MTP già individuato)
- Modalità headless: display sulla scheda madre, ~1.1GB di VRAM recuperati

### Coda OSINT

| Cosa | Perché |
|---|---|
| Chiavi mancanti: Sentinel Hub, NASA Earthdata, Shodan, GFW | sbloccano immagini satellitari, radar SAR, dispositivi esposti, pesca — tutte gratuite |
| `prediction_markets` vuoto | pesa il **25%** di `threat_level`, che risulta sottostimato |
| Stream SSE al posto del polling a 700 ms | ShadowBroker pubblica già `layer_changed`; toglierebbe l'ultimo ritardo |
| `osint_storico` (Time Machine) | "com'era tre ore fa" — c'è, mai provato |
| Evidenziazione per entità, non per punto | oggi `highlight` disegna anelli su coordinate; filtrare la sorgente MapLibre sarebbe più preciso |
| Ampliare i luoghi noti | `geo.POSTI` ne ha 60; oltre quelli si ripiega sul geocoder |

## Idee valutate, da riprendere quando maturano

| Cosa | Quando riguardarla |
|---|---|
| **agent-browser** (Vercel) | quando chiudono i bug Windows: 200-400 token a pagina cambierebbe tutto |
| **Fara1.5-9B** (Microsoft, MIT) | agente browser sulla nostra stessa base; profilo llama-swap dedicato |
| **Holo3.1** (0.8B/4B/9B, Apache 2.0) | modelli di puntamento per il controllo del PC, se la vista di QwenPaw non bastasse |
| **Qwen3.6-35B-A3B** | dopo l'upgrade RAM: il "muscolo" per i compiti pesanti |
| **Gemma 4 E4B** | rivale per la velocità pura, con audio nativo |
| **VTube Studio** | se un giorno serve l'avatar visibile mentre si gioca |

## Note di manutenzione

- **Dopo ogni aggiornamento di Odysseus** rifare il giro descritto in
  [03-modifiche-al-core.md](03-modifiche-al-core.md), a partire dal controllo
  dell'import `Any`.
- I processi vanno avviati **staccati** per sopravvivere alla chiusura del
  terminale (verificato: hanno resistito a un crash di VSCode).
- `llama-swap` gira con `--watch-config`: modificando il suo YAML le modifiche
  si applicano senza riavvio.
- Le ricerche approfondite vanno **sempre** salvate in `d:\assistenteeee\ricerche\`.
