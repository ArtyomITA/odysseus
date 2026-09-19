# Modello e hardware: vincoli, scelte, misure

## L'hardware

- **GPU: GTX 1080, 8GB GDDR5X**, architettura Pascal (capacità di calcolo 6.1).
  Niente tensor core, niente FP8/INT8. CUDA 13 ha **abbandonato Pascal**: si resta
  su CUDA 12.x e sul ramo driver 580xx.
- **16GB di RAM di sistema.** È la risorsa più stretta dopo la VRAM: ci girano
  ChromaDB, la sintesi vocale, la trascrizione, gli embedding e il proiettore
  visivo.
- **PCIe 3.0 x16.** Su modelli densi come il nostro, spostare anche pochi livelli
  su CPU significa far viaggiare quei pesi sul bus **a ogni token**: crollo di
  velocità molto peggiore che sui modelli a esperti. **L'offload dei livelli è
  l'ultima risorsa, non una leva.**
- Windows 11. Il desktop con le applicazioni aperte ruba **~1.1GB di VRAM**.

## Il modello scelto: QwenPaw-Flash-9B

Finetune di Qwen3.5-9B fatto dal team AgentScope (Alibaba) **specificamente per
gli agenti autonomi**: invocazione di strumenti, comandi da terminale, gestione
del filesystem, ricerca web multi-passo, memoria attiva. Apache 2.0.

Perché lui e non Qwen3.5-9B liscio: è addestrato sul nostro caso d'uso esatto, il
che riduce il lavoro che dovremmo fare con le skill.

Particolarità architetturale che ci ha favorito: su 32 livelli **solo 8 usano
attenzione classica** (che accumula cache), gli altri 24 usano attenzione lineare
a stato fisso. La cache cresce quindi solo per 8 livelli: **circa un terzo** di
un transformer classico da 9B. È il motivo per cui riusciamo a tenere 48K di
contesto.

### I file scaricati

| File | Dimensione | Uso |
|---|---|---|
| `QwenPaw-Flash-9B.i1-Q4_K_M.gguf` | 5.24 GiB | profilo base (predefinito) |
| `QwenPaw-Flash-9B.i1-Q5_K_M.gguf` | 6.02 GiB | qualità, non in elenco (costringe a 8K) |
| `QwenPaw-Flash-9B.mmproj-f16.gguf` | 0.86 GiB | proiettore visivo, precisione piena |
| `QwenPaw-Flash-9B.mmproj-Q8_0.gguf` | 0.58 GiB | proiettore visivo compresso |
| `QwenPaw-Flash-9B-heretic-Q4_K_M.gguf` | 5.24 GiB | variante senza rifiuti |
| `mmproj-heretic-BF16.gguf` | 0.86 GiB | proiettore della variante |

