# KV Materialization Qwen3.5 Frontier Plan

## Constraints

- Execute only in the current 180-evaluation container; do not use SSH or a host environment.
- Use Qwen3.5-35B-A3B revision `712cf74392b05026a6db2bf213d343747d1f6d45`.
- Use vLLM `d0f22d2bda562156e4dbf433ce645e1769b4f804` and vLLM-Ascend `03766ac696fde5ab1980d80ca0b8543d3580c989` from source.
- Preserve BF16, TP2/PP1/DP1, APC, MTP2, async scheduling, FULL_AND_PIECEWISE, Mamba align, max model length 262144, max sequences 16, max batched tokens 4096, and per-device KV budget 26038239232 bytes.
- Use `swe-prefix-reuse/v1`, prepared workload SHA256 `8044561ffa1bb430bea8f778ef814d96649321e1a92654b95f64263b996d5e85`, tokenizer fingerprint `3f9ca78537850303ee04bfa6640c020be89723c62f37121c0f27a4c0babc53e0`, D1, and real HTTP requests.
- Reuse only the published unified Native baseline; do not run another Native.
- Formal candidate windows are C1/C2/C4/C8/C16, 900 seconds each, with complete raw evidence.
- Do not publish simulated, replayed, projected, smoke, short, stitched, or incomplete data.

## Phases

1. Environment, NPU, model, process, storage, and repository inventory.
2. Baseline/evidence and workload provenance audit.
3. MOD runtime seam, trigger, counters, manifest/provider, and compatibility audit.
4. Prepare exact runtime commits and Extension Manager lifecycle.
5. Qualification: model load, health, 60-second traffic, protocol checks, APC/MTP/async/graph/Mamba/MOD evidence, clean release.
6. Run C1, C2, C4, C8, C16 formal windows and hash all evidence.
7. Calculate paired geometric-mean gain from raw candidate and published Native points.
8. Update website data/UI/tests without overwriting the historical Qwen2.5 observation.
9. Push PRs, wait for relevant CI, merge, wait for Pages, and validate production in a real browser.
10. Audit remaining performance MODs lacking unified Qwen3.5 data and continue where configuration compatibility is exact.

## Error Log

- 2026-09-28: system Git HTTPS clones repeatedly failed with `gnutls_handshake() failed: The TLS connection was non-properly terminated`; HTTPS API/codeload remained healthy. Installed Dulwich and cloned over HTTPS without SSH.
- 2026-09-28: preinstalled `/vllm-workspace` source commits do not match the unified runtime base; isolated HUST source checkouts are required.
- 2026-09-28: the unmodified unified vLLM base lacked the MOD's scheduler-owned runtime-control seam. Forward-ported the two generic carrier commits onto the required base rather than using the historical carrier revision.
- 2026-09-28: an initial full MOD test run resolved vLLM from the preinstalled workspace and produced two expected seam failures. Re-running with explicit source paths resolved vLLM from `/root/vllm-hust` and passed all 89 tests.
- 2026-09-28: the first complete C4 window was invalidated because an attempted merge briefly changed the runtime source working tree during measurement. The merge was aborted, exact commit `556671b117716300121b2ac78b112443b83d1958` and a clean status were restored, all resources were released, and the whole window was archived as `C4-invalid-source-worktree-mutation-1`. No data from it was published or combined; the fresh-service replacement C4 completed successfully.
- 2026-09-28: website main advanced after the initial PR push and introduced ADM using the retired per-entry comparison fields. The branch was rebased, ADM was migrated to the generic observations schema, and the prohibition on stored/precomputed gain remained intact. Full Node, pytest, and pre-commit validation passed afterward.
