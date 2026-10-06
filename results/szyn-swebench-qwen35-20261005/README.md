# SZYN SWE-bench Verified 500, Qwen3.5 B0

This is an agent-resolution Dataset Matrix baseline, **not** a
`swe-prefix-reuse/v1` throughput Frontier point. The execution contract is
[`config/szyn-swebench-qwen35-execution-v3.json`](../../config/szyn-swebench-qwen35-execution-v3.json):
Qwen3.5-35B-A3B BF16, TP2, thinking off, fixed 500-task pool, unchanged
1800-second agent and grader limits, official SWE-bench images, and separated
root-only reference trees. The formal execution ID is
`szyn-qwen35-thinking-off-tp2-reference-separated-20261005`.

The selected result is **232 resolved / 500 tasks = 46.4%**. All 500 task
IDs have collection and grader terminal records. The pinned v3
[`summary-raw.json`](summary-raw.json) remains `publishable=false` because it
classifies one `grader_timeout` as infrastructure failure. No raw terminal,
original checkpoint, contract, or pinned summary script was altered to hide
that state.

The separately verified [`summary-adjudicated.json`](summary-adjudicated.json)
counts that one task as `unresolved` without changing the numerator or
denominator. [`timeout-adjudication.json`](timeout-adjudication.json) hashes two
unchanged-contract timeouts for `sphinx-doc__sphinx-7590`, its agent patch, and
an independent empty-patch control. The control used the identical official
image digest and native-proot backend and completed in 17.29 seconds; the
agent patch's added suffix loop instead consumes the parser's `EOF` sentinel
without terminating. The control is diagnostic only, not a model attempt.

The [evidence release](https://github.com/vLLM-HUST/vllm-hust-dev-hub/releases/tag/szyn-swebench-qwen35-20261005-attempt3-evidence)
holds 21 immutable checkpoint archives covering the fixed pool exactly once,
each with a SHA256 sidecar. The separate
`szyn-attempt3-500-adjudication-addendum.tar.gz` (SHA256
`0cd8a2013dced4c9b05895ff893240e398a2fc4c124beb97a53eeb9360532ef1`)
contains the newer selected timeout terminal, empty-patch control, raw and
adjudicated summaries, isolation/retry audit, and service/grader/NPU logs.
The original timeout also remains in checkpoint 0376-0400. Nine other
quarantined tasks were released only after current artifacts, first-attempt
archives, and isolation logs passed file-by-file validation; their selected
results are in checkpoint 0492-0500.

The raw 500-task status counts are 232 resolved, 144 unresolved, 53 invalid
patches, 67 agent timeouts, 3 agent errors, and 1 grader timeout. The
adjudicated counts are the same except 145 unresolved and no unclassified
grader timeout. This post-run causal adjudication is explicit so consumers
can choose to display the raw blocker alongside the B0 value.
