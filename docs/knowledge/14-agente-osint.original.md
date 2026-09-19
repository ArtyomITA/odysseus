# L'agente OSINT: come il modello interroga ShadowBroker

1 agosto 2026. Analisi dei dati in
[ricerche/shadowbroker-dati-e-domande-possibili.md](../../../ricerche/shadowbroker-dati-e-domande-possibili.md),
misure in [ricerche/shadowbroker-agente-misure.md](../../../ricerche/shadowbroker-agente-misure.md).

---

## L'idea, in una riga

**Il modello non sceglie mai cosa è importante. Lo riceve già deciso.**

Il primo tentativo di progetto era "dare al modello degli attrezzi per pescare
dati". Sbagliato: le domande vere — *"cosa sta succedendo di importante"*,
*"fammi una classifica"* — sono domande di **classifica e sintesi**, e
ShadowBroker le classifiche le ha già calcolate.

```
1. RACCOLTA     Python scarica i layer INTERI e li tiene in memoria.
                Nessun limite, nessuna compressione.

2. CLASSIFICA   Python ordina, filtra per distanza vera, geolocalizza,
   (Python)     deduplica, compone. Usa i punteggi che esistono gia'.
                Deterministico: zero token, zero allucinazioni. Il 90%.

3. NARRAZIONE   Al modello arriva un briefing gia' ordinato, ~1.000 token.
   (modello)    Racconta in italiano, comanda la mappa, chiede
                approfondimenti sui pochi elementi che contano.
```

Numeri misurati:

| | Token | % del contesto da 48K |
|---|---|---|
| Loro catalogo, 62 strumenti | 12.374 | 25,2% |
| **Nostro catalogo, 10 strumenti** | **1.689** | **3,4%** |
| Domanda ingenua sui conflitti | 47.891 | 97,4% |
| **Stesso briefing, dal ponte** | **1.019 medio, 2.311 massimo** | **2,1% / 4,7%** |

---

## Le quattro classifiche già pronte

Scoperte inventariando i dati, non leggendo la loro documentazione.

### `threat_level` — un numero per "quanto è grave adesso"

```json
{"score": 26, "level": "GUARDED",
 "drivers": ["3 CRITICAL-tier news items", "Max oracle score 8.0/10",
             "Cross-layer correlations: 0 HIGH + 9 MED"]}
```

Fusione pesata a 7 componenti (`services/oracle_service.py:199`): sentimento
negativo 25%, mercati conflitto 25%, eventi ad alto rischio 10%, oracolo 10%,
anomalia militare 10%, jamming GPS 10%, correlazioni 10%.

**Le motivazioni sono già frasi leggibili.** Il modello traduce e racconta.

> **Attenzione:** i mercati predittivi sono vuoti e pesano il **25%**. Il
> punteggio è quindi sistematicamente **sottostimato**. Il briefing lo dichiara
> in `non_osservabile`.

### `correlations` — cosa succede in più layer nello stesso punto

```json
{"type": "infra_cascade", "severity": "medium", "score": 60,
 "drivers": ["Internet outage 24%", "KiwiSDR receivers in affected zone"]}
```

### `tracked_flights` — velivoli già classificati

139-177 velivoli, database Plane-Alert da **16.077 aeromobili** più 2.308
immatricolazioni. Ogni voce porta `alert_category`, `alert_operator`,
`alert_tags`, `alert_type`.

> **Trappola:** `tracked_flights` **non** è un elenco militare. È la lista dei
> velivoli *notevoli*: le categorie osservate comprendono "Flying Doctors" (24),
> "Aerial Firefighter" (16), "As Seen on TV" (13), "Dogs with Jobs" (4).
> Rispondendo "quali forze militari si muovono" con l'elenco intero si
> restituiscono ambulanze aeree e Labcorp. `_e_militare()` filtra per categoria
> e operatore; gli esclusi si **contano** e si dichiarano, non si nascondono.

> **Seconda trappola:** `alert_tags` è una **stringa** separata da virgole, non
> una lista. Iterarla direttamente dà i singoli caratteri, e il raggruppamento
> per ruolo non scatta mai — senza nessun errore.

### GT Strategic Risk Analytics — classifica per regione

**Era spento.** Si accende con **due** variabili:

```powershell
$env:GT_ANALYTICS_ENABLED="true"
$env:GT_ANALYTICS_ACK_LOW_CPU="true"   # richiesta se il profilo runtime e' "lean"
```

Passate come variabili d'ambiente al processo funzionano; **dal `.env` no**.

Processa **1.641 regioni**, produce probabilità per dominio (conflitto,
disordini, finanza), potenziale di contagio e una `interpretation` in linguaggio
naturale. Le regioni arrivano etichettate con le coordinate grezze
(`"12.86,30.22"`): il ponte le converte in nomi con `reverse_geocoder`.

