# Finnhub: cosa dà davvero il piano gratuito

Misurato il 1 agosto 2026 chiamando **ogni endpoint con la nostra chiave**, non
leggendo la documentazione. La documentazione di Finnhub è una pagina JavaScript
che non dichiara i livelli, e i blog in giro si contraddicono: c'è chi scrive 50
chiamate al minuto, chi 60, chi parla di un tetto giornaliero.

Sonda: `scripts/sonda_finnhub.py`.

---

## Il tetto vero

L'API lo dichiara da sé, in ogni risposta:

```
X-Ratelimit-Limit:     60      chiamate al minuto
X-Ratelimit-Remaining: 44      quante ne restano adesso
X-Ratelimit-Reset:     1785616895   quando riparte il contatore
```

**Nessun tetto giornaliero** compare nelle intestazioni. Le voci sui "300 al
giorno" non trovano conferma nella risposta dell'API.

Conseguenza pratica: **quel numero va letto, non stimato.** La stessa chiave la
usano tre fetcher diversi, e solo l'intestazione sa quanto è rimasto davvero.
`services/fetchers/financial.py` lo fa: `budget_residuo()` legge il residuo e
accorcia la passata se non c'è spazio, lasciando 8 chiamate agli altri.

---

## I 22 endpoint che funzionano

| Endpoint | Cosa torna | Volume misurato |
|---|---|---|
| `/quote` | prezzo, variazione, apertura/chiusura | 8 campi |
| `/stock/profile2` | anagrafica azienda, settore, capitalizzazione | 14 campi |
| `/news?category=general` | flusso notizie di mercato | **100 voci** |
| `/company-news` | notizie di un titolo, per intervallo | **49** su 7 giorni |
| `/stock/recommendation` | consigli analisti (buy/hold/sell aggregati) | 4 periodi |
| `/stock/earnings` | utili passati, atteso contro realizzato | 4 trimestri |
| `/calendar/earnings` | **calendario utili di tutto il mercato** | **1.500 voci** |
| `/calendar/ipo` | quotazioni in arrivo | 3 |
| `/stock/insider-transactions` | movimenti degli interni, per titolo | **127** su RTX |
| `/stock/insider-sentiment` | aggregato mensile (vedi MSPR) | 3 mesi |
| `/stock/financials-reported` | bilanci depositati | 16 |
| `/stock/metric?metric=all` | indicatori fondamentali | 4 blocchi |
| `/stock/filings` | **archivio depositi SEC** | **250** |
| `/stock/peers` | aziende comparabili | 12 |
| `/stock/market-status` | borsa aperta o chiusa | 6 campi |
| `/stock/symbol` | elenco simboli di una borsa | **30.918** |
| `/search` | ricerca per nome | — |
| `/crypto/exchange` | borse cripto supportate | 12 |
| `/stock/lobbying` | **spese di lobbying dichiarate** | 48 RTX · 101 LMT |
| `/stock/usa-spending` | **contratti federali statunitensi** | **2.000** RTX · 954 LMT |
| `/stock/uspto-patent` | brevetti depositati | 142 |
| `/stock/visa-application` | richieste di visto lavorativo | 402 |

### La trappola che nasconde metà del valore

Gli ultimi quattro rispondono **200 con zero righe** se la finestra temporale è
stretta. Sono dati **trimestrali o annuali**, non giornalieri.

```
finestra 7 giorni   ->  data: 0      sembra "non ho il permesso"
finestra 2 anni     ->  data: 2000   e invece c'era tutto
```

Ci sono cascato nella prima sonda. Un endpoint che risponde `200 {"data": []}`
sembra vuoto per mancanza di accesso, e invece è vuoto perché gli hai chiesto la
settimana sbagliata.

---

## I 15 negati

```
sentiment notizie      obiettivi di prezzo     calendario economico
scambi Congresso       fondi istituzionali     azionisti
dividendi              frazionamenti           candele azioni
candele cripto         cambio valute           ETF profilo
indice costituenti     catena fornitura        social sentiment
```

Tutti rispondono `403 {"error":"You don't have access to this resource."}`.

Due meritano una nota, perché il codice di ShadowBroker li chiama lo stesso:

**`/stock/congressional-trading`** — è il motivo per cui `congress_trades` è
sempre **0**. Non è un difetto della configurazione né una chiave sbagliata:
quell'endpoint è a pagamento. Il pannello Markets mostra la scheda vuota senza
dire perché.

**`/stock/candle` e `/crypto/candle`** — niente storico dei prezzi. Si possono
avere solo le quotazioni **istantanee**. Qualsiasi grafico va costruito
accumulando le letture nel tempo, non chiedendo la serie.

---

## I tre giacimenti che nessuno usa

Sono gratuiti, sono già raggiungibili, e ShadowBroker **non li chiama**.

### 1. Contratti federali statunitensi — `/stock/usa-spending`

Duemila righe per la sola RTX. Un record contiene:

```
recipientName              RAYTHEON COMPANY
recipientParentName        RTX CORP
potentialAmount            38.120.620
actionDate                 2026-07-03
awardingAgencyName         General Services Administration
awardingSubAgencyName      Federal Acquisition Service
awardDescription           FEDERAL SUPPLY SCHEDULE CONTRACT
naicsCode                  334511
performanceState / City / County / ZipCode
performanceCongressionalDistrict    VA-08
permalink                  usaspending.gov/award/...
```

