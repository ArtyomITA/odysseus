# Reti e ricevitori pubblici: cosa sono i puntini della mappa

Il layer SIGINT e i pannelli laterali di ShadowBroker mostrano **hardware vero
di persone vere**, non simulazioni. Questa pagina spiega cos'è ciascuno, a
cosa serve e quali sono i limiti — comprese le due cose che sembrano rotte e
non lo sono.

Conteggi misurati il 2 agosto 2026, dopo il fix del fetcher (sotto).

| Sorgente | Elementi | Cos'è |
|---|---|---|
| SIGINT (Meshtastic + APRS) | ~800 | nodi radio che si annunciano da soli |
| KiwiSDR | 833 | ricevitori radio in cui si entra dal browser |
| PSK Reporter | 1.723 | chi ha sentito chi via radio, nel mondo |
| Infonet | 0 | rete interna di ShadowBroker: **nessun seed pubblico** |
| Shodan | — | motore di ricerca dei dispositivi: **a pagamento, chiave assente** |

---

## Meshtastic — i puntini verdi con i nomi

Rete radio **a maglia**, senza internet e senza SIM: schede da ~30 € (ESP32 +
radio LoRa, 868 MHz in Europa) che si passano messaggi di testo saltando da un
nodo all'altro. 2-10 km a salto, ma dieci nodi in catena coprono una città.

Sulla mappa li vediamo perché **alcuni proprietari collegano il nodo a
internet via MQTT** e da lì posizione, nome e messaggi finiscono su un feed
pubblico. Il nome (`LoreAndrea`, `dinamite`) è testo libero scelto dal
proprietario: nomi in serie = una persona con più nodi, non un'organizzazione.

Cosa significano i campi:

- **ROUTER** — quel nodo ritrasmette anche il traffico altrui, non solo il
  proprio: è un ripetitore della maglia.
- **LongFast** — il canale predefinito che hanno tutti. La chiave di cifratura
  di default **è pubblica e nota**: "cifrato" sulla carta, in pratica
  leggibile da chiunque ascolti, e archiviato sui server MQTT pubblici.
- **`!A83BB37C`** — indirizzo del nodo, derivato dal MAC della scheda.

Usi tipici: gruppi fuori copertura (montagna, vela, deserto), emergenze quando
cadono le celle, eventi sparsi su chilometri, community cittadine che allargano
la copertura, telemetria di sensori.

**Nota di prudenza**: scrivere su LongFast dichiara il proprio nodo —
indirizzo e spesso posizione — su una rete pubblica e archiviata.

## KiwiSDR — ascoltare da dove non sei

Ricevitore radio fisico (0-30 MHz, onde corte) che qualcuno tiene acceso a
casa sua e **condivide su internet**: fino a 4 persone insieme, si entra dal
browser. Le onde corte rimbalzano sulla ionosfera, quindi da un ricevitore a
Roma si sentono aerei transoceanici, navi, radioamatori, stazioni militari.

Usi tipici: radioamatori che si ascoltano da fuori per giudicare la propria
antenna; ascolto di emittenti internazionali e *numbers station*; utility
(controllo aereo HF, WEFAX, NAVTEX); studio della propagazione. Il pezzo forte
per l'OSINT è il **TDoA**: lo stesso segnale preso da tre-quattro ricevitori,
confrontando i ritardi si **localizza il trasmettitore** — senza avere
hardware da nessuna parte.

Come leggere una scheda: `IZ0INA` è il nominativo del radioamatore (IZ0 =
Lazio); "Off-Center Feed Dipole 21 m, N/S" è il tipo e l'orientamento
dell'antenna (nord-sud significa che sente meglio **est-ovest**); il filtro
passa-basso a 54 MHz evita l'accecamento da FM e TV.

### Il bug che teneva la lista congelata (2 ago 2026)

Sintomo: **TUNE IN apriva schede morte**. Il ricevitore di Roma era davvero
spento, ma la causa vera era nostra e riguardava tutti i ricevitori.

