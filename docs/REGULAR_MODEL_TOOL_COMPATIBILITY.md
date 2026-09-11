# Regular-model tool compatibility

Last verified: 2026-09-09 through the authenticated 7011 Agent UI as
`sft_alex_creator`.

This is the legacy-RAG track. The exact model
`odysseus-qwen3.5-tools-pre-heretic` is excluded and remains on its model-owned
clean compact runtime.

## Current baseline

| Endpoint | Model | Ten-family result | State |
|---|---|---:|---|
| DeepSeek | `deepseek-v4-flash` | 10/10 | passed |
| DeepSeek | `deepseek-v4-pro` | 10/10 | passed |
| OpenAI | `gpt-5.5` | 10/10 | passed |
| OpenAI | `gpt-5.6-sol` | 10/10 | passed |
| OpenAI | `gpt-5.6-terra` | 10/10 | passed |
| OpenAI | `gpt-5.6-luna` | 10/10 | passed |
| OpenRouter | `moonshotai/kimi-k3` | 10/10 | passed |
| OpenRouter | `x-ai/grok-4.5` | 10/10 | passed |
| OpenRouter | `qwen/qwen3-vl-235b-a22b-instruct` | 10/10 | passed |
| OpenRouter | `openai/gpt-5-image` | n/a | image generation; chat tools unsupported |
| Local `100.69.120.65:8062` | `Qwen/Qwen3.5-9B` | not run | endpoint unavailable |
| Local `100.69.120.65:8062` | `GLM-5.3-Flash-Alis-MLX-4bit` | not run | endpoint unavailable |

The ten-family baseline covers one read-only functional turn each for notes,
calendar, email accounts, tasks, documents, memory, skills, Cookbook/admin,
web search, and shell. It verifies the legacy route, expected native tool call,
execution result, visible UI answer, and absence of reasoning leakage. It is not
yet a claim that every mutation/action variant, typo, or follow-up passes.

## Typo and follow-up profile

The stricter real-UI profile sends one misspelled read-only request to every
family, followed immediately by a noun-free reference to the returned result.
Read-only follow-ups must not call any tool; search follow-ups may either use
the existing evidence or fetch the prior link. Across the nine chat-capable API
models, the composited post-repair result is **178/180 turns (98.89%)**:

| Model | Conversation result |
|---|---:|
| `deepseek-v4-flash` | 20/20 |
| `deepseek-v4-pro` | 20/20 |
| `gpt-5.5` | 20/20 |
| `gpt-5.6-sol` | 20/20 |
| `gpt-5.6-terra` | 20/20 |
| `gpt-5.6-luna` | 18/20 |
| `moonshotai/kimi-k3` | 20/20 |
| `x-ai/grok-4.5` | 20/20 |
| `qwen/qwen3-vl-235b-a22b-instruct` | 20/20 |

Luna's only remaining family miss is a deliberately misspelled Shell request.
The correct-spelling baseline passes. The harness does not auto-execute a shell
command to hide that model-owned limitation.

The shared repair recognizes a uniquely misspelled action verb and family noun,
then seals only declared safe private reads with immutable canonical arguments.
This repaired Tasks/Documents/Memory and adjacent read families across providers
without widening mutation or Shell authority. A compact native-tool instruction
also tells regular API models to map clear typos to a currently offered tool.

Conversation evidence:

- `reports/regular-model-conversation-flash-r3-20260909.json`
- `reports/regular-model-conversation-remaining-r1-20260909.json`
- `reports/regular-model-conversation-repair-r1-20260909.json`
- `reports/regular-model-conversation-shell-r1-20260909.json`
- `reports/regular-model-conversation-qwen-repair-r1-20260909.json`
- `reports/regular-model-conversation-qwen-tail-r1-20260909.json`
- `reports/regular-model-conversation-qwen-search-r1-20260909.json`

Evidence:

- `reports/regular-model-tools-provider-final-r4-20260909.json` — Flash, GPT-5.5, Kimi: 30/30.
- `reports/regular-model-tools-repair-r3-20260909.json` — Pro and Sol: 20/20; retained Qwen pre-final 9/10 miss.
- `reports/regular-qwen-vl-full-r4-20260909.json` — Qwen-VL final family-switch run: 10/10.
- `reports/regular-model-tools-remaining-20260909.json` — Terra, Luna, Grok: 30/30; records unavailable/unsupported models and pre-repair failures.
- `reports/regular-model-tools-postfix-r1-20260909.json` — post-hardening
  rerun: nine chat-capable API models passed 90/90 family turns with zero model
  failures. Its overall status is non-passing only because the two configured
  local endpoints were offline; the image-only model remains unsupported.

## Family switch and page inspection

The six-turn switch/back flow covers notes → calendar → notes from prior
evidence → web search → explicit `web_fetch` → calendar from prior evidence.
All nine API models have a clean 6/6 reproduction (**54/54**). Kimi skipped
search once in the retained first run and passed a fresh reproduction; that
variability remains visible instead of being erased.

Evidence:

- `reports/regular-model-switchback-flash-r2-20260909.json`
- `reports/regular-model-switchback-remaining-r1-20260909.json`
- `reports/regular-model-switchback-kimi-r1-20260909.json`

## Repair that produced the clean baseline

Regular models no longer inherit up to three stale tool families into every
explicit new request. Referential follow-ups still resolve from typed recent
tool evidence, while explicit family switches receive the current family only.
Safe required reads use `active_capabilities`, so stale offered context cannot
disable their immutable operation. The stream layer also stops an exact long
block repeated twice instead of waiting for a provider's full timeout.

The composer no longer treats generic words such as “source”, “system”, “app”,
or “review” as authority to silently enable Bash. Explicit shell, terminal,
repository, code-file, and direct coding requests retain workspace
auto-escalation. This is a shared UI authority fix, not a model-name exception.

Run a bounded subset with:

```sh
MODELS='deepseek-v4-flash,gpt-5.5' \
FAMILIES='notes,calendar' WORKERS=2 \
REPORT_PATH=reports/regular-model-check.json \
node scripts/verify_regular_model_tools.mjs
```

Set `PROFILE=conversation` to run the typo plus follow-up profile.

The runner discovers only enabled pinned models (visible cached local models
when no pins exist), retains no tool outputs or private rows, and deletes only
the exact sessions it creates.