**Ha i campi geografici.** Cioè: chi ha vinto quale commessa militare, da quale
agenzia, per quanti soldi, **e dove viene eseguita**. È l'unico dato di Finnhub
che può finire direttamente sulla mappa insieme a basi, voli e navi.

Attenzione: `performanceState` e simili sono **vuoti** su alcuni contratti (le
forniture a catalogo, per esempio). Vanno trattati come opzionali, non dati per
presenti — è lo stesso errore già fatto con i titoli delle notizie.

### 2. Lobbying dichiarato — `/stock/lobbying`

Chi paga chi, per far passare cosa. 101 righe per Lockheed Martin.

### 3. Depositi SEC — `/stock/filings`

250 documenti. Un 8-K fuori calendario di un contractor è un segnale che precede
la notizia.

---

## MSPR: l'unico indicatore da spiegare

`/stock/insider-sentiment` non restituisce transazioni ma un **aggregato
mensile**:

| Campo | Significato |
|---|---|
| `change` | acquisti meno vendite di **tutti** gli interni nel mese |
| `mspr` | *Monthly Share Purchase Ratio*, da **-100 a +100** |

Il dato nasce dai moduli 3, 4 e 5 depositati alla SEC. Chi lo pubblica dichiara
che valori estremi anticipano movimenti a **30-90 giorni**.

**Come va usato da noi:** è un numero già normalizzato e già interpretabile, come
`threat_level` per la mappa. Non serve che il modello inventi una soglia — gli si
dà il numero e il segno.

---

## Cosa usa ShadowBroker oggi

| Endpoint | Chi lo chiama | Stato |
|---|---|---|
| `/quote` | `financial.py`, `unusual_whales_connector.py` | ✅ |
| `/stock/insider-transactions` | `unusual_whales_connector.py` | ✅ 50 movimenti |
| `/stock/congressional-trading` | `unusual_whales_connector.py` | ❌ 403, sempre 0 |
| `/crypto/candle` | `unusual_whales_connector.py` | ❌ 403 |
| `/news` + `/company-news` | **`finnhub_news.py` (nostro)** | ✅ 60 notizie |

**Diciassette endpoint gratuiti non sono chiamati da nessuno.**

---

## Le nostre modifiche al fetcher

Prima:

```
pianificazione   ogni 30 minuti
per giro         3 simboli (BTC, ETH + 1 a rotazione)
passata completa 25 simboli / 1 per giro = oltre 11 ore
```

La soglia interna era tarata a 3 secondi, come se il fetcher girasse ogni 3
secondi. Ma lo chiamava lo scheduler ogni mezz'ora: **la maggior parte dei prezzi
era della sessione precedente, e niente lo diceva.**

Adesso:

```
pianificazione   ogni minuto            FINANCIAL_REFRESH_MINUTES
soglia interna   30 secondi             FINNHUB_THROTTLE_SECONDS
per giro         tutti e 25 i simboli
budget           legge X-Ratelimit-Remaining, accorcia se serve, lascia 8 agli altri
notizie          ogni 10 minuti         FINNHUB_NEWS_REFRESH_MINUTES
```

Conto: 25 chiamate ogni 30 secondi sono 50 al minuto su 60. Le notizie ne
aggiungono 7 ogni dieci minuti, gli insider sono in cache. La guardia serve
proprio per i minuti in cui capitano insieme.

---

## Fonti

- [Insider Sentiment API](https://finnhub.io/docs/api/insider-sentiment)
- [Market News API](https://finnhub.io/docs/api/market-news)
- [Finnhub: Insiders Sentiment Analysis](https://medium.com/@stock-api/finnhub-insiders-sentiment-analysis-cc43f9f64b3a)
- Il resto è misurato: `scripts/sonda_finnhub.py`

---

## Aggiornamento 2026-08-02: budget risanato e config runtime

Quattro sprechi trovati misurando e chiusi:

| Era | Ora |
|---|---|
| 13 chiamate/giro a `congressional-trading` (**sempre 403** sul free tier) | spente di default (`UW_CONGRESS=1` per riattivarle) |
| `unusual_whales` sovrascriveva il layer `stocks` (25 -> 8 simboli per ~60 s) | le sue quotazioni restano nel suo layer |
| news e insider ciechi sul budget | tutti i fetcher leggono e alimentano `X-Ratelimit-Remaining` (margine 8) |
| job allineati ogni 30 min (73 chiamate in un minuto, tetto 60) | partenze sfasate (+25 s news, +40 s insider) |

Ed è arrivata la **config runtime** (`GET/POST /api/financial/config`,
persistita in `data/financial_config.json`, impostabile dal popup Financial
di Odysseus):

- `preset`: `core` (25 simboli, ogni minuto) o `broad` (60 simboli, metà per
  sweep alternate -> ogni titolo si aggiorna ogni 2 minuti, ~30 chiamate/min)
- `deep_news`: 30 titoli con finestra 7 giorni invece di 13 su 3
- `realtime`: 10 titoli chiave riquotati ogni 30 s (job dedicato, merge
  per-simbolo, mai sostituzione del layer)

Aritmetica completa in `ricerche/financial-piano-espansione.md`.
