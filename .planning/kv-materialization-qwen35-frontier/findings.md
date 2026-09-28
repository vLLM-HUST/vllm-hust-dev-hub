# Findings

## Environment

- Date: 2026-09-28 UTC.
- Host execution is the current evaluation container only.
- Four visible Ascend 910B2 devices: logical IDs 1, 5, 6, 7; all reported `Health OK`, zero AICore utilization, no running NPU processes.
- System memory: 2.0 TiB total, about 1.9 TiB available at inventory time.
- Root/model overlay: about 681 GiB free at inventory time; `/root` is a separate 98 GiB volume.
- CANN: `/usr/local/Ascend/cann -> /usr/local/Ascend/cann-9.1.0`.
- Python 3.12.13; torch 2.10.0+cpu; torch-npu 2.10.0.post4.
- `gh` is absent. Credentials exist in `/root/.env`, mode 0600; values were not printed.

## Model

- Path: `/models/modelscope_cache/Qwen/Qwen3___5-35B-A3B`.
- Size: about 67 GiB.
- Architecture: `Qwen3_5MoeForConditionalGeneration`; BF16; max position embeddings 262144; hybrid linear/full-attention model.
- The remote ModelScope revision file tree for `712cf74392b05026a6db2bf213d343747d1f6d45` was archived and all 27 locally present runtime files match its SHA256 values, including all 14 weight shards. `.gitattributes` is the only remote non-runtime file absent locally; no mismatches were found. Evidence: `/root/frontier-kvmat-runs/model-integrity-summary.json`.
- A compatibility symlink at `/workspace/models/Qwen3.5-35B-A3B` points to the same snapshot so the canonical prepared workload path reproduces the published tokenizer fingerprint.

## Runtime

- Current default imports resolve to `/vllm-workspace/vllm` and `/vllm-workspace/vllm-ascend`.
- Their observed HEADs were vLLM `0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665` and vLLM-Ascend `1cdb8c4db6e50f36f1fb3283b3e3dd618f6821e8`, so they are not acceptable for the unified run.
- Exact HUST source checkout: `/root/vllm-hust`, based on `d0f22d2bda562156e4dbf433ce645e1769b4f804`.
- Exact Ascend source checkout: `/root/vllm-ascend-hust`, HEAD `03766ac696fde5ab1980d80ca0b8543d3580c989`.
- The unified vLLM base lacked the scheduler-owned runtime seam. Generic carrier changes were forward-ported as commits `39f68ed4d1` and `667adc79cd` on branch `codex/kv-materialization-unified-seam`.
- Runtime seam test result: 3 passed. MOD test suite against these explicit source roots: 89 passed.
- Verified import origins are `/root/vllm-hust/vllm/__init__.py` and `/root/vllm-ascend-hust/vllm_ascend/__init__.py`.
- The exact Ascend checkout's 34 custom transformer operators were built for Ascend 910B2 and installed under the checkout. `libcust_opapi.so` SHA256 is `0584c942e4fc195417ab5eb7c5f415f5cf3873b2effa75078ec81f874790aba9`; `liboptiling.so` SHA256 is `bf671c4e7ccf94371a746e2d510c06c9b27d200393f3a9fa35fd623679b82da5`.
- The exact Python/C++ extension was separately built from the same checkout. `vllm_ascend_C` SHA256 is `7d20f75034dc44637d667673c0bda135ffcd58c237132a41ca4c5be8cd7c6147`; `libvllm_ascend_kernels.so` SHA256 is `d31cd01109d1714e821fc788b4ebef4aa60565684a85c18d770999544f3be4f0`.
- Import/registration qualification confirmed two container-visible devices map to physical devices 1 and 5, `enable_custom_op()` is true, and `npu_add_rms_norm_bias` is registered. The check process released all NPU resources.
- Four service attempts isolated environment issues without producing benchmark data: missing CANN Python path, an overwritten CANN path, incorrect use of physical device IDs in the container mask, and the absent exact custom-operator build. These are preserved as qualification failures, not combined or published.
- Subsequent pre-measurement attempts identified duplicate editable Bundle discovery, two missing unified-worker module paths, and a runtime-seam initialization bug. The first true request invoked the MOD controller and selected request-scoped recompute, then exposed that `KVCacheManager.hash_block_size` had not been retained by the forward port. Runtime commit `556671b117716300121b2ac78b112443b83d1958` fixes this and adds a constructor regression test; the focused suite passes 4 tests and Ruff.

