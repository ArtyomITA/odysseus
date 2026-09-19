# Configurazione: dove sta cosa e come si cambia

Riferimento pratico ricavato leggendo il codice. Tutto si fa **senza toccare il
core**, salvo dove indicato.

## Impostazioni

**Dove vivono**
- `data/settings.json` — globali (solo admin)
- `data/features.json` — interruttori funzionalità: `web_search`, `web_fetch`,
  `deep_research`, `memory`, `document_editor`, `rag`, `sensitive_filter`, `gallery`
- `data/user_prefs.json` — preferenze **per utente** (`{"_users": {"admin": {...}}}`)

Lista autorevole delle chiavi: `DEFAULT_SETTINGS` in `src/settings.py`. Il file
salvato viene fuso sopra i predefiniti, quindi una chiave assente = predefinito.
Cache di 2 secondi: **una modifica a mano si applica quasi subito, senza riavvio**.

**Chiavi che contano**

| Tema | Chiavi |
|---|---|
| Modelli per ruolo | `default_endpoint_id`, `default_model`, `default_model_fallbacks`, `utility_*`, `vision_model`, `vision_enabled`, `research_endpoint_id`, `research_model`, `task_endpoint_id`, `task_model`, `teacher_model`, `image_model` |
| Tuning agente | `agent_max_rounds` (20, limiti 1-200), `agent_max_tool_calls` (0 = illimitato), `agent_input_token_budget` (6000 = "auto"), `agent_input_token_hard_max` (200000), `agent_stream_timeout_seconds` |
| Skill | `skill_max_injected` (3, limiti 0-12), `skill_autosave_min_confidence` (0.85) |
| Ricerca | `search_provider`, `search_fallback_chain`, `search_result_count`, chiavi API |
| Voce | `tts_enabled`, `tts_provider`, `tts_voice`, `tts_model`, `stt_enabled`, `stt_provider`, `stt_model`, `stt_language` |
| Reminder | `reminder_channel`, `reminder_llm_persona`, `reminder_ntfy_topic` |

**Admin contro utente.** Tutte le chiavi di `settings.json` le scrive solo un
admin. Un sottoinsieme è sovrascrivibile per utente (`_PER_USER_KEYS`): modelli di
default, utility, vision, immagini, research. Il resto ignora la preferenza utente.

**Tre modi per cambiarle**
1. Interfaccia: ingranaggio in sidebar o `Ctrl+,`, oppure `/settings [tab]`
2. API: `POST /api/auth/settings` (JSON, solo admin). Per utente: `PUT /api/prefs/{key}`
3. File: editare `data/settings.json`, rilettura entro 2 secondi

Scorciatoia: esiste il tool `manage_settings`. Si può dire in chat "cambia il
canale dei reminder in ntfy" e lo fa. Le chiavi API restano di sola lettura.

## La nostra configurazione attuale

```json
{
  "default_endpoint_id": "<id dell'endpoint llama-swap>",
  "default_model": "qwenpaw",
  "utility_model": "qwenpaw",
  "vision_model": "qwenpaw-vista",
  "vision_enabled": true,
  "search_provider": "duckduckgo",
  "tts_enabled": true,
  "tts_provider": "endpoint:<id del ponte voce>",
  "tts_model": "pocket-tts",
  "tts_voice": "estelle",
  "stt_enabled": true,
  "stt_provider": "stream",
  "stt_model": "nemotron-3.5-streaming",
  "stt_language": "it"
}
```

`stt_provider: "stream"` è **nostro**, non di Odysseus: significa trascrizione in
diretta via WebSocket su `/api/stt/stream`. Per tornare al giro a lotti (Parakeet,
che resta installato):

```powershell
$env:STT_PROVIDER = "endpoint:<id del ponte voce>"
d:\assistenteeee\tts-venv\Scripts\python.exe d:\assistenteeee\voce\configura_odysseus.py
```

### Manopole della trascrizione in diretta

Variabili d'ambiente **del processo ponte voce** (`:8013`):

| Variabile | Predefinito | Effetto |
|---|---|---|
| `ASR_MODELLO` | `asr-models\...320ms-int8...` | quale cartella modello |
| `ASR_LINGUA` | `it` | lingua dichiarata; `auto` la fa decidere al modello |
| `ASR_THREAD` | `2` | più alto ruba core a llama.cpp; a 2 il RTF è già 0,5 |
| `ASR_SILENZIO` | `0.5` | secondi di silenzio per chiudere il turno (→ ~870 ms reali) |

