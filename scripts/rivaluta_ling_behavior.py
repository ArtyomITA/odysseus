r"""Rivaluta offline i JSON di prova_ling_behavior.py con le regole correnti del banco
(attese per lingua: `args_en`) e stampa un riepilogo per variante e per caso.

Serve quando una corsa e' partita con un valutatore piu' vecchio: le chiamate sono
salvate nel JSON, il giudizio si puo' rifare senza rifare le richieste al modello.

Uso: venv\Scripts\python.exe scripts\rivaluta_ling_behavior.py ricerche\ling-behavior-*.json
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import prova_ling_behavior as plb  # noqa: E402


def _case(case_id: str):
    for c in list(plb.CASES) + list(getattr(plb, "COMMUNICATION_CASES", ())):
        if c.case_id == case_id:
            return c
    return None


def rivaluta(row: dict) -> bool | None:
    case = _case(row.get("case", ""))
    if case is None:
        return None
    calls = row.get("calls") or []
    lang = row.get("language") or "it"
    if not case.should_call:
        return not calls
    if not calls:
        return False
    first = calls[0]
    name_ok = first.get("name") in case.expected
    args_ok = plb._arg_score(case, first.get("args") or {}, lang)
    exact = len(calls) == 1
    valid = all(c.get("valid_json", True) for c in calls)
    return bool(name_ok and args_ok and exact and valid)


def main(paths):
    rows = []
    for p in paths:
        data = json.load(open(p, encoding="utf-8"))
        rows.extend(data if isinstance(data, list) else data.get("rows") or [])
    per_var = collections.defaultdict(lambda: [0, 0])
    per_case = collections.defaultdict(lambda: [0, 0])
    per_suite = collections.defaultdict(lambda: [0, 0])
    cambiati = 0
    for r in rows:
        v = rivaluta(r)
        if v is None:
            continue
        if bool(r.get("correct")) != v:
            cambiati += 1
        for d, k in ((per_var, r.get("variant")), (per_case, r.get("case")), (per_suite, r.get("suite"))):
            d[k][1] += 1
            d[k][0] += int(v)
    print(f"righe {len(rows)} · giudizi cambiati dalla rivalutazione: {cambiati}\n")
    for titolo, d in (("PER SUITE", per_suite), ("PER VARIANTE", per_var), ("PER CASO", per_case)):
        print(f"== {titolo}")
        for k, (ok, n) in sorted(d.items(), key=lambda kv: -(kv[1][0] / max(kv[1][1], 1))):
            print(f"  {ok:>3}/{n:<3} {100*ok/max(n,1):5.1f}%  {k}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
