# Additional Qwen3.5 MOD campaign: Pipeline Microbatch

Completed **real-online** matched PP2 campaign. All four 900-second observations
passed and both owned servers released their devices. Observed throughput changes
are +3.63% at C4 and −0.95% at C16; this single pair does not establish a consistent
or statistically significant speedup. See RESULTS.json and the public report.

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
at least 40 decode rows per rank, and chronological 70/30 holdout checks with
median relative error≤35% and P90≤75%. Fixed layer counts make three of the
six original features collinear; these coefficients are structurally zero.
Calibration includes communication and synchronization intervals and is not
an end-to-end performance score.

`qualify.py` must run under the exact dedicated supervisor config. It checks
source hashes, free participating devices and port, starts the owned server,
runs all 26 retrieval probes, optionally collects calibration, and stops the
server in an outer finally. Failed and interrupted attempts remain preserved.

Qualification findings:

- Original PP2 runtime, profiling on and off, failed the first 1024-token
  retrieval (`cobalt-seven-7-42` instead of `cobalt-seven-42`).
- Traces showed MTP acceptance offsets lost when an empty/disjoint batch removed
  persistent rows. The common experimental backend now retains offsets by request
  identity and resets them on explicit finish/preemption/resume/new lifecycles.
- Earlier PP stages now consume final-stage accepted-token and valid-count feedback.
- An older intermediate-prefill output incorrectly released a newer final-prefill
  decode fence. Fence retirement now belongs to the exact scheduling output that
  established it, preserving chunked-prefill pipeline overlap.
- The combined correction passed all 26 retrieval probes in nativepp-r8, including
  cold/warm 262080 and 16 concurrent requests. Cleanup verified no device owners.
  This is a narrow retrieval qualification, not a general quality certification.
- Candidate continuous batches additionally exposed stale nonfinal-stage draft
  slots and duplicate optimistic rejection correction. Earlier PP stages now
  scatter the actual scheduled drafts; fenced, already-retired output counts are
  authoritative. Asynchronous execution remains enabled.
- The combined backend passed all 26 candidate retrieval probes in pipelinepp-r3.
  Nativepp-r12 recollected calibration on these exact common source bytes and
  passed all 26 probes plus both calibration windows with zero request errors.
- Launchers explicitly source CANN and ATB environments. The supervisor controller
  waits up to 30 seconds for the exact owned Bash launcher to exec the vLLM command;
  foreign commands are rejected immediately.
- A source-only backend copy omitted wheel operator libraries and failed before
  requests. The repaired capsule preserves the complete qualified installed
  wheel; all 7 shared libraries match the baseline byte-for-byte.

`debug_worker.py` is diagnostic only. `qualify.py --measure` refuses debug and
profiling launchers, runs full retrieval followed by a 60-second protocol check
and 900-second C4/C16 windows, verifies prefix reuse, and requires actual policy
admission/completion counters without aborts, faults or builtin fallbacks.
Calibration and diagnostic artifacts cannot become Frontier points.

Current source manifests record experimental backports. The core adds neutral
batch-admission API support to pinned 752a3a5. Because this older Request has no
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
2420 decode observations, with 726 held out. Median relative errors are
3.589%,3.561%,3.399%,3.428%; P90 errors are 7.311%,7.314%,8.005%,7.894%.
The profile constructor accepts the actual model and PP2×TP2 topology.
`calibrated-profile-r9` is retained as an earlier diagnostic profile and is not
used by the final measured launchers.

Development commits are published at core 77e6192e7ce7947050f88306d0ae0e85ec864b75
and Ascend 66350e7b7d8ec68ad68a14fb841678054f2c0f98. The included exact-source
patches and per-file manifest remain authoritative for the executed capsule.

## Completed measurement

`paired-measurement-r2` completed native and Pipeline C4/C16 arms. The earlier
pair-controller attempt failed before either server started and remains archived.
Native output token/s/chip: C4=18.970277777777778, C16=24.79861111111111.
Pipeline: C4=19.65861111111111, C16=24.56277777777778. Every window is 900 seconds,
with zero errors. Pipeline admissions/completions are 13197 and 9036, respectively;
aborts/failures/invalid admissions/fallbacks are zero. Both services stopped with
exit status 0 and no remaining selected-device owners. All 720 raw requests meet
exact output-token budgets, including in-flight drains; their actual token IDs
are nonnegative. Drains are excluded from throughput.

Public report: https://github.com/vLLM-HUST/vllm-hust-website/blob/main/docs/FRONTIER-QWEN35-PIPELINE-K8S.md

For reproduction, preserve the frozen runtime and use a fresh output namespace.
Calibration requires a new writable `FRONTIER_PP_CALIBRATION_DIR`; collect actual
rank records with the common worker, fit/validate them, then qualify the candidate
with profiling unset. Never overwrite earlier receipts to reuse an attempt name.
The final measurement supervisor is launched using its absolute configuration
path. The `measure-pair` program invokes both separately supervised arm controllers.
Run the importer only after the complete pair and resource releases have passed.
