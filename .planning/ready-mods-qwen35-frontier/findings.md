# Findings

## PegaFlow qualification

- Source: `vLLM-HUST/pegaflow-hust`
- Revision: `bf92464b91ec79c46c57b2d03851b51b2a0689d5`
- Runtime: vLLM `d0f22d2bda562156e4dbf433ce645e1769b4f804`,
  vLLM-Ascend `03766ac696fde5ab1980d80ca0b8543d3580c989`
- Manager: `701aa95a00d54de36a12d51b398620aa50ea3e54`
- PegaFlow Ascend server and Python wheel built successfully. Connector unit
  tests passed (271 passed, 15 skipped, 11 deselected); provider tests passed
  (5 passed).
- Manager inspect, configure, check, plan, render, enable, status and dry-run
  completed. The separately operated PegaFlow service reported healthy.
- Model and MTP weights loaded, async scheduling and FULL_AND_PIECEWISE graph
  compilation began, then EngineCore failed before `/health` became available.
- Root cause: `PegaKVConnector` is not a `SupportsHMA` connector. vLLM disables
  its hybrid manager, but Qwen3.5 attention and recurrent/Mamba cache specs
  cannot be collapsed to one type.
- Correctness boundary: scheduler code selects `blocks.get_block_ids()[0]`,
  `req.block_ids[0]` and `new_block_ids[0]`; intents contain one flat block-ID
  list; the worker load RPC applies that list to all registered layers. Merely
  declaring HMA support would risk restoring the wrong recurrent state.
- Existing PR #16 contains an older multi-group design but was closed for a
  cumulative-hash boundary collision. It also documents group_id > 0
  recurrent membership as fail-closed, so it cannot be used as qualification
  evidence for Qwen3.5.
- Maintainer follow-up:
  https://github.com/vLLM-HUST/pegaflow-hust/issues/28#issuecomment-5868490586

## Remaining published performance MODs

- ADM commit `16362b2d6c229ec1c900b87cdb2c974039db95a6`: mechanism replaces a
  data-parallel metadata collective. The unified contract is DP1, and the
  implementation explicitly calls Native at DP1. Its manifest requests TP4 /
  DP2 and its source fingerprint targets different runtime commits. It cannot
  produce an exercised unified DP1 observation.
- BetterScale: the documented supported Qwen path requires no MTP and a
  different worker/runtime envelope. MTP2 is immutable in this cohort.
- pipeline-microbatch-migration: mechanism requires PP2; cohort is PP1.
- vSpec and DiffSpec: replace the native speculative path; cohort requires
  native MTP2.
- LatchMoE: supported envelope rejects APC and FULL_AND_PIECEWISE; both are
  immutable.
- bidkv, DLA, kv-tiering-migration, Mooncake connector, KVCompress and
  kv-materialization already have unified Qwen3.5 series and should not be
  rerun merely to select a better point.

## Resource release

- Owned vLLM and PegaFlow processes were stopped after the failed
  qualification.
- All four NPUs report healthy with no running NPU processes.
- Qualification ports 33784, 50055 and 9091 no longer have owned listeners.

## Organization-wide current-head expansion

- The GitHub organization currently exposes 71 repositories. The earlier
  website-derived list was not a complete MOD inventory.
- The newly screened current heads and classifications are recorded in
  `docs/FRONTIER-QWEN35-MOD-COVERAGE.md` under the 2026-09-28 current-head
  delta section.
- `vllm-hust-legacy017-perf/async-output-row-deferral` is the only newly found
  candidate that preserves every immutable unified Frontier feature. A real
  60-second C1 qualification passed after a minimal current-ABI repair, with
  APC/MTP2 live and a nonzero runtime-effective counter.
- KVCompress 0.8 has advanced beyond the stale catalog rejection and supports
  the feature combination on a newer runtime, but its published C4 evidence is
  not cohort-compatible and the extension declares a different host line.
- FreshKV requires model-produced reuse declarations, request scope metadata,
  a named tool protocol and host hooks absent from the unified SWE contract.
  Its own README does not claim a general serving advantage over LRU.
- OPset, quantized KV and Tricard require a materially different configuration
  or topology; LatchMoE explicitly disables APC; ADM has no active mechanism at
  DP1; the remaining newly found carriers are tool/control-plane, import-only,
  or lack host integration.
- An independently owned StateAxis campaign is using the first device pair.
  It has been left untouched. Formal Frontier throughput must not be measured
  while that adjacent service can introduce shared-system interference.
