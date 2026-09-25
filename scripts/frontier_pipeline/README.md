# Additional Qwen3.5 MOD campaign: Pipeline Microbatch

Experimental qualification, **not yet a performance result**. No measured
Pipeline gain is currently certified by this capsule.

The fresh comparison uses Qwen3.5-35B-A3B, PP2×TP2 on four devices in the
user-provided Kubernetes container. It retains the prior SWE workload, BF16,
MTP2, APC, asynchronous scheduling, graph captures, 262144 context and explicit
26038239232-byte per-chip KV budget. Both arms must use identical common runtime
patches. Comparison against the previous TP2-only native score is not a matched
MOD speedup.

The plugin source is `a15a22961a0e4858da74a0ab806575c82cb254e6`.
Its host contract requires actual calibrated cost profiles for performance
claims. `pipeline_worker.py` collects rank-local event intervals only when
`FRONTIER_PP_CALIBRATION_DIR` is set. Timed Frontier windows must unset it.
`fit_calibration.py` requires all four ranks, complete execute/sample pairs,
at least40decode rows per rank, and chronological70/30holdout checks with
median relative error≤35% and P90≤75%. Fixed layer counts make three of the
six original features collinear; these coefficients are structurally zero.
Calibration includes communication and synchronization intervals and is not
an end-to-end performance score.

`qualify.py` must run under the exact dedicated supervisor config. It checks
source hashes, free participating devices and port, starts the owned server,
runs all26retrieval probes, optionally collects calibration, and stops the
server in an outer finally. Failed and interrupted attempts remain preserved.

Qualification findings:

- Original PP2 runtime, profiling on and off, failed the first1024-token
  retrieval (`cobalt-seven-7-42` instead of `cobalt-seven-42`).
- Traces showed MTP acceptance offsets lost when an empty/disjoint batch removed
  persistent rows. The common experimental backend now retains offsets by request
  identity and resets them on explicit finish/preemption/resume/new lifecycles.
- Earlier PP stages now consume final-stage accepted-token and valid-count feedback.
- An older intermediate-prefill output incorrectly released a newer final-prefill
  decode fence. Fence retirement now belongs to the exact scheduling output that
  established it, preserving chunked-prefill pipeline overlap.
- The combined correction passed all26retrieval probes in nativepp-r8, including
  cold/warm262080 and16concurrent requests. Cleanup verified no device owners.
  This is a narrow retrieval qualification, not a general quality certification.
- Candidate continuous batches additionally exposed stale nonfinal-stage draft
  slots and duplicate optimistic rejection correction. Earlier PP stages now
  scatter the actual scheduled drafts; fenced, already-retired output counts are
  authoritative. Asynchronous execution remains enabled.
- The combined backend passed all26 candidate retrieval probes in pipelinepp-r3.
  Nativepp-r12 recollected calibration on these exact common source bytes and
  passed all26 probes plus both calibration windows with zero request errors.
- Launchers explicitly source CANN and ATB environments. The supervisor controller
  waits up to30seconds for the exact owned Bash launcher to exec the vLLM command;
  foreign commands are rejected immediately.
- A source-only backend copy omitted wheel operator libraries and failed before
  requests. The repaired capsule preserves the complete qualified installed
  wheel; all7sharedlibraries match the baseline byte-for-byte.

`debug_worker.py` is diagnostic only. `qualify.py --measure` refuses debug and
profiling launchers, runs full retrieval followed by a60-second protocol check
and900-second C4/C16 windows, verifies prefix reuse, and requires actual policy
admission/completion counters without aborts, faults or builtin fallbacks.
Calibration and diagnostic artifacts cannot become Frontier points.

Current source manifests record experimental backports. The core adds neutral
batch-admission API support to pinned752a3a5. Because this older Request has no
in-flight token counter, snapshots derive it from EngineCore's queued actual
SchedulerOutputs. Forty targeted core tests and seven plugin tests passed.
No synthetic/balanced profile or failed qualification may be exported to the
Frontier data as a measured MOD point.

`core-qualified.patch.gz` and `ascend-qualified.patch.gz` are extracted from the
actual qualified runtime files, not a later reformatted checkout. The backend
includes the final continuous-batch fixes qualified in pipelinepp-r3. Apply them
to the pinned base revisions after preserving the complete installed backend
wheel artifacts. The core patch includes the common preemption/feedback changes
as well as neutral batch admission; do not apply the earlier campaign patches
again. Admission manifests hash every overlaid source file and all shared
libraries. A separately linted development core commit (`77e6192e7c`) includes
formatting and policy-metric variable renaming; it is not mislabeled as the exact
executed core source bytes.

`run_pair.py --gate ATTEMPT` requires a passed candidate qualification and
successful release, then starts each separately supervised measurement arm in
sequence. A failed native arm prevents starting the candidate. Both controllers
retain their own cleanup, and the pair controller stops an active child on
interruption. No server automatically restarts.

`import_website.py` admits only a completed pair with full retrieval, exact
900-second windows, four participating chips, no request errors, observed prefix
hits and actual candidate lifecycle counters. Failed attempts and calibration
records remain distinct from public performance points.

Final calibrated profile: `calibrated-profile-r12`. Each of four ranks supplies
2420 decode observations, with726 held out. Median relative errors are
3.589%,3.561%,3.399%,3.428%; P90 errors are7.311%,7.314%,8.005%,7.894%.
The profile constructor accepts the actual model and PP2×TP2 topology.
`calibrated-profile-r9` is retained as an earlier diagnostic profile and is not
used by the final measured launchers.

Development commits are published at core77e6192e7ce7947050f88306d0ae0e85ec864b75
and Ascend66350e7b7d8ec68ad68a14fb841678054f2c0f98. The included exact-source
patches and per-file manifest remain authoritative for the executed capsule.
