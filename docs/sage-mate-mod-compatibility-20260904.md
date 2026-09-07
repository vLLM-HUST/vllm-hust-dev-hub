# Sage Mate Mod compatibility candidate status (2026-09-04)

The exact target is Core `762f85b3` / `0.28.1rc1.dev319`, Ascend `4e57439e` /
`0.25.1rc1`, Qwen3.8-27B, Ascend TP4, graph mode. Legacy images, TP1 and eager
mode are not accepted as final qualification paths.

## Current status

| Mod | Source state | Runtime state | Compatibility verdict |
| --- | --- | --- | --- |
| BidKV | migrated to versioned preemption-policy API v1; bounded safe abstention replaces requester self-preemption; no runtime monkey patch | Current-main a4d6/2c8c TP4 graph: 5/13 Stage-1 cells and two alternating 3× A/B cells retained; graph/rank/policy/cancel/recovery gates passed, but corrected output gates need a fresh run | artifact functional-compatible for Qwen3.8-27B; ascending mixed is `inconclusive`; interactive c=8 is `not-beneficial-in-tested-cell`; eight cells remain pending and no whole-Mod effectiveness claim is allowed |
| DiffSpec | current Eagle3, Ascend attention, model runner, sampler and speculative metadata surfaces adapted | Qwen3.8-27B plus `VirVen/Qwen3.5-27B-EAGLE3-v2` passed TP4 FULL_DECODE_ONLY graph, four-rank draft loading, output, cancellation/recovery, concurrency and long-context gates | functional-compatible, but performance degraded (acceptance 19.29%; ~14.00 vs ~47.72 tok/s target-only P50) |
| LatchMoE | current MoE routing quantization and MLP-builder ABI adapted through seam v2 | Qwen3.8-27B is dense and Not Applicable; Qwen3-30B-A3B passed TP4 PIECEWISE graph, four-rank mapping, swap, 48/48 address checks, concurrency, cancellation and exception recovery | functional-compatible for Qwen3-30B-A3B, but performance degraded (~2.91 vs ~23.57 tok/s baseline) |
| Pipeline Microbatch | migrated from scheduler monkey patches to batch-admission policy API v1.1; current Scheduler/Request/queue/KV snapshots and Ascend Mamba KV group ABI adapted | Qwen3.8-27B passed PP2 × TP2 FULL_DECODE_ONLY graph, exact-output, cancellation/recovery and runtime-effective receipt gates on NPU0-3 | **not compatible** on the tested four-card configuration: uniform c=8 throughput -4.37%; fixed-work mixed c=8 throughput -26.33% and P95 latency +80.16% |

The target model config identifies `Qwen3_5ForConditionalGeneration` with a
hybrid GDN/full-attention text stack. Marketing/model-path naming must not override
the architecture and vocabulary recorded by the actual config.

## Lifecycle and evidence rule

`installed`, `configured`, `enabled`, and `runtimeEffective` are separate states.
Only the last state means the live worker and bounded inference request observed the
candidate. These runtime states are independent of artifact functional compatibility.
An uninstalled, disabled, or unobserved candidate is not thereby incompatible. Effectiveness
is classified per test cell only as `not-beneficial-in-tested-cell`, `inconclusive`,
or `beneficial`, with its configuration, workload, repetitions and intervals attached.

A qualifying run must retain exact source/image/model provenance, all four rank logs,
graph capture/replay evidence, bounded output comparisons, failure injection and
rollback/recovery records, and metrics. BidKV additionally needs policy call/selection/
failure counters. DiffSpec needs per-rank draft and accept/reject/KV metadata witnesses,
concurrent cancellation/recovery, acceptance rate, P50/P95 latency and throughput.
LatchMoE needs per-rank expert mapping, host/device swap witnesses and stable graph
addresses on its separate MoE model.
Pipeline Microbatch needs nonzero admission/completion receipts and must pass a
matched topology-specific performance gate; installation or functional execution
alone is insufficient.

## Resource gate

After explicit authorization, the campaign stopped the managed Sage Mate service and
used NPU0-3 for the TP4 runs. Native Engine reserved NPU4-7 remained excluded; the
campaign did not start, stop or configure its independently managed workload. Every launch used the managed service path; no TP1, eager or
legacy-image result was accepted. The original Qwen3.8-27B TP4 graph service was
restored after each Mod, returned HTTP 200 and finally produced `DIFFSPEC_ROLLBACK_OK`.

## Measured results

