# Matched native, BidKV and DLA curves (preparation)

The next TP2 campaign targets Qwen3.5-35B-A3B with unchanged SWE input IDs,
output budgets, 256K context capacity, MTP2, APC, async and graph execution.
All three arms use the same new core capsule. Each repeats26 retrieval probes,
a60s cache/protocol gate, then C1/C2/C4/C8/C16 for900s per cell.

DLA enables both the original selector through immutable request snapshots and
the full-sequence output-budget admission check. Because the workload declares
exact output budgets with ignore_eos, this campaign uses known budgets, not a
learned length predictor. The admission mechanism is a capacity check; it does
not exclusively hold future KV blocks across scheduler iterations. An exercised
check does not establish a beneficial performance effect, nor does it prove the
preemption selector was called. Counter receipts distinguish these mechanisms.

Pinned runtime commits are recorded in `prepare.py`. The core starts from the
previous common capsule77e6192; `core-output-budget.patch.gz` gives its exact
changes relative to752a3a5. Provide `core-source.tar.gz` and `plugin-source.tar.gz` matching
`source-lock.json` (gzip with mtime=0 over `git archive CORE vllm` and
`git archive DLA src`). Preparation verifies and extracts these exact archives,
refusing existing source directories. Common Ascend
binaries and Python overlay remain the phase2 capsule; no running files change.

This directory is preparation, not a published result. The script refuses the
wrong container or occupied devices, verifies model/workload sources, and writes
`software_tests_passed=false`. Full runtime API/allocator/metrics integration
checks must pass before setting that receipt and launching supervised arms.
The current phase3 measurement must finish and release devices first. No
supervisor or server for this campaign has been started yet.

Software checks so far: core7 admission-boundary tests and all changed-file
pre-commit checks (including mypy); DLA21tests/1optional-predictor skip;
4counter-receipt tests. Hardware qualification and full runtime integration are
pending. Never import this preparation as leaderboard evidence.

`test_runtime_integration.py` exercises the real allocator for full-attention and
hybrid Mamba cache groups, the actual preemption controller and scheduler option.
It has been syntax checked but has not yet run in the target package environment.
Run CPU-only suites separately from live benchmark windows.

`run_campaign.py` runs Native, BidKV, then DLA serially under the dedicated
supervisor. It refuses an incomplete software-test manifest and stops after any
failed qualification, measurement, or device-release receipt. Each arm has a
16,000-second wall-clock deadline; no automatic restart or repeated observation
is enabled. Start `campaign` only after the runtime integration receipt is valid.
The controller and counter-receipt CPU suites pass (6 tests); these do not replace
the pending actual-runtime and hardware checks.

Preparation also pins the installed editable BidKV source path and every BidKV
Python file, plus the qualified Ascend binaries and common worker, in both the
manifest and per-arm metadata. Core metadata identifies the new full commit and
output-budget patch instead of inheriting the old PP2 core patch description.
A fixture preparation test verifies matched TP2/PP1, APC, async and MTP flags,
DLA-only admission flags, and those source records; it is not a hardware test.

After preparation and after all prior device owners release, run
`python verify_software.py` in the assigned container. It uses the generated
Native launcher's environment to execute the real runtime integration suite,
records its log/exit code, verifies source hashes before and after, and only then
sets `software_tests_passed=true`. This runner is prepared and syntax checked;
it has not been executed against the container yet.

`import_website.py` prepares a separate five-point series for each of Native,
BidKV and DLA only after all three actual arms pass and release their devices.
It validates raw streaming-window counts using two participating chips, compares
exact source records and normalized common launch arguments, and distinguishes
admission activity from preemption activity. It does not join historical TP2
controls that used a different core. No actual phase4 observations exist yet.
The preparation/import/controller/counter CPU checks pass (11 tests).

The source lock additionally pins all 65 installed BidKV Python files to
`a0cba97d9abdc99908e46616db622f0e0099127f`. A read-only container hash snapshot
matched all 65 files; preparation repeats this check before starting anything.

A positive `extended_checks` counter only proves that the capacity check ran.
The overall effectiveness label remains `not-exercised` when neither admission
deferrals nor preemption selections occurred. Receipts expose these separately;
even observed deferrals/selections do not by themselves prove a speedup or that
a matched Native request would have made a different decision.

2026-09-25 target update: preparation verified all model/workload/source files.
The first actual runtime suite exposed fixture API mismatches (removed Request
`eos_token_id`; required SchedulerConfig `is_encoder_decoder`). Its failure receipt
is preserved as `software-integration-r1-failed`; the corrected fixture and hash
transition are recorded. The second actual-container run passed all 6 tests,
verified unchanged runtime sources, and left no device owners. The serial campaign
was then started. This is software readiness, not a performance result.
