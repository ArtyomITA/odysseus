"""Banco diretto modalita' Vista: Ling sceglie il tool giusto fra gli occhi
(vista_*), Windows-MCP e browser? Stessa forma di prova_modello_finanza.py:
schemi reali + REGOLE_VISTA in coda al system, tool_choice auto, temp 0.2.

Non esegue i tool (gli occhi catturano lo schermo: un banco non deve
cliccare in giro). Misura la SCELTA. Il loop vero lo misura prova_e2e.

Uso: venv\Scripts\python.exe scripts\prova_modello_vista.py [modello]
"""
import json, sys, time, urllib.request
sys.path.insert(0, r"d:\assistenteeee\odysseus")
sys.stdout.reconfigure(encoding="utf-8")

LLAMA = "http://127.0.0.1:8012/v1/chat/completions"
MODELLO = sys.argv[1] if len(sys.argv) > 1 else "ling"
VARIANTE = sys.argv[2] if len(sys.argv) > 2 else "lite"   # lite (default) | piena

# Schemi MCP "finti" ma fedeli (nome nudo: nel loop sono mcp__<id>__Nome)
MCP = [
    ("mcp__windows__Snapshot", "Capture the UI accessibility tree of the active window: interactive elements with ids, text and coordinates. Use to find labelled buttons, fields, menus before clicking.",
     {"use_dom": {"type": "boolean"}}),
    ("mcp__windows__Click", "Click at screen coordinates.", {"loc": {"type": "array", "items": {"type": "integer"}}, "button": {"type": "string"}}),
    ("mcp__windows__Type", "Type text at screen coordinates (clicks first).", {"loc": {"type": "array", "items": {"type": "integer"}}, "text": {"type": "string"}, "press_enter": {"type": "boolean"}}),
    ("mcp__windows__Scroll", "Scroll at coordinates.", {"loc": {"type": "array", "items": {"type": "integer"}}, "direction": {"type": "string"}}),
    ("mcp__windows__Shortcut", "Press a keyboard shortcut like ctrl+s.", {"shortcut": {"type": "string"}}),
    ("mcp__windows__App", "Launch, switch to or close an application by name.", {"name": {"type": "string"}, "mode": {"type": "string"}}),
    ("mcp__windows__Screenshot", "Capture the screen as an image (only for vision models).", {}),
    ("browser_open", "Open a URL in the dedicated browser and return the page state with refs.", {"url": {"type": "string"}}),
    ("browser_read", "Read the current browser page: links, fields, headings with refs.", {}),
    ("browser_find", "Find text or an element in the current page; returns refs.", {"text": {"type": "string"}}),
    ("browser_click", "Click an element in the browser page by ref.", {"ref": {"type": "string"}}),
    ("browser_type", "Type into a browser element by ref.", {"ref": {"type": "string"}, "text": {"type": "string"}, "submit": {"type": "boolean"}}),
    ("browser_back", "Go back to the previous page.", {}),
]

