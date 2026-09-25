# L'harness attorno a LFM2.5-2.6B: cosa è acceso, cosa è spento e perché

Aggiornato al 24 settembre 2026. Questo documento descrive come Vergilius guida il modello
predefinito, LFM2.5-2.6B di Liquid AI, adottato il 19 settembre 2026 al posto di Ling-3.0-tiny.
Raccoglie in un solo posto ciò che prima stava sparso tra i commenti di `vergilius-lfm.env`, le
note in cima a [02](02-modello-e-hardware.md) e [10](10-decisioni-e-alternative-scartate.md) e i
file di misura nel laboratorio.

Per «harness» si intende tutto ciò che Odysseus fa attorno al modello: quali strumenti gli manda,
come ricostruisce la storia, quanto lo lascia ragionare, quali controlli applica alla risposta.

---

## 1. Il principio

Con Ling l'harness era pieno di vincoli: congelamento degli strumenti, regole con MUST e NEVER,
chiamata obbligatoria sulle domande di attualità, rilevatore di numeri inventati con rilancio
automatico. Servivano perché Ling seguiva le istruzioni a metà e inventava dati.

LFM si comporta al contrario: sceglie bene gli strumenti e obbedisce alla lettera. Le stesse regole,
lette da un modello obbediente, diventano gabbie. Il caso misurato più chiaro: la regola
«numbers from tools, never invented» più il rilancio automatico facevano rifiutare a LFM calcoli
banali, come convertire un prezzo con il cambio scritto dall'utente nella domanda.

La regola che ne è uscita, e che vale per ogni modello futuro: **tenere ciò che non peggiora la
risposta (infrastruttura, cache, velocità) e togliere i vincoli che il modello non richiede.** Un
vincolo si riaccende solo se una misura mostra un difetto preciso che quel vincolo copre.

---

## 2. Modello e server

| cosa | valore |
|---|---|
| modello | `LFM2.5-2.6B-Q8_0.gguf` (2,87 GB), denso ibrido: 22 blocchi convoluzionali + 8 di attenzione |
| bozza speculativa | `LFM2.5-2.6B-DSpark-Q8_0.gguf` (0,36 GB), drafter ufficiale Liquid |
| profilo llama-swap | `lfm`, alias `lfm-vista` (stesso processo; il suffisso serve a Odysseus per avviare gli occhi Holo su CPU) |
| binario | `llama-pre5-b02` (b10549 compilato per sm_61, grafi CUDA accesi) |
| contesto | 49152 token, KV q8_0, flash attention on, `--slot-save-path`, `--metrics` |
| campionamento | valori Liquid: temp 0,1, top-k 50, repeat-penalty 1,1 |
| speculativa | `--spec-type draft-dspark --spec-draft-n-max 3 --spec-draft-n-min 0` |
| VRAM | circa 4,8 GB a contesto pieno |

**Velocità misurata sulla GTX 1080** (llama-bench, 19 set):

| | LFM2.5-2.6B Q8_0 | Ling-3.0-tiny Q6_K (per confronto) |
|---|---|---|
| prefill a vuoto | 1940 tok/s | circa 850 |
| prefill a 8k di profondità | 1423 tok/s | circa 700 |
| generazione | 64 tok/s | 58 |

**DSpark**, banco greedy su tre tipi di testo (`lfm-speculativa.json`):

| lunghezza bozza | prosa | copia di un elenco | JSON |
|---|---|---|---|
| nessuna (base) | 62,5 tok/s | 57,7 | 58,1 |
| **3 (adottata)** | **78,2 (1,25×)** | **98,0 (1,70×)** | **99,5 (1,71×)** |
| 5 | 67,8 | 95,1 | 84,3 |
| 10 (consiglio Liquid) | 48,2 (0,77×) | 110,3 | 76,0 |

Tre cose da sapere:
- con bozza 10 la prosa rallenta del 23% e in un caso la risposta è risultata peggiore del modello base;
- il drafter in F16 dimezza la velocità: la 1080 non ha fp16 veloce, quindi va tenuto in Q8_0;
- l'output con DSpark **non** è identico al modello base (2 risposte su 6 uguali, differenze di una
  parola nella prosa). Liquid dichiara output identici; da noi non lo sono.

**Caratteristiche del modello che l'harness deve conoscere:**
- pensa sempre: non esiste un interruttore per spegnere il ragionamento, si può solo limitarlo;
- scrive le chiamate in formato Pythonico tra marcatori speciali; il parser di llama.cpp b10549 le
  converte in `tool_calls` standard (verificato);
- in streaming le chiamate a strumento arrivano intere anche con il pensiero attivo (verificato il
  20 set), per questo i giri con strumenti sono tornati in streaming.

