# Catalogo dei dati: tutto quello che l'assistente può sapere

Inventario completo, letto dal backend **vivo** il 1 agosto 2026, non dalla
documentazione. Serve a rispondere a una domanda sola: *quando chiedo una cosa,
da dove può arrivare la risposta — e da dove non può?*

Per come sono fatti i dati dentro (le quattro forme, le coordinate invertite,
dove finiscono i token) vedi
[15-shadowbroker-come-funziona.md](15-shadowbroker-come-funziona.md).
Per Finnhub in dettaglio, [16-finnhub.md](16-finnhub.md).

---

## Regola numero uno

> **Un layer vuoto non è «tutto tranquillo». È assenza di informazione.**

Sono due cose diverse e il modello, lasciato solo, le confonde. Se `cctv` ha zero
elementi non vuol dire che non ci sono telecamere: vuol dire che quel feed non
sta producendo. Il ponte lo dichiara esplicitamente
(`briefing.py`, dizionario `SPIEGAZIONI_VUOTI`) proprio per questo.

---

## Dove sta la roba, per domanda

| Se chiedi… | Guarda | Ha dati? |
|---|---|---|
| cosa succede nel mondo adesso | `gdelt`, `news`, `threat_level` | ✅ |
| conflitti e linee del fronte | `frontlines`, `gdelt`, `telegram_osint` | ✅ |
| aerei militari in movimento | `military_flights`, `tracked_flights` | ✅ |
| navi e portaerei | `ships` | ✅ 30.454 |
| infrastruttura critica di una zona | `power_plants`, `datacenters`, `military_bases` | ✅ |
| ascolto radio e intercettazioni | `sigint`, `kiwisdr` | ✅ |
| disastri naturali | `earthquakes`, `weather_alerts` | ✅ |
| blackout di rete | `internet_outages` | ✅ |
| classifica del rischio per regione | `gt_risk` | ✅ |
| **mercati e difesa** | **`stocks`, `finnhub_news`, `unusual_whales`** | ✅ **nuovo** |
| incendi | `firms_fires` | ❌ vuoto ora |
| telecamere | `cctv` | ❌ mai popolato |
| disturbo GPS | `gps_jamming` | ❌ |
| allarmi aerei Ucraina | `ukraine_alerts` | ❌ |
| mercati predittivi | `prediction_markets` | ❌ **e pesa il 25% del rischio** |

---

## I 33 layer con dati, adesso

```
34.936  power_plants        centrali elettriche, mondiali
30.454  ships               AIS in tempo reale
 7.528  sigint              emissioni radio localizzate
 4.899  datacenters
 1.963  private_flights
 1.170  airports
 1.055  gdelt               eventi indicizzati, raggruppati per luogo
   833  kiwisdr             ricevitori radio aperti (era 798: lista congelata, vedi doc 20)
   646  military_bases
   492  satellites
   260  trains
   191  wastewater          sorveglianza epidemiologica
   157  tracked_flights     velivoli marcati (Plane-Alert)
    60  finnhub_news        NUOVO — notizie finanziarie
    50  news                RSS geolocalizzate
    48  earthquakes
    41  weather_alerts
    25  stocks              NUOVO conteggio — erano 6
    22  military_flights
     9  gt_risk             regioni classificate per rischio
     6  telegram_osint      con il testo, unico caso
     5  internet_outages
     4  threat_level        punteggio globale + motivazioni
     4  frontlines          poligoni, non punti
     3  space_weather
     3  unusual_whales      quotazioni + insider + Congresso
     1  commercial · meshtastic · malware · correlations
     1  financial · stocks_oil · viirs
```

I layer da **1** sono oggetti singoli, non liste vuote: `threat_level` è un
punteggio, `correlations` è un blocco. Vedi le quattro forme nel doc 15.

## I 14 vuoti, e perché

| Layer | Motivo |
|---|---|
| `prediction_markets` | **il più grave**: pesa il 25% di `threat_level`, che risulta strutturalmente sottostimato |
| `cctv` | mai popolato dal feed |
| `gps_jamming` | il feed non produce ora |
| `firms_fires` | aveva 5.000 elementi ieri — è **intermittente**, non morto |
| `ukraine_alerts`, `uavs`, `volcanoes` | feed silenziosi |
| `air_quality`, `fishing_activity` | mancano le chiavi (GFW) |
| `scanners`, `crowdthreat`, `fimi`, `liveuamap`, `uap_sightings` | non configurati |

`firms_fires` è l'esempio che spiega la regola numero uno: **lo stesso layer era
pieno poche ore fa**. Un modello che leggesse «zero incendi» come «nessun
incendio nel mondo» direbbe una cosa falsa.

---

## Finnhub: il pezzo nuovo

Con la chiave configurata si aprono **22 endpoint gratuiti**. ShadowBroker ne
chiamava quattro, di cui **due negati** dal piano gratuito.

### Cosa c'è adesso

| Layer | Contenuto | Aggiornamento |
|---|---|---|
| `stocks` | 25 simboli: 14 tech, 6 difesa, 5 cripto | **ogni minuto** |
| `finnhub_news` | 60 notizie: flusso generale + 6 titoli difesa | ogni 10 minuti |
| `unusual_whales` | quotazioni difesa + 50 movimenti insider | ogni 15 minuti |

### Cosa esiste ma nessuno chiama

