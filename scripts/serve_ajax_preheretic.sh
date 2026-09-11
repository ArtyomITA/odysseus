#!/usr/bin/env bash
# Run on Ajax. Pre-heretic BF16, four TP2 replicas; no weight modifications.
set -euo pipefail
export PATH=/home/pewds/qwen35-env/bin:/usr/local/bin:/usr/bin:/bin
export NCCL_P2P_DISABLE=1
# Installed FlashInfer sampling JIT fails against the installed CUB headers.
# vLLM's native sampler avoids that optional kernel compilation.
export VLLM_USE_FLASHINFER_SAMPLER=0
exec /home/pewds/qwen35-env/bin/vllm serve \
  /home/pewds/odysseus-backups/pre-heretic-control-20260908 \
  --served-model-name odysseus-qwen3.5-tools-pre-heretic \
  --host 0.0.0.0 --port 19184 --dtype bfloat16 \
  --tensor-parallel-size 2 --data-parallel-size 4 --data-parallel-size-local 4 \
  --distributed-executor-backend mp --disable-custom-all-reduce \
  --gpu-memory-utilization 0.9 --max-model-len 16384 --max-num-seqs 8 \
  --enforce-eager --trust-remote-code --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder --limit-mm-per-prompt '{"image":3,"video":0}' \
  --gdn-prefill-backend triton --disable-log-stats