Le varianti del modello disponibili sono 80, 160, 320, 560 e 1120 ms: è la
finestra che il riconoscitore guarda. Più corta = meno ritardo, un po' meno
precisione. Noi usiamo **320 ms**.

## Endpoint dei modelli

Non stanno in `.env`: sono righe della tabella `model_endpoints` del database.

Campi che contano: `base_url`, `endpoint_kind` (`auto`|`local`|`api`|`proxy`),
`model_type` (`llm`|`image` — **non esiste "tts"**), `supports_tools`,
`cached_models`, `hidden_models`, `model_refresh_mode`.

**`supports_tools` è importante**: Odysseus usa il tool calling nativo solo se è
`true` **oppure** se il nome del modello matcha una lista di parole chiave
(qwen3, claude, gemini...). I nostri nomi di profilo (`qwenpaw`, `heretic`) **non
matchano**, quindi va messo a mano. Altrimenti ripiega su un protocollo testuale a
blocchi di codice.

I due endpoint registrati:
1. **llama-swap** su `http://127.0.0.1:8012/v1` — i 4 profili modello
2. **ponte voce** su `http://127.0.0.1:8013/v1` — sintesi e trascrizione, con i
   suoi due modelli **nascosti dal menu** via `hidden_models`

## llama-swap: i profili

File: `d:\assistenteeee\llama-swap\config.yaml`. Avviato con `--watch-config`:
**modificando il file le modifiche si applicano senza riavviare**.

In cima ci sono due macro che valgono per tutti i profili:
```yaml
macros:
  comune: "--n-gpu-layers 999 -fa on --cache-type-k q8_0 --cache-type-v q8_0 --no-mmap --mlock"
  campionamento: "--temp 1.0 --top-p 0.95 --top-k 20 --presence-penalty 1.5"
```
Cambiando lì, cambia dappertutto.

| Profilo | Modello | Contesto | Vista |
|---|---|---|---|
| `qwenpaw` | base | 48K | no |
| `qwenpaw-vista` | base | 32K | sì, proiettore su RAM |
| `heretic` | senza rifiuti | 48K | no |
| `heretic-vista` | senza rifiuti | 32K | sì, proiettore BF16 su RAM |

Il profilo Q5 è commentato nel file: a parità di VRAM costringe a 8K di contesto e
il guadagno non lo giustifica.

Tre modi per modificare le configurazioni:
1. **chiederlo in chat all'assistente** ("porta heretic a 32K") — ha gli strumenti
   per modificare il file, e llama-swap ricarica da solo
2. il **pannello web** su `127.0.0.1:8012/ui`: log dal vivo, caricamento manuale
3. modificare a mano il file, che è commentato in italiano

## Temi e aspetto

Il tema non sta in Settings: è un modale a parte (icona in sidebar, o `/theme`).
Variabili CSS su `document.documentElement`, dichiarate in `static/style.css`. Le
fondamentali: `--bg`, `--fg`, `--panel`, `--border`, `--red`.

16 temi predefiniti, massimo 8 personalizzati. Persistenza in localStorage con
copia sul server: il tema è **per utente**.

Font personalizzati: file in `static/fonts/custom/`.

