# Personalità e skill

## La personalità: i preset

Odysseus gestisce personalità con **preset**, non con file di prompt
modificabile. Codice è in `src/preset_manager.py`, dati in `data/presets.json`.

Campi di un preset: `name`, `character_name`, `system_prompt`, `inject_prefix`,
`inject_suffix`, `temperature`, `max_tokens`, `enabled`.

- **Predefiniti**: `code_analyze` (temperatura 0.2), `brainstorm` (0.9),
  `reason` (0.3).
- **`custom`**: slot editabile, spento di default. **È qui che va personalità
  persistente.**
- **`user_templates`**: libreria di personaggi salvati da cui caricare nello slot
  custom.

### Tre modi per impostarla

1. Interfaccia: barra chat → `+` → **Prompt** → tab **Persona**.
2. API: `POST /api/presets/custom` — **corpo JSON**, non form (errore che abbiamo
   fatto e corretto).
3. File: `data/presets.json`, chiave `custom`, con `"enabled": true`.

### Tre dettagli che contano

**Il prompt del preset non sostituisce quello di base.** Viene aggiunto come
messaggio di sistema in testa. Prompt di base è assemblato a runtime dalle
sezioni degli strumenti: non esiste file di testo da editare. Quindi
personalità **non rompe** tool, memoria o skill.

**Il preset si attiva al caricamento della pagina.** Odysseus lo auto-seleziona
all'avvio se è abilitato e ha contenuto. Dopo averlo salvato serve **una ricarica**
perché entri in vigore nella sessione corrente.

**`inject_prefix` e `inject_suffix` non vanno nel prompt di sistema**: vengono
attaccati al testo del messaggio utente lato browser, solo a preset attivo.

## Le emozioni dell'avatar, agganciate alla personalità

Requisito dell'utente: poter riscrivere personalità **senza rompere
emozioni**.

Soluzione in `static/js/avatarPersona.js`: modulo compone prompt come
*personalità scritta dall'utente* **più** blocco di istruzioni sulle emozioni
generato automaticamente, che elenca tag realmente supportati dal modello Live2D
caricato.

Prima di riattaccare blocco, lo **toglie** dalla versione precedente (cerca
marcatore HTML nascosto). Così riscrivere personalità dieci volte non accumula
dieci copie né perde istruzioni.

Se un domani si cambia personaggio con espressioni diverse, elenco dei tag si
aggiorna da solo.

---

## Le skill

### Formato e percorso

`data/skills/<categoria>/<nome>/SKILL.md`. Frontmatter YAML più corpo markdown.

Campi che contano: `name` e `description` (i due che finiscono nel prompt), più
`version`, `category`, `tags`, `platforms`, `requires_toolsets`, `status`
(`draft` | `published`), `confidence`, `source`.

Sezioni riconosciute nel corpo: `## When to Use`, `## Procedure`, `## Pitfalls`,
`## Verification`.

### Come entrano nel prompt — e perché è un problema

**Due livelli:**

1. **Indice completo**: una riga per **ogni** skill (`nome — descrizione`),
   sempre presente in ogni prompt.
2. **Le prime N complete**: fino a `skill_max_injected` (predefinito 3) iniettate
   per intero, scelte per rilevanza.

Il primo livello è il problema. **Con 1000 skill installate avresti 1000 righe
fisse prima ancora della tua domanda.** Su modello da 9B con 48K di contesto è
insostenibile.

Verificato leggendo `src/agent_loop.py` (funzione `_build_base_prompt`) e
`services/memory/skills.py` (`index_for`).

Non esiste oggi ottimizzazione lato Odysseus. **Il piano R3 dell'utente**
(embedding + recupero delle skill) è esattamente la risposta giusta al problema
giusto.

### Cosa abbiamo installato

**13 skill curate**, non 1000. Verificate visibili da Odysseus.

| Categoria | Skill |
|---|---|
| `assistente-pc` | desktop-zero, file-access-preflight, git-troubleshooter, debugging-log-analyser, screenshot-teardown |
| `ricerca-web` | fact-check-pass, source-triangulation, research-protocol, boolean-search-builder, multi-source-signal-synthesiser |
| `voce-persona` | voice-agent-design, prompt-optimizer |
| `gaming` | teach-the-game |

Script che le installa: `d:\assistenteeee\scripts\installa-skill.ps1`.

### La trappola del formato

SKILL.md in formato Claude hanno **solo** `name` e `description` nel
frontmatter. Odysseus richiede anche **`status: published` e `category`**, altrimenti
skill resta **invisibile senza dare errore**. Script le aggiunge in automatico.

### Cosa c'è nelle raccolte pubbliche (e cosa no)

Sfatiamo mito delle "1000+ skill pronte":

- **VoltAgent/awesome-agent-skills**: è solo un **indice di link** in un README,
  non skill scaricabili.
- **pm-claude-skills**: 2574 skill vere, ma quasi tutte business e project
  management (decodificare piani pensionistici, organizzare assemblee...).
  Utili per noi: una trentina.
- **gamedev-skills**: 67 skill, ma è sviluppo di videogiochi (Unity, Unreal,
  Godot), non giocarci.

Repository clonati in `d:\assistenteeee\skills-src\`.

### Libri consigliati per il futuro (conversione book-to-skill)

Tooling [virgiliojr94/book-to-skill](https://github.com/virgiliojr94/book-to-skill)
converte PDF/EPUB in bundle di skill (SKILL.md + capitoli + glossario).

Fonti legali e adatte, in ordine di valore per noi:

1. **PowerShell 101** e **The Big Book of PowerShell Gotchas** (DevOps Collective,
   gratuiti su Leanpub mettendo 0€) — ricette e trappole passo-passo, si mappano
   perfettamente su Procedura e Trappole. Per assistente PC.
2. **Dump di wiki di gioco con licenza CC** (Minecraft, Terraria, Stardew Valley
   hanno export legali) — build, strategie e tabelle diventano capitoli e glossario.
3. **Web Literacy for Student Fact-Checkers** di Caulfield (CC BY, su Pressbooks) —
   metodo procedurale per verifica delle fonti.
4. **Prompt Engineering Guide** (DAIR.AI, MIT) — per personalità del compagno
   vocale.

### La trappola delle preferenze

Impostazioni delle skill nella modale **Brain** (auto-estrazione,
auto-approvazione, numero massimo iniettate) scrivono in `data/user_prefs.json` e
**hanno la precedenza** sulle omonime globali di `settings.json`.

Se modifica globale "non fa effetto", colpevole è quasi sempre questo.
