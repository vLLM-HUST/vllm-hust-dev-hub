# Qwen3.5 measured-series completion target

Date: 2026-09-30

## Objective

Replace accidental standalone presentation with evidence-backed measurement series. A line is
allowed only when every point has the same model, model revision, runtime pair, MOD source,
server configuration, workload protocol and session-rotation depth; concurrency is the intended
independent variable. Never run or relabel a point merely to make the chart look connected.

## Current audit

The Qwen3.5 SWE Prefix Reuse setting contained 175 visible points and 21 standalone points.

- Five Native Rotation2 observations already form one C2/C4/C8/C16 series, including two retained
  C16 repeats. Website PR #331 adds only the missing series identity. It changes no metric.
- Nine observations are historical smoke, capacity, MTP or topology experiments. They belong on
  precise setting pages and must not be completed against the unified Native series.
- Seven BetterScale observations are genuine one-point configurations: resident State C16; full
  and incremental cache at E16/R20 C16 D1; full and incremental cache at E16/R20 C16 D2; and full
  and incremental cache at E36/R36 C32 D1.

After the metadata repair, 16 standalone points remain. That number is an audit signal, not a quota
for arbitrary new runs.

## Experiment targets

### P0: metadata repair

- Connect the five existing Rotation2 observations by their measured campaign identity.
- Preserve both C16 repeats as independent observations.
- Expected display after deployment: 175 points, 35 measured-series lines, 16 standalone points.

### P1: BetterScale resident State D1

Produce a fresh C1/C2/C4/C8/C16 series from one clean source and one runtime contract. The existing
C16 observation remains immutable reference evidence and cannot complete a new-source series.

Before any NPU window, BetterScale must either:

1. pass a compatibility port against the unified runtime pair `d0f22d2` / `03766ac`, or
2. declare a separate source-pinned setting with its own freshly measured Native control series.

The existing BetterScale route is pinned to `752a3a5` / `9bf964c`; mixing those observations with
the unified Native control is prohibited.

### P2: BetterScale incremental-cache comparison

For E16/R20, measure full and incremental modes as paired arms at C1/C2/C4/C8/C16. D1 and D2 are
separate settings. Alternate arm order across concurrency points and preserve regressions. This is
20 formal windows after clean qualification, not a request to reuse the older C16 points.

### P3: capacity and topology settings

Move E36/R36 C32, TP8, TP8EP8, DP8EP8, MTP0 and historical capacity points to accurately named
setting pages. Add a capacity sweep only when its owner predeclares a valid concurrency range and
matching baseline. Do not manufacture a line solely to remove a standalone marker.

## Formal window contract

Unless a separate setting explicitly says otherwise:

- Qwen3.5-35B-A3B BF16, Ascend 910B2, TP2/PP1/DP1, expert parallel disabled
- `max_model_len=262144`, `max_num_seqs=16`, `max_num_batched_tokens=4096`
- APC and async scheduling enabled, Mamba cache mode `align`, native MTP with two draft tokens
- thinking enabled, temperature zero, graph mode `FULL_AND_PIECEWISE`
- 26,038,239,232 bytes KV cache per card
- `swe-prefix-reuse/v1`, prepared workload SHA256
  `8044561ffa1bb430bea8f778ef814d96649321e1a92654b95f64263b996d5e85`
- tokenizer fingerprint
  `3f9ca78537850303ee04bfa6640c020be89723c62f37121c0f27a4c0babc53e0`
- one cold-start 900-second measurement window per point; drain is recorded separately

Qualification and formal windows require all four visible NPUs to be free of unrelated experiment
load. Shared-load results remain diagnostic and are not published as formal measurements.

## Evidence gate

Every point must retain raw requests, token timestamps, throughput, per-user P90 decode speed,
correctness, APC and MTP counters, MOD control-action evidence, service logs, NPU state, window and
drain boundaries, exit/resource-release records and SHA256 manifests. A control path that did not
execute is marked `not-exercised`. Gains are computed from stored candidate and matching baseline
values; they are never typed as editorial numbers.

## Completion criteria

- Each published line passes the identical-setting audit above.
- The MOD repository contains the complete evidence before website import.
- Repository and browser CI pass, the website PR is merged, Pages reaches the merge commit, and
  production is checked in English/Chinese, desktop/mobile and light/dark modes.