**CSS o JavaScript personalizzati: non supportati.** Non esiste alcun meccanismo
di iniezione. Per andare oltre le variabili bisogna editare `static/style.css`,
cioè modificare il core (che è quello che abbiamo fatto per l'avatar).

L'agente può cambiare tema da solo: azioni `set_theme` e `create_theme`.

**Appearance** in Settings è un'altra cosa: solo visibilità degli elementi
dell'interfaccia. È lì che abbiamo aggiunto le nostre due schede.

## Dove clicco

| Cosa | Percorso |
|---|---|
| Modelli per ruolo | Settings → AI Defaults |
| Giri massimi agente, limite strumenti | Settings → Agent Tools (admin) → card Agent |
| Strumenti integrati on/off | Settings → Agent Tools → Built-in Tools |
| Ricerca web | Settings → Search |
| MCP | Settings → Integrations → + Add Integration |
| Memoria e skill | modale Brain in sidebar |
| Personalità | barra chat → `+` → Prompt → Persona |
| Temi | icona tema in sidebar, o `/theme` |
| **Avatar e dispositivi audio** (nostri) | Settings → Appearance, in fondo |
| **Voce on/off** (nostro, riabilitato) | barra chat → `+` → Voce |

## Avvertenze verificate

- `agent_input_token_budget` e `agent_input_token_hard_max` **non hanno controlli
  nell'interfaccia**: solo API o file.
- `task_model` / `task_endpoint_id`: nessuna interfaccia.
- `teacher_model` / `teacher_enabled`: l'interfaccia è **codice morto**, cerca
  elementi che non esistono.
- **Voce**: la scheda TTS è nascosta di proposito e il codice STT punta a elementi
  inesistenti. Configurabile solo via API o file. (Il pulsante di accensione l'abbiamo
  riabilitato noi.) In più il menu a tendina della trascrizione **non conosce**
  il valore `stream`: sceglierne un altro da lì lo sovrascriverebbe.
- Le impostazioni skill nella modale Brain scrivono in `user_prefs.json` e
  **vincono** sulle globali.
- Nella cartella `docs/` originale non esiste documentazione sui temi.

## Riavvio completo dopo un riavvio del PC

```powershell
# 1. modello
d:\assistenteeee\scripts\start-llama-swap.ps1
# 2. memoria vettoriale
d:\assistenteeee\chroma-venv\Scripts\chroma.exe run --host 127.0.0.1 --port 8100 --path d:\assistenteeee\chroma-data
# 3. voce — il ponte carica Nemotron all'avvio (~5s, 680MB): e' voluto,
#    caricarlo pigramente farebbe perdere la prima frase della sessione.
d:\assistenteeee\scripts\start-voce.ps1
#    verifica: deve rispondere stream_disponibile e stream_caricato entrambi true
#    curl http://127.0.0.1:8013/health

# 4. ShadowBroker — dati. GT va passato al processo: dal .env NON funziona.
$env:GT_ANALYTICS_ENABLED="true"
$env:GT_ANALYTICS_ACK_LOW_CPU="true"
cd d:\assistenteeee\shadowbroker\backend ; .\venv\Scripts\python.exe main.py

# 5. ShadowBroker — cruscotto. Senza questa variabile Odysseus non puo'
#    incorporarlo: risponde X-Frame-Options: DENY.
$env:SHADOWBROKER_FRAME_ANCESTORS = "'self' http://localhost:7000 http://127.0.0.1:7000"
cd d:\assistenteeee\shadowbroker\frontend ; npm run dev:frontend

# 6. Odysseus
cd d:\assistenteeee\odysseus
.\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 7000
```

Avviarli **staccati** (`Start-Process -WindowStyle Hidden`) se si vuole che
sopravvivano alla chiusura del terminale.

### Per spegnere ShadowBroker

Non basta uccidere `main.py`: uvicorn con reload lascia figli
`multiprocessing.spawn` in ascolto sulla porta, e Windows lo permette senza
lamentarsi. Vanno uccisi anche quelli, altrimenti il riavvio successivo **parla
ancora col processo vecchio**.

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*shadowbroker\backend*" -or
                 $_.CommandLine -like "*multiprocessing.spawn*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### Manopole di ShadowBroker

| Variabile | Dove | Effetto |
|---|---|---|
| `SHADOWBROKER_FRAME_ANCESTORS` | processo frontend | chi può incorporare il cruscotto. **Mai `*`** |
| `GT_ANALYTICS_ENABLED` | processo backend | accende la classifica di rischio per regione |
| `GT_ANALYTICS_ACK_LOW_CPU` | processo backend | serve se il profilo runtime è "lean" |
| `OPENCLAW_ACCESS_TIER` | `backend/.env` | **`full`** dal 20 ago (era `restricted`): sblocca le scritture del canale OpenClaw — pin, watch, snapshot, inject — che le facciate `osint_sorveglianza`/`osint_storico` usano. In loopback l'auth è già bypassata, ma il **tier** è un gate a parte, quindi va messo esplicito |
| `SHADOWBROKER_URL` | processo Odysseus | dove sta il cruscotto (predefinito `:3000`) |
| `SHADOWBROKER_API_URL` | processo Odysseus | dove sta l'API (predefinito `:8000`) |
| `OSINT_MAX_CARATTERI` | processo Odysseus | tetto di una risposta OSINT (predefinito 21.600 ≈ 6k token) |

Chiavi API in `shadowbroker\backend\.env`, **ignorato da git**. Configurate:
OpenSky (voli globali) e aisstream (navi).
