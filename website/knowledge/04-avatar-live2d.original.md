# Avatar Live2D: architettura e realizzazione

## L'obiettivo

Un avatar animato che **è** l'assistente: quando Odysseus ragiona ha l'aria
pensierosa, quando usa uno strumento si vede che lavora, quando risponde parla
muovendo la bocca a tempo con la voce, e cambia espressione secondo il tono.

Vincolo posto dall'utente: **un cervello solo**. Non due programmi che si parlano.

## La decisione: dentro, non fuori

Scartata l'ipotesi Open-LLM-VTuber come applicazione separata: avrebbe avuto un
suo ciclo di ragionamento, una sua memoria e una sua configurazione, e non
saprebbe mai *cosa* sta facendo Odysseus, solo cosa dice.

Scartata anche VTube Studio come corpo pilotato da Odysseus: darebbe animazione
più ricca (fisica, respiro, battito di ciglia già pronti) ma vive in una finestra
separata e **non è incorporabile in una pagina web**.

Vale la pena registrare una correzione fatta in corsa: avevo detto che l'opzione
"tela dentro la pagina" avrebbe avuto animazione povera perché fisica e respiro
andrebbero riscritti. **Falso**: il ciclo di aggiornamento del modello nella
libreria chiama già fisica, respiro, battito di ciglia e posa. Quello che VTube
Studio aggiunge davvero è l'interfaccia utente, il tracciamento della webcam e le
scorciatoie — non la vita del personaggio.

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

Il nucleo non sa niente di come l'avatar viene disegnato: dice solo "adesso
pensa", "adesso è felice", "adesso la bocca è aperta al 40%". Chi disegna è
intercambiabile.

I comandi viaggiano su un canale condiviso del browser (`BroadcastChannel`), così
la finestra staccata usa **lo stesso identico renderer** e resta in sincronia con
la pagina principale.

## Da dove vengono gli stati (costo zero)

Odysseus emette già, durante ogni risposta, gli eventi che descrivono in che stato
si trova l'agente. Il dispatcher unico è in `static/js/chat.js` riga ~2320.

| Segnale | Momento | Animazione |
|---|---|---|
| `json.thinking === true` | il modello ragiona | posa pensierosa |
| `json.delta` senza thinking | scrive la risposta | parla + labiale |
| `tool_start` / `tool_progress` / `tool_output` | usa uno strumento | posa "al lavoro" |
| `agent_step` | nuovo giro di ragionamento | pensa |
| `metrics` / `[DONE]` | ha finito | riposo |

**Nessun costo in token, nessuna latenza.** L'avatar segue il ritmo reale
dell'agente, non una simulazione.

## Le emozioni

Il modello scrive un tag all'inizio della risposta (`[joy]`, `[anger]`...), il
nucleo lo estrae e lo mappa sull'espressione del modello Live2D.

Approccio preso da Open-LLM-VTuber. Scartato il classificatore di sentimento di
SillyTavern: richiede un secondo modello e un giro in più.

Il nucleo accetta **sia italiano che inglese** (`[gioia]` o `[joy]`) tramite una
tabella di alias, perché il modello scrive in italiano ma le espressioni del
personaggio hanno nomi inglesi.

Le istruzioni su quali tag usare vengono **aggiunte automaticamente** al preset
personalità (vedi [06-personalita-e-skill.md](06-personalita-e-skill.md)): l'utente
può riscrivere la personalità quante volte vuole senza rompere le emozioni.

## Il labiale

Analisi dell'audio vero: si preleva il segnale dall'elemento audio del TTS, lo si
passa in un analizzatore, si calcola l'ampiezza (RMS) e si pilota il parametro
della bocca.