---

## I diciassette strumenti OSINT

| Strumento | Risponde a |
|---|---|
| `osint_situazione` | "cosa succede di importante", "fammi una classifica" |
| `osint_notizie` | notizie (luogo/soggetto/tema) **e il testo vero** di un articolo (url o id) |
| `osint_militare` | "quali forze militari si muovono", "ci sono aerei spia" |
| `osint_allerte` | allarmi VIVI adesso: meteo, sismi, blackout, incendi |
| `osint_zona` | "cosa c'è vicino a Odessa" |
| `osint_dettaglio` | la scheda **intera** di un elemento citato |
| `osint_cerca` | "dov'è Air Force One" |
| `osint_recon` | IP, dominio, CVE, sanzioni |
| `osint_mappa` | centra, spegni livelli, evidenzia, preset, ripristina |
| `osint_web` | quello che i feed non sanno: background, biografie, contesto |
| `osint_rischio` | rischio geopolitico che **sale** (modello GT), classifica/dossier |
| `osint_sorveglianza` | watch persistenti + `azione=avvisi` (legge gli alert spinti dal watchdog) |
| `osint_storico` | Time Machine: "com'era 3 ore fa", cattura/riproduci snapshot |
| `osint_geocode` | nome↔coordinate (`/api/geocode`), da chiamare PRIMA di una query geografica |
| `osint_cyber` | threat intel: botnet C2 (abuse.ch), CISA KEV, indice rischio-paese |
| `osint_radio` | scanner pubblici vicini, KiwiSDR vicini, ACARS/HFDL datalink di un aereo |
| `osint_satellite` | on-demand: anomalia termica SWIR, previsione passaggi satellitari |

