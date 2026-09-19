"""Calcolatrice generale per l'agente (19 set 2026).



Perche': un modello da 2-3B sbaglia l'aritmetica a piu' cifre (misurato: 3 x 309,48 = 284,39).

Lo strumento e' generale, non finanziario: vale per ogni profilo. Valuta espressioni con un

interprete AST a lista chiusa: niente eval, niente nomi liberi, niente attributi.

"""

from __future__ import annotations



import ast

import math

import operator

from typing import Any, Dict, List



_OP_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,

           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,

           ast.Pow: operator.pow}

_OP_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_FUNZIONI = {"abs": abs, "round": round, "min": min, "max": max, "sum": lambda *a: sum(a),

             "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp,

             "floor": math.floor, "ceil": math.ceil,

             "media": lambda *a: sum(a) / len(a),

             "percento": lambda parte, totale: parte / totale * 100,

             "variazione_percento": lambda prima, dopo: (dopo - prima) / prima * 100}

_COSTANTI = {"pi": math.pi, "e": math.e}

_MAX_NODI = 200

_MAX_ESPONENTE = 1000





def _normalizza(espr: str) -> str:

    """Accetta la scrittura italiana: 1.234,56 -> 1234.56 ; 0,92 -> 0.92 ; x e ÷ come operatori."""

    import re

    s = str(espr or "").strip().replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")

    s = re.sub(r"(?<=\d)[xX](?=\s*\d)|(?<=\d)\s+[xX]\s+(?=\d)", "*", s)

    s = re.sub(r"[€$£]|\b(?:eur|usd|euro|dollari)\b", "", s, flags=re.IGNORECASE)

    s = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"(\1/100)", s)

    # 1.234.567,89 oppure 1.234 (migliaia all'italiana, solo se i gruppi sono da tre cifre)

    s = re.sub(r"\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b", lambda m: m.group(0).replace(".", "").replace(",", "."), s)

    # dentro una chiamata di funzione la virgola separa gli argomenti: media(3,4,8) non e' 3.4.8
    s = re.sub(r"[a-z_0-9]+\([^()]*\)", lambda m: m.group(0).replace(",", ";"), s)
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    return s.replace(";", ",").strip()


def _valuta(nodo: ast.AST, contatore: List[int]) -> float:

    contatore[0] += 1

    if contatore[0] > _MAX_NODI:

        raise ValueError("espressione troppo lunga")

    if isinstance(nodo, ast.Expression):

        return _valuta(nodo.body, contatore)

    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)) and not isinstance(nodo.value, bool):

        return nodo.value

    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _OP_BIN:

        a, b = _valuta(nodo.left, contatore), _valuta(nodo.right, contatore)

        if isinstance(nodo.op, ast.Pow) and abs(b) > _MAX_ESPONENTE:

            raise ValueError("esponente troppo grande")

        return _OP_BIN[type(nodo.op)](a, b)

    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _OP_UN:

        return _OP_UN[type(nodo.op)](_valuta(nodo.operand, contatore))

    if isinstance(nodo, ast.Name) and nodo.id in _COSTANTI:

        return _COSTANTI[nodo.id]

    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id in _FUNZIONI and not nodo.keywords:

        return _FUNZIONI[nodo.func.id](*[_valuta(a, contatore) for a in nodo.args])

    raise ValueError("elemento non ammesso: solo numeri, + - * / // % **, parentesi e "

                     + ", ".join(sorted(_FUNZIONI)))





def _pulito(v: float) -> Any:

    if isinstance(v, float):

        if math.isnan(v) or math.isinf(v):

            raise ValueError("risultato non finito")

        v = round(v, 10)

        if v == int(v) and abs(v) < 1e15:

            return int(v)

    return v





def calcola(espressioni: Any) -> Dict[str, Any]:

    """Una espressione o una lista: ogni voce torna con il suo risultato o il suo errore."""

    voci = espressioni if isinstance(espressioni, list) else [espressioni]

    voci = [str(v) for v in voci if str(v or "").strip()][:20]

    if not voci:

        return {"errore": "nessuna espressione. Esempio: calcola(espressioni=[\"3 * 309.48\", \"81173.76 * 0.92\"])"}

    fuori = []

    for e in voci:

        try:

            albero = ast.parse(_normalizza(e), mode="eval")

            fuori.append({"espressione": e, "risultato": _pulito(_valuta(albero, [0]))})

        except ZeroDivisionError:

            fuori.append({"espressione": e, "errore": "divisione per zero"})

        except (ValueError, SyntaxError, TypeError, OverflowError) as ex:

            fuori.append({"espressione": e, "errore": str(ex)[:160] or type(ex).__name__})

    return {"risultati": fuori, "nota": "risultati esatti: riportali cosi', arrotonda solo in scrittura"}





async def _handler_calcola(content: Any, ctx: Any = None) -> Dict[str, Any]:

    import json

    args = content

    if isinstance(content, str):

        try:

            args = json.loads(content)

        except Exception:  # noqa: BLE001  testo nudo = una sola espressione

            args = {"espressioni": [content]}

    if not isinstance(args, dict):

        args = {"espressioni": args}

    esito = calcola(args.get("espressioni") or args.get("espressione") or args.get("expression"))

    testo = json.dumps(esito, ensure_ascii=False)

    return {"output": testo, "exit_code": 1 if "errore" in esito else 0}





CALC_TOOL_NAMES = frozenset({"calcola"})

CALC_TOOL_HANDLERS = {"calcola": _handler_calcola}

CALC_TOOL_SCHEMAS = [{

    "type": "function",

    "function": {

        "name": "calcola",

        "description": ("Exact arithmetic. Use it for any multi-digit computation: totals, differences, "

                        "percentages, currency conversion, averages. Pass every expression you need in ONE call. "

                        "Numbers come from tool results or from the user; this tool only computes."),

        "parameters": {

            "type": "object",

            "properties": {

                "espressioni": {

                    "type": "array", "items": {"type": "string"},

                    "description": ("Expressions with numbers and + - * / % ** ( ). Functions: round(x, n), "

                                    "abs, min, max, sum, sqrt, media(a, b, ...), percento(parte, totale), "

                                    "variazione_percento(prima, dopo). Example: [\"3 * 336.13\", "

                                    "\"81173.76 * 0.92\", \"variazione_percento(49.89, 50.45)\"]"),

                },

            },

            "required": ["espressioni"],

        },

    },

}]

