# Finnhub: cosa dà davvero il piano gratuito

Misurato 1 agosto 2026 chiamando **ogni endpoint con nostra chiave**, non
leggendo documentazione. Documentazione Finnhub è pagina JavaScript
senza livelli dichiarati, blog in giro si contraddicono: chi scrive 50
chiamate al minuto, chi 60, chi parla di tetto giornaliero.

Sonda: `scripts/sonda_finnhub.py`.

---

## Il tetto vero

API lo dichiara da sé, in ogni risposta:

```
X-Ratelimit-Limit:     60      chiamate al minuto
X-Ratelimit-Remaining: 44      quante ne restano adesso
X-Ratelimit-Reset:     1785616895   quando riparte contatore
```

**Nessun tetto giornaliero** nelle intestazioni. Voci sui "300 al
giorno" non trovano conferma nella risposta API.

Conseguenza pratica: **quel numero va letto, non stimato.** Stessa chiave
usano tre fetcher diversi, solo intestazione sa quanto è rimasto davvero.
`services/fetchers/financial.py`: `budget_residuo()` legge residuo,
accorcia passata se manca spazio, lascia 8 chiamate agli altri.

---

## I 22 endpoint che funzionano

| Endpoint | Cosa torna | Volume misurato |
|---|---|---|
| `/quote` | prezzo, variazione, apertura/chiusura | 8 campi |
| `/stock/profile2` | anagrafica azienda, settore, capitalizzazione | 14 campi |
| `/news?category=general` | flusso notizie di mercato | **100 voci** |
| `/company-news` | notizie di titolo, per intervallo | **49** su 7 giorni |
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
| `/stock/symbol` | elenco simboli di borsa | **30.918** |
| `/search` | ricerca per nome | — |
| `/crypto/exchange` | borse cripto supportate | 12 |
| `/stock/lobbying` | **spese di lobbying dichiarate** | 48 RTX · 101 LMT |
| `/stock/usa-spending` | **contratti federali statunitensi** | **2.000** RTX · 954 LMT |
| `/stock/uspto-patent` | brevetti depositati | 142 |
| `/stock/visa-application` | richieste di visto lavorativo | 402 |

### La trappola che nasconde metà del valore

Ultimi quattro rispondono **200 con zero righe** se finestra è
stretta. Dati **trimestrali o annuali**, non giornalieri.

```
finestra 7 giorni   ->  data: 0      sembra "non ho il permesso"
finestra 2 anni     ->  data: 2000   e invece c'era tutto
```

Cascato nella prima sonda. Endpoint che risponde `200 {"data": []}`
sembra vuoto per mancanza accesso, invece vuoto perché chiesta
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

Due meritano nota, perché codice ShadowBroker li chiama lo stesso:

**`/stock/congressional-trading`** — motivo per cui `congress_trades` è
sempre **0**. Non difetto di configurazione né chiave sbagliata:
endpoint a pagamento. Pannello Markets mostra scheda vuota senza
spiegare.

**`/stock/candle` e `/crypto/candle`** — niente storico prezzi. Solo
quotazioni **istantanee**. Qualsiasi grafico va costruito
accumulando letture nel tempo, non chiedendo serie.

---

## I tre giacimenti che nessuno usa

Gratuiti, già raggiungibili, ShadowBroker **non li chiama**.

### 1. Contratti federali statunitensi — `/stock/usa-spending`

Duemila righe per sola RTX. Record:

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

**Ha campi geografici.** Chi ha vinto quale commessa militare, da quale
agenzia, per quanti soldi, **e dove viene eseguita**. Unico dato Finnhub
che finisce direttamente sulla mappa insieme a basi, voli e navi.

Attenzione: `performanceState` e simili sono **vuoti** su alcuni contratti (le
forniture a catalogo, per esempio). Trattarli come opzionali, non dati
presenti — stesso errore già fatto coi titoli delle notizie.

### 2. Lobbying dichiarato — `/stock/lobbying`

Chi paga chi, per far passare cosa. 101 righe per Lockheed Martin.

### 3. Depositi SEC — `/stock/filings`

250 documenti. 8-K fuori calendario di un contractor è segnale che precede
notizia.

---

## MSPR: l'unico indicatore da spiegare

