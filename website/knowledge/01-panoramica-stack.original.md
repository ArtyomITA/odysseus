# Panoramica dello stack

Vergilius è un fork personale di Odysseus, adattato per girare **interamente in
locale su Windows 11 nativo**, senza Docker, su hardware modesto.

## I servizi e le porte

| Porta | Servizio | Cosa fa | Come si avvia |
|---|---|---|---|
| 7000 | **Odysseus / Vergilius** | interfaccia, agente, memoria, skill | `venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 7000` |
| 8012 | **llama-swap** | espone i profili modello come modelli OpenAI | `scripts\start-llama-swap.ps1` |
| 8013 | **ponte voce** | traduce OpenAI ↔ PocketTTS, e ospita **Nemotron-3.5** per la trascrizione in diretta (WebSocket) | `scripts\start-voce.ps1` |
| 8014 | **PocketTTS** | sintesi vocale italiana, in streaming | idem |
| 8100 | **ChromaDB** | memoria vettoriale e RAG | `chroma-venv\Scripts\chroma run --host 127.0.0.1 --port 8100 --path d:\assistenteeee\chroma-data` |
| 3000 | **ShadowBroker GUI** | mappa OSINT, incorporata nel pannello di Odysseus | `cd shadowbroker\frontend ; npm run dev:frontend` |
| 8000 | **ShadowBroker API** | 60+ feed OSINT, canale agente | `cd shadowbroker\backend ; venv\Scripts\python.exe main.py` |
| — | **Windows-MCP** | 13 strumenti di controllo del PC (sfoltiti da 20) | sottoprocesso di Odysseus (stdio) |
| — | **Playwright MCP** | 24 strumenti browser | sottoprocesso di Odysseus (npx) |

Tutti i processi vanno avviati **staccati** (`Start-Process ... -WindowStyle Hidden`):
sopravvivono alla chiusura del terminale e a un crash dell'editor.

## Dove sta cosa

```
d:\assistenteeee\
├── odysseus\            il fork (Vergilius)
│   ├── venv\            Python 3.13
│   ├── data\            settings.json, presets.json, skills\, app.db, chroma\
│   ├── static\          frontend, incluse le nostre aggiunte (avatar, audio)
│   └── docs\knowledge\  questa base di conoscenza
├── llama\               llama.cpp b10091 CUDA 12.4 (binari Windows)
├── llama.cpp-src\       build Linux da sorgente (gcc-12, CUDA 12.x, arch 61)
├── llama-swap\          llama-swap v245 + config.yaml con i profili
├── models\              i GGUF (vedi 02-modello-e-hardware.md)
├── asr-models\          Nemotron-3.5 streaming per sherpa-onnx (~680MB, CPU)
├── voce\                ponte_voce.py, asr_streaming.py, script di configurazione
├── tts-venv\            kokoro-onnx, piper, edge-tts, pocket-tts, onnx-asr, sherpa-onnx
├── chroma-venv\         ChromaDB 1.4.4
├── Windows-MCP\         il server MCP di controllo PC
├── shadowbroker\        piattaforma OSINT (Next.js + FastAPI, niente Docker)
├── Open-LLM-VTuber\     clonato come riferimento (non usato in produzione)
├── skills-src\          repository di skill da cui abbiamo pescato
├── scripts\             script di avvio e utilità
├── ricerche\            tutte le ricerche approfondite, in italiano
└── voice-samples\       campioni delle voci per il confronto
```

## Il flusso di una richiesta

```
PARLI  ─► AudioWorklet 16 kHz, pezzi da 100 ms
      └─► WebSocket /api/stt/stream ─► ponte :8013 ─► Nemotron-3.5 (CPU)
             testo parziale a 1,2s      fine turno da sola dopo ~870 ms
      │
      ▼
Odysseus :7000 ── costruisce il prompt: sistema + skill + memoria + strumenti
      │
      ├─► llama-swap :8012 ─► llama-server ─► QwenPaw sulla GTX 1080
      │
      ├─► Windows-MCP (stdio) ─► controllo del PC
      │
      ├─► ChromaDB :8100 ─► memoria semantica e RAG
      │
      ├─► ponte OSINT ──► ShadowBroker :8000 ─► 60+ feed in tempo reale
      │        │                     │
      │        │                     └─► coda azioni ─► mappa :3000 si muove
      │        │
      │        └─ Python classifica, filtra, comprime: al modello arriva un
      │           briefing GIA' ORDINATO (~1.000 token, non 47.891)
      │
      └─► taglio sotto-frase ─► ponte :8013 ─► PocketTTS :8014
                 (virgola + 25 car)        primo suono a 0,98s, in streaming
                                   │
                                   ▼
                          avatar Live2D (labiale + espressioni)
```

**Niente si accumula prima di essere consegnato.** In entrata il microfono manda
100 ms alla volta; in uscita l'audio suona mentre viene ancora generato. Erano
quattro punti che raccoglievano tutto prima di passarlo, e da soli valevano ~4
secondi su 6. Misure in
[ricerche/voce-streaming-misure.md](../../../ricerche/voce-streaming-misure.md).

## Principi che hanno guidato le scelte

1. **Tutto in locale.** Nessun dato esce dalla macchina, tranne le ricerche web e
   (se scelto) le voci cloud di Edge.
2. **Niente Docker.** Scelta deliberata: su Windows costerebbe una macchina
   virtuale da 2GB di RAM che non abbiamo.
3. **La GPU è solo del modello.** Voce, trascrizione, embedding e proiettore
   visivo girano tutti su CPU. Nemotron-3.5 in streaming rispetta la regola: 680
   MB di RAM, **zero VRAM**, e RTF 0,5 con 2 thread.
4. **Modifiche al core minime e reversibili.** Dove possibile si usano i punti di
   estensione ufficiali (skill, preset, MCP) invece di toccare il codice.
5. **Il contesto è la risorsa scarsa.** 48K token con un modello da 9B: ogni
   strumento, skill e risultato di ricerca va pesato.