Il fetcher provava **prima HTTPS** su un mirror che parla **solo HTTP** — lo
diceva il commento in cima al nostro stesso file. Il tentativo HTTPS falliva,
e quel fallimento apriva il **circuit breaker** sull'host per due minuti, che
bloccava il ripiego HTTP immediatamente dopo. Risultato: l'aggiornamento non è
mai riuscito **nemmeno una volta**, e la mappa serviva per sempre il *bundle
statico* incluso nel codice, pieno di ricevitori morti da mesi.

```
prima:  798 ricevitori dal bundle congelato (con dentro i morti)
dopo:   833 ricevitori dal mirror live (i morti spariti da soli)
```

Fix: HTTP per primo (`services/kiwisdr_fetcher.py`). La difesa lì non era il
TLS — che su quell'host **non esiste** — ma la validazione di forma, che
resta. Lezione generale: **un ripiego che passa dallo stesso circuit breaker
del tentativo fallito non è un ripiego.**

## PSK Reporter — la mappa della propagazione

Rapporti di ricezione dei radioamatori: chi ha decodificato chi, dove e su
quale banda. Non è comunicazione, è **misura**: dice in tempo reale quali
tratte radio sono aperte nel mondo. Utile per capire se un collegamento è
fisicamente possibile in un dato momento.

## Infonet — non è rotta, è vuota

La rete di messaggistica decentralizzata **interna** a ShadowBroker: messaggi
firmati, canali tematici ("gates"), messaggi diretti via "Dead Drop", il tutto
instradato dal **Wormhole** (lo strato di offuscamento). Nessun account:
l'identità è una chiave.

Attivando un nodo compare `bootstrap manifest not found:
backend/data/bootstrap_peers.json`. **Non è un file mancante per errore**:

- non viene distribuito nessun seed pubblico (`MESH_RNS_PEERS` vuoto, nessun
  manifesto firmato nel repo, niente indirizzi nella documentazione)
- le installazioni nuove **non usano un seed clearnet** per scelta di privacy
- quindi la rete, per un'installazione fresca, **non esiste**: si è il primo
  nodo

Le tre strade: qualcuno passa il suo indirizzo (onion/RNS) e si firma un
manifesto; oppure si crea una rete privata propria
(`backend/scripts/bootstrap_manifest_helper.py`, chiavi Ed25519 + manifesto
firmato); oppure la si lascia stare — la documentazione del progetto stesso
dichiara che **la privacy non è garantita**, è codice testnet.

Per mappa, OSINT e profilo Financial l'Infonet è **del tutto irrilevante**.

**Da non confondere**: Infonet nasce chiusa e si apre per invito; Meshtastic è
l'opposto — pubblica, i nodi si dichiarano da soli, ed è quella che si vede
sulla mappa.

## Shodan — motore di ricerca dei dispositivi

Indicizza **macchine connesse a internet** invece di pagine: server, router,
telecamere, database, impianti industriali, con IP, porta, banner, città.

Nel nostro connettore (manuale, chiave dell'operatore, tutto locale):
**Search** (query stile `port:443`, host sulla mappa), **Count** (solo
conteggi + facet `country,port,org`: statistiche senza scaricare i
risultati), **Host** (scheda completa di un IP con storico). Più preset
salvabili ed export CSV.

Stato attuale: `configured: false` — **nessuna `SHODAN_API_KEY` nel `.env`**,
quindi il pannello non cerca. È un'API a pagamento. Freni già previsti: 1-2
pagine per ricerca, cooldown ~1 s, nessun polling in background.

Il confine: **guardare** i risultati è ricognizione passiva e lecita;
**connettersi** a un dispositivo trovato senza autorizzazione è accesso
abusivo. Shodan mostra la porta aperta, entrarci è un'altra cosa.

## Layer vuoti (2 ago 2026)

`satnogs`, `tinygs`, `scanners`, `meshtastic_map_nodes` risultavano a **0**
subito dopo un riavvio: certi feed lenti girano a intervalli lunghi, quindi
può essere solo tempistica. Se restano vuoti a regime, vanno guardati — vale
la regola di sempre: **un layer vuoto è un'informazione, non silenzio**.
Vedi [17-catalogo-dati.md](17-catalogo-dati.md).
