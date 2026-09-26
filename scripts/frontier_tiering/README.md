# Managed Frontier KV Tiering campaign

Experimental Qwen3.5-35B-A3B TP2 qualification using the Extension Manager. This
campaign preserves the current Frontier model, BF16/auto KV dtype, 256K context,
APC, MTP2, async scheduling, graph buckets and explicit KV memory budget.

The first attempt stopped before readiness on the host connector's Tensor-only
cache registration. Subsequent revisions add a plugin-owned Ascend connector
a synchronous copy worker for separate attention and recurrent cache views, explicit secondary-tier registration,
and adaptation to the frozen host file-mapping API.
`source-lock.json` pins that development revision; this is not a released feature
or a claimed speedup. Seven installed-wheel tests passed in the assigned container,
including real NPU round trips and actual-host segment file store/restore. Serving qualification remains an independent gate.

The scripts use the retained experiment capsule under
`/home/coder/frontier-mods-qwen35-20260925`. The model, workload, frozen phase4
manifest/launcher/metadata and exact pinned runtime must already be present.
Build the plugin wheel from its pin into a dedicated overlay environment; retain
previous environments unchanged. No shared host installation is altered.

`prepare.py` verifies frozen sources and the wheel test receipt before creating
an entirely new `phase6/serving-r4` directory. Copy qualify.py to
`phase6/qualify-managed.py`, and run_campaign.py/transfer_receipt.py to phase6 before
preparation. The resulting dedicated supervisor owns all controllers and services.
The pair controller runs the candidate first to detect any serving failure before
spending time on a new control. Tiering and Native
then run serially, each with 26 retrieval checks, a 60-second prefix-reuse gate and
C1/C2/C4/C8/C16 windows of 900 seconds. No automatic retry or eager fallback occurs.

Per-request streams, summaries, actual manager-child argv, source hashes, metric
snapshots and process-release receipts are retained. Transfer counters distinguish
store-only from observed restoration; neither establishes speedup or secondary-tier
activity. Publish only completed, released, qualified real observations. Container
placement is provenance, not a separate MOD.

Software controller checks: `python3 -m pytest scripts/frontier_tiering -q`.
