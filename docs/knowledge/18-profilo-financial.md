# Il profilo Financial

Sottoinsieme di Intelligence, non aggiunta. **Otto strumenti invece di
undici**, più preset di mappa che si accende insieme al profilo e popup
di configurazione che compare a ogni attivazione.

Per dati grezzi vedi [16-finnhub.md](16-finnhub.md) e
[17-catalogo-dati.md](17-catalogo-dati.md).

---

## Perché restringere invece di aggiungere

Con dieci strumenti OSINT davanti, alla domanda *«come sta messa la difesa?»*
un 9B chiama `osint_militare` — che parla di aerei, non di titoli. Parole si
somigliano, dati no.

Misurato con modello vero (`scripts/prova_modello_finanza.py`):

```
prima delle correzioni       6 / 10 scelte corrette
dopo (regole in italiano)   10 / 10   tempo medio 27 s
dopo (regole in inglese)    10 / 10   tempo medio 24,7 s
```

Passaggio all'inglese ha richiesto un giro di taratura: prima stesura
faceva 9/10 («nascondi tutto tranne i contratti» si fermava al passo 1).
Rinforzato passo 2 («after the data tool returns, your NEXT tool call is
osint_mappa») tornato 10/10 — lezione della regola scritta come ricetta
vale in qualunque lingua.

Tre errori trovati e chiusi, in fondo a questa pagina.

## Cosa contiene

| Strumento | Ruolo |
|---|---|
| `fin_mercati` | quotazioni difesa/tech/cripto + notizie + **l'anomalia già trovata**; con `titolo` quota UN titolo per nome/ticker (Finnhub `/search` + `/quote`), oppure `disponibile: false` col motivo (27 ago 2026, caso Leonardo) |
| `fin_appalti` | contratti federali con **il luogo**: unici dati economici mappabili |
| `fin_insider` | movimenti degli interni con **MSPR**, indice da -100 a +100 |
| `fin_archivio` | **il passato**: archivio RAG di notizie, picchi, contratti, insider |
| `osint_mappa` | per evidenziare — senza, modello descrive a parole e mappa resta ferma |
| `osint_notizie` | per incrociare con geopolitica **e leggere il testo** di un articolo (url/id) |
| `osint_dettaglio` | scheda intera di qualcosa già citato |
| `osint_web` | background che wire e archivio non hanno: «chi è il CEO», «cosa produce X» |

Mappa e notizie **non sono aggiunta di comodo**: «questa commessa dove sta» e
«che notizie la spiegano» sono esattamente le domande per cui profilo esiste.
`osint_web` (2 ago) è via d'uscita quando feed non sanno: regola gli
impone parole chiave in inglese, fonte dichiarata, **numeri mai dagli
snippet** — quelli restano ai `fin_*`.

**E il viceversa**: Intelligence ha ricevuto `fin_mercati` (solo quello — 11
strumenti in tutto), con regola simmetrica: lì news di default sono
mondiali e mercati si toccano solo se domanda è di mercati; qui news
di default sono finanziarie e `osint_notizie` serve a incrociare.

## Costo

```
fin_mercati    1.165 token
fin_appalti    1.409
fin_insider    1.072
                        i tre insieme: 3.360 token = 7,0% di 48K
```

---