`/stock/insider-sentiment` non restituisce transazioni ma **aggregato
mensile**:

| Campo | Significato |
|---|---|
| `change` | acquisti meno vendite di **tutti** interni nel mese |
| `mspr` | *Monthly Share Purchase Ratio*, da **-100 a +100** |

Dato nasce dai moduli 3, 4 e 5 depositati alla SEC. Chi lo pubblica dichiara
valori estremi anticipano movimenti a **30-90 giorni**.

**Come va usato da noi:** numero già normalizzato e interpretabile, come
`threat_level` per mappa. Non serve che modello inventi soglia — gli si
dà numero e segno.

---

## Cosa usa ShadowBroker oggi

| Endpoint | Chi lo chiama | Stato |
|---|---|---|
| `/quote` | `financial.py`, `unusual_whales_connector.py` | ✅ |
| `/stock/insider-transactions` | `unusual_whales_connector.py` | ✅ 50 movimenti |
| `/stock/congressional-trading` | `unusual_whales_connector.py` | ❌ 403, sempre 0 |
| `/crypto/candle` | `unusual_whales_connector.py` | ❌ 403 |
| `/news` + `/company-news` | **`finnhub_news.py` (nostro)** | ✅ 60 notizie |

**Diciassette endpoint gratuiti non chiamati da nessuno.**

---

## Le nostre modifiche al fetcher

Prima:

```
pianificazione   ogni 30 minuti
per giro         3 simboli (BTC, ETH + 1 a rotazione)
passata completa 25 simboli / 1 per giro = oltre 11 ore
```

Soglia interna tarata a 3 secondi, come se fetcher girasse ogni 3
secondi. Ma lo chiamava scheduler ogni mezz'ora: **maggior parte dei prezzi
era della sessione precedente, niente lo diceva.**

Adesso:

```
pianificazione   ogni minuto            FINANCIAL_REFRESH_MINUTES
soglia interna   30 secondi             FINNHUB_THROTTLE_SECONDS
per giro         tutti e 25 i simboli
budget           legge X-Ratelimit-Remaining, accorcia se serve, lascia 8 agli altri
notizie          ogni 10 minuti         FINNHUB_NEWS_REFRESH_MINUTES
```

Conto: 25 chiamate ogni 30 secondi sono 50 al minuto su 60. Notizie
aggiungono 7 ogni dieci minuti, insider sono in cache. Guardia serve
per minuti in cui capitano insieme.

---

## Fonti

- [Insider Sentiment API](https://finnhub.io/docs/api/insider-sentiment)
- [Market News API](https://finnhub.io/docs/api/market-news)
- [Finnhub: Insiders Sentiment Analysis](https://medium.com/@stock-api/finnhub-insiders-sentiment-analysis-cc43f9f64b3a)
- Resto è misurato: `scripts/sonda_finnhub.py`

---

## Aggiornamento 2026-08-02: budget risanato e config runtime

Quattro sprechi trovati misurando e chiusi:

| Era | Ora |
|---|---|
| 13 chiamate/giro a `congressional-trading` (**sempre 403** sul free tier) | spente di default (`UW_CONGRESS=1` per riattivarle) |
| `unusual_whales` sovrascriveva layer `stocks` (25 -> 8 simboli per ~60 s) | sue quotazioni restano nel suo layer |
| news e insider ciechi sul budget | tutti i fetcher leggono e alimentano `X-Ratelimit-Remaining` (margine 8) |
| job allineati ogni 30 min (73 chiamate in un minuto, tetto 60) | partenze sfasate (+25 s news, +40 s insider) |

Ed è arrivata **config runtime** (`GET/POST /api/financial/config`,
persistita in `data/financial_config.json`, impostabile dal popup Financial
di Odysseus):

- `preset`: `core` (25 simboli, ogni minuto) o `broad` (60 simboli, metà per
  sweep alternate -> ogni titolo si aggiorna ogni 2 minuti, ~30 chiamate/min)
- `deep_news`: 30 titoli con finestra 7 giorni invece di 13 su 3
- `realtime`: 10 titoli chiave riquotati ogni 30 s (job dedicato, merge
  per-simbolo, mai sostituzione del layer)

Aritmetica completa in `ricerche/financial-piano-espansione.md`.
