# Qwen3.5 unified Frontier: remaining performance MODs

## Contract

- Preserve the published Qwen3.5-35B-A3B unified configuration: BF16, TP2,
  PP1, DP1, APC, native MTP2, async scheduling, Mamba align,
  FULL_AND_PIECEWISE, 262144 context, 16 sequences, 4096 batched tokens and
  26038239232 bytes of KV cache per device.
- Reuse `swe-unified-native-20260927`; never run or select a MOD-specific
  Native arm.
- A MOD must pass a 60-second real-HTTP qualification, including mechanism
  counters and correctness, before any 900-second formal point.
- Do not turn a configuration-inactive mechanism into a claimed performance
  result.

## Phases

1. Screen remaining performance MODs against the immutable contract.
2. Run Extension Manager acceptance and a real service qualification for each
   eligible MOD.
3. For a compatibility failure, identify whether a small generic repair is
   safe; otherwise preserve the exact failure and contact the maintained
   repository.
4. Only after qualification, run C1/C2/C4/C8/C16 for 900 seconds each and
   publish the resulting candidate series.

## Current state

- PegaFlow and KVCompress have completed formal five-point campaigns, evidence
  merges, website publication and production verification. Do not rerun them.
- Legacy017 is deferred until its package is split into independently owned
  functional MODs.
- Organization-wide discovery covers all 71 repositories rather than only the
  website catalog. No newly updated MOD can immediately enter qualification.
- The nearest pending pair is PyramidKV PR #4 plus KVCompress PR #13. Their CPU
  contracts pass, but both PRs remain Draft and PyramidKV remains `import_only`
  with no activation entry point or fixed-host compatibility declaration.
- LatchMoE still conflicts with APC/MTP2; AQK remains gated by Draft host and
  activation work; ADM remains inactive at DP1; CLM remains a tool/control
  plane. These states are blockers, not zero or negative performance results.

## Error log

- 2026-09-28: first external PegaFlow start used physical device IDs `1,5`;
  PegaFlow expects logical IDs in the visible-device namespace. Retried with
  logical IDs `0,1`.
- 2026-09-28: Qwen3.5 EngineCore rejected the non-HMA connector with
  `ValueError: Hybrid KV cache manager is disabled but failed to convert the
  KV cache specs to one unified type.`
- 2026-09-28: Git smart-HTTP clone of the ADM repository repeatedly failed at
  the TLS handshake. Source audit used the GitHub API tarball pinned to commit
  `16362b2d6c229ec1c900b87cdb2c974039db95a6` without exposing credentials.
- 2026-09-28: an attempted formal async-output server on the first logical
  pair failed before readiness because an independently owned StateAxis run
  already held nearly all memory on that pair. No measurement window started;
  the process exited and its failure log was retained. The external run was
  not stopped or modified.
