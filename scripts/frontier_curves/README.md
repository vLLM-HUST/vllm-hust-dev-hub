# Qwen3.5-35B-A3B curve completion

Extends the measured Pipeline Microbatch / native TP2 x PP2 comparison with
C1, C2 and C8, each one 900-second real-online window. The existing C4/C16
observations stay separately identified. No measurements are synthesized or
pooled. Same SWE workload, MTP2, APC, async scheduling, BF16 and graph modes.

Target: user-assigned evaluation container, UID
`19a77c6d-a27a-4c6e-b955-e016beca3a82`, four 910B2 devices, 128 GiB RAM limit,
SSH port 31769. Root is `/home/coder/frontier-mods-qwen35-20260925/phase3`.
`prepare.py` verifies the frozen phase2 capsule and all model files, creates
fresh metadata/receipts and a dedicated supervisor. Both measured arms repeat
all26 retrieval probes and the60s cache/protocol gate in this container.
Controllers run serially, enforce source and launcher identities, and stop owned
servers with device-FD release verification even on failure.

`deployed-controller-r1.tar.gz` contains the exact running controller bytes,
launchers, metadata and manifest. Readable Python sources subsequently received
formatting/unused-import cleanup only; the archive is authoritative for this
attempt. Runtime dependencies remain the pinned capsule documented under
`../frontier_pipeline/`, unchanged. No running files are overwritten.

At C1 the batch policy may legitimately abstain. The controller records
`not-exercised` instead of treating a zero-admission observation as a gain or
silently discarding it. Policy errors/aborts/invalid selections remain failures.

Initial software validation: 13 controller/release/policy tests. Active attempt:
`receipts/paired-curves-r1`, arms `nativepp-measured-r1` then
`pipelinepp-measured-r1`. These names are scoped to phase3; phase2 evidence is
unchanged. Publication requires completed raw windows, policy receipts and
verified release; preparing or starting this campaign is not a performance
result.

`catalog-coverage.json` retains all46 ecosystem entries, including bridge,
router and model-preparation entries that a runtime-component-only filter would
miss. Infrastructure is identified separately. Pending source audits are not
claimed as blockers or completed measurements. This is an in-progress coverage
ledger; completion requires actual curves or verified, specific impediments for
each applicable treatment.
