# Modello e hardware: vincoli, scelte, misure

> **Nota 19 set 2026.** Modello predefinito ora **LFM2.5-2.6B** (Liquid AI),
> non più QwenPaw-Flash-9B. Tutto sotto
> descrive l'hardware (sempre valido) e il modello dell'epoca, QwenPaw
> (superato). Riassunto dell'attuale:
>
> - **LFM2.5-2.6B Q8_0 GGUF** (2.87 GB) + drafter speculativo ufficiale
>   **LFM2.5-2.6B-DSpark Q8_0** (0.36 GB, deve restare Q8_0: F16 dimezza la
>   velocità su Pascal). Profilo llama-swap `lfm` (alias vista `lfm-vista`).
> - **Contesto 49152**, **VRAM ≈ 4.8 GB**.
> - Campionamento (valori ufficiali Liquid): temp 0.1, top-k 50,
>   repeat-penalty 1.1.
> - Speculative decoding: `--spec-type draft-dspark --spec-draft-n-max 3`
>   (non 10 come da raccomandazione Liquid: su Pascal 10 rallenta la prosa
>   del 23%).
> - Misurato su questa GTX 1080: prefill 1940 tok/s (i modelli precedenti erano
>   molto più lenti in prefill, ≈850), decodifica 64 tok/s, 78-100 tok/s con
>   DSpark attivo. Suite allucinazioni: 48/48 turni con lo strumento giusto,
>   0 invenzioni.
> - Leve specifiche del modello in `vergilius-lfm.env`, caricato dal boot
>   quando `VERGILIUS_MODELLO=lfm` in `vergilius.env`.
> - Licenza: **LFM Open License v1.0** (basata su Apache-2.0, uso commerciale
>   libero sotto 10M USD di ricavi annui). Pesi non inclusi nel repo, scaricati
>   da Hugging Face; si accetta la licenza scaricando.
>
> Dettagli architetturali di QwenPaw sotto (attenzione lineare, scala A0-A4,
> misure Q4/Q5) **non sono stati riverificati su LFM2.5-2.6B**: lasciati come
> riferimento storico, non applicare alla configurazione attuale senza
> rimisurare.

## L'hardware

- **GPU: GTX 1080, 8GB GDDR5X**, architettura Pascal (capacità calcolo 6.1).
  Niente tensor core, niente FP8/INT8. CUDA 13 ha **abbandonato Pascal**: si resta
  su CUDA 12.x e ramo driver 580xx.
- **16GB RAM di sistema.** Risorsa più stretta dopo VRAM: ci girano
  ChromaDB, sintesi vocale, trascrizione, embedding e proiettore
  visivo.
- **PCIe 3.0 x16.** Su modelli densi come nostro, spostare anche pochi livelli
  su CPU significa far viaggiare quei pesi sul bus **a ogni token**: crollo di
  velocità molto peggiore che sui modelli a esperti. **L'offload dei livelli è
  ultima risorsa, non una leva.**
- Windows 11. Desktop con applicazioni aperte ruba **~1.1GB di VRAM**.

## Il modello scelto: QwenPaw-Flash-9B (superato, vedi nota in cima)

Finetune di Qwen3.5-9B fatto dal team AgentScope (Alibaba) **specificamente per
agenti autonomi**: invocazione strumenti, comandi terminale, gestione
filesystem, ricerca web multi-passo, memoria attiva. Apache 2.0.

Perché lui e non Qwen3.5-9B liscio: addestrato sul nostro caso d'uso esatto,
riduce lavoro che dovremmo fare con skill.

Particolarità architetturale favorevole: su 32 livelli **solo 8 usano
attenzione classica** (accumula cache), altri 24 usano attenzione lineare
a stato fisso. Cache cresce quindi solo per 8 livelli: **circa un terzo** di
transformer classico da 9B. Motivo per cui riusciamo a tenere 48K di
contesto.

### I file scaricati

| File | Dimensione | Uso |
|---|---|---|
| `QwenPaw-Flash-9B.i1-Q4_K_M.gguf` | 5.24 GiB | profilo base (predefinito) |
| `QwenPaw-Flash-9B.i1-Q5_K_M.gguf` | 6.02 GiB | qualità, non in elenco (costringe a 8K) |
| `QwenPaw-Flash-9B.mmproj-f16.gguf` | 0.86 GiB | proiettore visivo, precisione piena |
| `QwenPaw-Flash-9B.mmproj-Q8_0.gguf` | 0.58 GiB | proiettore visivo compresso |
| `QwenPaw-Flash-9B-heretic-Q4_K_M.gguf` | 5.24 GiB | variante senza rifiuti |
| `mmproj-heretic-BF16.gguf` | 0.86 GiB | proiettore variante |

