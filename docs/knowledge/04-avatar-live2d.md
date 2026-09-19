# Avatar Live2D: architettura e realizzazione

## L'obiettivo

Avatar animato che **è** l'assistente: quando Odysseus ragiona ha aria
pensierosa, quando usa strumento si vede che lavora, quando risponde parla
muovendo bocca a tempo con voce, cambia espressione secondo tono.

Vincolo posto dall'utente: **un cervello solo**. Non due programmi che si parlano.

## La decisione: dentro, non fuori

Scartata ipotesi Open-LLM-VTuber come applicazione separata: avrebbe suo
ciclo di ragionamento, sua memoria e sua configurazione, non
saprebbe mai *cosa* sta facendo Odysseus, solo cosa dice.

Scartata anche VTube Studio come corpo pilotato da Odysseus: darebbe animazione
più ricca (fisica, respiro, battito ciglia già pronti) ma vive in finestra
separata e **non è incorporabile in pagina web**.

Vale registrare correzione fatta in corsa: avevo detto che opzione
"tela dentro pagina" avrebbe avuto animazione povera perché fisica e respiro
andrebbero riscritti. **Falso**: ciclo di aggiornamento del modello nella
libreria chiama già fisica, respiro, battito ciglia e posa. Ciò che VTube
Studio aggiunge davvero è interfaccia utente, tracciamento webcam e
scorciatoie — non vita del personaggio.

## L'architettura effettiva

```
Odysseus (eventi che già emette)
        │
        ▼
  nucleo avatar  ← macchina a stati + lettura emozioni + pilota del labiale
        │  emette comandi astratti: stato, emozione, apertura bocca
        ├──► schermo 1: tela dentro la pagina di Odysseus
        ├──► schermo 2: finestra widget separata (stessa logica)
        └──► schermo 3: VTube Studio, se un giorno servisse (basta un adattatore)
```

Nucleo non sa niente di come avatar viene disegnato: dice solo "adesso
pensa", "adesso è felice", "adesso bocca è aperta al 40%". Chi disegna è
intercambiabile.

Comandi viaggiano su canale condiviso del browser (`BroadcastChannel`), così
finestra staccata usa **stesso identico renderer** e resta in sincronia con
pagina principale.

## Da dove vengono gli stati (costo zero)

Odysseus emette già, durante ogni risposta, eventi che descrivono in che stato
si trova agente. Dispatcher unico è in `static/js/chat.js` riga ~2320.

| Segnale | Momento | Animazione |
|---|---|---|
| `json.thinking === true` | modello ragiona | posa pensierosa |
| `json.delta` senza thinking | scrive risposta | parla + labiale |
| `tool_start` / `tool_progress` / `tool_output` | usa strumento | posa "al lavoro" |
| `agent_step` | nuovo giro di ragionamento | pensa |
| `metrics` / `[DONE]` | ha finito | riposo |

**Nessun costo in token, nessuna latenza.** Avatar segue ritmo reale
dell'agente, non simulazione.

## Le emozioni

Modello scrive tag a inizio risposta (`[joy]`, `[anger]`...), nucleo
lo estrae e mappa su espressione del modello Live2D.

Approccio preso da Open-LLM-VTuber. Scartato classificatore di sentimento di
SillyTavern: richiede un secondo modello e un giro in più.

Nucleo accetta **sia italiano che inglese** (`[gioia]` o `[joy]`) tramite
tabella di alias, perché modello scrive in italiano ma espressioni del
personaggio hanno nomi inglesi.

Istruzioni su quali tag usare vengono **aggiunte automaticamente** al preset
personalità (vedi [06-personalita-e-skill.md](06-personalita-e-skill.md)): utente
può riscrivere personalità quante volte vuole senza rompere emozioni.

## Il labiale

Analisi dell'audio vero: si preleva segnale dall'elemento audio del TTS, lo
si passa in analizzatore, si calcola ampiezza (RMS) e si pilota parametro
della bocca.

