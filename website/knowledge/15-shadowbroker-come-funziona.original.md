# ShadowBroker: come funziona dentro

Mappa dei dati e dei meccanismi. Serve a chi deve **modificare** il ponte o
aggiungere strumenti. Per usarlo basta [14-agente-osint.md](14-agente-osint.md).

---

## Tre processi

```
:3000  frontend   Next.js 16 + MapLibre GL          npm run dev:frontend
:8000  backend    FastAPI + APScheduler             venv\Scripts\python.exe main.py
:4000  AIS locale opzionale, RTL-SDR                —
```

Il browser parla **solo** con :3000. Il frontend inoltra `/api/*` a :8000.
Niente Docker: dev setup nativo, CPU-only, non tocca la GPU.

---

## Come arrivano i dati

APScheduler a due velocità:

```
veloce  ~60s    voli, navi, satelliti, SIGINT, CCTV, jamming GPS
lenta   min/ore GDELT, notizie, terremoti, mercati, correlazioni, Telegram
```

Tutto finisce in un dizionario in memoria (`services/fetchers/_store.py`,
`latest_data`) sotto lock. Non c'è database: **riavviare il backend azzera
tutto** e i layer si ripopolano nell'arco di minuti.

---

## Le quattro forme dei dati

Questo è il punto che fa perdere tempo. Lo stesso endpoint restituisce forme
diverse a seconda del layer.

| Forma | Layer | Come si legge |
|---|---|---|
| lista di dizionari | news, ships, trains, earthquakes | diretto |
| lista di Feature GeoJSON | **gdelt** | `properties` + `geometry.coordinates` |
| FeatureCollection unica | **frontlines** | un solo oggetto, migliaia di punti |
| oggetto singolo | threat_level, space_weather, gt_risk | non è una lista |

`store._appiattisci()` normalizza tutte e quattro.

### Coordinate: quattro convenzioni

```
lat / lng            la maggioranza
lat / lon            kiwisdr
coords: [lat, lng]   news, telegram_osint
geometry.coordinates GeoJSON -> (lng, lat)  ATTENZIONE: INVERTITO
```

Scambiare l'ordine GeoJSON manda i risultati in mezzo all'oceano senza nessun
errore. `geo.coordinate_di()` le gestisce tutte.

---

## Dove finiscono i token

Misurato. Un campo per layer mangia quasi tutto:

| Layer | Campo | Quota |
|---|---|---|
| military_flights | `trail` (scia, array di punti) | **83,5%** |
| news | `summary` | 64% |
| frontlines | il poligono | 100% |

Il resto — sigla, tipo, posizione, quota, operatore, punteggi — è il 16%.
Le sagome (`sagome.py`) tolgono il primo e tengono il secondo.

```
25 aerei grezzi        5.135 token
25 aerei con sagoma      780 token
```

---

## Il testo delle notizie: non c'è

| Fonte | Titolo | Data | Corpo |
|---|---|---|---|
| news (RSS) | pulito | al minuto | **assente** |
| gdelt | dallo slug URL | `event_date` AAAAMMGG | campo c'è, **mai popolato** |
| telegram_osint | sì | sì | **sì** (pochi elementi) |

Gli URL però ci sono sempre — fino a 10 per cluster GDELT. `testo.py` li tenta
in sequenza finché uno risponde. I paywall si saltano.

---

## Le classifiche già calcolate

Non serve che il modello inventi criteri di gravità.

| Cosa | Dove | Restituisce |
|---|---|---|
| `threat_level` | `oracle_service.py:199` | 0-100 + livello + motivi in inglese leggibile |
| `correlations` | layer | tipo, gravità, punteggio, `drivers` |
| `tracked_flights` | Plane-Alert, 16.077 velivoli | categoria, operatore, tag |
| GT analytics | `analytics/` | 1.641 regioni, probabilità per dominio, interpretazione |

### `threat_level`, i sette pesi

