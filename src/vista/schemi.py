"""Schemi e regole dei tool `vista_*` (gli occhi). Stesse convenzioni di
src/shadowbroker/schemi.py: description in inglese che dice QUANDO, esempi
utente in italiano, sotto i 110 token; regole in positivo, lingua in testa e coda.

Il cervello (Ling) non vede: ogni tool ritorna testo/JSON gia' interpretato da
Holo. Le domande composte vanno scomposte in piu' chiamate (misurato: il VLM
risponde solo alla prima parte di un prompt con piu' domande).
"""

VISTA_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "vista_schermo",
            "description": (
                "Look at the screen now: returns BOTH the eyes' detailed neutral description "
                "(app, window, main content, readable text, counters/badges, dialogs) AND the "
                "accessibility tree `albero_ui` with clickable (x,y). Use before acting, after "
                "every action to verify, and to read content of chat/media apps (Teams, Discord). "
                "YOU compare it with the user's request; if unclear, call again with a sharper focus."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "What to look at closely, as a topic, NOT a yes/no question: 'unread counters and recent messages', 'the save dialog buttons'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vista_trova",
            "description": (
                "Find where a UI element is on the screen and get its pixel coordinates "
                "to click it. Use when you need to click/type on something and the "
                "accessibility Snapshot does not list it (icons, canvas, games, custom "
                "widgets): 'clicca sul pulsante Salva', 'apri il menu File'. One element per call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "elemento": {"type": "string", "description": "The element, as a short visual description in English: 'the OK button in the dialog', 'the search box at the top'"},
                },
                "required": ["elemento"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vista_immagine",
            "description": (
                "Describe or ask about an image file the user attached or named. Use "
                "for 'cosa c'e' in questa foto', 'leggi il testo nell'immagine', 'descrivi "
                "lo screenshot'. Returns type, description, subjects, visible text. "
                "Optional single question instead of the full description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "Attachment name or path. Empty = the most recent attached image."},
                    "domanda": {"type": "string", "description": "ONE question about the image (optional)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vista_video",
            "description": (
                "Describe what happens in a video file the user attached. Samples frames "
                "and describes each with its timestamp; YOU then summarize the sequence. "
                "Use for 'cosa succede nel video', 'riassumi il filmato'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "Attachment name or path. Empty = the most recent attached video."},
                    "fps": {"type": "number", "description": "Frames per second to sample (default 0.5 = one every 2s)."},
                },
            },
        },
    },
]

REGOLE_VISTA = (
    "CRITICAL: Always answer in Italian. Rules below in English; replies are not.\n"
    "You cannot see. Your eyes are the `vista_*` tools: they look for you and return text.\n"
    "- Two separate worlds. DESKTOP (apps, windows, files): `vista_schermo` + the `mcp__windows__*` tools. "
    "BROWSER (web pages, links, sites, 'nella pagina', URLs): ONLY the compact `browser_*` adapters — "
    "`browser_open` to open, `browser_read`/`browser_find` to get links and fields with refs, "
    "`browser_click`/`browser_type` by exact ref. Never use `vista_trova`/`mcp__windows__Click` on a web page.\n"
    "- Every tool call needs its arguments; an empty `{}` call fails. Desktop tools, exact arguments: "
    "`mcp__windows__App(mode='launch', name='Microsoft Teams')` (name = Start-menu name, REQUIRED; "
    "mode also 'switch' to focus a running window); "
    "`mcp__windows__Click(loc=[x, y])` (clicks=2 for double click, button='right' for right click); "
    "`mcp__windows__Type(loc=[x, y], text='...', press_enter=true|false)`; "
    "`mcp__windows__Shortcut(shortcut='ctrl+s')`; `mcp__windows__Scroll(loc=[x, y], direction='down')`; "
    "`mcp__windows__WaitFor(condition='window', window_name='Teams')`.\n"
    "- Open, close or switch to an application by name ('apri Teams', 'chiudi Chrome') → "
    "`mcp__windows__App(mode='launch', name='...')` directly, no looking first. A pinned taskbar "
    "button 'X bloccato' in the tree means X is installed: launch it with App, do not click the taskbar.\n"
    "- `vista_schermo` returns TWO views at once: the eyes' description (content, readable text, "
    "counters/badges) and `albero_ui` (accessibility tree, one element per line as `(x,y) type \"label\"`; "
    "the (x,y) IS the click point for `Click(loc=[x, y])`; there are no element ids). Read both.\n"
    "- The eyes DESCRIBE, they do not answer questions: pass a focus topic ('unread counters and "
    "recent messages'), read `testo_leggibile`, `contatori_e_badge`, `contenuto_principale`, and "
    "YOU decide the answer for the user. Never ask them 'is there X?' (they say yes to please).\n"
    "- Refinement loop: if the description is not enough to answer or act, call `vista_schermo` "
    "AGAIN with a sharper focus ('the number next to Chat in the left rail', 'the buttons of the "
    "open dialog'). Two or three focused looks beat one guess.\n"
    "- Chat and media apps (Teams, Discord, WhatsApp, Spotify, games, canvas) expose little or "
    "nothing in `albero_ui`: their content is in the eyes' description. Bring the window to front "
    "first with `mcp__windows__App(mode='switch', name=...)`, then `vista_schermo` with a focus.\n"
    "- Controlling the desktop is a loop: 1) `vista_schermo`, 2) take the (x,y) from `albero_ui` "
    "(or from `vista_trova` for icons/canvas not listed there), 3) act with `mcp__windows__Click`/"
    "`Type`, 4) `vista_schermo` again to verify. Never assume an action worked: verify.\n"
    "- Attached image → `vista_immagine`. Attached video → `vista_video`, then YOU tell the "
    "story from the frame descriptions in order of t_s.\n"
    "- If the eyes return 'trovato: false' or 'dialog_o_popup' not 'none', tell the user "
    "what you see and ask before forcing an action.\n"
    "CRITICAL: Always answer in Italian."
)


