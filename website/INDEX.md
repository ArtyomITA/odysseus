# Vergilius — indice della documentazione

Vergilius è un fork personale di [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus),
adattato per girare **interamente in locale su Windows 11 nativo**, senza Docker,
su una GTX 1080 da 8GB.

Ultimo aggiornamento: 1 agosto 2026 (voce interamente in streaming: vedi
[05](knowledge/05-voce-tts-stt.md) e
[ricerche/voce-streaming-misure.md](../../ricerche/voce-streaming-misure.md)).

---

## Base di conoscenza (`docs/knowledge/`)

Le decisioni, le scoperte e lo stato del progetto. **Da leggere in quest'ordine**
se si arriva nuovi.

| # | Documento | Contenuto |
|---|---|---|
| 01 | [Panoramica dello stack](knowledge/01-panoramica-stack.md) | servizi, porte, struttura delle cartelle, flusso di una richiesta, principi guida |
| 02 | [Modello e hardware](knowledge/02-modello-e-hardware.md) | vincoli della GTX 1080; predefinito attuale **LFM2.5-2.6B** (19 set 2026, vedi nota in cima al file); sotto, storico QwenPaw: perché QwenPaw, la scala di configurazioni A0-A4, **tutte le misure fatte**, ottimizzazioni applicate e non |
| 03 | [Modifiche al core](knowledge/03-modifiche-al-core.md) | **registro completo** di cosa abbiamo toccato di Odysseus, file nuovi, e la procedura per riapplicare dopo un aggiornamento |
| 04 | [Avatar Live2D](knowledge/04-avatar-live2d.md) | architettura, da dove vengono gli stati, emozioni, labiale, perché non MCP, licenze |
| 05 | [Voce: sintesi e trascrizione](knowledge/05-voce-tts-stt.md) | tutto in streaming: PocketTTS senza buffer, Nemotron-3.5 in diretta, fine turno automatica, filtro emoji, dispositivi audio |
| 06 | [Personalità e skill](knowledge/06-personalita-e-skill.md) | i preset, il blocco emozioni automatico, il formato SKILL.md e il problema dell'indice |
| 07 | [MCP e controllo del PC](knowledge/07-mcp-e-controllo-pc.md) | Windows-MCP, l'architettura a livelli, cosa installare e cosa no |
| 08 | [Trappole e scoperte](knowledge/08-trappole-e-scoperte.md) | **i bug che ci sono costati tempo**, le scoperte che ce l'hanno risparmiato, e i miti da sfatare |
| 09 | [Configurazione](knowledge/09-configurazione.md) | dove sta ogni impostazione, come cambiarla, la nostra configurazione attuale, riavvio completo |
| 10 | [Decisioni e alternative scartate](knowledge/10-decisioni-e-alternative-scartate.md) | ogni bivio con il motivo della scelta |
| 11 | [Stato e da fare](knowledge/11-stato-e-da-fare.md) | cosa funziona, cosa va testato, la coda dei lavori |
| 12 | [Caricamento modelli e vista](knowledge/12-caricamento-modelli-e-vista.md) | le API di llama-swap, l'overlay di caricamento, come si rileva davvero la vista, gli strumenti tolti ai profili ciechi |
| 13 | [ShadowBroker: il collegamento](knowledge/13-shadowbroker-dentro-odysseus.md) | il pannello incorporato, le due intestazioni di sicurezza da sbloccare, `local`/`remote` spiegato |
| 14 | [ShadowBroker: orchestrazione verso il modello](knowledge/14-agente-osint.md) | **i dieci strumenti OSINT**, i briefing precalcolati, il controllo mappa, la modalità dedicata, le prove |
| 15 | [ShadowBroker: come funziona dentro](knowledge/15-shadowbroker-come-funziona.md) | **mappa dei dati**, le quattro forme, dove finiscono i token, le classifiche già pronte, tutte le trappole |
| 16 | [Finnhub: cosa dà il piano gratuito](knowledge/16-finnhub.md) | **22 endpoint provati uno per uno**, i 15 negati, i tre giacimenti inutilizzati, il tetto vero letto dall'API |
| 17 | [Catalogo dei dati](knowledge/17-catalogo-dati.md) | **cosa l'assistente può sapere e cosa no**: 33 layer pieni, 14 vuoti e perché, cosa arriva al modello e cosa si ferma prima |
| 18 | [Il profilo Financial](knowledge/18-profilo-financial.md) | mercati, appalti federali sulla mappa, insider con MSPR; **da 6/10 a 10/10** di scelte corrette, e le cinque trappole nei dati |
| 19 | [Il loop agente](knowledge/19-loop-agente.md) | **dove muore una tool call** (quattro colpevoli, tutti nostri), le difese nel loop, il doppio banco di prova obbligatorio, la politica caveman sui prompt |
| 20 | [Reti e ricevitori pubblici](knowledge/20-reti-e-ricevitori-pubblici.md) | cosa sono i puntini SIGINT: **Meshtastic, KiwiSDR, PSK Reporter**; perché Infonet è vuota e non rotta; Shodan; e la lista congelata da un circuit breaker |