## MOD Initial Audit

- Default branch HEAD at clone: `10428b81e2b383cdcb183d4548f38a98929fd0e4`.
- Maintainer is documented as Wei He (`healer-positive`); repository states it is maintained.
- Plugin entry point uses `vllm.general_plugins`.
- Controller action set: `full_reuse`, `partial_reuse`, `recompute`.
- Current runtime truth boundary: full reuse is anchor-scoped prefix-cache reuse; recompute is request-scoped bypass; partial reuse is block-aligned and may fall back. Exact token-level materialization is unavailable.
- Repository pins a carrier submodule commit `68b8be04493d39d5706f3d0d18f465f5eab947c4`; this differs from the unified runtime and must be audited rather than silently used.
- Historical M2 result is negative and explicitly stopped the mechanism direction. Applied action mixes may differ from engine realization; scheduler-owned counters are required before claiming realized reuse.
- The old plugin imported `vllm.entrypoints.openai.engine.serving`, removed in the unified base, so registration silently failed. The compatible serving/render surface is now used and covered by a registration test.
- The unified SWE client provides stable per-session `X-Correlation-ID` headers but not the historical `X-KV-*` request metadata. The MOD now uses that identity and exact prior prompt plus prior fixed output budget to infer the reusable prefix for closed-loop `ignore_eos` requests.
- Controller evaluation previously occurred twice for each request. The render-stage observation and exact plan are now recorded and reused for sampling parameters.
- MOD compatibility commit: `53a6b1130cbff58925782eb62d7e88cd37e4e20a` on `codex/qwen35-swe-compat`.
- A generic Extension Manager bundle manifest was added with no machine-specific paths. Manager resolves the extension as installed, discovered, compatible, configured, and enabled under explicit host version 0.25.1.

## Baseline Provenance

- Website series `swe-unified-native-20260927` was directly verified in `data/leaderboard_frontier.json`.
- Published Native output throughput: C1 91.54555555555555, C2 152.7211111111111, C4 217.47555555555556, C8 291.1066666666667, C16 359.75 output tok/s.
- Points use the required 900-second real-online contract, exact model/runtime revisions, and unified cohort. No Native rerun will be performed.

## Workload Provenance

- Canonical prepared file: `/root/frontier-kvmat-runs/prepared/qwen35.json`.
- SHA256: `8044561ffa1bb430bea8f778ef814d96649321e1a92654b95f64263b996d5e85`.
- Tokenizer fingerprint: `3f9ca78537850303ee04bfa6640c020be89723c62f37121c0f27a4c0babc53e0`.
- Contains 8 fixed sessions and 360 accepted turns under `swe-prefix-reuse/v1`.
- Transformers 5.17.0 is required to reproduce the canonical tokenization. An earlier 5.5.4 diagnostic artifact was retained separately and is not eligible for measurement.

## Experiment Data