Preso dall'estensione VRM di SillyTavern. Scartato l'approccio della loro
estensione Live2D, che fa un labiale **finto** (onda sinusoidale per un tempo
proporzionale alla lunghezza del testo, senza nemmeno ascoltare l'audio).

**Nota dopo il passaggio allo streaming (1 agosto 2026).** L'elemento audio ora
riceve una URL che scarica progressivamente invece di un blob già completo.
L'analizzatore non se ne accorge — lavora sul segnale riprodotto, non sul file —
ma vale la pena saperlo: se un giorno il labiale partisse in ritardo, il sospetto
è che l'elemento venga agganciato prima di avere abbastanza dati bufferizzati.

Due correzioni rispetto alla libreria:

1. **Disattivato il labiale interno.** La libreria forza l'apertura minima al 40%
   appena c'è un suono: è il motivo per cui negli avatar VTuber la bocca
   "sbatacchia" invece di seguire il parlato.
2. **Aggancio all'evento giusto.** Un normale ticker verrebbe sovrascritto: il
   modello aggiorna i suoi parametri *dopo*. L'unico punto che sopravvive è
   l'evento `beforeModelUpdate`.

Trucco copiato da Open-LLM-VTuber: amplificare l'ampiezza (circa ×2), altrimenti
la bocca si muove troppo poco.

## MCP: perché no

Valutato e scartato per le animazioni. Motivi:

- La specifica MCP (revisione 28 luglio 2026) **non ha alcuna primitiva di
  streaming** e vieta i messaggi iniziati dal server: non esiste il canale per
  mandare parametri a 60 fotogrammi al secondo.
- Esiste **un solo** server MCP per VTube Studio su GitHub: 7 stelle, abbandonato.
- Costo: quel server espone 36 strumenti, e gli schemi pesano ~100-1000 token
  ciascuno **prima ancora della domanda**.
- Il progetto meglio riuscito del settore (`Mitscherlich/live2d-mcp`) fa
  esattamente quello che facciamo noi: MCP solo per i comandi discreti, canale
  separato per i dati ad alta frequenza.

**Dove MCP avrebbe senso**: gesti volontari ("salutami", "fai il broncio"), cioè
quando l'animazione è un'azione decisa e non uno stato. Per quelli Odysseus ha già
il meccanismo giusto: il tool `ui_control`, con il suo gestore nel frontend. Basta
aggiungere un ramo `avatar`. **Non serve scrivere un server MCP.**

## Il modello del personaggio

`mao_pro` (Niziiro Mao), incluso in Open-LLM-VTuber e scaricabile dai
[campioni ufficiali Live2D](https://www.live2d.com/en/learn/sample/). Licenza
Free Material: uso personale e ricerca sì, rivendita no.

Ha **8 espressioni** già mappate: neutro, gioia, rabbia, tristezza, paura,
sorpresa, disgusto, ghigno. E un gruppo di movimenti "Idle".

**Attenzione al formato**: Open-LLM-VTuber (e la nostra libreria) supportano
**Cubism 3, 4 e 5, non il 2.1**. In pratica: il modello deve avere un file
`.model3.json` (col "3" finale). Se ha `model.json` senza il 3, è vecchio e non
funziona.

Dove scaricarne altri: i [campioni ufficiali](https://www.live2d.com/en/learn/sample/)
(inglese, gratis, i più completi), [BOOTH](https://booth.pm/en/search/free%20live2d),
[nizima](https://nizima.com/) (marketplace ufficiale),
[Eikanya/Live2d-model](https://github.com/Eikanya/Live2d-model) (enorme raccolta
estratta da giochi, licenza problematica).

## Interfaccia utente

**Impostazioni → Aspetto**, scheda in fondo:
- interruttore di accensione (spento di default)
- menu di scelta del modello
- casella della personalità con nome e pulsante "Applica"

Il riquadro si **trascina** col mouse, si **ridimensiona** dall'angolo, e
posizione e dimensione vengono **ricordate**. Resta sempre dentro lo schermo anche
ridimensionando la finestra. Due pulsantini al passaggio del mouse: stacca in
finestra separata, nascondi.

Inquadratura: i modelli Live2D sono altissimi (mao_pro è 5800×8400 pixel), quindi
farli entrare interi in un riquadro piccolo lascia una faccia grande come un
francobollo. Il renderer inquadra il busto.

## Compatibilità futura con Odysseus

Odysseus ha già in cantiere una funzione "Agent Avatar" (issue #4182, #4184,
#4185, in stato "pronte per revisione", **non ancora nel ramo main** — verificato:
`static/js/avatarEmotion.js` non esiste nel nostro checkout).

È pensata per un ritratto statico con anello CSS pulsante, non per un avatar
animato, ma definisce i **nomi degli eventi**. Ci siamo allineati:

- evento `avatar-speak` con `detail.audio`
- evento `avatar-emotion`
- proprietà CSS `--speak-intensity` pilotata dall'ampiezza
- classe `is-speaking` sui nodi `.role-agent-avatar`

Così il giorno che loro rilasciano la loro versione, la nostra si incastra invece
di rompersi.

## Licenze

- La libreria di disegno: MIT.
- **Il Cubism Core: licenza proprietaria Live2D**, ma è "codice ridistribuibile":
  il self-hosting è esplicitamente permesso a condizione di servirlo **immutato**
  (non ri-minificarlo, non concatenarlo in un bundle, non togliere l'intestazione).
- Modelli campione: Free Material License.
- Licenza di rilascio SDK: esenzione per privati e aziende sotto i 10 milioni di
  yen di fatturato. **Uso personale: gratis.**
- Trappola per il futuro: le "applicazioni espandibili" (dove l'utente finale può
  caricare modelli Live2D propri) richiedono **sempre** approvazione e licenza, a
  prescindere dal fatturato. Riguarda solo un'eventuale distribuzione pubblica.