```
0,25  sentimento negativo nelle notizie
0,25  mercati "CONFLICT"          <- VUOTI da noi: punteggio sottostimato
0,10  quota eventi ad alto rischio
0,10  punteggio oracolo massimo
0,10  anomalia militare (sopra 30 voli tracciati)
0,10  jamming GPS                  <- spesso vuoto
0,10  correlazioni fra layer
```

### GT: due variabili, non una

```powershell
$env:GT_ANALYTICS_ENABLED="true"
$env:GT_ANALYTICS_ACK_LOW_CPU="true"   # se il profilo runtime e' "lean"
```

Dal `.env` **non funziona**: vanno passate al processo.

---

## Il canale agente

```
POST /api/ai/channel/command   {cmd, args}
POST /api/ai/channel/batch     fino a 20, concorrenti
GET  /api/ai/tools             catalogo (12.374 token: mai al modello)
GET  /api/ai/agent-actions     coda azioni per la mappa, svuotata in lettura
```

**Su loopback niente firma.** L'HMAC serve solo a un agente su un'altra
macchina. `local`/`remote` nel loro pannello = **dove gira l'agente**, non che
modello usa. ShadowBroker non contiene nessun LLM.

### Livelli di permesso

```
READ_COMMANDS   letture
VIEW_COMMANDS   nostri: map_focus, set_layers, highlight   <- tier restricted
WRITE_COMMANDS  place_pin, inject_data, osint_sweep…       <- tier full
```

`VIEW_COMMANDS` è una categoria che abbiamo aggiunto noi: cambia cosa
l'operatore *guarda*, non i dati. Metterli fra le scritture avrebbe costretto a
concedere anche l'iniezione dati e la scansione attiva di sottoreti solo per
spostare una telecamera.

---

## Le trappole, tutte in un posto

| Trappola | Effetto | Rimedio |
|---|---|---|
| `get_telemetry` | **2.470.667 token** | bloccato nel client |
| `get_slow_telemetry` | 2.300.977 token | bloccato |
| `radius_km` / `radius_miles` | **ignorati in silenzio**, ricade su 500 miglia | usare `radius`, e ricontrollare |
| `brief_area.context_layers` | primi N **mondiali**, non locali | usare solo `nearby` |
| `limit_per_layer` su frontlines | non lo tocca: 18.769 token | escluso |
| `alert_tags` | è una **stringa**, non lista | `_tag_lista()` |
| `tracked_flights` | non è militare: c'è "Dogs with Jobs" | `_e_militare()` |
| rate limiter | 429 dopo ~20 richieste, senza `Retry-After` | pausa 120ms + backoff |
| processi orfani | uvicorn reload lascia figli in LISTEN | uccidere anche `multiprocessing.spawn` |
| proxy AIS | è Node, deps mai installate dal loro setup | `cd backend && npm install` |

L'ultima è la peggiore per debug: **Windows permette a più processi di restare
in LISTEN sulla stessa porta**, quindi le richieste possono finire al processo
vecchio senza nessun segnale.

---

## Layer con dati, adesso

```
34.936 power_plants     1.553 gdelt          115 telegram_osint
12.783 sigint           1.468 private_flights  54 news
12.316 meshtastic       1.170 airports         40 weather_alerts
 5.434 commercial         798 kiwisdr          37 earthquakes
 5.000 firms_fires        646 military_bases   28 military_flights
 4.899 datacenters        492 satellites       11 ships (portaerei)
                          246 trains            9 internet_outages
                          177 tracked_flights   5 gt_risk / malware
```

**Vuoti (20):** air_quality, cctv, crowdthreat, fimi, financial,
fishing_activity, gps_jamming, liveuamap, oil, prediction_markets, sar_*,
scanners, stocks, uap_sightings, uavs, ukraine_alerts, viirs, volcanoes.

Alcuni per mancanza di chiave, altri perché il feed non produce nulla ora.
**Vanno dichiarati, non interpretati come "tutto tranquillo".**

---

## Chiavi API

In `shadowbroker/backend/.env`, ignorato da git.

