# Progress

## Completed

- Safely loaded `/root/.env`; confirmed credential variables exist without printing values; verified mode 0600.
- Inventoried OS, NPU, storage, memory, Python, Git, CANN, installed torch/torch-npu, active processes, model paths, and current runtime import origins.
- Confirmed all four NPUs are healthy and idle and no unrelated accelerator process needs intervention.
- Located the Qwen3.5-35B-A3B snapshot and found the required checkpoint revision in local provenance metadata.
- Cloned dev-hub, website, Extension Manager, MOD, workload, vLLM, vLLM-Ascend, and the pinned workload-source repository over HTTPS using Dulwich after system Git TLS failures.
- Read repository instructions and the relevant MOD, Manager, unified Frontier, and SWE continuation guides.
- Created branch `codex/kv-materialization-qwen35-frontier` in dev-hub.
- Directly verified the unique unified Native series and its five published values in the website repository.
- Reproduced the exact canonical prepared workload SHA and tokenizer fingerprint with Transformers 5.17.0.
- Forward-ported the MOD runtime seam onto the required vLLM base and committed it on an isolated branch.
- Updated the MOD for the current serving layout and SWE correlation metadata, added a generic Extension Manager bundle, and committed `53a6b1130cbff58925782eb62d7e88cd37e4e20a`.
- Passed 89 MOD tests against explicit target runtime source roots; passed the focused Ruff checks for all changed files.
- Ran Extension Manager inspect, check, plan, configure, enable, status, and environment resolution; extension state is installed/discovered/compatible/configured/enabled.
- Verified the complete local model snapshot against the remote target revision file tree; 27 of 27 runtime files match.
- Built the exact vLLM-Ascend checkout's custom transformer operator package and Python/C++ extension for Ascend 910B2, recorded SHA256 provenance, and passed source-origin, extension-import, operator-registration, device-visibility, and resource-release checks.
- Preserved four failed startup attempts as diagnostic evidence; none was used as benchmark data.
- Completed an exact-source service startup through health and graph capture. The first qualification request exercised the MOD but found a runtime-seam initialization defect; its 0.06-second aborted window is retained as invalid diagnostic evidence.
- Fixed the defect in vLLM commit `556671b117716300121b2ac78b112443b83d1958`; 4 focused tests and Ruff pass.
- Passed the replacement 60-second C1 qualification with 7 strict-protocol requests, zero errors, real MOD controller calls, scheduler-owned APC evidence, and MTP activity.
- Passed all 26 unified long-context retrieval checks and verified clean Manager stop, port release, process release, and NPU release.

## Current

- The kv-materialization campaign is complete and its website PR is merged. Follow-on KVCompress and Legacy017 work is paused because an unrelated experiment began using part of the NPU pool. All resumable state is documented in `handoff-20260928.md`; no formal point was claimed under shared accelerator load.

## Formal Windows

- C1: complete and valid. 81,532 in-window output tokens, 90.5911111111111 output tok/s, P90 decode 107.36876391861011 tok/s/user, 147 completed requests, zero errors, one drained request.
- C2: complete and valid. 139,256 in-window output tokens, 154.7288888888889 output tok/s, P90 decode 98.92568495208843 tok/s/user, 222 completed requests, zero errors, two drained requests.
- C4: replacement complete and valid. 213,772 in-window output tokens, 237.52444444444444 output tok/s, P90 decode 84.76666140724171 tok/s/user, 349 completed requests, zero errors, four drained requests. The separate first window remains invalid and excluded.
- C8: complete and valid. 293,176 in-window output tokens, 325.75111111111113 output tok/s, P90 decode 59.8154350121774 tok/s/user, 474 completed requests, zero errors, eight drained requests.
- C16: complete and valid. 372,863 in-window output tokens, 414.2922222222222 output tok/s, P90 decode 36.79618457742906 tok/s/user, 622 completed requests, zero errors, sixteen drained requests.

## Delivery

- Runtime seam PR: `vLLM-HUST/vllm-hust#42` merged as `55d6c601da6ae2ed61ce9b7b3d5e3607a6402023`.
- MOD compatibility PR: `vLLM-HUST/vllm-hust-kv-materialization-arrival-control#25` merged as `be6fc7819269e8897e610f44040a7c83236ee174`.
- Five-point geometric-mean throughput gain versus `swe-unified-native-20260927`: +7.1301343328886935%.
- Website branch `codex/kv-materialization-qwen35-frontier`: five candidate points, public evidence, generic multi-model plugin observations, computed gain, tests and model-scoped regression coverage implemented.
- Website validation on current main: Node 73/73, pytest 374 passed with 3 skips, and all pre-commit hooks passed. Real Chromium validation passed English/Chinese, desktop/mobile, and light/dark coverage.
- Website PR: `vLLM-HUST/vllm-hust-website#313`, merged as `10ee82ae2ee2e7b7d74ebc8e9578ff052379f61e`; all reported CI checks passed.
- Follow-on KVCompress PR: `vLLM-HUST/vllm-ascend-kvcompress-hust#11`, branch head `5f4cfcc238162485f8b9443ccb2e138981011264`; compatibility code, tests, qualification, failures, hashes, and raw evidence are uploaded.
- Follow-on Legacy017 async-output PR: `vLLM-HUST/vllm-hust-legacy017-perf#1`; qualification and formal runner are uploaded, but the five formal windows remain outstanding.
- Audited DiffSpec, vSpec, LatchMoE, Quantized KV Cache, and Split-Batch against the exact unified contract. Each has a documented intrinsic/configuration blocker; concrete findings were posted to their existing maintainer issues without creating duplicate tickets.
