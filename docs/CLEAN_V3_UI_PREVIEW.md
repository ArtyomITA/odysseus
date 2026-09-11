# Tools v3 — No-RAG preview

Select this endpoint in the 7011 model picker, with model
`odysseus-qwen3.5-tools-pre-heretic`. This endpoint owns its complete tool loop
and enters Agent mode server-side on every turn, including ambiguous follow-ups;
it does not depend on the legacy per-message intent classifier. Start a new chat
for an uncontaminated comparison. Enable Web for searches. Clean routing is
owned by the exact model identity, so both the normal `preheret` endpoint and
the `cleanv3` alias use this runtime. Every other model remains on legacy RAG.

Endpoint ID: `cleanv3`. Its base URL uses the same inference server's Tailscale
DNS name, `http://odysseus.tailb895f4.ts.net:18182/v1`, to distinguish it from
the original IP-address route when existing chats omit endpoint IDs.

## Implementation

- `src/clean_agent_preview.py` is a separate streamed native-tool loop, entered
  before legacy routing and substitutions. It uses real authenticated tool
  dispatch, the tool-work `compact_contract_v5` builder, temperature 0,
  and thinking disabled. No weights change or inference server was started.
- The offered tool inventory is stable except for permissions/toggles. Safe,
  explicit personal creates/updates are enabled for notes, tasks, calendar,
  memory, skills and documents. Destructive operations, shell/code, outbound
  email, browser interaction, deployment/admin changes and unrelated-family
  write substitution remain blocked. No tool or argument substitution is
  applied by the loop.
- Native calls and matching results persist in `clean_v3_turn` metadata so
  follow-ups use actual evidence. History retains at most eight complete turns,
  trimming oldest whole turns for size; individual outputs cap at 8000 chars.
- Real search still uses the existing search backend and its provider handling;
  this does not claim that provider quality or every backend transform is fixed.
- All routing, privileges and default settings outside this exact Odysseus model
  remain unchanged. The loop has six execution/eight-round limits.
- Write completion is evidence-bound: affirmative success text is replaced
  unless a private-write tool succeeded during the turn. Proposed call batches
  are policy-preflighted atomically, so a batch containing a blocked operation
  cannot partially execute before denial.

## Verification

399 focused Python tests passed after route integration. Browser runs r1/r2
accidentally exercised the old loop and are not preview evidence. The runner
now explicitly asserts `selection_mode=clean_compact_v3_preview`.

`reports/clean-v3-live-ui-r3-20260909.json` confirms the preview route, real notes
execution, correct repetition from history, successful search and no-tool
summary, plus visible incremental growth. Its notes assertions were for the
old routed contract: they prohibited offering web tools even with Web enabled,
and required another notes call for a verbatim repeat. The updated preview
checks permit stable offers and accept an exact match to the preceding saved
answer without re-execution; execution permissions are still asserted.

`reports/clean-v3-live-ui-r4-20260909.json` is the corrected four-turn check,
including notes with Web off and search with Web on: **4/4 passed**, with the
preview selection mode explicitly confirmed on every turn.
These are UI smoke tests, not all-family or factual-answer benchmark scores.

## Disable

Disabling only endpoint `cleanv3` removes the duplicate picker alias; it does
not disable this model-owned runtime. To roll back the runtime, revert the exact
model route in `routes/chat_routes.py`. Do not delete weights, adapters, or user
chats. The v3 schema builder dependency is
`/home/pewds/odysseus-tool-work/scripts/eval_alltools_unseen_compare.py` and its
schema-dropout helper; preserve those with this deployment.

## Expanded UI checks — 2026-09-09

24 additional turns completed through the preview: 23 automated passes and one
checker false alarm. The Cookbook follow-up correctly shortened the previous
six-server result to the first three requested names without another call. The
checker required either a fresh call or a verbatim repeat; manual inspection
confirmed the requested subset. Raw failure evidence is retained, not rescored.

Covered notes/misspellings/second-note selection, calendar/second-event time,
tasks, documents, memory, skills, Cookbook listing, misspelled search, and Web
toggle changes. Cross-family flows passed: Germany news → “whats my notes”,
notes → “seach current stock mraket news”, and calendar → “now show my noes”.
The model chose `current stock market news` itself. Every completed turn's
audit confirmed the preview mode. Search source factual accuracy is not graded
by this suite, and successful reads do not establish mutation coverage.

Email was separately attempted but the test guard stopped it because the
stable offered inventory exceeded its metadata-only verified scope. Email
therefore remains unverified in this expanded run; the guard was not weakened.
No production code, service settings or weights changed during these tests.

Evidence under `reports/`:

- `clean-v3-broader-ui-20260909.json`: 16 turns, 15 automatic passes, Cookbook caveat.
- `clean-v3-topic-switch-ui-20260909.json`: 6/6 passed.
- `clean-v3-second-note-ui-20260909.json`: 2/2 passed.
- `clean-v3-email-notes-ui-20260909.json`: blocked email attempt; notes not run in that file.

## Picker route fix

The previous tests selected sessions through the API, missing a real picker
bug: local entries were deduplicated by model ID, hiding alternative endpoints
with the same weights. The picker now uses endpoint+model identity for local
routes too, displays the endpoint name, and scopes its last-picked send override
to the current chat. `/api/sessions` returns owner-filtered endpoint identity
for unambiguous saved URLs, so reload labels do not depend on loading the model
catalog. Ambiguous identical URLs are not guessed.

The user-authorized chat `ec0683a2-015f-41d7-aa1f-34135c9640cb` was switched to
`cleanv3` using the authenticated session PATCH API; no messages were inserted
and no tool actions ran in that chat. Defaults and other chats were unchanged.