> **Aggiornamento 2 ago, sera:** multistep in chat era rotto per quattro
> cause di LOOP, non di profilo — storia intera sta in
> [19-loop-agente.md](19-loop-agente.md). Regole sono ora compresse in
> stile caveman-full (misurato: nessuna degradazione; description invece
> restano piene, comprimerle fa regredire keyword all'italiano).

## Le regole sono in inglese (e l'output resta italiano)

`REGOLE_FINANCE`/`REGOLE_OSINT` e description dei tool sono state
riscritte in inglese: modello piccolo segue istruzioni molto meglio
nella sua lingua-pivot, e function calling di Qwen è addestrato su schemi
inglesi. Output resta italiano per regola esplicita, **ripetuta in testa e
in coda** (istruzioni si dimenticano coi turni). Esempi fra virgolette
restano in italiano: devono somigliare a ciò che scrive utente.
Fonti e misure: `ricerche/lingua-system-prompt-inglese-vs-italiano.md`.

## Il popup di configurazione

A **ogni** attivazione del profilo (e all'avvio, se era rimasto acceso)
compare popup di configurazione — scelte pesano sul budget Finnhub
condiviso e non vanno ereditate in silenzio:

| Opzione | Effetto |
|---|---|
| Titoli Core (25) / Broad (60) | broad = +35 simboli (banche, energia, industriali, farmaceutici), prezzi ogni 2 min invece di 1 |
| Deep news | notizie su 30 titoli con finestra 7 giorni (invece di 13 su 3) |
| Realtime | 10 titoli chiave riquotati ogni 30 s |

Popup mostra anche **le regole vere del profilo** (da
`GET /api/shadowbroker/rules`) — operatore legge stesso contratto che
vincola modello. Scelte finiscono in `data/financial_config.json` del
backend via `POST /api/shadowbroker/financial-config` (proxy: CSP
`connect-src 'self'` impedisce al browser di parlare con porta 8000).

## La regola della mappa: evidenzia, non spegne

Accendendo profilo, mappa riceve preset `financial`, **magro di
proposito**:

```
gdelt · news · military_bases · datacenters
```

Prima conteneva anche voli militari, navi e centrali elettriche: sullo
schermo erano 40.000 punti arancioni che non parlavano di finanza, preset
sembrava non fare nulla. Eventi e news restano (alert servono
anche qui), basi restano (è dove atterrano appalti evidenziati),
resto si accende a richiesta. Nel cruscotto ShadowBroker stesso insieme
vive nello switch **FINANCIAL MAP MODE** del pannello FINANCIAL.

Da lì in poi modello **evidenzia e basta**. `osint_mappa azione=livelli`
spegnerebbe quello che operatore sta guardando, preset tiene già acceso
solo ciò che serve: far risaltare basta, cancellare no.

Vale **anche** quando richiesta è «nascondi tutto tranne i contratti». Nella
prova, dopo riscrittura regole, modello risponde con
`fin_appalti` + `osint_mappa(azione=evidenzia)` — cosa giusta.

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

Tutte trovate misurando, nessuna leggendo documentazione.

### 1. I contratti quadro seppellivano quelli veri

Ordinando per importo, primi dieci posti erano **veicoli OASIS+ e GWAC**: tetti
nominali da mille miliardi, senza luogo di esecuzione né significato come
"commessa". Risultato: **zero contratti mappabili su dieci**, commesse vere
(missili per il Qatar, motori F-22) sparite sotto.

Filtro: importo ≥ 100.000 M$ **oppure** oggetto che contiene `OASIS`, `GWAC`,
`GOVERNMENT-WIDE ACQUISITION`, `ALLIANT`, `UMBRELLA`, `FEDERAL SUPPLY SCHEDULE`,
`IDIQ`, `IGF::`.

Dopo filtro, in cima: **Columbia class design completion, 42.184 M$,
Connecticut**. Numero di esclusi viene dichiarato, non nascosto.

### 2. Lo stesso contratto fino a quattro volte

`F119 CY25-CY27 ENGINE SUSTAINMENT` a 5.390,7 M$ compariva **quattro volte**, con
date d'azione diverse. Sono ri-obbligazioni dello stesso programma.

Chiave di deduplica quindi **non include la data**: solo simbolo, importo,
agenzia e oggetto. Su dodici mesi di sei contractor: 2.106 duplicati scartati.

### 3. MSPR satura, e il mio ordinamento ci è cascato

MSPR è un **rapporto**: vale +100 sia per acquisto da 162 azioni sia per uno
da centomila. Ordinando per |MSPR| finivano in cima quattro +100 da poche
centinaia di azioni, mentre vendita da **183.876 azioni** con MSPR -63
restava sotto.

Ordinamento corretto: `|MSPR| × log₁₀(10 + |azioni|)`. Rapporto dice *quanto
unanime* è stato il mese, quantità dice *quanto pesa* — servono entrambi.

### 4. Il codice `A` non è un acquisto

Fra movimenti di Palantir: `Buckley Jeffrey A +17.124 @ 0`. Prezzo zero. È
un'**assegnazione**, non decisione di mercato. Contarla come acquisto
invertirebbe segno del segnale.

Solo `P` e `S` sono decisioni. Ogni movimento porta `decisione_di_mercato`
esplicito e spiegazione del codice.

### 5. Il luogo c'è nel 90% dei casi, ma non sempre

`performanceState` è popolato su 1.805 righe su 2.000. Forniture a catalogo
non hanno luogo di esecuzione. Va trattato come **opzionale**: campo che
esiste nello schema non è campo che esiste nel dato — stesso errore già
pagato coi titoli delle notizie.

Luogo è lo **stato**, approssimato al suo centro. Fingere precisione
maggiore sarebbe peggio che dichiarare approssimazione.

---

## I tre errori del modello, e cosa li ha chiusi

| Sbagliava | Perché | Correzione |
|---|---|---|
| *«qual è l'MSPR di Palantir?»* → rispondeva a memoria | sapeva cosa significa MSPR, non che è un dato da leggere | descrizione ora **apre** con MSPR; regola: «non rispondere a memoria su un dato che uno strumento ha» |
| *«che tempo fa a Milano?»* → chiamava `osint_notizie` | nessuna via d'uscita dal profilo | regola: se è fuori tema, dillo in una riga e non forzare uno strumento |
| *«mostrami sulla mappa»* → non chiamava niente | regola era scritta al negativo («non usare livelli») | riscritta in positivo, come **ricetta a due passi**: prendi i dati, poi evidenzia gli id |

Ultima è la più istruttiva. Regola che dice solo cosa **non** fare lascia
modello senza alternative, e risposta diventa silenzio.

### Il quarto errore: il nesso inventato, e perché non era colpa del modello

Domanda reale: *«quali sono le ultime novità dei mercati? analizza le news in
base ai picchi più grandi»*. Picco era **Amazon +15,32%**. Risposta:

> *le notizie su PLTR menzionano temi di AI/LLM che potrebbero correlarsi con il
> sentiment tech*

Ponte fra Amazon e articolo su Palantir. Nessun nesso.

Ma modello **non aveva alternative**: fetcher scaricava notizie
azienda solo per sei titoli della difesa, movimento più grande della
giornata era un tech. Otto notizie in mano, picco del 15% scoperto: nesso
fabbricato per riempire il buco.

Nessuna regola nel prompt avrebbe risolto. **Rimedio era dargli notizia che
mancava**, in tre pezzi:

1. `finnhub_news` copre ora 13 titoli, non 6 (i sette tech che si muovono)
2. `fin_mercati` ordina notizie **sui picchi**, non per ordine di arrivo
3. campo nuovo `picchi_senza_notizia`, che dichiara buco invece di lasciarlo
   indovinare

Rifatta stessa domanda dopo correzione:

| | Prima | Dopo |
|---|---|---|
| Amazon +15,32% | nesso inventato con Palantir | Jassy sul cloud da mille miliardi — notizia vera |
| Google +6,73% | non menzionato | **«Ha notizia collegata: NO»**, con ipotesi etichettate come tali |
| Apple −7,35% | non trovato | massimo ribasso, con sua notizia |

**Lezione generale:** quando modello inventa collegamento, prima
domanda non è «come glielo vieto» ma «gli ho dato di che rispondere?». È
stessa regola dei layer vuoti, applicata a un livello più su.

Nota minore trovata nella stessa risposta: usava 🔴 sia per +15% sia per −7%.
Su pannello finanziario colore **è** il dato, quindi regola ora dice
verde sale, rosso scende.

### Nota di metodo: la prova sbagliata

Prima versione della prova faceva **una sola chiamata**. Su domanda di
mappa registrava «non ha chiamato osint_mappa» — ma prendere prima dati e poi
mostrarli è sequenza **giusta**, e scatto singolo non può vederla.

Prova ora esegue davvero strumenti e rimanda risultato al modello, come
ciclo vero dell'agente. Senza quella correzione avrei "aggiustato" un
comportamento corretto.

---

## L'archivio: `fin_archivio` e il RAG dedicato

Tutti layer finanziari vivono in memoria e free tier nega
`/stock/candle`: riavvio perdeva tutto, e «cosa è successo a RTX nelle
ultime due settimane» era irrispondibile. `src/shadowbroker/archivio.py`
conserva, su una **collection Chroma separata** (`financial_rag` — le news di
mercato non inquinano documenti personali):

| Entra | Filtro |
|---|---|
| notizie | titolo obbligatorio, dedup per URL, niente oltre 14 giorni |
| picchi | solo come **evento datato** («2026-08-02: AMZN +15,3%, senza notizia») — unica forma storica sensata di un prezzo |
| appalti | un documento per contratto, quadro già esclusi a monte |
| insider | solo decisioni P/S |

Ingestione opportunistica (a ogni briefing, in un thread) più giro di
fondo ogni 10 minuti. `fin_archivio` si usa **solo per domande sul passato**
(regola esplicita). Sopra soglia RAM (`FIN_RAG_RAM_MB`, 2800 di default)
o 20.000 documenti, archivio **avvisa e propone** `comprimi()`: digest
settimanali per ticker oltre 30 giorni, cancellazione oltre 90 giorni. Propone,
non esegue.

Richiede server ChromaDB nativo: `chroma-venv\Scripts\chroma.exe run
--path odysseus\data\chroma --host 127.0.0.1 --port 8100` (venv dedicato —
venv di Odysseus ha solo client HTTP).

## I grafici: il modello disegna senza eseguire codice

Fence ```` ```chart ```` con JSON piatto
(`{"type":"bar","title":…,"labels":[…],"data":[…]}`, tipi bar/line/pie,
multi-serie con `series`). Renderer fidato (`static/js/charts.js` +
Chart.js self-hosted in `static/js/vendor/`) valida, disegna su canvas a
fence chiuso e su spec invalida mostra code block originale. Modello
controlla solo dati, mai stile; TTS non lo legge (fence sono già
strippati). Regola d'uso sta in `REGOLE_FINANCE`: si disegna quando
utente lo chiede, con numeri presi dagli strumenti.

## Come si accende

Barra chat → `+` → **Financial**. Accende anche Intelligence (senza, in modalità
chat gli strumenti non esistono e modello inventerebbe invece di leggere),
imposta preset di mappa e apre popup di configurazione.

Preferenza sta in `localStorage` come `odysseus.financial.mode`.

## File

| File | Ruolo |
|---|---|
| `src/shadowbroker/finanza.py` | tre briefing, filtri, tabella degli stati USA |
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
niente**: modello non l'ha mai ricevuta. Ora viene iniettata in coda al
prompt di sistema quando profilo è attivo — in coda e non in messaggio
nuovo, perché messaggio in più cambia prefisso e con esso la cache, che su
questo hardware costa 32 volte un turno normale.