Da [mradermacher](https://huggingface.co/mradermacher/QwenPaw-Flash-9B-i1-GGUF)
(quantizzazioni con matrice di importanza) e
[FadedRedStar](https://huggingface.co/FadedRedStar/QwenPaw-Flash-9B-heretic-GGUF).

Nota: le quantizzazioni dinamiche Unsloth (UD-Q4_K_XL) che il piano originale
raccomandava **non esistono** per QwenPaw. Le i1 di mradermacher sono
l'equivalente più vicino.

### La variante "heretic"

Stesso modello con i rifiuti rimossi chirurgicamente (ablazione sui livelli
13-16). Numeri dichiarati: **12 rifiuti su 100 contro 96 su 100**, divergenza
0.0099 (danno alle capacità praticamente nullo).

Motivazione: un agente che si blocca a metà di un compito perché "non se la sente"
di leggere un file o lanciare un comando è inutilizzabile. Contropartita onesta:
quel filtro non distingueva i falsi allarmi dalle richieste davvero problematiche,
quindi cade anche il giudizio sulle seconde.

Campionamento raccomandato dalla sua scheda: temperatura 1.0, top-p 0.95, top-k 20,
penalità di presenza 1.5. È scritto nei profili di llama-swap.

**Il predefinito è il modello normale**, non heretic. Heretic si sceglie dal menu
quando serve.

## La scala di configurazioni (dal piano originale)

Progettata partendo dalla massima accuratezza e degradando per costo crescente:

| Livello | Pesi | Cache | Contesto | Note |
|---|---|---|---|---|
| A0 | Q6_K | f16 | 8K | riferimento di qualità, richiede offload: lentissimo |
| A1 | Q5_K_M | f16 | 8-12K | massima accuratezza tutta in GPU |
| **A2** | **Q4_K_M** | **q8_0** | **48K** | **la configurazione operativa** |
| A3 | Q4_K_M + proiettore | q8_0 | 32K | con la vista |
| A4 | IQ4_XS | q8_0 | quel che entra | pavimento assoluto |

**Regola invalicabile: mai sotto IQ4 sui pesi.** Il tool calling si rompe a IQ3
(fallimenti intermittenti nel produrre JSON valido). Sotto quella soglia non si
cambia quantizzazione: si cambia modello (9B → 4B).

Ordine di degradazione, dal più economico al più costoso:
1. cache f16 → q8_0 (quasi gratis)
2. pesi Q5 → Q4 (quasi gratis con le quantizzazioni a matrice di importanza)
3. contesto ↓ (reversibile, costo funzionale non qualitativo)
4. pesi Q4 → IQ4_XS (piccola perdita, -5/10% di velocità)
5. vista da residente a su richiesta
6. cache del valore a q4_0 (ultimo, e solo quella)

## Le misure vere, fatte su questa macchina

Tutte con desktop attivo (~1.1GB di VRAM occupati da Windows).

| Configurazione | Generazione | Prompt | VRAM | Tool calling |
|---|---|---|---|---|
| Q4, 32K, cache f16 | 24.5 tok/s | 105 tok/s | 7410 MiB | OK |
| Q5, 8K, cache f16 | 22.2 tok/s | 198 tok/s | 7273 MiB | OK |
| **Q4, 64K, cache q8_0, flash attention** | **27.1 tok/s** | **522 tok/s** su 13.8K | 7793 MiB | OK |
| via llama-swap (heretic) | 23.6 tok/s | — | 7303 MiB | — |

Caricamento a freddo di un modello: **~50 secondi** (5.24GB da disco).

### Le tre scoperte delle misure

**1. La flash attention su Pascal funziona, e accelera.** Era il rischio numero
uno del piano (il kernel di ripiego poteva mancare o essere lento). Invece:
**+10% di generazione**. E soprattutto sblocca la cache compressa, che è il vero
premio.

Chiarimento importante: `-fa on` di llama.cpp **non è** la libreria FlashAttention
originale (quella richiede i tensor core e su Pascal non gira proprio). È una
reimplementazione con più kernel alternativi, che sulle GPU vecchie ripiega su
operazioni normali. Stesso risultato matematico, nessun hardware speciale.

**2. La cache q8_0 non degrada il recupero.** Test dell'ago nel pagliaio: un
codice segreto messo all'inizio di un prompt da 13.8K token è stato ripescato
esatto, con la generazione ancora a ~25 tok/s a cache piena.

**3. Il Q5 non vale il prezzo.** Guadagno di qualità impercettibile sul Q4 con
matrice di importanza, ma costringe il contesto da 48K a 8K. Escluso dai profili.

## Il contesto ottimale (ricerca)

Il limite dichiarato del modello è 262K token. Il contesto **effettivo** è tutt'altra
cosa: tipicamente il 50-80% del massimo, e il degrado inizia molto prima
("context rot": le informazioni al centro della finestra si perdono, curva a U).

Regola pratica del settore per assistenti locali: **8-32K più un buon recupero
batte 128K senza recupero**. Che è esattamente la nostra architettura (skill
selezionate semanticamente invece di riempire la finestra).

Per il nostro uso (orchestratore con strumenti, skill iniettate, memoria): **32-48K
è il punto d'equilibrio**. Oltre si paga VRAM per qualità che cala.

## Le ottimizzazioni: fatte e non fatte

**Fatte e validate:**
- flash attention (`-fa on`)
- cache KV a q8_0
- tutti i livelli in GPU, niente offload
- `--no-mmap --mlock`
- proiettore visivo su RAM (`--no-mmproj-offload`): libera ~900MB di VRAM e
  permette 32K di contesto con la vista invece di 16K

**Disponibili ma non fatte:**
- **speculative decoding / MTP**: esiste il drafter pronto
  ([SC117/QwenPaw-Flash-9B-MTP-GGUF](https://huggingface.co/SC117/QwenPaw-Flash-9B-MTP-GGUF)),
  si attiva con `--spec-type draft-mtp --spec-draft-n-max 2`. Potenziale +20-30%.
  Costo: 0.3-0.8GB di VRAM per il modello di bozza.
- **modalità headless**: display sulla scheda madre invece che sulla 1080,
  recupera ~1.1GB. Su Linux si otterrebbe gratis.
- **fork AtomicBot** (cache turbo per contesti da 128K): **mai installato**.
  Siamo su llama.cpp ufficiale. Non serve: con q8_0 abbiamo già i 48K.
- **fork ik_llama.cpp** (quantizzazioni IQ4_KS quasi senza perdita): non provato,
  ha un crash noto proprio sulla GTX 1080.
- **upgrade RAM 16 → 32GB**: fuori dal software, ma è la mossa che sbloccherebbe
  di più (seconda istanza, modelli MoE grandi in ibrido).