- BidKV bounded-preemption matrix: all five executed stage-one pairs were
  runtime/policy-safety clean. The cancellation cell completed four streams, cancelled four, then
  returned the exact recovery marker; the candidate made 218 policy calls with
  zero failures/invalid selections. In two ascending-mixed repeats that invoked
  the selector, both arms made 63 preemptions and candidate throughput deltas
  were +0.33% and +0.12%; the pre-fix -57.79% collapse did not recur. Because a
  third repeat did not invoke the policy, that cell is `inconclusive`. The
  interactive c=8 cell invoked the policy 24 times in every repeat and is
  `not-beneficial-in-tested-cell`: throughput delta mean -25.31% (95% CI
  -26.66% to -23.96%) and P95 latency delta mean +34.57% (95% CI +31.96% to
  +37.17%). The legacy warm-up forced generation past EOS and leaked special
  tokens identically in both arms; legacy long outputs retained only prefixes.
  Thus the corrected short exact and long semantic gates are pending, and long
  hash differences are not a candidate correctness failure because baseline is
  itself nondeterministic. Eight of thirteen Stage-1 cells have no real run and
  remain pending. These are cell-scoped results, not a compatibility verdict.
- LatchMoE Qwen3-30B-A3B: 10-request TTFT p50/p95 3.678/7.730 s,
  latency p50/p95 25.941/31.808 s, output throughput p50/p95 2.907/3.010 tok/s.
  The no-plugin baseline output throughput was about 23.57 tok/s.
- DiffSpec: final contract suite 26/26. Four ranks loaded the qualified draft and
  entered ACLGraph; 4/4 graph captures completed. Two 10-request suites were
  correct, four concurrent answers were correct, cancellation drained in 0.529 s,
  malformed-request recovery and a 5,425-token prompt passed. Draft/accepted
  counters were 534/103 (19.29%). Warm TTFT P50/P95 was 0.459/0.469 s, latency
  P50/P95 0.744/3.990 s, and output throughput P50/P95 14.00/14.24 tok/s versus
  target-only 47.72/56.97 tok/s; therefore the lane is not an acceleration recommendation.
- Pipeline Microbatch: the final candidate made 908 policy calls and recorded
  757 admissions plus 757 completions, with zero failures, invalid results or
  fallbacks. Five exact-output hashes matched baseline and cancellation recovery
  returned the expected marker. Uniform c=8 candidate throughput was 117.81 vs
  123.20 tok/s (-4.37%), with P50/P95 latency +1.92%/+0.89%. A fixed-work mixed
  c=8 test exposed the calibration failure: throughput 97.30 vs 132.07 tok/s
  (-26.33%), P50 -11.29%, but P95 +80.16%. The old PP4 × TP2 coefficients from
  Qwen3-32B/Qwen3-235B are therefore not valid evidence for Qwen3.8 PP2 × TP2.

## Candidate commits and publication gate

Machine-readable candidates are in
[`config/sage-mate-mod-candidate-lock.json`](../config/sage-mate-mod-candidate-lock.json).
The qualified commits have been pushed to the `vLLM-HUST` organization `main`
branches. BidKV main is `ba700cb69e`; DiffSpec main is `42e5909fc6`; LatchMoE
main is `9b2d4acdbf`. The generic contracts were merged through
[vLLM-HUST/vllm-hust#11](https://github.com/vLLM-HUST/vllm-hust/pull/11) and
[vLLM-HUST/vllm-ascend-hust#9](https://github.com/vLLM-HUST/vllm-ascend-hust/pull/9).
The exact hardware-tested bases and artifacts remain separately pinned in the
lock. No submission to `vllm-project` or `vllm-project/vllm-ascend` was requested
or made; their work is context, not a publication gate for organization repos.

Pipeline Microbatch remains on organization draft PRs pending human review:
[Core #12](https://github.com/vLLM-HUST/vllm-hust/pull/12),
[Ascend #10](https://github.com/vLLM-HUST/vllm-ascend-hust/pull/10), and
[Mod #4](https://github.com/vLLM-HUST/vllm-hust-pipeline-microbatch/pull/4),
with Mod Center activation in
[Extension Manager #4](https://github.com/vLLM-HUST/extension-manager/pull/4).
The Sage Mate `TP × PP = device count` launcher correction is
[RIDE-Lab/sage-mate#29](https://github.com/RIDE-Lab/sage-mate/pull/29).
Its runtime code is `7115254bca0a`, qualification metadata is `63bcab8f02d2`,
and candidate image ID is `sha256:934701650b9d...`. It must not be merged or
published as compatible until fresh rank-local calibration passes the matched
performance gate.

On 2026-09-05 the accidentally transferred BidKV repository was transferred
back intact from `Qixin-Gaoke` to `vLLM-HUST`. Its canonical repository is now
`https://github.com/vLLM-HUST/vllm-hust-bidkv`, and organization `main` resolves
to bounded-preemption qualification head
`ba700cb69ed5c84f012e5103eb115aa22cdbc1f5`; the exact hardware-tested runtime
tree is `199e0bdc6fc38fc9b14b626515efdcbf81de0b62`.
