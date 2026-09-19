# Il profilo Financial

Sottoinsieme di Intelligence, non un'aggiunta. **Otto strumenti invece di
undici**, più un preset di mappa che si accende insieme al profilo e un
popup di configurazione che compare a ogni attivazione.

Per i dati grezzi vedi [16-finnhub.md](16-finnhub.md) e
[17-catalogo-dati.md](17-catalogo-dati.md).

---

## Perché restringere invece di aggiungere

Con i dieci strumenti OSINT davanti, alla domanda *«come sta messa la difesa?»*
un 9B chiama `osint_militare` — che parla di aerei, non di titoli. Le parole si
somigliano, i dati no.

Misurato con il modello vero (`scripts/prova_modello_finanza.py`):

```
prima delle correzioni       6 / 10 scelte corrette
dopo (regole in italiano)   10 / 10   tempo medio 27 s
dopo (regole in inglese)    10 / 10   tempo medio 24,7 s
```

Il passaggio all'inglese ha richiesto un giro di taratura: la prima stesura
faceva 9/10 («nascondi tutto tranne i contratti» si fermava al passo 1).
Rinforzato il passo 2 («after the data tool returns, your NEXT tool call is
osint_mappa») è tornato 10/10 — la lezione della regola scritta come ricetta
vale in qualunque lingua.

I tre errori trovati e come sono stati chiusi, in fondo a questa pagina.

## Cosa contiene

| Strumento | Ruolo |
|---|---|
| `fin_mercati` | quotazioni difesa/tech/cripto + notizie + **l'anomalia già trovata**; con `titolo` quota UN titolo per nome/ticker (Finnhub `/search` + `/quote`), oppure `disponibile: false` col motivo (27 ago 2026, caso Leonardo) |
| `fin_appalti` | contratti federali con **il luogo**: gli unici dati economici mappabili |
| `fin_insider` | movimenti degli interni con **MSPR**, indice da -100 a +100 |
| `fin_archivio` | **il passato**: l'archivio RAG di notizie, picchi, contratti, insider |
| `osint_mappa` | per evidenziare — senza, il modello descrive a parole e la mappa resta ferma |
| `osint_notizie` | per incrociare con la geopolitica **e leggere il testo** di un articolo (url/id) |
| `osint_dettaglio` | la scheda intera di qualcosa già citato |
| `osint_web` | background che wire e archivio non hanno: «chi è il CEO», «cosa produce X» |

Mappa e notizie **non sono un'aggiunta di comodo**: «questa commessa dove sta» e
«che notizie la spiegano» sono esattamente le domande per cui il profilo esiste.
`osint_web` (2 ago) è la via d'uscita quando i feed non sanno: la regola gli
impone parole chiave in inglese, fonte dichiarata, e **numeri mai dagli
snippet** — quelli restano ai `fin_*`.

**E il viceversa**: Intelligence ha ricevuto `fin_mercati` (solo quello — 11
strumenti in tutto), con la regola simmetrica: lì le news di default sono
mondiali e i mercati si toccano solo se la domanda è di mercati; qui le news
di default sono finanziarie e `osint_notizie` serve a incrociare.

## Costo

```
fin_mercati    1.165 token
fin_appalti    1.409
fin_insider    1.072
                        i tre insieme: 3.360 token = 7,0% di 48K
```

---