- The accepted 60-second C1 qualification completed 7 requests with zero failures and 2,986 in-window output tokens. The strict client validated prompt-token echo, usage, `[DONE]`, length finish, and exact fixed output budgets on every request.
- Qualification controller actions: observed recompute 1, partial reuse 1, full reuse 5; effective recompute 1 and full reuse 6. The partial action fell back to full reuse because block-aligned partial reuse was dominated by full reuse.
- Scheduler-owned qualification evidence used the actual 2048-token hash block size, realized recompute on 5 lookups and partial reuse on 2, and recorded 6,144 reused versus 21,423 recomputed prompt tokens.
- The 26-request retrieval gate passed at prompt lengths 1,024, 8,192, 32,768, 131,072, and 262,080 plus 16 concurrent requests. This is correctness qualification only, not a performance result.
- The qualification service stopped, port 33783 refused connections, all four NPUs reported no running processes, and HBM returned to the idle floor.
- Formal C1 is complete and valid: 81,532 in-window output tokens, 90.5911111111111 output tok/s, P90 decode 107.36876391861011 tok/s/user, 147 completed requests, zero errors, one drained request, and 99.9332% full-concurrency residency.
- C1 controller evidence: 148 calls; observed actions recompute 6, partial reuse 3, full reuse 139; effective actions recompute 6 and full reuse 142. All three partial decisions explicitly fell back to full reuse because block-aligned partial reuse was dominated by full reuse.
- C1 scheduler-owned evidence: 148 lookups; realized recompute 22 and partial reuse 126; 2,406,400 reused versus 564,788 recomputed prompt tokens; 4,700 matched blocks; runtime hash block size 2,048. This proves the MOD was loaded, invoked, and exercised rather than silently behaving as Native.
- C1 clean release evidence confirms the server exited, port 33783 refused connections, no matching runtime processes remained, and all four NPUs had no running processes.
- Formal C2 is complete and valid: 139,256 in-window output tokens, 154.7288888888889 output tok/s, P90 decode 98.92568495208843 tok/s/user, 222 completed requests, zero errors, two drained requests, and 99.8618% full-concurrency residency.
- C2 controller evidence: 224 calls; observed actions recompute 8, partial reuse 3, full reuse 213; effective actions recompute 8 and full reuse 216. All three partial decisions explicitly fell back to full reuse because block-aligned partial reuse was dominated by full reuse.
- C2 scheduler-owned evidence: 225 lookups; realized recompute 30 and partial reuse 195; 5,117,952 reused versus 875,750 recomputed prompt tokens; 9,996 matched blocks; runtime hash block size 2,048.
- C2 clean release evidence confirms the server exited, port 33783 refused connections, no matching runtime processes remained, and all four NPUs had no running processes. The final evidence manifest contains 31 file hashes.
- The first C4 window was fully excluded because the source worktree was briefly changed during an attempted upstream merge. It is archived separately with an invalidation note and is not combined with any other window.
- Formal replacement C4 is complete and valid: 213,772 in-window output tokens, 237.52444444444444 output tok/s, P90 decode 84.76666140724171 tok/s/user, 349 completed requests, zero errors, four drained requests, and 99.7487% full-concurrency residency. Runtime HEAD and clean status were rechecked after the window.
- Replacement C4 controller evidence: 353 calls; observed actions recompute 12, partial reuse 6, full reuse 335; effective actions recompute 12 and full reuse 341. All six partial decisions explicitly fell back to full reuse because block-aligned partial reuse was dominated by full reuse.
- Replacement C4 scheduler-owned evidence: 356 lookups; realized recompute 45 and partial reuse 311; 9,091,072 reused versus 1,377,245 recomputed prompt tokens; 17,756 matched blocks; runtime hash block size 2,048.
- Replacement C4 clean release evidence confirms the server exited, port 33783 refused connections, no matching runtime processes remained, and all four NPUs had no running processes. The final evidence manifest contains 32 file hashes.
- Formal C8 is complete and valid: 293,176 in-window output tokens, 325.75111111111113 output tok/s, P90 decode 59.8154350121774 tok/s/user, 474 completed requests, zero errors, eight drained requests, and 99.7002% full-concurrency residency. Drain lasted 62.52 seconds and did not contribute tokens.
- C8 controller evidence: 482 calls; observed actions recompute 17, partial reuse 7, full reuse 458; effective actions recompute 17 and full reuse 465. All seven partial decisions explicitly fell back to full reuse because block-aligned partial reuse was dominated by full reuse.
- C8 scheduler-owned evidence: 490 lookups; realized recompute 66 and partial reuse 424; 10,987,520 reused versus 1,905,943 recomputed prompt tokens; 21,460 matched blocks; runtime hash block size 2,048.
- C8 clean release evidence confirms the server exited, port 33783 refused connections, no matching runtime processes remained, and all four NPUs had no running processes. The final evidence manifest contains 32 file hashes.
- Formal C16 is complete and valid: 372,863 in-window output tokens, 414.2922222222222 output tok/s, P90 decode 36.79618457742906 tok/s/user, 622 completed requests, zero errors, sixteen drained requests, and 99.6909% full-concurrency residency. Drain lasted 62.39 seconds and did not contribute tokens.
- C16 controller evidence: 638 calls; observed actions recompute 27, partial reuse 11, full reuse 600; effective actions recompute 27 and full reuse 611. All eleven partial decisions explicitly fell back to full reuse because block-aligned partial reuse was dominated by full reuse.
- C16 scheduler-owned evidence: 690 lookups; realized recompute 113 and partial reuse 577; 11,280,384 reused versus 2,775,821 recomputed prompt tokens; 22,032 matched blocks; runtime hash block size 2,048.
- C16 clean release evidence confirms the server exited, port 33783 refused connections, no matching runtime processes remained, and all four NPUs had no running processes. The final evidence manifest contains 32 file hashes.
- Candidate output throughput for C1/C2/C4/C8/C16 is 90.5911111111111, 154.7288888888889, 237.52444444444444, 325.75111111111113, and 414.2922222222222 output tok/s. Paired changes are -1.0425896032%, +1.3146694410%, +9.2189160468%, +11.9009450526%, and +15.1611458575%.
- The five-point geometric mean of candidate/native throughput ratios is +7.1301343328886935%.
- Every formal point exercised the controller and scheduler-owned runtime paths. The result is not `not-exercised`.