| Endpoint | Volume misurato | Perché conta |
|---|---|---|
| `/stock/usa-spending` | **2.000 righe** su RTX | contratti federali con **agenzia, importo, e luogo di esecuzione** |
| `/stock/lobbying` | 101 su LMT | chi paga chi, e per cosa |
| `/stock/filings` | 250 | un 8-K fuori calendario precede la notizia |
| `/calendar/earnings` | 1.500 | tutto il mercato, non un titolo |
| `/stock/insider-sentiment` | aggregato MSPR, da -100 a +100 | numero già normalizzato, come `threat_level` |
| `/stock/uspto-patent` | 142 | cosa sta sviluppando un contractor |

**`usa-spending` è l'unico dato finanziario che può stare sulla mappa**: ha
`performanceState`, `performanceCity`, `performanceCongressionalDistrict`. Un
contratto militare assegnato ha un posto, come una base o una nave.

Avvertenza già pagata una volta: quei campi geografici **sono spesso vuoti** (le
forniture a catalogo non hanno luogo di esecuzione). Vanno trattati come
opzionali. È lo stesso errore dei titoli delle notizie: un campo che c'è nello
schema non è un campo che c'è nel dato.

### Cosa il piano gratuito nega

```
scambi Congresso   ← e' il motivo per cui congress_trades e' sempre 0
candele storiche   ← niente serie temporali, solo il prezzo di adesso
cambio valute      obiettivi di prezzo    sentiment notizie
fondi istituzionali    dividendi          ETF    social sentiment
```

`congress_trades = 0` **non è un difetto di configurazione**: quell'endpoint
risponde 403. Il pannello Markets mostra la scheda vuota senza spiegarlo.

---

## Cosa può vedere il modello, e cosa no

Distinzione importante, perché non coincidono.

| | Nella piattaforma | Nel ponte verso il modello |
|---|---|---|
| gdelt, news, threat_level, correlations | ✅ | ✅ |
| voli, navi, basi, centrali, datacenter | ✅ | ✅ |
| gt_risk, frontlines, terremoti, allerte | ✅ | ✅ |
| **stocks, finnhub_news, unusual_whales** | ✅ | ❌ **non collegati** |

I dati finanziari arrivano, si vedono sulla mappa e nel pannello Markets, ma
**nessuno dei dieci strumenti OSINT li legge**. Compaiono solo in una riga che
dice «mercati finanziari non caricati».

Quindi oggi: se chiedi all'assistente com'è messa la difesa, non ha modo di
saperlo. È la prima cosa da collegare.

---

## I quattro giudizi già calcolati

Non serve che il modello inventi criteri di gravità: la piattaforma glieli dà.

| Cosa | Restituisce | Nota |
|---|---|---|
| `threat_level` | 0-100 + livello + motivi leggibili | 7 componenti, uno vuoto |
| `correlations` | tipo, gravità, punteggio, fattori | collega layer diversi |
| `tracked_flights` | categoria, operatore, etichette | **non** vuol dire militare |
| `gt_risk` | 1.641 regioni, probabilità per dominio | va acceso con **due** variabili |
| **MSPR** (Finnhub) | -100 / +100 | acquisti insider netti del mese |

MSPR è il quinto, ed è già della stessa natura degli altri quattro: un numero
normalizzato, interpretabile senza che il modello si inventi una soglia.

---

## Chiavi API: stato

| Chiave | Sblocca | Stato |
|---|---|---|
| `OPENSKY_CLIENT_ID/SECRET` | voli globali | ✅ |
| `AIS_API_KEY` | 30.454 navi | ✅ |
| `FINNHUB_API_KEY` | mercati, insider, notizie, contratti | ✅ **nuova** |
| `SH_CLIENT_ID/SECRET` | Sentinel Hub, immagini satellitari | ❌ |
| `MESH_SAR_EARTHDATA_*` | anomalie radar SAR | ❌ |
| `SHODAN_API_KEY` | dispositivi esposti | ❌ |
| `GFW_API_TOKEN` | attività di pesca | ❌ |

Sono tutte gratuite. Le quattro mancanti sbloccherebbero altrettanti layer oggi
vuoti.

Dove stanno: `backend/data/operator_api_keys.env`, scritto dall'interfaccia — non
`backend/.env`, che contiene una copia più vecchia. Se una chiave sembra non
funzionare, è quasi sempre perché si sta guardando il file sbagliato.

---

## Una proprietà da sapere: le richieste in uscita

`services/geopolitics.py` scarica **ogni URL che GDELT gli consegna**, per
ricavare il titolo vero della notizia invece di indovinarlo dallo slug.

Conseguenza: la tua macchina fa richieste HTTP a **qualunque sito che GDELT
indicizzi**. Migliaia di domini, nessuno scelto da noi. Se uno è compromesso o
finisce in una lista nera, l'antivirus segnala — ed è successo.

Non è un difetto nascosto, è la conseguenza dell'arricchimento dei titoli. Ma non
era scritto da nessuna parte. Rimedi possibili: spegnere l'arricchimento (i
titoli diventano slug), oppure una lista di domini da saltare.

---

## Aggiornamento 2026-08-02

- Il layer `finnhub_news` ora viaggia anche in `GET /api/live-data/slow`: lo
  legge il pannello **FINANCIAL** del cruscotto (news + switch map mode).
- Fix: `unusual_whales` non sovrascrive più `stocks` (restringeva 25 -> 8
  simboli per un minuto ogni quarto d''ora).
- Nasce l''**archivio storico** (`financial_rag`, ChromaDB): i layer restano
  in-memory e volatili, ma notizie, picchi, contratti e decisioni insider
  vengono conservati al passaggio e interrogati con `fin_archivio`.
  Dettagli e filtri d''ingresso in [18-profilo-financial.md](18-profilo-financial.md).