def _mcp_schema(n, d, p):
    return {"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p}}}

# (domanda, accettabili, sbagliato)
CASI = [
    ("Cosa vedi sullo schermo adesso?", {"vista_schermo"}, {"mcp__windows__Screenshot", "vista_immagine"}),
    ("C'e' un popup o una finestra di errore aperta?", {"vista_schermo"}, {"mcp__windows__Screenshot"}),
    ("Che programma e' aperto in primo piano?", {"vista_schermo", "mcp__windows__Snapshot"}, {"mcp__windows__Screenshot", "vista_immagine"}),
    ("Clicca sul pulsante Salva.", {"mcp__windows__Snapshot", "vista_trova", "vista_schermo"}, {"mcp__windows__Screenshot"}),
    ("Trova l'icona della campanella in alto a destra e cliccala.", {"vista_trova", "mcp__windows__Snapshot"}, {"mcp__windows__Screenshot"}),
    ("Apri Blocco note.", {"mcp__windows__App"}, {"vista_trova", "vista_schermo"}),
    ("Scrivi 'ciao mondo' nel campo di ricerca.", {"mcp__windows__Snapshot", "vista_trova", "mcp__windows__Type"}, {"mcp__windows__Screenshot"}),
    ("Cosa c'e' in questa foto che ti ho allegato?", {"vista_immagine"}, {"vista_schermo", "mcp__windows__Screenshot"}),
    ("Leggi il testo nell'immagine allegata.", {"vista_immagine"}, {"vista_schermo"}),
    ("Cosa succede nel video che ti ho mandato?", {"vista_video"}, {"vista_immagine", "vista_schermo"}),
    ("Riassumi il filmato allegato.", {"vista_video"}, {"vista_immagine"}),
    ("Vai su wikipedia.org e cerca Roma.", {"browser_open"}, {"vista_schermo", "mcp__windows__App"}),
    ("Nella pagina del browser clicca sul link 'Storia'.", {"browser_read", "browser_find", "browser_click"}, {"vista_trova", "mcp__windows__Click"}),
    ("Quante finestre sono aperte e quale sta sopra?", {"vista_schermo"}, {"mcp__windows__Screenshot"}),
    ("Salva il documento con ctrl+s.", {"mcp__windows__Shortcut"}, {"vista_trova", "vista_schermo"}),
    ("Dopo aver cliccato, verifica che il file sia stato salvato.", {"vista_schermo", "mcp__windows__Snapshot"}, {"mcp__windows__Screenshot"}),
]

SISTEMA = ("Sei l'assistente di Vergilius. Puoi controllare questo computer e il browser, "
           "ma non vedi: i tool vista_* sono i tuoi occhi. Rispondi in italiano.\n")


def chiama(messaggi, strumenti):
    corpo = {"model": MODELLO, "messages": messaggi, "tools": strumenti, "tool_choice": "auto",
             "temperature": 0.2, "max_tokens": 400}
    req = urllib.request.Request(LLAMA, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode())


def scelti(r):
    msg = r["choices"][0]["message"]
    nomi = [(c.get("function") or {}).get("name") for c in (msg.get("tool_calls") or [])]
    return [n for n in nomi if n], (msg.get("content") or "").strip()


# Risultati finti ma realistici per il 2o giro: il loop vero e' "guarda, poi agisci".
FINTI = {
    "vista_schermo": json.dumps({"app": "Notepad", "finestra_attiva": "documento.txt - Blocco note",
                                 "tipo_contenuto": "editor", "elementi_principali": ["File menu", "Edit menu", "text area", "Salva button"],
                                 "dialog_o_popup": "none", "testo_in_evidenza": "documento.txt", "schermo": "1920x1080"}, ensure_ascii=False),
    "mcp__windows__Snapshot": "[1] button 'Salva' (812,433)\n[2] textbox 'Cerca' (640,150)\n[3] menu 'File' (20,40)\n[4] link 'Storia' (300,220)",
    "vista_trova": json.dumps({"trovato": True, "x": 1807, "y": 151, "larghezza": 1920, "altezza": 1080, "passi": 2,
                               "come_usare": "Click at x=1807 y=151 (screen 1920x1080)."}),
    "browser_read": "- link 'Storia' [ref=e12]\n- link 'Geografia' [ref=e13]\n- textbox 'Cerca' [ref=e2]",
    "browser_open": "Navigated to https://it.wikipedia.org/wiki/Roma",
    "mcp__windows__App": "Launched Notepad",
    "mcp__windows__Click": "Clicked at (812,433)",
    "mcp__windows__Type": "Typed.",
    "mcp__windows__Shortcut": "Pressed ctrl+s",
    "vista_immagine": json.dumps({"tipo": "photo", "descrizione": "A dog on grass.", "soggetti": ["dog"], "testo_visibile": "none", "luogo_o_ambiente": "park"}),
    "vista_video": json.dumps({"frame": [{"t_s": 0, "descrizione": "a man walks in"}, {"t_s": 2, "descrizione": "he sits down"}]}),
}

# Per il 2o giro: dopo il primo tool, quale tool (o nessuno = risposta) e' giusto?
SECONDO = {
    "Clicca sul pulsante Salva.": ({"mcp__windows__Snapshot", "mcp__windows__Click", "vista_trova"}, set()),
    "Trova l'icona della campanella in alto a destra e cliccala.": ({"vista_trova", "mcp__windows__Click", "mcp__windows__Snapshot"}, set()),
    "Apri Blocco note.": ({"mcp__windows__App", None}, {"vista_trova"}),
    "Scrivi 'ciao mondo' nel campo di ricerca.": ({"mcp__windows__Snapshot", "mcp__windows__Type", "vista_trova"}, set()),
    "Nella pagina del browser clicca sul link 'Storia'.": ({"browser_read", "browser_find", "browser_click"}, {"vista_trova", "mcp__windows__Click"}),
    "Dopo aver cliccato, verifica che il file sia stato salvato.": ({None, "vista_schermo", "mcp__windows__Snapshot"}, set()),
}


def main():
    from src.vista.schemi import VISTA_TOOL_SCHEMAS, REGOLE_VISTA_LITE, REGOLE_VISTA_PIENA
    REGOLE_VISTA = REGOLE_VISTA_PIENA if VARIANTE == "piena" else REGOLE_VISTA_LITE
    strumenti = list(VISTA_TOOL_SCHEMAS) + [_mcp_schema(*m) for m in MCP]
    sistema = SISTEMA + "\n" + REGOLE_VISTA
    print(f"modello {MODELLO} | regole {VARIANTE} | strumenti {len(strumenti)} (4 vista + {len(MCP)} PC/browser) | sistema ~{round(len(sistema)/3.6)} tok\n" + "=" * 96)
    g = a = x = z = 0; tempi = []
    for dom, ok, no in CASI:
        t0 = time.time()
        msgs = [{"role": "system", "content": sistema}, {"role": "user", "content": dom}]
        try:
            r = chiama(msgs, strumenti)
        except Exception as e:
            print(f" X  {dom[:56]:<58} {type(e).__name__}: {str(e)[:30]}"); x += 1; continue
        nomi, testo = scelti(r)
        catena = list(nomi[:1])
        # 2o giro: rispondo al tool e guardo la mossa successiva (max 2 passi)
        for _ in range(2):
            if not nomi: break
            tc = r["choices"][0]["message"].get("tool_calls") or []
            msgs.append(r["choices"][0]["message"])
            for c in tc:
                n = (c.get("function") or {}).get("name")
                msgs.append({"role": "tool", "tool_call_id": c.get("id", "x"), "content": FINTI.get(n, "ok")})
            try:
                r = chiama(msgs, strumenti)
            except Exception:
                break
            nomi, testo = scelti(r)
            catena.append(nomi[0] if nomi else None)
        dt = time.time() - t0; tempi.append(dt)
        primo = catena[0] if catena else None
        if primo is None:
            seg, txt = "-", f"NESSUNO (a memoria: {testo[:36]})"; z += 1
        elif primo in ok:
            seg, txt = " ", ""; g += 1
        elif primo in no:
            seg, txt = "X", "SBAGLIO primo passo"; x += 1
        else:
            # primo passo non atteso: accettabile se il 2o passo e' quello giusto (loop "guarda poi agisci")
            ok2, no2 = SECONDO.get(dom, (ok, no))
            seguito = [c for c in catena[1:]]
            if any(s in ok2 for s in seguito) and not any(s in no2 for s in seguito if s):
                seg, txt = " ", "(via loop)"; g += 1
            elif any(s in no2 for s in seguito if s):
                seg, txt = "X", "SBAGLIO al 2o passo"; x += 1
            else:
                seg, txt = "~", "ok-ish"; a += 1
        print(f" {seg}  {dom[:56]:<58} {dt:>5.1f}s  {' -> '.join(str(c) for c in catena)}  {txt}")
    print("=" * 96)
    print(f"  {g}/{len(CASI)} centrati - {a} accettabili - {x} SBAGLIATI - {z} senza strumento")
    if tempi:
        print(f"  tempo medio {sum(tempi)/len(tempi):.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