The runner's `--picker-route true` starts on the original route, clicks the
preview in the real picker, sends a greeting, reloads the chat permalink, then
asks for notes. Early picker/reload reports are incomplete, not passes: their
label check exposed the unloaded-catalog issue. Focused route/picker/history
tests: 16 passed.

Final picker test: `reports/clean-v3-picker-reload-r5-20260909.json`, **2/2
passed**. Real picker click, greeting, permalink reload, and notes follow-up
all confirmed the preview route. The label survived reload. R4 retained a
history/DOM mismatch from sending before restored history was ready; the final
driver explicitly waits for the saved first answer to render before sending.
This does not claim a general fix for sending during unfinished history loading.

## Native image/VL status

The inference launcher previously set `--limit-mm-per-prompt` to zero images,
so vLLM rejected attachments before the model saw them. The durable Odysseus
launcher now permits up to three images per prompt; video remains disabled.

`reports/clean-v3-vl-live-r4-20260909.json` proves the real 7011 attachment
path, clean compact route, object/color/spatial recognition, permalink reload,
and ambiguous image follow-up. Those checks pass. Exact OCR of the deterministic
`ODYSSEUS 42` heading fails in both the untouched Qwen 3.5 9B base and the
fine-tune, so it remains a base/runtime capability limitation rather than a
fine-tune regression or harness failure.

The same native path also passes JPEG and lossless WebP transport, object
recognition, reload, and follow-up grounding. Evidence:
`reports/clean-v3-vl-jpeg-r1-20260909.json` and
`reports/clean-v3-vl-webp-r1-20260909.json`. Both remain `partial` only because
the shared OCR check fails.

## Reversible write check

`scripts/verify_clean_v3_write.mjs` runs against only `sft_alex_creator`. It
creates one UUID-named note through the real 7011 UI, verifies that exact row,
requests a destructive bulk deletion, verifies the row still exists, and then
deletes only its own test row through the authenticated API. The cleanup is
verified by a 404 lookup.

Final evidence: `reports/clean-v3-write-ui-r8-20260909.json`, **passed**. Both
turns reported `selection_mode=clean_compact_v3_preview`; creation executed via
`manage_notes(action=add)`, the destructive action did not execute, and the
canonical response was “No changes were made.” The earlier r3/r5 files are
startup/placement failures, while r4/r6/r7 retained genuine intermediate
harness and verifier failures; none should be interpreted as passes.

## Stateful, search, and email checks

The reversible stateful runner passes all six mutation families in one run:
calendar, notes, tasks, documents, memory, and skills (**6/6**). Each flow
creates a UUID-only artifact through the real Agent UI, verifies it by
owner-scoped API, applies a noun-free correction, verifies persistence, and
removes only that artifact. A direct database audit found zero active synthetic
calendar, note, task, or document rows afterward.

The document failure was harness-owned. Compact description dropout left a
vague free-form `command` field, error envelopes defaulted to exit code 0, and
the clean loop dropped the active document ID. Compact v5 now exposes only
required structured `edits`, reports errors truthfully, and executes against
the request's explicit active document. Fresh document and combined stateful
runs pass.

Search Web-toggle combinations `00`, `01`, `10`, and `11` pass **8/8** across
two turns. A web question can no longer silently enable Bash because it says
“official source”, and an unavailable Web capability exposes no unrelated
fallback family. The quality suite passes **3/3**: evidence reuse without a
second call, explicit official-page inspection with `web_fetch`, correction of
“stock mraket” in actual search arguments, and a truthful unsupported result
for a synthetic company.

Production-path email reads pass **3/3** through the running email MCP: account
list, latest inbox list, and referential read of the first result. The report
retains no account names, addresses, subjects, bodies, prompts, or answers.

Post-fix representative direct/follow-up coverage also passes for every family:
notes/calendar 4/4, tasks/documents/memory/skills/Cookbook/search/shell 14/14,
and email 3/3 in its privacy-preserving runner. The combined legacy verifier's
metadata-only email guard correctly refused its broader stable inventory; that
stopped report is not counted as a model failure.

Evidence:

- `reports/clean-v3-stateful-all-r3-20260909.json`
- `reports/clean-v3-stateful-documents-r2-20260909.json`
- `reports/clean-v3-search-toggle-final-r6-20260909.json`
- `reports/clean-v3-search-quality-r3-20260909.json`
- `reports/clean-v3-email-read-r1-20260909.json`
- `reports/clean-v3-ten-family-tail-postfix-r1-20260909.json`

These checks verify routing, execution, persistence, follow-up, and selected
answer-quality invariants. They are not yet the sealed all-action ship score.

## Compact v5 and corrected contract evidence

Compact v5 keeps the compact-v3 surface and adds only development-positive
field hints for Email, Search/Hugging Face quant selection, and Shell/files.
A Calendar date hint regressed development and was excluded. The Python tool now
emits one final bare expression, REPL-style, without duplicating explicit
`print(...)`; this turns otherwise correct computation calls into visible tool
evidence for all models.

Under frozen scorer `odysseus.contract.v2.5`, development is 327/344 raw
(95.06%) and 327/336 scorable (97.32%). Sealed blind is 311/344 raw (90.41%)
and 311/336 scorable (92.56%), with zero reasoning leakage. Calendar, Shell,
and Tasks remain below the 90% family ship floor, so the model is not yet a
full benchmark ship candidate.

Fresh post-deploy real-UI evidence passes: stateful flows 6/6, Email 3/3,
Search quality/recovery 3/3, private browser 3/3, and VL workflow 3/3. The
Search check accepts a failed attempt only when a later tool succeeds and the
final answer remains grounded.
