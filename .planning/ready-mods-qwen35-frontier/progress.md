# Progress

## Completed

- Audited and tested the PegaFlow Manager/provider path.
- Built and tested the Ascend PegaFlow service and connector.
- Started the exact unified Qwen3.5 runtime through Manager and captured the
  real hybrid-cache initialization failure.
- Audited the HMA contract, PegaFlow scheduler/worker block mapping, the
  closed multi-group PR and its correctness review.
- Added the reproduced failure and recommended repair boundary to existing
  maintained issue #28.
- Audited ADM and every other performance entry that lacks an eligible unified
  Qwen3.5 series.
- Released all owned service and accelerator resources.
- Expanded discovery from the website catalog to all 71 current organization
  repositories and classified the additional performance, separate-cohort,
  tool/control-plane, import-only and migration candidates.
- Ported `async-output-row-deferral` from the obsolete async output class to
  the actual Qwen3.5 MTP runner ABI, passed 71 repository tests and a real
  60-second C1 qualification, and added an opt-in atomic runtime counter
  snapshot for exact formal-window action counts.

## Formal windows

- None started for PegaFlow. Qualification failed before `/health`.
- None started for ADM. Under DP1 its optimized collective is unreachable by
  design, so it is not an exercised candidate under the immutable cohort.
- None started for async output deferral yet. Its qualification passed, but an
  unrelated long-running service remains active on another device pair; its
  throughput is excluded and formal runs wait for an interference-free host.

## Delivery

- PegaFlow follow-up comment:
  https://github.com/vLLM-HUST/pegaflow-hust/issues/28#issuecomment-5868490586
- No website change is warranted: there is no valid new five-point series.
- Next executable event is a PegaFlow general-connector repair that provides
  group-aware query/save/load semantics plus divergent-prompt and recurrent
  state restoration tests. The fixed configuration can then be retried
  without changing the workload or Native baseline.
