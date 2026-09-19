# Il loop agente: come funziona, dove si rompeva, come si prova

Il 2 agosto il multistep in chat era morto: il modello faceva una chiamata e
poi «annunciava» la seconda senza farla. La caccia notturna ha trovato
**quattro colpevoli veri** — tutti nostri, nessuno del modello — e ha
lasciato un metodo di prova che questa pagina fissa.

Cronaca completa con le misure:
`ricerche/tracce-e-loop-agente-misure.md`. Le ricerche gemelle:
`ricerche/harness-agentici-ciclo-multistep.md` (come lo fanno Claude Code,
Cline, Qwen-Agent & co.) e
`ricerche/multi-turn-tool-calling-qwen-llamacpp.md`.

---

## Il percorso di una chiamata (e dove può morire)

```
modello emette tool_call (nativa, nello stream)
   ↓ llm_core: parsing dello stream          ← moriva qui (bug streaming llama.cpp)
   ↓ agent_loop: _resolve_tool_blocks
   ↓ tool_schemas: function_call_to_tool_block
       gate: nome ∈ TOOL_TAGS?              ← moriva qui (fin_* mai registrati)
   ↓ TOOL_HANDLERS[nome] esegue
   ↓ _append_tool_results → giro successivo
```

**La proprietà maligna**: ogni morte in questa catena è SILENZIOSA per
l'utente. La chiamata scartata non produce errori in chat — produce un
modello che sembra «pigro». Se il modello annuncia e non fa: prima sospetta
la catena, poi il modello.

## I quattro colpevoli del 2 agosto (in ordine di scoperta)

1. **Budget di contesto 6000** — la scoperta della finestra fallisce via
   llama-swap → default conservativo → il compattatore AMPUTAVA il system a
   2.000 caratteri («[System prompt truncated for context limits]»), regole
   morte a metà. Fix: `agent_input_token_budget = 40000` esplicito (via
   /api/auth/settings, onorato alla lettera).
2. **La regola "riga-piano"** (nostra, dello stesso giorno) — col system
   integro il modello scriveva il piano SENZA la chiamata. Rimossa,
   sostituita da «Act, do not narrate».
3. **Streaming llama.cpp perde le tool call** dei modelli con thinking —
   provato con A/B: payload identico, non-stream chiama, stream restituisce
   nulla. Fix: `_nonstream_tools_call` in `llm_core.py` — richieste LOCALI
   con tools vanno non-stream, SSE sintetizzato verso il loop
   (`ODYSSEUS_LOCAL_TOOLS_NONSTREAM=0` per disattivare). Bonus misurato:
   thinking OFF peggiora la scelta — il thinking resta acceso.
4. **`TOOL_TAGS`** — il principale. I nomi `fin_*` non erano nel registro:
   il convertitore scartava le chiamate con `Unknown function call` nel log
   e basta. Ora i nomi si derivano dagli handler
   (`agent_tools/__init__.py`): un tool nuovo con prefisso `osint_`/`fin_`
   è registrato automaticamente.

## Le difese ora nel loop

- **Supervisore "ha annunciato ma non ha chiamato"** (`agent_loop.py`,
  `_INTENT_RE`): bilingue (compresi gerundi e «iniziamo/analizziamo»), più
  rete generale sui verbi al FUTURO italiano («approfondiremo»). Il nudge è
  in **ruolo user** stile Cline (`[ERROR] You wrote … but called no tool`),
  contatore a 3; il giro dopo il nudge forza `tool_choice: "required"`
  (llama.cpp lo garantisce per grammatica).
- **Promemoria di stato dal 3° giro** (ruolo user): «tools già usati: …
  chiudi o fai LA chiamata mancante» — append-only, il prefisso cache resta.
- **Thinking strippato dalla storia** (`_append_tool_results`): regola
  ufficiale Qwen — nei turni precedenti resta solo l'output finale.
  `reasoning_content` re-iniettato solo per DeepSeek.
- **Temperatura per fase**: giri con schemi ≤0,25; sintesi finale a
  temperatura del preset.
- **Scala anti-spirale nel dato** (`briefing.py`, tema): match espanso
  IT→EN → ricerca approfondita dichiarata → tutto-senza-filtro con
  dichiarazione d'incapacità e alternative. Mai il vuoto secco a un 9B.