---

## 3. Come si carica la configurazione

Il boot (`boot/vergilius_boot.py`) legge tre file in quest'ordine, e ogni file sovrascrive il
precedente:

1. `vergilius.env`: impostazioni generali, valide su qualunque macchina;
2. `vergilius-hardware.env`: impostazioni tarate su questa GPU e su questo server;
3. `vergilius-<modello>.env`: caricato solo se `vergilius.env` contiene `VERGILIUS_MODELLO=<modello>`.
   Oggi `VERGILIUS_MODELLO=lfm`, quindi si carica `vergilius-lfm.env`.

Una variabile già presente nell'ambiente di sistema vince su tutti e tre i file. I valori
effettivamente applicati finiscono in `logs/startup-impostazioni.log` a ogni avvio.

Attenzione a leggere i valori: `vergilius.env` contiene ancora le impostazioni pensate per Ling
(per esempio `ODYSSEUS_GROUNDING_RETRY=1`), ma `vergilius-lfm.env` le sovrascrive. Il valore che
conta è quello della tabella qui sotto.

---

## 4. Le leve attive oggi (valori effettivi con `VERGILIUS_MODELLO=lfm`)

### Infrastruttura: sempre accesa, non tocca il comportamento del modello

| leva | valore | cosa fa |
|---|---|---|
| storia con le chiamate a strumento | nel codice | la storia rimandata al modello contiene le vere `tool_calls` e i risultati, non solo la prosa. Senza, il modello impara a rispondere senza strumenti (causa radice delle invenzioni scoperta ad agosto) |
| `ODYSSEUS_HISTORY_REPLAY` | 1 | ogni turno viene rigiocato identico a come fu inviato, così la cache del prompt resta valida |
| `ODYSSEUS_MEMORY_TAIL` | 1 | le memorie recuperate vanno in fondo al prompt, non in testa, dove cambiavano a ogni turno e rompevano la cache |
| `ODYSSEUS_TOOL_OUTPUT_CHARS` / `HISTORY_TOOL_CHARS` | 8000 / 8800 | taglio degli output degli strumenti dentro il turno e nella storia. Devono restare allineati (storia leggermente più lunga), altrimenti la cache si rompe. Con Ling era 3000/3300: col prefill di LFM gli output possono restare quasi interi |
| `ODYSSEUS_AGENT_MAX_TOKENS_CAP` | 4096 | rete di sicurezza contro le generazioni senza fine; in uso normale non scatta |
| `ODYSSEUS_LOCAL_SLOT_PIN` + `ERASE` | 1 + 1 | la chat usa sempre lo slot 0, i servizi (titoli, memorie, skill) lo slot 3, svuotato a fine chiamata. Il pin senza svuotamento peggiora (misurato con Ling: 114 s contro 66) |
| `ODYSSEUS_LOCAL_TOOLS_NONSTREAM` | 0 | anche i giri con gli strumenti vanno in streaming (pensiero visibile, metriche vere) |
| `ODYSSEUS_GROUNDING_CHECK` | 1 | solo una riga `[grounding]` nel log a fine turno; non cambia la risposta |
| `fin_mercati` con `titolo` | nel codice | quotazione di un titolo per nome o ticker, con albero titoli e ripiego su Yahoo; la quotazione sta in testa al risultato, dice quale società ha quotato quando il nome è ambiguo |
| `calcola` | nel codice | calcolatrice per totali, differenze, percentuali, conversioni: toglie gli errori aritmetici del modello |

### Allentate: servono, ma meno forti che con Ling

| leva | valore | perché |
|---|---|---|
| `ODYSSEUS_TOOL_ROUND_REASONING_BUDGET` | 256 (era 128) | limita il ragionamento prima di una chiamata a strumento. Senza limite il turno passa da 30 a 40 s di mediana e arriva a 128 s |
| `ODYSSEUS_TOOL_ROUND_REASONING_MESSAGE` | `Enough thinking. Act now.` | frase che chiude il ragionamento quando il budget finisce |
| `ODYSSEUS_VOICE_REASONING_BUDGET` | 96 | solo nei turni vocali: il testo dentro il pensiero non viene letto, quindi la voce resta muta finché il pensiero non finisce |
| `ODYSSEUS_INTENT_NUDGE_MAX` / `FORCE` / `MAX_CHARS` | 1 / 1 / 1200 | se il modello scrive «chiamo lo strumento» ma non lo chiama, un solo richiamo per turno con chiamata forzata al giro dopo. La soglia a 1200 caratteri copre il caso visto nella suite lunga (risposta di 664 caratteri, soglia vecchia 400) |
| `ODYSSEUS_EMPTY_TOOLCALL_RETRY` | 1 | una chiamata vuota (marcatori senza nome, segnalata dalla comunità dopo molti giri) viene rilanciata una volta invece di chiudere il turno |
| `ODYSSEUS_BROWSER_AUTO_ESCALATION` | 1 | dopo 2 errori di fila degli strumenti browser semplici, si sblocca per il giro dopo solo la categoria Playwright adatta |
| `VERGILIUS_REGOLE_PROFILO` | `libere` | regole dei profili Financial e OSINT senza MUST/NEVER/ZERO: stessi fatti, 1957 caratteri invece di 3365, più la riga che dice al modello che fare i conti è compito suo |

