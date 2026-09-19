# MCP, controllo del PC e navigazione web

## Cosa c'è ora (aggiornato 1 ago 2026)

**Windows-MCP** (CursorTouch), trasporto stdio, sottoprocesso di Odysseus.
**Sfoltito a 13 strumenti** su 20. Telemetria disattivata.

```
comando: uv --directory d:\assistenteeee\Windows-MCP run windows-mcp serve
         --exclude-tools "Registry,Notification,MultiSelect,MultiEdit,Move,DisplayInventory,Process"
ambiente: UV_NO_SYNC=1, ANONYMIZED_TELEMETRY=false, WINDOWS_MCP_MAX_TREE_ELEMENTS=180
```

**Playwright MCP**: installato e connesso, **24 strumenti** (senza capacità
visive sarebbero 30). Registrato da Odysseus all'avvio ora che pacchetto è
nella cache npm.

---

## Le misure vere fatte su questa macchina

Script: `d:\assistenteeee\scripts\misura_snapshot.py` e `misura_snapshot_ridotto.py`.
Stima a ~3.6 caratteri per token (non tokenizzatore di Qwen: buona per
confronti relativi, non per numeri assoluti).

### Windows-MCP, prima e dopo lo sfoltimento

| | Prima | Dopo | Differenza |
|---|---|---|---|
| Strumenti | 20 | 13 | −7 |
| Schemi (catalogo intero) | 6.729 token | 4.604 | **−32%** |
| Fotografia dell'interfaccia | 3.519 token | **1.766** | **−50%** |
| Una richiesta con osservazione | 10.248 | 6.370 | **−38%** |

Fotografia era **esattamente al limite** dei 3.500 token oltre i quali ricerca
dice che modello piccolo peggiora. Ora è a metà strada.

### Il confronto che conta: MCP contro nativi

| | Strumenti | Token totali | Media per strumento |
|---|---|---|---|
| Nativi di Odysseus | 71 | 17.096 | **241** |
| Windows-MCP (sfoltito) | 13 | 4.604 | **354** |