| Chiave | Sblocca | Stato |
|---|---|---|
| `AIS_API_KEY` | 25.000 navi | **configurata** |
| `OPENSKY_CLIENT_ID/SECRET` | voli globali | **configurata** |
| `SH_CLIENT_ID/SECRET` | Sentinel Hub | mancante |
| `MESH_SAR_EARTHDATA_*` | anomalie SAR | mancante |
| `SHODAN_API_KEY` | dispositivi esposti | mancante |
| `GFW_API_TOKEN` | pesca | mancante |

---

## Interfaccia grafica

![ShadowBroker](../immagini/shadowbroker-gui.png)

Cosa si vede, da sinistra:

| Zona | Contenuto |
|---|---|
| pannello sinistro | **DATA LAYERS** — AIRCRAFT 1895, MARITIME 2000, SPACE 492, HAZARDS 65; sotto **Meshtastic Chat**, **Shodan Connector**, **Recon Toolkit**, **Supply Chain** |
| mappa | grappoli numerati, bandiere di nazionalità, riquadri **ALERT LVL 1-10** sopra gli eventi |
| pannello destro | **TIME MACHINE**, **DATA FILTERS**, **GLOBAL THREAT INTERCEPT** con `THREAT: GUARDED 20/100` e le notizie con `ORACLE: 8.0/10 [CRITICAL] // SENTIMENT: -0.66` |
| barra in basso | coordinate sotto il puntatore, **STYLE** (DEFAULT/SATELLITE/FLIR/NVG/CRT), **SOLAR**, e i contatori live `ADS-B 1.9K · AIS 2.0K · NEWS 19 · SAT 492` |
| in alto a destra | **NODE** (mesh InfoNet), **TERMINAL** (CLI), **UPDATES**, ricerca coordinate/luogo/sigla |

Il riquadro `THREAT: GUARDED 20/100` in alto a destra è lo stesso `threat_level`
che il ponte legge: quello che vede l'utente e quello che riceve il modello sono
lo stesso numero.

### Catturare uno screenshot

Playwright funziona, ma serve **una riga di configurazione** o la pagina resta
bloccata su "PRIORITIZING MAP FEEDS" per sempre. Vedi la trappola qui sotto.

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    pg = b.new_page(viewport={'width': 1600, 'height': 900})
    pg.goto('http://127.0.0.1:3000', wait_until='domcontentloaded')
    pg.wait_for_selector('.maplibregl-map canvas', timeout=90000)
    pg.screenshot(path='gui.png')
```

---

## La trappola più insidiosa: `allowedDevOrigins`

In sviluppo Next.js considera **`127.0.0.1` e `localhost` origini diverse** e
blocca le proprie risorse interne — font e WebSocket HMR — quando la pagina è
stata aperta con la forma "sbagliata". Il chunk della mappa non arriva mai.

Il sintomo è crudele: la pagina si carica, l'intestazione e i pannelli si
disegnano, resta scritto **"PRIORITIZING MAP FEEDS"** all'infinito. Nessun errore
in pagina, `window.maplibregl` semplicemente `undefined`. In console solo
`403 Forbidden` su `/__nextjs_font/...` e un WebSocket HMR che fallisce — due
cose che sembrano innocue.

Riguarda **anche l'iframe di Odysseus**: l'indirizzo può essere l'una o l'altra
forma a seconda di come si è arrivati su Odysseus.

```ts
// frontend/next.config.ts
allowedDevOrigins: ['127.0.0.1', 'localhost'],
```

Ho perso tempo dando la colpa al CDN delle tessere. WebGL funzionava (ANGLE sulla
GTX 1080), Playwright funzionava, il canvas non c'era perché il **componente non
si montava mai**.

**Confermato dall'utente:** prima di questa correzione la mappa dentro il
pannello di Odysseus **non caricava affatto**. Dopo, carica in 15-20 secondi.

### 15-20 secondi sono normali

`load` dell'iframe scatta quando arriva il documento, ma MapLibre deve ancora
scaricare le tessere e disegnare 45 livelli. Il pannello lo dichiara
("carico la mappa…") invece di lasciare un rettangolo nero che sembra rotto.