### Spente: LFM regge da solo

| leva | perché è spenta |
|---|---|
| `ODYSSEUS_TOOLSET_FREEZE` | congelava la lista di strumenti per salvare la cache. Col prefill a 1900 tok/s rielaborare il prompt costa pochi secondi, e il congelamento toglieva strumenti utili nei turni successivi |
| `ODYSSEUS_GROUNDING_RULES` | quattro righe di divieti nel prompt: su LFM producevano rinunce |
| `ODYSSEUS_GROUNDING_RETRY` | il rilancio automatico sui numeri «non supportati»: faceva ritrattare calcoli giusti (vedi sezione 5) |
| `ODYSSEUS_STATE_REMINDER`, `ODYSSEUS_TRACE_HINT`, `ODYSSEUS_INTENT_NUDGE_FUTURO` | vincoli nascosti: nella suite lunga costavano il 27% di tempo senza cambiare nessun esito |

### Ancora accesa e in discussione

| leva | stato |
|---|---|
| `ODYSSEUS_FRESH_REQUIRED` | 1 (da `vergilius.env`). Obbliga una chiamata al primo giro quando la domanda chiede un dato di attualità. Con LFM le domande con entità o di attualità hanno sempre chiamato uno strumento anche senza, ma in un turno della suite lunga il modello ha promesso la chiamata senza farla, e questa leva lo avrebbe coperto. Decisione aperta |

---

## 5. Cosa hanno mostrato le prove (19 settembre 2026)