- **Memoria delle tracce riuscite** (`src/tracce_agente.py` +
  `data/tracce_riuscite.jsonl`): i turni buoni registrano domanda+sequenza;
  alla domanda simile la sequenza vincente viene appesa in coda al
  messaggio utente (mai nel system: cache KV).

## Il quinto colpevole: il parametro usato male (2 ago, mattina)

«cercami news su Boeing» → il modello metteva **"Boeing" nel campo `luogo`**.
Il geocoder non lo risolve, la ricerca globale per solo-tema pescava proteste
in Svezia, e il modello riprovava con `luogo="Boeing stock"`. Equivale a non
trovare niente, sempre.

Fix nel codice, non nelle regole:

1. parametro **`soggetto`** esplicito (azienda/persona/organizzazione, cercato
   NEL TESTO, mai geocodificato);
2. `luogo` non riconosciuto → **diventa soggetto da solo**, dichiarandolo
   (`luogo_come_soggetto`) invece di fallire in silenzio;
3. con un soggetto Python aggrega **tre fonti in una chiamata**: gdelt +
   wire finanziario (`finnhub_news`) + web come ripiego se gdelt è magro.
   «Cercami news su X» diventa **una mossa**, non tre.

Misura sul caso esatto del bug: prima zero risultati utili; dopo, con la
**stessa chiamata sbagliata**, 2 notizie dal wire + 6 dal web.

**La lezione**: un campo chiamato `luogo` prima o poi riceve un'azienda. Il
server converte e dichiara; non fallisce muto.

## La prova: doppio banco, obbligatorio

| Banco | Cosa misura | Cosa NON vede |
|---|---|---|
| `scripts/prova_modello_finanza.py` | scelta dello strumento (15 casi, 3 giri, tool eseguiti) | la catena del loop: esegue gli handler per nome, salta il convertitore |
| `scripts/prova_e2e_agente.py` | IL LOOP VERO: login, sessione, `/api/chat_stream`, stessi turni dell'utente | — |

Ultima corsa verde (2 ago, sera): banco **17/17** e **E2E 4/4**, compresi i
due casi nuovi di `osint_web` (background CEO → web; prezzo NVDA → MAI il
web) e `osint_notizie(soggetto=Boeing)`.

Avvertenza da cold-start: il **primo** turno dopo il boot può morire in «The
model returned an empty response» mentre llama-swap carica il modello
(~5 min sprecati in attesa). Non è il loop: l'E2E si giudica **a caldo** —
stessa corsa, riprovata subito dopo, 4/4.

Il banco diretto ha fatto 13/13 mentre la chat vera moriva: **un verde sul
banco sbagliato certifica il nulla**. Diagnosi quando l'E2E fallisce:
`ODYSSEUS_LLM_DUMP=<dir>` al riavvio → ogni payload verso il modello finisce
su disco → si legge ESATTAMENTE cosa riceve il modello al giro incriminato.
Nel log (`avvio-odysseus.log`): `Unknown function call`, `FAILED to
convert`, `[System prompt truncated`.

## La lingua dei prompt (misurato, non teorizzato)

A/B/C sul banco diretto (2 ago):

| Variante | Esito |
|---|---|
| Regole piene + description piene | 13/13 logico |
| Regole caveman (−24÷56%) + description piene | **13/13** |
| Tutto caveman (anche description) | 13/13 logico ma il modello torna a cercare in ITALIANO |

Politica adottata: **REGOLE in caveman-full** (via articoli e riempitivi,
frasi leggibili — in produzione da oggi), **DESCRIPTION mai compresse** (là
le sfumature lavorano: «ENGLISH keywords», gli esempi d'uso). Regole in
inglese, esempi utente in italiano, «Always answer in Italian» in testa E
coda — vedi `ricerche/lingua-system-prompt-inglese-vs-italiano.md`.

## File

| File | Ruolo |
|---|---|
| `src/agent_loop.py` | loop, supervisore intent, promemoria, strip thinking |
| `src/llm_core.py` | ponte non-stream per tools locali, `tool_choice`, dump payload |
| `src/agent_tools/__init__.py` | `TOOL_TAGS` (derivazione osint_/fin_) |
| `src/tool_schemas.py` | convertitore nativa→ToolBlock (il gate) |
| `src/tracce_agente.py` | memoria delle sequenze riuscite |
| `src/context_budget.py` | budget di contesto (40K esplicito nei settings) |
| `scripts/prova_e2e_agente.py` | il banco end-to-end |