Da [mradermacher](https://huggingface.co/mradermacher/QwenPaw-Flash-9B-i1-GGUF)
(quantizzazioni con matrice importanza) e
[FadedRedStar](https://huggingface.co/FadedRedStar/QwenPaw-Flash-9B-heretic-GGUF).

Nota: quantizzazioni dinamiche Unsloth (UD-Q4_K_XL) che piano originale
raccomandava **non esistono** per QwenPaw. Le i1 di mradermacher sono
equivalente più vicino.

### La variante "heretic"

Stesso modello con rifiuti rimossi chirurgicamente (ablazione livelli
13-16). Numeri dichiarati: **12 rifiuti su 100 contro 96 su 100**, divergenza
0.0099 (danno capacità praticamente nullo).

Motivazione: agente che si blocca a metà compito perché "non se la sente"
di leggere file o lanciare comando è inutilizzabile. Contropartita onesta:
quel filtro non distingueva falsi allarmi da richieste davvero problematiche,
quindi cade anche giudizio sulle seconde.

Campionamento raccomandato dalla scheda: temperatura 1.0, top-p 0.95, top-k 20,
penalità presenza 1.5. Scritto nei profili di llama-swap.

**Il predefinito è modello normale**, non heretic. Heretic si sceglie dal menu
quando serve.

## La scala di configurazioni (dal piano originale)

Progettata partendo da massima accuratezza e degradando per costo crescente:

| Livello | Pesi | Cache | Contesto | Note |
|---|---|---|---|---|
| A0 | Q6_K | f16 | 8K | riferimento qualità, richiede offload: lentissimo |
| A1 | Q5_K_M | f16 | 8-12K | massima accuratezza tutta in GPU |
| **A2** | **Q4_K_M** | **q8_0** | **48K** | **configurazione operativa** |
| A3 | Q4_K_M + proiettore | q8_0 | 32K | con vista |
| A4 | IQ4_XS | q8_0 | quel che entra | pavimento assoluto |

**Regola invalicabile: mai sotto IQ4 sui pesi.** Tool calling si rompe a IQ3
(fallimenti intermittenti produrre JSON valido). Sotto soglia non si
cambia quantizzazione: si cambia modello (9B → 4B).

Ordine degradazione, dal più economico al più costoso:
1. cache f16 → q8_0 (quasi gratis)
2. pesi Q5 → Q4 (quasi gratis con quantizzazioni a matrice importanza)
3. contesto ↓ (reversibile, costo funzionale non qualitativo)
4. pesi Q4 → IQ4_XS (piccola perdita, -5/10% velocità)
5. vista da residente a su richiesta
6. cache del valore a q4_0 (ultimo, solo quella)

## Le misure vere, fatte su questa macchina

Tutte con desktop attivo (~1.1GB VRAM occupati da Windows).

| Configurazione | Generazione | Prompt | VRAM | Tool calling |
|---|---|---|---|---|
| Q4, 32K, cache f16 | 24.5 tok/s | 105 tok/s | 7410 MiB | OK |
| Q5, 8K, cache f16 | 22.2 tok/s | 198 tok/s | 7273 MiB | OK |
| **Q4, 64K, cache q8_0, flash attention** | **27.1 tok/s** | **522 tok/s** su 13.8K | 7793 MiB | OK |
| via llama-swap (heretic) | 23.6 tok/s | — | 7303 MiB | — |

Caricamento a freddo modello: **~50 secondi** (5.24GB da disco).

### Le tre scoperte delle misure

**1. La flash attention su Pascal funziona, e accelera.** Era rischio numero
uno del piano (kernel di ripiego poteva mancare o essere lento). Invece:
**+10% generazione**. E soprattutto sblocca cache compressa, vero
premio.

Chiarimento importante: `-fa on` di llama.cpp **non è** libreria FlashAttention
originale (richiede tensor core, su Pascal non gira proprio). È
reimplementazione con più kernel alternativi, sulle GPU vecchie ripiega su
operazioni normali. Stesso risultato matematico, nessun hardware speciale.

**2. La cache q8_0 non degrada il recupero.** Test ago nel pagliaio: codice
segreto messo a inizio prompt da 13.8K token ripescato
esatto, generazione ancora a ~25 tok/s a cache piena.

**3. Il Q5 non vale il prezzo.** Guadagno qualità impercettibile su Q4 con
matrice importanza, ma costringe contesto da 48K a 8K. Escluso dai profili.

## Il contesto ottimale (ricerca)

Limite dichiarato del modello è 262K token. Contesto **effettivo** è tutt'altra
cosa: tipicamente 50-80% del massimo, degrado inizia molto prima
("context rot": informazioni al centro finestra si perdono, curva a U).

Regola pratica settore per assistenti locali: **8-32K più buon recupero
batte 128K senza recupero**. Esattamente nostra architettura (skill
selezionate semanticamente invece di riempire finestra).

Per nostro uso (orchestratore con strumenti, skill iniettate, memoria): **32-48K
è punto d'equilibrio**. Oltre si paga VRAM per qualità che cala.

## Le ottimizzazioni: fatte e non fatte

**Fatte e validate:**
- flash attention (`-fa on`)
- cache KV a q8_0
- tutti i livelli in GPU, niente offload
- `--no-mmap --mlock`
- proiettore visivo su RAM (`--no-mmproj-offload`): libera ~900MB VRAM e
  permette 32K contesto con vista invece di 16K

**Disponibili ma non fatte:**
- **speculative decoding / MTP**: esiste drafter pronto
  ([SC117/QwenPaw-Flash-9B-MTP-GGUF](https://huggingface.co/SC117/QwenPaw-Flash-9B-MTP-GGUF)),
  si attiva con `--spec-type draft-mtp --spec-draft-n-max 2`. Potenziale +20-30%.
  Costo: 0.3-0.8GB VRAM per modello di bozza.
- **modalità headless**: display su scheda madre invece che su 1080,
  recupera ~1.1GB. Su Linux si otterrebbe gratis.
- **fork AtomicBot** (cache turbo per contesti da 128K): **mai installato**.
  Siamo su llama.cpp ufficiale. Non serve: con q8_0 abbiamo già 48K.
- **fork ik_llama.cpp** (quantizzazioni IQ4_KS quasi senza perdita): non provato,
  ha crash noto proprio su GTX 1080.
- **upgrade RAM 16 → 32GB**: fuori dal software, ma è mossa che sbloccherebbe
  di più (seconda istanza, modelli MoE grandi in ibrido).
