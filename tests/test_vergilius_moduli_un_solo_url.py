"""Vergilius fork invariant: no ES module specifier carries a ?v= cache-bust tag.

Vergilius fork: module specifiers carry no ?v= (one URL per module; static is
served no-cache + etag). Inconsistent ?v= values used to make the browser load
the same module two or three times under different URLs, each with its own
duplicated module state. Static files are served with Cache-Control: no-cache
plus an etag, so bare URLs revalidate themselves without needing a cache-bust
query string.

This test scans static/**/*.js, static/**/*.html and static/sw.js (excluding
any file whose name contains "-variants", which are intentional test/demo
pages) for the literal substring ".js?v=" and fails, listing every occurrence,
if any remain.
"""

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_NEEDLE = ".js?v="


def _iter_candidate_files():
    static_dir = _REPO / "static"
    patterns = ["**/*.js", "**/*.html"]
    seen = set()
    for pattern in patterns:
        for path in static_dir.glob(pattern):
            if "-variants" in path.name:
                continue
            if path in seen:
                continue
            seen.add(path)
            yield path
    sw_js = static_dir / "sw.js"
    if sw_js.exists() and sw_js not in seen:
        yield sw_js


def test_no_module_specifier_carries_a_v_cache_bust_tag():
    offenders = []
    for path in _iter_candidate_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if _NEEDLE not in text:
            continue
        rel = path.relative_to(_REPO)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if _NEEDLE in line:
                offenders.append(f"{rel}:{line_no}: {line.strip()}")

    assert not offenders, (
        "Found '.js?v=' module specifiers (Vergilius fork requires bare, "
        "un-versioned module URLs so the browser never loads a module twice "
        "under two cache-bust variants):\n" + "\n".join(offenders)
    )
