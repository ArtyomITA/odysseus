# No-RAG clean loop: first diagnostic

## Setup

No live UI, service configuration, or weights changed. The standalone loop sends
conversation history, native assistant calls and matching tool results directly
to the served pre-Heretic model. It never rewrites queries, invents calls, swaps
families, or strips output. Invalid calls return errors. Six executions per turn
and seven model rounds bound the test.

Both arms use temperature 0, thinking disabled, 768 output tokens, and the
original tool-work evaluator's `tools_for_mode(..., 'compact_contract_v3')`.
This matters: the app's plain compact scrubber deletes descriptions, whereas v3
retains empirically tested micro-hints. Previous plain-compact tests were not
exact reproductions of the passing benchmark setup.

The 76 tools come from the current app's ten-family inventory, transformed by
the original v3 builder. This is not a byte-identical frozen 99-tool benchmark
inventory or proof of training-data identity. The report records schema and
builder hashes. No schemas are invented for this experiment.

- **Stable:** same compact inventory on every turn, irrespective of spelling.
- **Routed:** same loop, but existing `requested_capabilities` chooses inventory
  each turn. This isolates that selector; it is not the complete production RAG
  or Agent UI path. Other production normalizers are absent in both arms.
- Private records are synthetic. No real private dispatcher is imported.
  Only fixture reads and optional public SearXNG calls execute. Other operations
  return explicit errors, so this does not validate their functionality.
- Live search sends the exact model query to local SearXNG Bing/Yep, bypassing
  app query rewriting/filtering. Source results may vary between arms.

## Observations, not a blind score

| Case | Stable compact inventory | Selector arm |
|---|---|---|
| `whats the current stock mraket` | Selected `web_search`, query `current stock market` | Offered zero tools; declined live lookup |
| Exact seeded failed exchange, then `can you look up` | Searched with corrected query | Also searched with corrected query |
| Summarize search, explicitly no tools | Answered without tools or permission failure | Same |
| Calendar → email → calendar | Recalled second event at 14:30 | Same |
| Notes → second note → what does it say | Correct `view` ID and content | Same after fixture correction |
| Deliberately irrelevant search result | Did not automatically retry | Did not automatically retry |
| User asks for a better source | Refined and executed another search | Proposed search was not offered and was rejected |
| Web-disabled lookup | Attempted network access via bash; sandbox rejected it | Invented unsupported current market news without tools |

The initial stable stock answer listed sources, not current index values. It
does not establish that the market question was fully answered. Its subsequent
`can you look up` elicited clarification after it had already searched. The
separate seeded replay removes that differing-history confound.

The first notes fixture incorrectly accepted `get/read`, not the real `view`
action. Both models selected the correct action, but the fixture rejected it.
Those six original turns are invalid for execution comparison. A corrected
six-turn rerun succeeded in both arms; the failed evidence is retained.

Web-off results are a release blocker: removing named web tools alone does not
enforce network denial across general-purpose tools. The fixture prevented real
execution, but any UI integration must use the real cross-tool permissions and
clearly communicate unavailable capabilities. Neither arm is ready for a live
switch. Source recovery and grounded completion also remain weak.

## What this changes

There is direct evidence that the selector can withhold needed tools, and that
the model can repair the misspelled query itself when offered the tool. Clean
history also supports the tested topic switches without synthetic substitutions.
This supports continuing the clean-path experiment, not retraining or declaring
the UI fixed. Full inventory is slower in these requests; overlapping runs and
different source content prevent a controlled latency conclusion.

Next: integrate the clean loop behind a test-only UI profile with real permission
enforcement and one renderer, preserving the v3 contract. Test live read-only
follow-ups and explicit Web-off behavior before any rollout. Separately compare
a generic evidence-check/retry instruction on the weak-result fixture; do not
manufacture a retry query in the harness.

## Reproduce

Eight boundary tests pass:

```sh
/home/pewds/odysseus-cookbook-fresh/.venv/bin/pytest -q tests/test_clean_tool_loop.py
```

Run with a fresh report filename (existing evidence is never overwritten):

```sh
/home/pewds/odysseus-cookbook-fresh/.venv/bin/python scripts/test_clean_tool_loop.py --live-search --report reports/clean-loop-v3-new-run.json
```

Evidence:

- `reports/clean-loop-v3-20260909.json`: original 24 turns; notes fixture caveat above.
- `reports/clean-loop-v3-stock-seeded-20260909.json`: four matched seeded follow-up turns.
- `reports/clean-loop-v3-notes-fixture-corrected-20260909.json`: corrected six notes turns.

Each report retains model requests, responses, offered inventory and execution
results. The `completed` status means the request loop finished, **not** that
the answer passed functional evaluation. These are synthetic/public traces, not
private user conversations. This test does not measure UI rendering or streaming.