Suite allucinazioni: 20 domande a sessione nuova, ripetute 3 volte. Quattro popolazioni: 6 con
un'entità nominata («quanto sta Apple oggi»), 6 di attualità («che novità sui mercati»), 4 di
calcolo («10 azioni Apple al prezzo di adesso, quanto spendo»), 4 da conoscenza pura che non devono
chiamare strumenti («cos'è il rapporto P/E»).

| braccio | configurazione | esito | turno mediano |
|---|---|---|---|
| Ling H3 (per confronto) | tutti i controlli | 35/36 con strumento, 1 astensione, negative 10/12 | 47 s |
| **LFM LH1** | tutti i controlli di Ling | 48/48 con strumento, 0 invenzioni, negative 9/12; **rilancio su 9 calcoli su 12, 4 rinunce** | 30 s |
| **LFM LP0** | infrastruttura sì, vincoli no, nessun budget di pensiero (fermata a 25/60) | 21/21 con strumento, **4/4 calcoli giusti, 0 rinunce** | 40 s (max 128) |

Le tre negative sbagliate sono sempre la stessa domanda, «cosa significa spread BTP-Bund»: il
modello consulta i mercati prima di spiegare. È una domanda ambigua (lo spread è anche un valore di
mercato), non un difetto.

**Il reperto centrale.** Nel braccio LH1 il rilancio scattava sui calcoli perché il rilevatore
considerava «inventato» ogni numero assente dai risultati degli strumenti, compresi il cambio
scritto dall'utente e il risultato di una moltiplicazione. Tre esempi dalla stessa suite:
- «quanto vale un Bitcoin in euro con un cambio di 0,92»: rilancio 3 volte su 3, risposta finale
  «non è disponibile il tasso di cambio», anche se il cambio era nella domanda;
- «se avessi investito 5000 dollari in Nvidia ieri»: rilancio 3 volte su 3, rinuncia al conto;
- «10 azioni Apple»: nessun rilancio (le cifre di 10 × prezzo restano le stesse), conto giusto.

Il rilevatore è stato poi corretto: i numeri scritti dall'utente e quelli ricavabili da due numeri
supportati (somma, differenza, prodotto, quoziente, percentuale) contano come supportati. Il
rilancio resta comunque spento: con LFM non serve.

**Suite lunga**: 4 scenari da 5 turni nella stessa chat (`scripts/suite-lunga-e2e.py`).

| braccio | configurazione | turno mediano | durata totale | chiamate |
|---|---|---|---|---|
| L1 | profilo LFM | 45 s | 15,4 min | 30 |
| L2 | stesso, con i vincoli nascosti riaccesi | 57 s | 21,0 min | 38 |

Esiti identici turno per turno. Tre difetti comuni ai due bracci, tutti corretti dopo nel codice
e **non ancora riverificati**:
- turno S2.4: il modello attribuisce ad Apple la variazione di Boeing, oppure promette la chiamata
  e si ferma (da cui la soglia del richiamo portata a 1200 caratteri);
- turno S3.3: errore aritmetico (3 × 309,48 scritto come 284,39), da cui lo strumento `calcola`;
- turno S3.5: notizia attribuita al titolo sbagliato, da cui le notizie per titolo in `fin_mercati`.

**Dove va il tempo in un turno.** Il primo turno di una chat rielabora 12-15 mila token (prompt di
sistema più 17 schemi di strumenti): 9-14 secondi. Dal secondo turno la cache li salta. La
risposta finale pesa 350-1000 token, circa metà dei quali di ragionamento. La GPU lavora a 84 °C
con il clock fermo a 1632 MHz: il prefill reale è circa metà di quello del banco a freddo.

---

## 6. Cosa non è ancora verificato

L'elenco completo e ordinato sta in `D:\vergilius-lab\ricerche\opt-1080\43-test-da-fare-lfm.md`.
I punti che toccano l'harness:

- le correzioni del 19 settembre (rilevatore, quotazione per nome, `calcola`, notizie per titolo,
  soglia del richiamo a 1200) non sono ancora passate da una suite;
- apostrofi negli argomenti delle chiamate («l'Italia», «dell'Eni»): la issue llama.cpp #26658
  segnala stringhe corrotte proprio su questo modello;
- valori booleani `True`/`False` in stile Python negli argomenti;
- chiamate vuote dopo molti giri di strumenti;
- se le chiamate di servizio (memorie, skill) ragionano anche quando non dovrebbero;
- `lfm-uncensored`: il profilo tiene spenti regole e rilancio perché il modello base non inventa,
  ma sulla variante senza rifiuti non c'è nessuna misura;
- Holo sulla GPU accanto a LFM (conto stimato 7,3-7,6 GB su 8,2).

I problemi dell'interfaccia trovati dal vivo il 20 settembre (streaming, metriche, Stop, modifica
dei messaggi, voce) sono nei referti `D:\vergilius-lab\qa\2026-09-20-*.md`; la maggior parte è stata
corretta la notte stessa, vedi `2026-09-20-verifica-finale-odysseus.md`.

---

## 7. Dove stanno le misure

Tutte in `D:\vergilius-lab\ricerche\opt-1080\misure\` (fuori dal repository):

| file | contenuto |
|---|---|
| `onda4/alluc-LH1.json`, `alluc-LH1bis.json` | suite allucinazioni LFM con tutti i controlli (LH1bis è una replica involontaria della stessa configurazione) |
| `onda4/alluc-LP0.json` | suite allucinazioni LFM senza vincoli, 25 turni su 60 |
| `onda4/lunga-L1.json`, `lunga-L2.json` | suite lunga, profilo LFM e vincoli nascosti riaccesi |
| `lfm-speculativa.json` | banco DSpark (bozza 3, 5, 7, 10, drafter F16, ngram) |

Script: `scripts/suite-allucinazioni-e2e.py`, `scripts/suite-lunga-e2e.py`,
`scripts/banco-lfm-speculativa.py`, lettori `scripts/onda4-alluc-leggi.py` e
`scripts/onda4-risposte-leggi.py`.

---

## 8. Se si cambia di nuovo modello

1. Creare `vergilius-<nuovo>.env` e impostare `VERGILIUS_MODELLO=<nuovo>` in `vergilius.env`.
2. Partire con i vincoli spenti e l'infrastruttura accesa, come in `vergilius-lfm.env`.
3. Misurare prima di aggiungere: suite allucinazioni e suite lunga, confrontando sempre bracci
   girati nella stessa sessione (tra due corse identiche in notti diverse si è vista una differenza
   del 25%).
4. Riaccendere un vincolo solo se una misura mostra il difetto che copre, e rileggere le regole dei
   profili: un modello più obbediente legge un divieto come un ordine assoluto.
5. Prima di ogni corsa lunga, una prova a secco di due turni per braccio, verificando che a
   rispondere sia davvero l'istanza appena avviata: il 19 settembre una suite intera ha misurato la
   configurazione sbagliata perché la vecchia istanza di Odysseus era rimasta sulla porta 7000.
