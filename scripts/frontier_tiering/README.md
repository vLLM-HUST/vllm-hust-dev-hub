# Managed Frontier KV Tiering campaign

Experimental Qwen3.5-35B-A3B TP2 qualification using the Extension Manager. This
campaign preserves the current Frontier model, BF16/auto KV dtype, 256K context,
APC, MTP2, async scheduling, graph buckets and explicit KV memory budget.

The first attempt stopped before readiness on the host connector's Tensor-only
cache registration. Subsequent revisions add a plugin-owned Ascend connector
a synchronous copy worker for separate attention and recurrent cache views, explicit secondary-tier registration,
and adaptation to the frozen host file-mapping API.
`source-lock.json` pins that development revision; this is not a released feature
or a claimed speedup. Ten installed-wheel tests passed in the assigned container,
including real NPU round trips and actual-host segment file store/restore. Serving qualification remains an independent gate.

The scripts use the retained experiment capsule under
`/home/coder/frontier-mods-qwen35-20260925`. The model, workload, frozen phase4
manifest/launcher/metadata and exact pinned runtime must already be present.
Build the plugin wheel from its pin into a dedicated overlay environment; retain
previous environments unchanged. No shared host installation is altered.

`prepare.py` verifies frozen sources and the wheel test receipt before creating
an entirely new `phase6/serving-r8` directory. Copy qualify.py to
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

The serving-r4 and r5 candidates failed warm-8192 marker retrieval
(48 token-ID-zero outputs); the matching r4 Native passed all 26 probes. No
performance window ran. r5 counters recorded stores but no external restores.

serving-r6 applies the three-file Host fix pinned in source-lock.json to a fresh
copy of the runtime, shared by both arms. Independent hybrid-group cache hits now
require an explicit connector capability: NIXL restores missing recurrent state,
whereas Tiering must start from the ordinary all-group local cache boundary.
The original capsule stays immutable, and preparation verifies every copied file
against either its original hash or the explicit patch hashes. Copy
core-patch-r6.json and the patched core-r6 tree before running prepare.py.
Diagnostics are disabled for r6. Qualification still gates all performance windows;
starting the campaign does not establish either correctness or performance.

serving-r6 passed the formerly failing warm-8192 probe but stalled on an async
secondary lookup before any performance window. A deterministic regression
reproduced both HIT and MISS results remaining unconsumed after an early retry.
serving-r7 uses the corrected plugin (drain completed results on every retry),
retains core-r6 unchanged, and uses a fresh environment and secondary store.

serving-r7 passed all 26 retrieval probes and prefix reuse (118,784 hit tokens).
Its partial C1 window was stopped to fix the collection script: the host declares
counter families before their first labelled sample. An empty declared family is
zero activity; a missing family remains an error. The corrected serving-r8 uses
the same runtime/environment, has passed both qualification gates, and is running
the complete pair. Earlier partial windows are not Frontier points.

After both arms finish and release their devices, copy the complete serving-r8
capsule locally and import with:

```sh
python3 scripts/frontier_tiering/import_results.py \
  --artifacts /path/to/serving-r8 \
  --site /path/to/website \
  --evidence-url https://github.com/vLLM-HUST/vllm-hust-website/blob/main/docs/FRONTIER-KV-TIERING-20260926.md \
  --artifact-base-url https://vllm-hust.sage.org.ai/reports/frontier-managed-tiering-20260926
python3 scripts/frontier_tiering/render_report.py --site /path/to/website
```

The importer checks full matching configuration, 26 retrieval checks, prefix
reuse, all ten 900-second windows, raw streamed token counts and release receipts.
It archives compressed raw requests and full source metadata beside the site.
The renderer accepts only the complete pair. Review the rendered figure and the
interactive Frontier before publication; partial windows are never imported.

`collect_when_complete.py` can run under a local `Restart=no` user service with a
frozen source snapshot and an output manifest. It waits for the pair, downloads
only evidence (not the secondary cache), verifies all import gates, writes the
website artifacts and renders the measured plot. The service stops at
`ready-for-visual-review`; it does not commit or publish automatically. Its
manifest pins the collector source and the two website input JSON files, so
concurrent changes are rejected rather than overwritten. Downloaded request
archives retain both compressed-artifact and uncompressed-content SHA256 values.

Before publishing, independently recompute the plotted P90 decode rate and P95
TTFT with `verify_latency_metrics.py`. It derives each request's rate from its
first/last streamed token timestamps, excludes drained requests from latency
percentiles, uses the standard-library inclusive percentile calculation, and
also checks window token totals and mean in-flight concurrency. Pass the ten
`receipts/{native,tiering}-measured-r1/c{1,2,4,8,16}` directories and retain its
JSON output beside the published evidence.