**Gli strumenti MCP costano il 47% in più a testa.** Due ragioni: Windows-MCP
infarcisce descrizioni di parole chiave di proposito (*"Keywords: screenshot,
screen capture, see screen..."*) per farsi trovare da qualunque modello, e
Odysseus aggiunge prefisso `[MCP:Nome server]` a ognuna.

**Ma non vengono inviati tutti.** Odysseus seleziona per rilevanza semantica: ne
prende **8** più tre sempre presenti (`manage_memory`, `ask_user`, `update_plan`).
Costo reale per richiesta è quindi ~2.200 token, non 21.700.

Conseguenza pratica: **sfoltimento serve meno per costo che per
confusione**. Con Playwright installato abbiamo due modi di cliccare e due di
navigare; meno candidati simili significa meno occasioni di sbagliare per un 9B.

## I 20 strumenti di Windows-MCP

Documentazione interna del progetto ne dichiara 16, manifest 18, ma
codice ne registra **20**:

`Snapshot` (albero di accessibilità con etichette e coordinate, con modalità DOM
per browser), `Screenshot`, `Click`, `Type`, `Scroll`, `Move`, `Shortcut`,
`Wait`, `WaitFor`, `App`, `PowerShell`, `FileSystem`, `Scrape`, `MultiSelect`,
`MultiEdit`, `Clipboard`, `Process`, `Notification`, `Registry`, `DisplayInventory`.

### Caratteristiche e limiti verificati nel codice

- **Vision opzionale**: lavora su albero UI testuale, non ha bisogno di modello
  visivo. Ottimo per modello piccolo.
- **`Snapshot(use_dom=True)` legge il DOM tramite API di accessibilità**, non
  tramite protocollo di debug del browser. Significa che può leggere il **tuo
  Chrome già autenticato senza aprire porte di debug**. Scoperta importante.
- Percorsi relativi di `FileSystem` puntano al **Desktop dell'utente**, non a
  cartella corrente.
- **Non guida applicazioni elevate** se non gira elevato.
- Tool `App` in modalità "lancia dal menu Start" **si rompe su Windows non
  inglese** — nostro caso.
- **Non adatto ai videogiochi**: albero UI non dice nulla di un gioco. Lì serve
  screenshot più vista.
- Nessuna sandbox: `PowerShell`, `Registry`, `FileSystem` fanno quello che
  vogliono. Escludibili con `--exclude-tools`.

### Trappola verificata

Tool `Scrape` chiede al client di riassumere pagina con proprio modello
(funzione "sampling" di MCP), ma **Odysseus non implementa quella funzione**:
ripiega su contenuto grezzo. Va passato `use_sampling=False`, oppure — meglio —
implementare sampling instradandolo sul nostro modello locale. Sarebbe vittoria
più economica del lotto.

## Come Odysseus gestisce MCP

- Server registrati nella tabella `mcp_servers` del database (`data/app.db`), non
  in file di configurazione.
- API: `POST /api/mcp/servers` (form multipart, solo admin), `GET /api/mcp/tools`,
  `PATCH /api/mcp/servers/{id}/tools` con `{"disabled": [...]}` per **disabilitare
  singoli strumenti**.
- Interfaccia: Settings → Integrations → + Add Integration → MCP Tool Server.
- Server integrati registrati da soli: `image_gen`, `memory`, `rag`, `email`, più
  `builtin_browser` via npx.
- Odysseus **espone anche propria memoria e RAG come server MCP**: altri
  agenti possono leggerli e scriverli.

## La scoperta che cambia il piano: il selezionatore c'è già

In `src/tool_index.py` c'è **indice a embedding** che recupera primi k
strumenti per rilevanza e **indicizza anche quelli MCP**, più lista di
sempre-disponibili e disabilitazione per server salvata nel database.

Significa che **non dobbiamo costruire router degli strumenti**: dobbiamo solo
smettere di registrare strumenti che non useremmo mai.

## L'architettura a livelli (la decisione)

Domanda dell'utente era: "computer use o browser use?". Risposta è **sono
assi indipendenti**, e vera domanda è *per ogni compito, qual è
rappresentazione più economica dello stato?*

| Compito | Strumento | Perché |
|---|---|---|
| leggere una pagina | `Scrape` | il più economico |
| agire nel **mio** browser già loggato | `Snapshot(use_dom=True)` + `Click` | usa mie sessioni, niente porte di debug |
| lavoro ripetibile e isolato su 20 pagine | Playwright dedicato | profilo usa-e-getta, invisibile |
| applicazioni desktop | `Snapshot` + `Click`/`Type` | albero UI è testo, economico |
| **cose fattibili senza cliccare** | `PowerShell` | vedi sotto |

### Il livello sottovalutato: scrivere codice invece di cliccare

Anthropic misura **150.000 → 2.000 token (meno 98.7%)** passando da chiamate
dirette agli strumenti a esecuzione di codice. Cloudflare spiega perché: *"gli
LLM sanno scrivere TypeScript meglio di quanto sappiano emettere chiamate a
strumenti"*, perché materiale di addestramento ne è pieno. CodeAct lo conferma
accademicamente: **fino a +20 punti di riuscita e ~30% di passi in meno** su 17
modelli.

Per un 9B è decisivo: rinominare 200 file con una riga di PowerShell costa 30
token; farlo cliccando ne costa 15.000.

## Configurazione raccomandata (da applicare)

**1. Sfoltire Windows-MCP.** Da 20 strumenti a ~13:
```
--exclude-tools "Registry,Notification,MultiSelect,MultiEdit,Move,DisplayInventory,Process"
WINDOWS_MCP_MAX_TREE_ELEMENTS=180
```
Valore predefinito di 500 elementi vale 7-8k token per fotografia. **Va misurato
sulla nostra macchina prima di tarare.**

**2. Riconfigurare Playwright MCP prima di installarlo.** Oggi Odysseus lo registra
con `--headless --caps vision`. Quelle capacità visive aggiungono **6 strumenti a
coordinate**, peggiori dei riferimenti per modello piccolo, e ogni screenshot
costa migliaia di token. Sostituire con:
```
--headless --isolated --snapshot-mode none --output-mode file --image-responses omit
```
`--snapshot-mode none` elimina fotografia automatica dopo **ogni** azione;
`--output-mode file` scrive fotografie e log **su disco** invece che nel contesto —
è il trucco che porta 114k token a 27k, disponibile dentro MCP.

Installazione: `npm i -g @playwright/mcp@latest` (popola cache, così Odysseus lo
registra da solo) e `npx playwright install chromium` — **solo Chromium**, ~120MB.
Con tutti e tre i browser si arriva a 1.2GB. Attenzione: npx non scarica browser
da solo, è passo separato.

**3. Tre righe di instradamento nel prompt di sistema** con la tabella qui sopra.

## Cosa non installare, e perché

| Progetto | Motivo dello scarto |
|---|---|
| **agent-browser** (Vercel) | il più economico in token (200-400 a pagina), ma bug Windows **aperti**: uno manda in stallo la CLI quando PowerShell cattura l'output — e Odysseus cattura l'output. **Riguardare fra tre mesi.** |
| **lightpanda** | **nessuna build Windows** (solo Linux/macOS, su Windows serve WSL). E **non renderizza**: niente CSS né layout. Strumento da estrazione dati, non da interazione. |
| **pinchtab** | Windows dichiarato "supporto limitato, best effort" dagli autori, e **non è MCP nativo**: collegamenti sono di terze parti non ufficiali. |
| **chrome-devtools-mcp** | ~18.000 token di sole descrizioni = 37% del nostro contesto prima di iniziare. Complementare, non sostitutivo. |
| **OmniParser v2** | GPU satura → girerebbe su CPU con secondi di latenza per fotogramma. Più una vulnerabilità di esecuzione remota corretta solo dalla 2.0.1. |
| **UI-TARS** | versioni compresse hanno degrado noto nel puntamento, e **sostituirebbe** nostro 9B sugli 8GB invece di affiancarlo. |
| **Windows-Use** (stesso autore di Windows-MCP) | è un **agente completo** con loop proprio, non un fornitore di strumenti. Sarebbe un secondo cervello. |

## Da valutare più avanti

**Fara1.5-9B** di Microsoft: licenza MIT, **costruito sulla stessa base del nostro
modello** (Qwen3.5-9B), 86.6 su WebVoyager, con versioni GGUF e proiettore visivo
già pronti. Profilo llama-swap dedicato darebbe un vero agente per il browser.
Limite dichiarato: **solo browser, solo screenshot** — non controlla il desktop.

**MCP dentro Windows**: esiste ma in anteprima, con registro di agenti e
connettori per Esplora file e Impostazioni. Riservato ai PC Copilot+ con NPU, non
nostra macchina.

I numeri che giustificano tutte queste scelte sono in
[ricerche/controllo-pc-numeri-benchmark.md](../../ricerche/controllo-pc-numeri-benchmark.md).
