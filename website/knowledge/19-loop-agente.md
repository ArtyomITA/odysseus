# Il loop agente: come funziona, dove si rompeva, come si prova

Il 2 agosto multistep in chat era morto: modello faceva una chiamata e
poi «annunciava» seconda senza farla. Caccia notturna ha trovato
**quattro colpevoli veri** — tutti nostri, nessuno del modello — e
lasciato metodo di prova che questa pagina fissa.

Cronaca completa con misure:
`ricerche/tracce-e-loop-agente-misure.md`. Ricerche gemelle:
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

**Proprietà maligna**: ogni morte in questa catena è SILENZIOSA per
utente. Chiamata scartata non produce errori in chat — produce
modello che sembra «pigro». Se modello annuncia e non fa: sospetta
prima catena, poi modello.

## I quattro colpevoli del 2 agosto (in ordine di scoperta)

1. **Budget di contesto 6000** — scoperta della finestra fallisce via
   llama-swap → default conservativo → compattatore AMPUTAVA system a
   2.000 caratteri («[System prompt truncated for context limits]»), regole
   morte a metà. Fix: `agent_input_token_budget = 40000` esplicito (via
   /api/auth/settings, onorato alla lettera).
2. **La regola "riga-piano"** (nostra, dello stesso giorno) — col system
   integro modello scriveva piano SENZA chiamata. Rimossa,
   sostituita da «Act, do not narrate».
3. **Streaming llama.cpp perde tool call** dei modelli con thinking —
   provato con A/B: payload identico, non-stream chiama, stream restituisce
   nulla. Fix: `_nonstream_tools_call` in `llm_core.py` — richieste LOCALI
   con tools vanno non-stream, SSE sintetizzato verso loop
   (`ODYSSEUS_LOCAL_TOOLS_NONSTREAM=0` per disattivare). Bonus misurato:
   thinking OFF peggiora scelta — thinking resta acceso.
4. **`TOOL_TAGS`** — il principale. Nomi `fin_*` non erano nel registro:
   convertitore scartava chiamate con `Unknown function call` nel log
   e basta. Ora nomi si derivano dagli handler
   (`agent_tools/__init__.py`): tool nuovo con prefisso `osint_`/`fin_`
   è registrato automaticamente.

## Le difese ora nel loop

- **Supervisore "ha annunciato ma non ha chiamato"** (`agent_loop.py`,
  `_INTENT_RE`): bilingue (compresi gerundi e «iniziamo/analizziamo»), più
  rete generale sui verbi al FUTURO italiano («approfondiremo»). Nudge è
  in **ruolo user** stile Cline (`[ERROR] You wrote … but called no tool`),
  contatore a 3; giro dopo nudge forza `tool_choice: "required"`
  (llama.cpp lo garantisce per grammatica).
- **Promemoria di stato dal 3° giro** (ruolo user): «tools già usati: …
  chiudi o fai LA chiamata mancante» — append-only, prefisso cache resta.
- **Thinking strippato dalla storia** (`_append_tool_results`): regola
  ufficiale Qwen — nei turni precedenti resta solo l'output finale.
  `reasoning_content` re-iniettato solo per DeepSeek.
- **Temperatura per fase**: giri con schemi ≤0,25; sintesi finale a
  temperatura del preset.
- **Scala anti-spirale nel dato** (`briefing.py`, tema): match espanso
  IT→EN → ricerca approfondita dichiarata → tutto-senza-filtro con
  dichiarazione d'incapacità e alternative. Mai vuoto secco a un 9B.
- **Memoria delle tracce riuscite** (`src/tracce_agente.py` +
  `data/tracce_riuscite.jsonl`): turni buoni registrano domanda+sequenza;
  alla domanda simile la sequenza vincente viene appesa in coda al
  messaggio utente (mai nel system: cache KV).

## Il quinto colpevole: il parametro usato male (2 ago, mattina)

«cercami news su Boeing» → modello metteva **"Boeing" nel campo `luogo`**.
Geocoder non lo risolve, ricerca globale per solo-tema pescava proteste
in Svezia, modello riprovava con `luogo="Boeing stock"`. Equivale a
non trovare niente, sempre.

Fix nel codice, non nelle regole:

1. parametro **`soggetto`** esplicito (azienda/persona/organizzazione, cercato
   NEL TESTO, mai geocodificato);
2. `luogo` non riconosciuto → **diventa soggetto da solo**, dichiarandolo
   (`luogo_come_soggetto`) invece di fallire in silenzio;
3. con soggetto Python aggrega **tre fonti in una chiamata**: gdelt +
   wire finanziario (`finnhub_news`) + web come ripiego se gdelt è magro.
   «Cercami news su X» diventa **una mossa**, non tre.

Misura sul caso esatto del bug: prima zero risultati utili; dopo, con
**stessa chiamata sbagliata**, 2 notizie dal wire + 6 dal web.

**La lezione**: campo chiamato `luogo` prima o poi riceve un'azienda.
Server converte e dichiara; non fallisce muto.

## La prova: doppio banco, obbligatorio

| Banco | Cosa misura | Cosa NON vede |
|---|---|---|
| `scripts/prova_modello_finanza.py` | scelta dello strumento (15 casi, 3 giri, tool eseguiti) | catena del loop: esegue handler per nome, salta il convertitore |
| `scripts/prova_e2e_agente.py` | IL LOOP VERO: login, sessione, `/api/chat_stream`, stessi turni dell'utente | — |

Ultima corsa verde (2 ago, sera): banco **17/17** e **E2E 4/4**, compresi
due casi nuovi di `osint_web` (background CEO → web; prezzo NVDA → MAI il
web) e `osint_notizie(soggetto=Boeing)`.

Avvertenza da cold-start: **primo** turno dopo il boot può morire in «The
model returned an empty response» mentre llama-swap carica modello
(~5 min sprecati in attesa). Non è il loop: E2E si giudica **a caldo** —
stessa corsa, riprovata subito dopo, 4/4.

Banco diretto ha fatto 13/13 mentre chat vera moriva: **verde sul
banco sbagliato certifica il nulla**. Diagnosi quando E2E fallisce:
`ODYSSEUS_LLM_DUMP=<dir>` al riavvio → ogni payload verso modello finisce
su disco → si legge ESATTAMENTE cosa riceve modello al giro incriminato.
Nel log (`avvio-odysseus.log`): `Unknown function call`, `FAILED to
convert`, `[System prompt truncated`.

## La lingua dei prompt (misurato, non teorizzato)

A/B/C sul banco diretto (2 ago):

| Variante | Esito |
|---|---|
| Regole piene + description piene | 13/13 logico |
| Regole caveman (−24÷56%) + description piene | **13/13** |
| Tutto caveman (anche description) | 13/13 logico ma modello torna a cercare in ITALIANO |

Politica adottata: **REGOLE in caveman-full** (via articoli e riempitivi,
frasi leggibili — in produzione da oggi), **DESCRIPTION mai compresse** (là
sfumature lavorano: «ENGLISH keywords», esempi d'uso). Regole in
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