> **Aggiornamento 2 ago, sera:** il multistep in chat era rotto per quattro
> cause di LOOP, non di profilo — la storia intera sta in
> [19-loop-agente.md](19-loop-agente.md). Le regole sono ora compresse in
> stile caveman-full (misurato: nessuna degradazione; le description invece
> restano piene, comprimerle fa regredire le keyword all'italiano).

## Le regole sono in inglese (e l'output resta italiano)

Le `REGOLE_FINANCE`/`REGOLE_OSINT` e le description dei tool sono state
riscritte in inglese: un modello piccolo segue le istruzioni molto meglio
nella sua lingua-pivot, e il function calling di Qwen è addestrato su schemi
inglesi. L'output resta italiano per regola esplicita, **ripetuta in testa e
in coda** (le istruzioni si dimenticano coi turni). Gli esempi fra virgolette
restano in italiano: devono somigliare a ciò che scrive l'utente.
Fonti e misure: `ricerche/lingua-system-prompt-inglese-vs-italiano.md`.

## Il popup di configurazione

A **ogni** attivazione del profilo (e all'avvio, se era rimasto acceso)
compare il popup di configurazione — le scelte pesano sul budget Finnhub
condiviso e non vanno ereditate in silenzio:

| Opzione | Effetto |
|---|---|
| Titoli Core (25) / Broad (60) | broad = +35 simboli (banche, energia, industriali, farmaceutici), prezzi ogni 2 min invece di 1 |
| Deep news | notizie su 30 titoli con finestra 7 giorni (invece di 13 su 3) |
| Realtime | 10 titoli chiave riquotati ogni 30 s |

Il popup mostra anche **le regole vere del profilo** (da
`GET /api/shadowbroker/rules`) — l'operatore legge lo stesso contratto che
vincola il modello. Le scelte finiscono in `data/financial_config.json` del
backend via `POST /api/shadowbroker/financial-config` (proxy: la CSP
`connect-src 'self'` impedisce al browser di parlare con la porta 8000).

## La regola della mappa: evidenzia, non spegne

Accendendo il profilo, la mappa riceve il preset `financial`, **magro di
proposito**:

```
gdelt · news · military_bases · datacenters
```

Prima conteneva anche voli militari, navi e centrali elettriche: sullo
schermo erano 40.000 punti arancioni che non parlavano di finanza, e il
preset sembrava non fare nulla. Eventi e news restano (gli alert servono
anche qui), le basi restano (è dove atterrano gli appalti evidenziati), il
resto si accende a richiesta. Nel cruscotto ShadowBroker lo stesso insieme
vive nello switch **FINANCIAL MAP MODE** del pannello FINANCIAL.

Da lì in poi il modello **evidenzia e basta**. `osint_mappa azione=livelli`
spegnerebbe quello che l'operatore sta guardando, e il preset tiene già acceso
solo ciò che serve: far risaltare basta, cancellare no.

Vale **anche** quando la richiesta è «nascondi tutto tranne i contratti». Nella
prova, dopo la riscrittura delle regole, il modello risponde con
`fin_appalti` + `osint_mappa(azione=evidenzia)` — che è la cosa giusta.

Catena verificata da capo a fondo:

```
preset financial  ->  4 livelli accesi
fin_appalti       ->  5 contratti, 3 mappabili, ognuno con un id
osint_mappa       ->  {"dispatched": true, "count": 3}
coda del cruscotto ->  [{"id":"appalti:bbf7c2","lat":41.6,"lng":-72.7,
                        "label":"GD 2026-04-03 42184M"}, …]
```

---

## Le trappole nei dati, e come sono chiuse

Tutte trovate misurando, nessuna leggendo la documentazione.

### 1. I contratti quadro seppellivano quelli veri

Ordinando per importo, i primi dieci posti erano **veicoli OASIS+ e GWAC**: tetti
nominali da mille miliardi, senza luogo di esecuzione e senza significato come
"commessa". Risultato: **zero contratti mappabili su dieci**, e le commesse vere
(missili per il Qatar, motori F-22) sparite sotto.

Filtro: importo ≥ 100.000 M$ **oppure** oggetto che contiene `OASIS`, `GWAC`,
`GOVERNMENT-WIDE ACQUISITION`, `ALLIANT`, `UMBRELLA`, `FEDERAL SUPPLY SCHEDULE`,
`IDIQ`, `IGF::`.

Dopo il filtro, in cima: **Columbia class design completion, 42.184 M$,
Connecticut**. Il numero di esclusi viene dichiarato, non nascosto.

### 2. Lo stesso contratto fino a quattro volte

`F119 CY25-CY27 ENGINE SUSTAINMENT` a 5.390,7 M$ compariva **quattro volte**, con
date di azione diverse. Sono ri-obbligazioni dello stesso programma.

La chiave di deduplica quindi **non include la data**: solo simbolo, importo,
agenzia e oggetto. Su dodici mesi di sei contractor: 2.106 duplicati scartati.

### 3. MSPR satura, e il mio ordinamento ci è cascato

MSPR è un **rapporto**: vale +100 sia per un acquisto da 162 azioni sia per uno
da centomila. Ordinando per |MSPR| finivano in cima quattro +100 da poche
centinaia di azioni, mentre una vendita da **183.876 azioni** con MSPR -63
restava sotto.

Ordinamento corretto: `|MSPR| × log₁₀(10 + |azioni|)`. Il rapporto dice *quanto
unanime* è stato il mese, la quantità dice *quanto pesa* — servono entrambi.

### 4. Il codice `A` non è un acquisto

Fra i movimenti di Palantir: `Buckley Jeffrey A +17.124 @ 0`. Prezzo zero. È
un'**assegnazione**, non una decisione di mercato. Contarla come acquisto
invertirebbe il segno del segnale.

Solo `P` e `S` sono decisioni. Ogni movimento porta `decisione_di_mercato`
esplicito e la spiegazione del codice.

### 5. Il luogo c'è nel 90% dei casi, ma non sempre

`performanceState` è popolato su 1.805 righe su 2.000. Le forniture a catalogo
non hanno luogo di esecuzione. Va trattato come **opzionale**: un campo che
esiste nello schema non è un campo che esiste nel dato — stesso errore già
pagato con i titoli delle notizie.

Il luogo è lo **stato**, approssimato al suo centro. Fingere una precisione
maggiore sarebbe peggio che dichiarare l'approssimazione.

---

## I tre errori del modello, e cosa li ha chiusi

| Sbagliava | Perché | Correzione |
|---|---|---|
| *«qual è l'MSPR di Palantir?»* → rispondeva a memoria | sapeva cosa significa MSPR, non che è un dato da leggere | la descrizione ora **apre** con MSPR; regola: «non rispondere a memoria su un dato che uno strumento ha» |
| *«che tempo fa a Milano?»* → chiamava `osint_notizie` | nessuna via d'uscita dal profilo | regola: se è fuori tema, dillo in una riga e non forzare uno strumento |
| *«mostrami sulla mappa»* → non chiamava niente | la regola era scritta al negativo («non usare livelli») | riscritta in positivo, come **ricetta a due passi**: prendi i dati, poi evidenzia gli id |

L'ultima è la più istruttiva. Una regola che dice solo cosa **non** fare lascia
il modello senza alternative, e la risposta diventa il silenzio.

### Il quarto errore: il nesso inventato, e perché non era colpa del modello

Domanda reale: *«quali sono le ultime novità dei mercati? analizza le news in
base ai picchi più grandi»*. Il picco era **Amazon +15,32%**. Risposta:

> *le notizie su PLTR menzionano temi di AI/LLM che potrebbero correlarsi con il
> sentiment tech*

Un ponte fra Amazon e un articolo su Palantir. Nessun nesso.

Ma il modello **non aveva alternative**: il fetcher scaricava le notizie di
azienda solo per i sei titoli della difesa, e il movimento più grande della
giornata era un tech. Otto notizie in mano, un picco del 15% scoperto: il nesso
è stato fabbricato per riempire il buco.

Nessuna regola nel prompt avrebbe risolto. **Il rimedio era dargli la notizia che
mancava**, in tre pezzi:

1. `finnhub_news` copre ora 13 titoli, non 6 (i sette tech che si muovono)
2. `fin_mercati` ordina le notizie **sui picchi**, non per ordine di arrivo
3. campo nuovo `picchi_senza_notizia`, che dichiara il buco invece di lasciarlo
   indovinare

Rifatta la stessa domanda dopo la correzione:

| | Prima | Dopo |
|---|---|---|
| Amazon +15,32% | nesso inventato con Palantir | Jassy sul cloud da mille miliardi — notizia vera |
| Google +6,73% | non menzionato | **«Ha notizia collegata: NO»**, con le ipotesi etichettate come tali |
| Apple −7,35% | non trovato | massimo ribasso, con la sua notizia |

**La lezione generale:** quando un modello inventa un collegamento, la prima
domanda non è «come glielo vieto» ma «gli ho dato di che rispondere?». È la
stessa regola dei layer vuoti, applicata a un livello più su.

Nota minore trovata nella stessa risposta: usava 🔴 sia per +15% sia per −7%.
Su un pannello finanziario il colore **è** il dato, quindi la regola ora dice
verde sale, rosso scende.

### Nota di metodo: la prova sbagliata

La prima versione della prova faceva **una sola chiamata**. Su una domanda di
mappa registrava «non ha chiamato osint_mappa» — ma prendere prima i dati e poi
mostrarli è la sequenza **giusta**, e uno scatto singolo non può vederla.

La prova ora esegue davvero gli strumenti e rimanda il risultato al modello, come
il ciclo vero dell'agente. Senza quella correzione avrei "aggiustato" un
comportamento corretto.

---

## L'archivio: `fin_archivio` e il RAG dedicato

Tutti i layer finanziari vivono in memoria e il free tier nega
`/stock/candle`: un riavvio perdeva tutto, e «cosa è successo a RTX nelle
ultime due settimane» era irrispondibile. `src/shadowbroker/archivio.py`
conserva, su una **collection Chroma separata** (`financial_rag` — le news di
mercato non inquinano i documenti personali):

| Entra | Filtro |
|---|---|
| notizie | titolo obbligatorio, dedup per URL, niente oltre 14 giorni |
| picchi | solo come **evento datato** («2026-08-02: AMZN +15,3%, senza notizia») — l'unica forma storica sensata di un prezzo |
| appalti | un documento per contratto, quadro già esclusi a monte |
| insider | solo decisioni P/S |

Ingestione opportunistica (a ogni briefing, in un thread) più un giro di
fondo ogni 10 minuti. `fin_archivio` si usa **solo per domande sul passato**
(regola esplicita). Sopra la soglia RAM (`FIN_RAG_RAM_MB`, 2800 di default)
o i 20.000 documenti, l'archivio **avvisa e propone** `comprimi()`: digest
settimanali per ticker oltre i 30 giorni, cancellazione oltre i 90. Propone,
non esegue.

Richiede il server ChromaDB nativo: `chroma-venv\Scripts\chroma.exe run
--path odysseus\data\chroma --host 127.0.0.1 --port 8100` (venv dedicato —
il venv di Odysseus ha solo il client HTTP).

## I grafici: il modello disegna senza eseguire codice

Fence ```` ```chart ```` con JSON piatto
(`{"type":"bar","title":…,"labels":[…],"data":[…]}`, tipi bar/line/pie,
multi-serie con `series`). Il renderer fidato (`static/js/charts.js` +
Chart.js self-hosted in `static/js/vendor/`) valida, disegna su canvas a
fence chiuso e su spec invalida mostra il code block originale. Il modello
controlla solo i dati, mai lo stile; il TTS non lo legge (i fence sono già
strippati). La regola d'uso sta in `REGOLE_FINANCE`: si disegna quando
l'utente lo chiede, con numeri presi dagli strumenti.

## Come si accende

Barra chat → `+` → **Financial**. Accende anche Intelligence (senza, in modalità
chat gli strumenti non esistono e il modello inventerebbe invece di leggere),
imposta il preset di mappa e apre il popup di configurazione.

La preferenza sta in `localStorage` come `odysseus.financial.mode`.

## File

| File | Ruolo |
|---|---|
| `src/shadowbroker/finanza.py` | i tre briefing, i filtri, la tabella degli stati USA |
| `src/shadowbroker/archivio.py` | il RAG finanziario: ingestione, ricerca, compressione |
| `src/shadowbroker/schemi.py` | `FINANCE_TOOL_SCHEMAS`, `PRESET_MAPPA`, `REGOLE_FINANCE` (in inglese) |
| `src/agent_tools/shadowbroker_tools.py` | i quattro handler, `FINANCE_TOOL_NAMES`, azione `preset` |
| `routes/chat_routes.py` | flag `financial_mode`, iniezione delle regole |
| `routes/shadowbroker_routes.py` | `/preset`, `/rules`, `/financial-config` (proxy) |
| `static/js/shadowbroker.js` | interruttore, preferenza, preset, **popup config** |
| `static/js/charts.js` + `vendor/chart.umd.js` | il renderer dei grafici |
| `shadowbroker/backend/services/financial_config.py` | config runtime (preset/deep/realtime) |
| `shadowbroker/frontend/src/components/FinancialPanel.tsx` | pannello FINANCIAL: news + map mode |
| `scripts/prova_finanza.py` | i briefing sui dati veri |
| `scripts/prova_modello_finanza.py` | **10 casistiche di orchestrazione, a due giri** |

## Rimasto fuori

`REGOLE_OSINT` esisteva da sempre in `schemi.py` e **non era collegata a
niente**: il modello non l'ha mai ricevuta. Ora viene iniettata in coda al
prompt di sistema quando il profilo è attivo — in coda e non in un messaggio
nuovo, perché un messaggio in più cambia il prefisso e con esso la cache, che su
questo hardware costa 32 volte un turno normale.