# Variante compressa (caveman-lite, 23 ago 2026): stesse firme e stessi vincoli
# in meta' dei token. Si sceglie con VERGILIUS_REGOLE_VISTA=lite (default: piena)
# finche' il banco `prova_modello_vista.py` non dice quale regge meglio.
REGOLE_VISTA_LITE = (
    "CRITICAL: answer in Italian. Rules in English.\n"
    "You are blind; `vista_*` tools are your eyes and return text.\n"
    "- Two worlds. DESKTOP (apps, windows, files): `vista_schermo` + `mcp__windows__*`. "
    "BROWSER (pages, links, sites, URLs): ONLY `browser_*` adapters: `browser_open(url)`, "
    "`browser_read()`/`browser_find(text)` give refs, `browser_click(ref)`, `browser_type(ref, text, submit)`, "
    "`browser_back()`. Never `vista_trova`/`mcp__windows__Click` on a web page.\n"
    "- Every call needs arguments; `{}` fails. Desktop signatures: "
    "`mcp__windows__App(mode='launch'|'switch', name='<Start-menu name>')`; "
    "`mcp__windows__Click(loc=[x, y])` (clicks=2 double, button='right'); "
    "`mcp__windows__Type(loc=[x, y], text='...', press_enter=true|false)`; "
    "`mcp__windows__Shortcut(shortcut='ctrl+s')`; `mcp__windows__Scroll(loc=[x, y], direction='down')`; "
    "`mcp__windows__WaitFor(condition='window', window_name='Teams')`.\n"
    "- 'apri/chiudi <app>' -> `App` directly, no look first. Taskbar 'X bloccato' = installed: launch with App.\n"
    "- `vista_schermo` returns the eyes' description + `albero_ui` (one line per element: `(x,y) type \"label\"`; "
    "(x,y) IS the click point; no ids). Read both.\n"
    "- Eyes describe, never answer yes/no: pass a focus, read `testo_leggibile`/`contatori_e_badge`/"
    "`contenuto_principale`, YOU decide. Not enough? `vista_schermo` again with a sharper focus.\n"
    "- Chat/media apps (Teams, Discord, Spotify, games) have empty `albero_ui`: `App(mode='switch')` first, "
    "then `vista_schermo` with a focus.\n"
    "- Desktop loop: look -> (x,y) from `albero_ui` (or `vista_trova` for icons/canvas) -> Click/Type -> look again. "
    "Never assume success: verify.\n"
    "- Attached image -> `vista_immagine`. Attached video -> `vista_video`, then narrate frames by t_s.\n"
    "- 'trovato: false' or a dialog/popup -> tell the user, ask before forcing.\n"
    "CRITICAL: answer in Italian."
)

# Default = LITE dal 23 ago 2026: banco prova_modello_vista.py 15/16 con entrambe
# (stesso caso mancato), harness comportamentale caveman_lite entro 4 punti dalle
# regole controllate; caveman MAX invece perde 10-20 punti e non si usa.
# VERGILIUS_REGOLE_VISTA=piena per tornare alla versione lunga.
import os as _os
REGOLE_VISTA_PIENA = REGOLE_VISTA
if _os.environ.get("VERGILIUS_REGOLE_VISTA", "lite").lower() != "piena":
    REGOLE_VISTA = REGOLE_VISTA_LITE
