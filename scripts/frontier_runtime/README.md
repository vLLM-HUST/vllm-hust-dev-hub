# Qwen3.5-35B-A3B Frontier container campaign

Execution is confined to the user-provided Kubernetes container, NodePort 30033,
namespace `coder-workspaces`, pod UID `33e57f4a-ee9b-4000-a326-7b5d45529e65`.
The task-owned serving deployment uses container devices 0 and 1 (TP2); the pod
quota is eight NPUs. Other six devices are not participating deployment chips.

Base source identities:

- vLLM: `752a3a504485790a2e8491cacbb35c137339ad34`.
- vLLM-Ascend: `9bf964cb4b87c8cd0d6852c41a55b3c29711fa95`.
- BidKV: `a0cba97d9abdc99908e46616db622f0e0099127f`.
- SWE prefix reuse: `6861242dbd9f17b707003191e4200b7752911d7c`.

`core-common.patch.gz` combines the neutral public preemption API port and the
Mamba feedback correction. `core-feedback-mailbox.patch.gz` is only the latter;
do not apply it again on top of `core-common.patch.gz`.
`ascend-feedback-mailbox.patch.gz` corrects the Ascend runner's corresponding read.
Both arms use these same patches. The feedback correction is qualified here
for the V1 async, Mamba `align`, SD-layout configuration; other combinations
are not certified by these runs.

`frontier_worker.py` adapts the pinned core's Mamba kernel call signature to the
pinned Ascend V1 SD implementation, rejecting unsupported layouts/index mapping.
The initial transferred version is semantically identical but has different
formatting; each runtime admission receipt hashes the actual executed file.

The official A2 wheel is
`vllm_ascend-0.25.1rc1-cp312-cp312-manylinux_2_34_aarch64.whl`, SHA256
`0e6ba24d581ef9200aa38ae6773363633070a21a84ce229fbe41bbedc054ae42`.
Before the feedback overlay, 477 Python files were compared with pinned source;
only generated `_version.py` differed. CANN 9.1.0, torch 2.10.0+cpu,
torch-npu 2.10.0.post4 and triton-ascend 3.2.2 come from the provided container.
This is a fresh matched pair, not a bitwise recreation of the historical host.

`VLLM_VERSION=0.25.1` selects the backend's exact-version compatibility branch.
Actual patched core metadata remains `0.25.1+frontier.bidkv.empty`. Preserve the
CANN environment when prepending the worker's directory to `PYTHONPATH`.

The 22 model files have a full SHA256 manifest in the container. Five identical
shards use the readonly mount; nine missing shards and metadata were copied into
the task-owned model directory. All22 hashes and sizes were subsequently matched against the official ModelScope
repository tree at historical revision `712cf74392b05026a6db2bf213d343747d1f6d45`.
The official ModelScope API resolves that revision and supplies the file hashes.
The tree response and comparison receipt are retained alongside the manifest.

`run_windows.py` must be launched by the dedicated supervisor. It binds to an
already admitted server PID/program, checks retrieval receipts, runs the public
SWE harness (C2/60 seconds, then C4 and C16 at 900 seconds), captures Prometheus
metrics, and stops that exact server program in `finally`. Two offline tests
verify refusal to stop a mismatched server and cleanup after a failed gate.
Raw harness output and a successful resource-release receipt are required before
publishing a point. An installed BidKV policy with zero selection calls is
`not-exercised`; it is not evidence of a policy benefit.

No eager fallback, synthetic speculative acceptance, shortened measured window,
or changed KV capacity is permitted to turn a failing run into a point.

Decompress the source overlays with `gzip -dc` before `git apply`; compression preserves unified-diff context bytes.