### I cinque documenti ShadowBroker, in ordine

```
17  catalogo dei dati        <- cosa si puo' sapere, e cosa no
15  come funziona dentro     <- le forme, i token, le trappole
16  Finnhub                  <- i mercati: cosa e' gratis e cosa no
13  il collegamento          <- il pannello nell'interfaccia
14  l'orchestrazione         <- come il modello lo interroga
```

Se hai cinque minuti e una domanda sola — *«questa cosa la sa o no?»* —
[17](knowledge/17-catalogo-dati.md) basta.

### Se hai poco tempo

- **Devi rimettere in piedi tutto?** → [09 Configurazione](knowledge/09-configurazione.md), sezione "Riavvio completo"
- **Hai aggiornato Odysseus da monte?** → [03 Modifiche al core](knowledge/03-modifiche-al-core.md), sezione finale
- **Qualcosa non funziona?** → [08 Trappole e scoperte](knowledge/08-trappole-e-scoperte.md)
- **Stai per aggiungere qualcosa?** → [10 Decisioni](knowledge/10-decisioni-e-alternative-scartate.md), forse è già stata valutata
- **Vuoi aggiungere uno strumento OSINT?** → [15](knowledge/15-shadowbroker-come-funziona.md) per i dati, poi [14](knowledge/14-agente-osint.md) per l'aggancio

---

## Ricerche approfondite (`d:\assistenteeee\ricerche\`)

Fuori dal repository perché riguardano il progetto, non il codice. Tutte in
italiano, con i link alle fonti.

| Documento | Domanda a cui risponde |
|---|---|
| [analisi-modelli.md](../../ricerche/analisi-modelli.md) | quale modello per una GTX 1080 da 8GB, e perché mai sotto IQ4 |
| [analisi-ottimizzazioni.md](../../ricerche/analisi-ottimizzazioni.md) | tutte le ottimizzazioni possibili su Pascal, ordinate per resa e rischio |
| [estensioni-assistente.md](../../ricerche/estensioni-assistente.md) | cosa ha costruito la community: avatar, emozioni, gaming, controllo PC, voce |
| [note-implementazione-avatar.md](../../ricerche/note-implementazione-avatar.md) | librerie Live2D, trappole CSP, licenze, compatibilità futura |
| [voce-architettura.md](../../ricerche/voce-architettura.md) | come far parlare l'assistente e collegare PocketTTS |
| [eco-microfono-aec.md](../../ricerche/eco-microfono-aec.md) | come impedire che l'assistente senta sé stesso |
| [interruzione-testo-non-detto.md](../../ricerche/interruzione-testo-non-detto.md) | cosa fare del testo generato ma non pronunciato |
| [browser-per-agente.md](../../ricerche/browser-per-agente.md) | quale browser dare all'agente: confronto e costi in token |
| [controllo-pc-numeri-benchmark.md](../../ricerche/controllo-pc-numeri-benchmark.md) | **i numeri veri**: albero UI contro screenshot, e perché comprimere migliora |
| [controllo-pc-architettura.md](../../ricerche/controllo-pc-architettura.md) | come lo fanno i grandi, e la decomposizione giusta per noi |
| [ricerca-web-searxng.md](../../ricerche/ricerca-web-searxng.md) | conviene SearXNG? (no, e il perché è interessante) |
| [shadowbroker-analisi-e-integrazione.md](../../ricerche/shadowbroker-analisi-e-integrazione.md) | com'è fatto ShadowBroker e come si aggancia |
| [shadowbroker-dati-e-domande-possibili.md](../../ricerche/shadowbroker-dati-e-domande-possibili.md) | **quali domande si possono fare**, per categoria di dato |
| [shadowbroker-agente-misure.md](../../ricerche/shadowbroker-agente-misure.md) | quanto costa in token ogni strumento OSINT |
| [headroom-per-shadowbroker.md](../../ricerche/headroom-per-shadowbroker.md) | comprimere i dati OSINT conviene? (no: tetto 14%, e il perché) |
| [cache-kv-e-compattazione.md](../../ricerche/cache-kv-e-compattazione.md) | **quanto costa cambiare il prefisso**: 32× un turno normale, misurato |
| [silero-vad5-e-qwen3-tts.md](../../ricerche/silero-vad5-e-qwen3-tts.md) | Silero VAD 5 serve? Qwen3-TTS quanta RAM? (sì / no, e perché) |
| [latenza-voce-alla-radice.md](../../ricerche/latenza-voce-alla-radice.md) | **dove sta davvero la latenza vocale**: quattro buffer e un pulsante |
| [voce-streaming-misure.md](../../ricerche/voce-streaming-misure.md) | cosa è cambiato dopo, con tutti i numeri misurati |
| [finnhub-cosa-e-gratis.md](../../ricerche/finnhub-cosa-e-gratis.md) | **22 endpoint provati uno per uno**, i tre giacimenti inutilizzati, gli strumenti ricavabili |

