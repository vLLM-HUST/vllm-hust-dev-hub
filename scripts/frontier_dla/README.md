# Matched native, BidKV and DLA curves (preparation)

The next TP2 campaign targets Qwen3.5-35B-A3B with unchanged SWE input IDs,
output budgets, 256K context capacity, MTP2, APC, async and graph execution.
All three arms use the same new core capsule. Each repeats26 retrieval probes,
a60s cache/protocol gate, then C1/C2/C4/C8/C16 for900s per cell.

DLA enables both the original selector through immutable request snapshots and
the full-sequence output-budget admission check. Because the workload declares
exact output budgets with ignore_eos, this campaign uses known budgets, not a
learned length predictor. The admission mechanism is a capacity check; it does
not exclusively hold future KV blocks across scheduler iterations. An exercised
check does not establish a beneficial performance effect, nor does it prove the
preemption selector was called. Counter receipts distinguish these mechanisms.

Pinned runtime commits are recorded in `prepare.py`. The core starts from the
previous common capsule77e6192; `core-output-budget.patch.gz` gives its exact
changes relative to752a3a5. Materialize `core/` from `git archive CORE vllm`, and
`plugin/` from `git archive DLA src` using those exact commits. Common Ascend
binaries and Python overlay remain the phase2 capsule; no running files change.

This directory is preparation, not a published result. The script refuses the
wrong container or occupied devices, verifies model/workload sources, and writes
`software_tests_passed=false`. Full runtime API/allocator/metrics integration
checks must pass before setting that receipt and launching supervised arms.
The current phase3 measurement must finish and release devices first. No
supervisor or server for this campaign has been started yet.

Software checks so far: core7 admission-boundary tests and all changed-file
pre-commit checks (including mypy); DLA21tests/1optional-predictor skip;
4counter-receipt tests. Hardware qualification and full runtime integration are
pending. Never import this preparation as leaderboard evidence.