## Website Import

- Candidate series ID: `swe-unified-kv-materialization-arrival-control-20260928`; five point IDs are unique and carry exact real run IDs.
- `data/plugin-performance.json` schema is now `plugin-performance/v7`, using generic per-entry `observations` and explicit `default_observation_id`. The kv-materialization entry preserves the six historical Qwen2.5 comparisons while selecting the Qwen3.5 Frontier series for the all-model view.
- The model selector independently produces -0.419361310853994% for Qwen2.5-7B-Instruct and +7.1301343328886935% for Qwen3.5-35B-A3B. No gain is stored in the data file.
- The unified Native points carry an older model-manifest hash in their historical `checkpoint_revision` field and the equivalent prepared workload variant `aa23f49...`. The active cohort now documents an explicit verified model-identity alias and its already-documented structurally equivalent workload variants; arbitrary aliases remain rejected by tests.
- Public evidence is in `docs/FRONTIER-QWEN35-KV-MATERIALIZATION.md` and `docs/evidence/kv-materialization-qwen35-20260928/summary.json`; the SWE evidence ledger contains all five exact client summaries and metrics.
- Website validation after rebasing onto current main: Node 73/73; pytest 374 passed, 3 skipped; pre-commit passed every hook. Real Chromium validation passed English/Chinese, desktop/mobile, and light/dark combinations for both the plugin and Frontier pages.

## Remaining Performance MOD Audit

- DiffSpec commit `42e5909fc6fe276ba0defe1901257a523653aefb` qualifies Qwen3.8-27B + Eagle3, TP4, `FULL_DECODE_ONLY`, with APC and async disabled. Its speculative configuration replaces native MTP2, so it cannot preserve the unified contract. The finding and required MTP2-preserving next step were added to issue #1.
- vSpec commit `d4c4f659495826e64802eedb195de52019282b47` only has Qwen2.5 target/draft or Eagle evidence. Its mechanism replaces speculative decoding and has no Qwen3.5-35B-A3B native-MTP2 path. The finding was added to issue #1; the Qwen2.5-14B B128 result remains a separate offline observation.
- LatchMoE commit `bbc22d95d79407421b2aef338c77e25ce0766b02` explicitly rejects APC and constrains its SEW dataplane to PIECEWISE because `FULL_AND_PIECEWISE` is unsafe. Its qualified model/topology is Qwen3-30B-A3B TP4, not the hybrid Qwen3.5 TP2 lane. The finding was added to issue #4.
- Quantized KV Cache commit `ae7b44bfee695d0ba580040dffd10eb802104485` requires `--kv-cache-dtype int8`, while its Manager Provider cannot yet express that option and its public qualification covers Qwen2.5-14B TP1/short context rather than Qwen3.5 hybrid TP2/262K/MTP2. The activation and matched-control requirements were added to issue #2.
- Split-Batch commit `f77dc2214727ab1448874f1aee787a67328f1433` deliberately fail-closes any `speculative_config` as `speculative_decode_conflict`; its documentation states this is not MTP support and produces no cascade acceleration. The k+1-row/graph-bucket work needed for native MTP2 was added to issue #2.
- None of these five can currently run the exact unified contract through a minimal safe compatibility repair. No incompatible probe or fabricated Frontier point was created.