Preso dall'estensione VRM di SillyTavern. Scartato approccio della loro
estensione Live2D, che fa labiale **finto** (onda sinusoidale per tempo
proporzionale a lunghezza del testo, senza nemmeno ascoltare l'audio).

**Nota dopo passaggio allo streaming (1 agosto 2026).** Elemento audio ora
riceve URL che scarica progressivamente invece di blob già completo.
Analizzatore non se ne accorge — lavora su segnale riprodotto, non su file —
ma vale la pena saperlo: se un giorno labiale partisse in ritardo, sospetto
è che elemento venga agganciato prima di avere abbastanza dati bufferizzati.

Due correzioni rispetto alla libreria:

1. **Disattivato labiale interno.** Libreria forza apertura minima al 40%
   appena c'è suono: è motivo per cui negli avatar VTuber bocca
   "sbatacchia" invece di seguire il parlato.
2. **Aggancio all'evento giusto.** Normale ticker verrebbe sovrascritto:
   modello aggiorna suoi parametri *dopo*. Unico punto che sopravvive è
   evento `beforeModelUpdate`.

Trucco copiato da Open-LLM-VTuber: amplificare ampiezza (circa ×2), altrimenti
bocca si muove troppo poco.

## MCP: perché no

Valutato e scartato per animazioni. Motivi:

- Specifica MCP (revisione 28 luglio 2026) **non ha alcuna primitiva di
  streaming** e vieta messaggi iniziati dal server: non esiste canale per
  mandare parametri a 60 fotogrammi al secondo.
- Esiste **un solo** server MCP per VTube Studio su GitHub: 7 stelle, abbandonato.
- Costo: quel server espone 36 strumenti, schemi pesano ~100-1000 token
  ciascuno **prima ancora della domanda**.
- Progetto meglio riuscito del settore (`Mitscherlich/live2d-mcp`) fa
  esattamente quello che facciamo noi: MCP solo per comandi discreti, canale
  separato per dati ad alta frequenza.

**Dove MCP avrebbe senso**: gesti volontari ("salutami", "fai il broncio"), cioè
quando animazione è azione decisa e non stato. Per quelli Odysseus ha già
meccanismo giusto: tool `ui_control`, con suo gestore nel frontend. Basta
aggiungere ramo `avatar`. **Non serve scrivere server MCP.**

## Il modello del personaggio

`mao_pro` (Niziiro Mao), incluso in Open-LLM-VTuber e scaricabile dai
[campioni ufficiali Live2D](https://www.live2d.com/en/learn/sample/). Licenza
Free Material: uso personale e ricerca sì, rivendita no.

Ha **8 espressioni** già mappate: neutro, gioia, rabbia, tristezza, paura,
sorpresa, disgusto, ghigno. E un gruppo di movimenti "Idle".

**Attenzione al formato**: Open-LLM-VTuber (e nostra libreria) supportano
**Cubism 3, 4 e 5, non 2.1**. In pratica: modello deve avere file
`.model3.json` (col "3" finale). Se ha `model.json` senza il 3, è vecchio e non
funziona.

Dove scaricarne altri: [campioni ufficiali](https://www.live2d.com/en/learn/sample/)
(inglese, gratis, i più completi), [BOOTH](https://booth.pm/en/search/free%20live2d),
[nizima](https://nizima.com/) (marketplace ufficiale),
[Eikanya/Live2d-model](https://github.com/Eikanya/Live2d-model) (enorme raccolta
estratta da giochi, licenza problematica).

## Interfaccia utente

**Impostazioni → Aspetto**, scheda in fondo:
- interruttore di accensione (spento di default)
- menu di scelta del modello
- casella della personalità con nome e pulsante "Applica"

Riquadro si **trascina** col mouse, si **ridimensiona** dall'angolo, e
posizione e dimensione vengono **ricordate**. Resta sempre dentro schermo anche
ridimensionando finestra. Due pulsantini al passaggio mouse: stacca in
finestra separata, nascondi.

Inquadratura: modelli Live2D sono altissimi (mao_pro è 5800×8400 pixel), quindi
farli entrare interi in riquadro piccolo lascia faccia grande come
francobollo. Renderer inquadra il busto.

## Compatibilità futura con Odysseus

Odysseus ha già in cantiere funzione "Agent Avatar" (issue #4182, #4184,
#4185, in stato "pronte per revisione", **non ancora nel ramo main** — verificato:
`static/js/avatarEmotion.js` non esiste nel nostro checkout).

È pensata per ritratto statico con anello CSS pulsante, non per avatar
animato, ma definisce **nomi degli eventi**. Ci siamo allineati:

- evento `avatar-speak` con `detail.audio`
- evento `avatar-emotion`
- proprietà CSS `--speak-intensity` pilotata dall'ampiezza
- classe `is-speaking` sui nodi `.role-agent-avatar`

Così il giorno che loro rilasciano loro versione, la nostra si incastra invece
di rompersi.

## Licenze

- Libreria di disegno: MIT.
- **Cubism Core: licenza proprietaria Live2D**, ma è "codice ridistribuibile":
  self-hosting è esplicitamente permesso a condizione di servirlo **immutato**
  (non ri-minificarlo, non concatenarlo in bundle, non togliere intestazione).
- Modelli campione: Free Material License.
- Licenza di rilascio SDK: esenzione per privati e aziende sotto 10 milioni di
  yen di fatturato. **Uso personale: gratis.**
- Trappola per il futuro: "applicazioni espandibili" (dove utente finale può
  caricare modelli Live2D propri) richiedono **sempre** approvazione e licenza, a
  prescindere dal fatturato. Riguarda solo eventuale distribuzione pubblica.
