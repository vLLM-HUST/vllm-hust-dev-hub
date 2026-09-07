# BidKV effectiveness qualification protocol

Functional compatibility, live runtime state, and effectiveness are independent.
The exact Qwen3.8-27B Ascend TP4 graph artifact has already passed functional
startup, request, concurrency, cancellation/recovery and rollback gates. A live
instance separately reports `installed`, `configured`, `enabled`, and
`runtimeEffective`.

Effectiveness is never a whole-Mod boolean. Each row in
[`config/bidkv-tp4-graph-matrix.json`](../config/bidkv-tp4-graph-matrix.json)
binds the workload, concurrency, KV pressure, configuration, order and repeats.
Its only allowed conclusions are `not-beneficial-in-tested-cell`, `inconclusive`,
or `beneficial`. The declared Stage 1 matrix contains thirteen representative
cells. Five matched pairs were executed after resource and trigger admission;
the other eight remain explicitly pending because no retained real-online run
exists and current production/reserved-device protection prevents re-execution.
the ascending-mixed trigger cell and interactive c=8 cell then advanced to three
alternating matched repetitions and interval analysis. Empty summaries,
unpaired candidate-only runs and baseline-varying long hashes cannot support an
effectiveness claim.

Future runs use an exact short-text gate (EOS respected), retain full long
outputs for semantic and special-token checks, and measure determinism within
baseline and candidate separately. The retained legacy warm-up forced 16 tokens
with `ignore_eos=true` and leaked `<|im_start|>` in both arms, so that warm-up is
an invalid correctness workload rather than evidence of a candidate failure.
The legacy long runs retained only 120-character prefixes, so their semantic
gate is incomplete. Cross-arm long exact hashes are diagnostic only: in the
three-repeat interactive cell, baseline itself was deterministic for only 1/8
request indices and candidate for 0/8.

The runner must capture immutable image/source/model identity, the complete
non-secret configuration, all four rank graph markers, policy INIT and counters,
Prometheus before/after snapshots, request-level timings, cancellation drain and
recovery, and production restoration. NPU0-3 are the only authorized devices;
NPU4-7 are an immutable exclusion witness.

The bounded-selector implementation passed startup, graph/rank, policy-safety,
cancellation/recovery and rollback gates with zero policy failures or invalid
selections. The corrected exact/semantic output gates still require a fresh run.
The ascending-mixed cell is
`inconclusive`: one repeat never invoked the policy, while the two exercised
repeats were effectively neutral and no longer reproduced the pre-fix collapse.
The interactive c=8 cell is `not-beneficial-in-tested-cell`: mean throughput
delta was -25.31% (95% CI -26.66% to -23.96%) and mean P95 latency delta was
+34.57% (95% CI +31.96% to +37.17%). These outcomes do not alter the separately
passed functional-compatibility verdict.
