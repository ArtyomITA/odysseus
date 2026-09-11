# Search and compact-tool experiment — 2026-09-09

## Decision

Keep the normal routed profile on 7011. The all-tools compact experiment is
implemented but **disabled**: direct routing success did not translate into a
working Agent UI. Do not retrain or promote a profile on these measurements.

## Changes

- Short public-web lookups on the target model have an execution budget: two
  distinct token-normalized searches, one fetch, and up to three browser calls
  after the two searches. This bounds attempts, not just recovery prose. Existing
  permissions still apply; this does not make unavailable tools executable.
- Failed/weak searches reach the model for evaluation and query refinement,
  instead of the earlier unconditional terminal evidence veto. Some legacy
  heuristics and official-site shortcuts remain; this is not a completed rewrite.
- Search providers retain query/engine/date provenance. Unconfigured credentialed
  fallbacks are skipped. When SearXNG is the sole configured usable provider, Yep
  on the same instance is an additional fallback.
- An unavailable warm-only family no longer vetoes an otherwise ordinary reply.
- The all-tools experiment offers the trained compact inventory subject to
  permissions. It requires the exact test-owner environment flag and exact model
  match. The temporary service flag was removed after failed UI testing.

## Evidence and limits

| Measurement | Result | What it establishes |
|---|---|---|
| Focused Python regression suite | 401 passed | Covered policy, contract, provider and recovery-budget behavior |
| Direct family-only compact schemas | 10/10 tool routing | Small public smoke test, not functional or blind accuracy |
| Direct all-family compact schemas | 10/10 tool routing | Inventory did not break these first calls; roughly 3–4x slower in this run |
| Full compact Agent UI, revision 3 | All eight turns failed one or more checks | Not suitable for activation; leaks, duplicate/incorrect rendering or missing expected calls |
| Normal-profile final UI control | Five passed checks, two product failures, one capture error | Not accepted; suite status incomplete |
| Clean synthetic notes tool-result continuation | Clean answer with both schema sizes | Model can continue correctly on that isolated input, not proof that UI failure is solely harness |

Direct probes used temperature 0; the UI target-model sampling path can cap at
0.2. Prompts, history and tool-result serialization also differ. Match those
before attributing UI failures to weights versus harness. Existing UI checks are
not a grounded factual-answer benchmark. Unit tests are not UI acceptance.

Normal-profile control details: notes initial, both calendar turns, AI search
initial, and history initial passed the automated checks. Notes follow-up hit a
Playwright `Network.getResponseBody` capture error and is inconclusive. AI search
follow-up explicitly requested a summary with no tools, but the contract still
required `search_browser` and returned a permission failure. The history search
follow-up failed the visible-leak check. These are separate from source relevance;
the earlier warm-only fix did not cover classification as an active requirement.
There is no matched pre-change control establishing a net improvement.

Provider isolation bypassed app relevance filters. Bing general often returned
broad or unrelated results despite the full query. Google/Mojeek returned no
results, DDG hit CAPTCHA, and Presearch timed out. Yep returned useful PostgreSQL
documentation, but was weak or empty for several other questions. Engine health
and source quality remain unresolved. Fallback cannot help when an earlier weak
result survives filtering; there is no claim of universal relevance here.

## Reproduce and inspect

- `scripts/audit_search_pipeline.py`: raw provider comparison, no model.
- `scripts/compare_compact_tool_inventory.py`: read-only model schema comparison;
  proposed calls are never executed.
- `scripts/verify_agent_turn_contract.mjs`: real 7011 Agent UI and persisted-history
  checks. Use the dedicated test account; reports can contain private tool data.
- `reports/search-provider-isolation.json`, `reports/search-yep-isolation.json`:
  public provider evidence.
- `reports/compact-inventory-ablation.json`: direct routing probe.
- `reports/full-compact-ui-audit-r3.json`: completed rejected UI experiment.
  Earlier experiment reports include an initialization error and an aborted run;
  do not combine them into an accuracy score.
- `reports/routed-control-ui-audit-final.json`: normal-profile control replay;
  eight attempts, incomplete because of the capture error; failures retained.

Focused suite:

```sh
/home/pewds/odysseus-cookbook-fresh/.venv/bin/pytest -q tests/test_turn_contract.py tests/test_turn_contract_integration.py tests/test_service_search_provider_guards.py tests/test_web_recovery_budget.py tests/test_tool_policy.py
```

UI replay (read-only prompts, creates test chats):

```sh
node scripts/verify_agent_turn_contract.mjs --families notes,calendar,search_ai,search_history --pairs notes:11,calendar:11,search_ai:11,search_history:11 --max-turns 8 --total-ms 360000 --turn-ms 45000 --report reports/routed-control-ui-audit-final.json
```

## Next discriminating test

Replay the same captured UI request directly, preserving sampling, compact
schemas, history and tool results. Then change one layer at a time. Separately
score retrieved-source relevance and supported answers. Replace failing generic
boundaries only when the replay identifies them; do not add rules for individual
user phrasings or treat successful tool routing as successful execution.