Diciassette e non sei: il costo non è il problema (105 token l'uno), la
**confusione** sì; l'indice semantico ne mostra ~8 per turno e i profili gli
gatekeepano. Ogni strumento copre una domanda che gli altri non sanno esprimere.

**I quattro ultimi (20 ago)** — geocode/cyber/radio/satellite — nascono dal gap
di ShadowBroker (`ricerche/gap-shadowbroker-capacita-non-considerate.md`): sono
capacità che il backend aveva già (endpoint HTTP diretti, non canale OpenClaw) e
che non esponevamo. Con questi Intelligence sale a 18 tool; se il banco LLM mostra
che confondono il 9B, si spostano dietro un sotto-profilo.

**Fusione (20 ago)**: `osint_testo` non esiste più come tool separato — leggere
il corpo di un articolo è ora `osint_notizie` con `url` o `id`. Un tool in meno
da scegliere, stessa capacità.

**Le tre facciate nuove (20 ago)** — `osint_rischio`, `osint_sorveglianza`,
`osint_storico` — non sono codice da zero: sono verbi che **smistano verso
comandi che il backend già espone** (`gt_*`, `*_watch*`, `timemachine_*`), con
la solita compressione. Nascono dalla scoperta che il canale OpenClaw offre ~85
comandi di cui usavamo una fetta (vedi `ricerche`/mappa agentica). Le loro azioni
di **scrittura** (cattura snapshot, aggiungi watch) girano perché il tier è
`OPENCLAW_ACCESS_TIER=full`; le letture andrebbero comunque.

### La composizione annidata

Sondando tutti e 62 i loro comandi è emerso che tre sono molto più ricchi di
quanto sembrasse, e vanno **composti**, non sostituiti.

`get_entity_profile` (1.182 token) contiene già una scheda articolata:

| Sezione | Token | Destino |
|---|---|---|
| `identity` | 116 | **tenuta** — sigla, matricola, proprietario, tag |
| `movement` | 93 | **tenuta**, ridotta a durata e numero di rilevazioni |
| `position` | 29 | tenuta |
| `notes` | 71 | **tenuta** — avvertenze oneste già scritte |
| `aircraft_state` | 5 | tenuta |
| `trail` | 355 | **scartata** — `movement` la riassume |
| `lookup` | 432 | **scartata** — `identity` è il distillato |

`correlate_entity` (1.690 token) aggiunge `signals`: inferenze **già valutate**
con confidenza e motivo in chiaro (*"10 other live tracked entities within
300 km"*, confidenza 0.5). E dichiara da sé
`claim_level: "evidence_pack_not_verdict"` — riportato al modello perché non lo
presenti come un fatto.

Risultato: **375 token base, 644 con contesto**, contro 3.145 grezzi.

---

## Le difese, e perché ognuna esiste

### Comandi bloccati a monte

`get_telemetry` = **2.470.667 token**, `get_slow_telemetry` = **2.300.977**.
Cinquanta volte il nostro contesto. Bloccati con un errore rumoroso.

### Il raggio si chiama `radius`, e gli altri nomi vengono ignorati

| Passi | Raggio applicato |
|---|---|
| `radius_km=50` | **500 miglia** |
| `radius_miles=50` | **500 miglia** |
| `radius=50` | 50 miglia |

Chiedendo "notizie entro 50 km da Kyiv" arrivavano Mosca e Varsavia. Il ponte
usa `radius` **e ricontrolla ogni distanza** con l'haversine.

### `brief_area` mescola locale e globale

`nearby` è davvero vicino; `context_layers` sono i primi N **mondiali senza
filtro**. Chiedendo Kyiv, i terremoti restituiti erano in Filippine, Indonesia e
Cina. Un modello che legge quel blocco dice che c'è stato un 5.1 vicino a Kyiv.
`briefing.zona()` non lo usa: filtra da sé.

### `limit_per_layer` non vale per i layer geometrici

`frontlines` con limite 1 costa **18.769 token**: non è una lista, è il poligono
del fronte ucraino. Escluso dalle letture multiple.

### I titoli illeggibili si marcano, non si cancellano

I titoli GDELT sono ricavati dallo slug dell'URL. Quando lo slug è un
identificativo (`2V2I2Yypobgvrnf76Nzytqcqge`) il titolo è inutile — ma
**l'articolo esiste**. Si marca `leggibile: false`, si tiene l'URL, e se
l'articolo entra fra i primi si recupera il titolo vero dalla pagina.

> La prima versione del filtro toglieva gli spazi prima di controllare, quindi
> "Russia Pounds Kyiv With Missiles" diventava una stringa alfanumerica e finiva
> fra gli scarti: **cancellava proprio le notizie**. Trovato misurando.

### Il testo degli articoli si recupera

Nessuna fonte porta il corpo: `news` ha solo il titolo, il campo estratti di
GDELT esiste ma **non viene mai popolato**. Gli URL però ci sono sempre — fino a
10 per cluster. Si tentano in sequenza finché uno risponde (i paywall si
saltano). Verificato: 1 su 2 nel campione.

### Ordine delle coordinate GeoJSON

Nelle Feature l'ordine è **(lng, lat)**, invertito rispetto a tutto il resto di
ShadowBroker. Scambiarlo manda i risultati in mezzo all'oceano. `geo.coordinate_di()`
gestisce tutte e quattro le convenzioni presenti.

### Il rate limiter

Interrogare i layer di fila dà HTTP 429 dopo ~20 richieste, senza `Retry-After`.
Il client serializza, aspetta 120 ms fra le chiamate e ritenta a scalare.

---

## Il controllo mappa

Prima esistevano **due sole azioni** (`show_image`, `fly_to`), e `fly_to` si
poteva innescare solo da `sar_focus_aoi`, che pretende un'area SAR già definita.
I toggle dei livelli vivevano nello stato React: **niente fuori dal browser
poteva raggiungerli**.

Aggiunti tre comandi in `openclaw_channel.py`:

```
map_focus(lat, lng, zoom)      -> centra su un punto qualsiasi
set_layers(on, off, solo)      -> "solo" spegne tutto tranne quello nominato
highlight(punti, ttl_seconds)  -> anelli sopra le entita' citate, poi svaniscono
```

**Nuova categoria di permessi: `VIEW_COMMANDS`**, non `WRITE_COMMANDS`. Questi
comandi cambiano cosa l'operatore *sta guardando* e nient'altro: non creano,
non cancellano, non iniettano. Metterli fra le scritture avrebbe costretto a
concedere anche `inject_data`, `osint_sweep` (scansione attiva di sottoreti) e
`post_gate_message` (pubblicazione sulla mesh) solo per far spostare una
telecamera. Funzionano a tier `restricted`.

Lato frontend (`useAgentActions.ts`):

- polling da **3.000 ms a 700 ms**. A 3 secondi la mappa si muoveva dopo che
  l'assistente aveva finito la frase: sembra rotto, non lento.
- `layersBeforeAgentRef` conserva la selezione dell'operatore **prima** che
  l'agente tocchi qualcosa, così `ripristina` rimette quello che aveva scelto
  l'utente e non i valori predefiniti. Una conversazione non deve riorganizzare
  in modo permanente il cruscotto di qualcuno.
- `AGENT_LAYER_ALWAYS`: giorno/notte, segnaposto AI e i livelli raster non si
  spengono mai con "mostra solo questi" — nasconderli fa sembrare la mappa rotta
  senza comunicare niente.

**Difetto loro corretto:** `flyTo` aveva `zoom: 8` scritto fisso e ignorava lo
zoom richiesto. Un agente che chiedeva di inquadrare una nazione (zoom 4) o un
singolo aeroporto (zoom 12) atterrava sempre a scala cittadina.

**Traduzione dei nomi** (`lib/agentLayerMap.ts`): i due vocabolari non
coincidono. Il canale parla di `military_flights`, i toggle si chiamano
`military`; `ships` ne accende quattro.

---

## Modalità dedicata

Con il pannello ShadowBroker aperto, `chat.js` manda `osint_mode=true` e il
backend restringe la dotazione ai soli strumenti OSINT più i tre sempre
disponibili. Tutto il resto finisce in `disabled_tools`.

Non è un risparmio di token: **impedisce a un 9B di rispondere con PowerShell
alla domanda "cosa succede in Ucraina"**. Stessa lezione dello sfoltimento di
Windows-MCP — meno candidati simili, meno scelte sbagliate.

---

## Voce: precaricamento del blocco successivo

Le pause di 3-4 secondi fra le frasi venivano da `sintetizza-poi-riproduci`:
PocketTTS impiega ~2 s per una frase corta e ~8 s per un paragrafo, e quell'attesa
cadeva in silenzio fra una frase e l'altra.

Blocchi più grossi avrebbero ridotto le pause ma ritardato la **prima** parola
della stessa quantità. Il precaricamento no: la sintesi del blocco N+1 si
sovrappone alla riproduzione del blocco N. Zero pause, zero ritardo iniziale.

> **Aggiornato il 1 agosto 2026.** Il precaricamento resta, ma non riempie più una
> cache di blob: crea l'elemento `<audio>` in anticipo e lo lascia bufferizzare,
> perché adesso l'audio arriva **in streaming**. Il ~2 s per frase corta citato qui
> sopra era il tempo per averla *tutta*; il primo suono adesso esce a **0,98 s**
> su una frase da 132 caratteri. Vedi [05-voce-tts-stt.md](05-voce-tts-stt.md).

---

## File

### Nuovi in Odysseus

| File | Ruolo |
|---|---|
| `src/shadowbroker/client.py` | HTTP con backoff, batch, comandi vietati, `radius` corretto |
| `src/shadowbroker/store.py` | magazzino per layer, identificativi stabili, schede intere |
| `src/shadowbroker/sagome.py` | che campi tenere per layer |
| `src/shadowbroker/geo.py` | distanze vere, nomi dei posti, 60+ luoghi noti |
| `src/shadowbroker/testo.py` | recupero articoli, titoli marcati non cancellati |
| `src/shadowbroker/briefing.py` | **i cinque briefing precalcolati** |
| `src/shadowbroker/entita.py` | composizione annidata delle schede |
| `src/shadowbroker/schemi.py` | schemi degli strumenti |
| `src/agent_tools/shadowbroker_tools.py` | i dieci handler |

### Modificati

`src/tool_schemas.py`, `src/agent_tools/__init__.py`, `routes/chat_routes.py`
(modalità OSINT), `static/js/chat.js` (flag), `static/js/tts-ai.js`
(precaricamento).

### In ShadowBroker

`backend/services/openclaw_channel.py` (`VIEW_COMMANDS` + tre comandi),
`frontend/src/hooks/useAgentActions.ts`, `frontend/src/lib/agentLayerMap.ts`
(nuovo), `frontend/src/app/page.tsx`, `frontend/src/components/MaplibreViewer.tsx`,
`frontend/src/types/dashboard.ts`.

---

## Prove

`scripts/prova_osint.py` — **48 controlli, 0 rotti, 0 oltre il tetto**.
Peso massimo 2.311 token (4,7% del contesto), media 1.019.

Copre: blocco dei comandi mostruosi, risoluzione dei luoghi, distanza
Kyiv-Mosca (756 km), ordine GeoJSON, titoli tenuti/scartati, nessun articolo
perso, i cinque briefing, la composizione delle entità, i dieci strumenti, i
rifiuti attesi, il ciclo briefing → identificativo → scheda intera, e la
coerenza fra schemi, handler e tag.

---

## Non ancora provato

**Il modello locale.** Tutta la catena è verificata fino allo strumento, ma non
è stato provato se **QwenPaw sceglie lo strumento giusto** — llama era spento su
richiesta. È l'unica cosa che manca, e serve accendere la GPU.

Da guardare quando si prova:

- sceglie `osint_situazione` per "cosa succede" invece di `osint_notizie`?
- chiama `osint_mappa` mentre parla, o se ne dimentica?
- riporta i buchi (`non_osservabile`) o afferma che non succede nulla?
- cerca in inglese (`conflict`) o in italiano (`conflitto`, che non trova nulla)?