---

## Documentazione originale di Odysseus (`docs/`)

Non nostra, ma utile.

| File | Contenuto |
|---|---|
| [setup.md](setup.md) | installazione, Docker e nativa, configurazione |
| [backup-restore.md](backup-restore.md) | salvataggio e ripristino di `data/` |
| [agent-migration.md](agent-migration.md) | importare memorie e skill da altri agenti |
| [attachments.md](attachments.md) | gestione degli allegati |
| [email-outlook.md](email-outlook.md) | limiti con Outlook e Microsoft 365 |
| [security-ci.md](security-ci.md) | controlli di sicurezza automatici |

Altre fonti utili non ufficiali: [DeepWiki](https://deepwiki.com/pewdiepie-archdaemon/odysseus)
(ricostruzione del codice, la migliore per capire l'architettura),
[odysseusai.run](https://odysseusai.run/guides/odysseus-ai-skills/) e
[odysseusai.dev](https://odysseusai.dev/brain-skills) (guide community).

---

## Script e utilità (`d:\assistenteeee\scripts\`)

| Script | Cosa fa |
|---|---|
| `start-llama-swap.ps1` | avvia llama-swap sulla 8012 (i 4 profili modello) |
| `start-voce.ps1` | avvia PocketTTS (8014) e il ponte voce (8013, che carica Nemotron all'avvio) |
| `start-A2.ps1` | llama-server diretto, configurazione quotidiana (alternativa a llama-swap) |
| `start-A2-heretic.ps1` | idem con la variante senza rifiuti |
| `start-A3-vision.ps1`, `start-A3-heretic-vision.ps1` | con la vista |
| `test-smoke.ps1` | verifica rapida: salute, chat, chiamata a strumento |
| `installa-skill.ps1` | installa la selezione curata di skill |

### Prove e misure (`scripts\`, si lanciano con `tts-venv`)

| Script | Cosa misura |
|---|---|
| `prova_osint.py` | 48 controlli sul ponte OSINT |
| `prova_modello_osint.py` | il modello sceglie lo strumento giusto? |
| `misura_cache_kv.py` | costo di cambiare il prefisso del prompt |
| `prova_asr_streaming.py` | RTF e ritardo per pezzo del riconoscitore |
| `prova_asr_finiturno.py` | quando scatta la fine turno, per tre soglie |
| `prova_ws_trascrizione.py` | la catena WebSocket a orario fisso |
| `prova_relay_stt.py` | quanto costa il tramite di Odysseus |
| `misura_voce_primo_suono.py` | **tempo al primo byte** di audio, nei tre punti |
| `sonda_finnhub.py` | quali endpoint Finnhub risponde davvero col piano gratuito |

E lato browser: `odysseus\tests\prova_tts_spezzettamento.mjs` (`node`), 16 casi
sul filtro e sul taglio del testo.

Configurazione della voce: `d:\assistenteeee\voce\configura_odysseus.py`
(registra l'endpoint e scrive le impostazioni, perché il pannello è disattivato).

---

## Convenzioni

- **Ogni ricerca approfondita va salvata** in `d:\assistenteeee\ricerche\`, in
  italiano, con i link alle fonti e le conclusioni operative.
- I documenti sono scritti per essere letti fra sei mesi da chi non ricorda niente:
  meglio ridondanti che ellittici.
- Quando una scelta viene scartata, si annota **perché** e **quando riguardarla**.
