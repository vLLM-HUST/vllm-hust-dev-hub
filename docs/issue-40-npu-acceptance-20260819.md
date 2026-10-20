# Issue #40 official-container NPU acceptance

Date: 2026-08-19 (Asia/Shanghai)

This record closes the remaining real-container gates for optimization entry
point installation. The runs used the official
`quay.io/ascend/vllm-ascend:v0.23.0-openeuler` image, the image's native
Python, pinned vLLM/vLLM-Ascend sources, and a real Ascend 910B2. Host conda
environments were not used.

## Pinned inputs

- Image digest: `sha256:b2d13e24b295171d8f63678506fad5542f142e81d57e407a0b8c98c16ba0c4f7`
- vLLM-HUST: `1a06c55468966de8ef471ecb7612c199e15a153a`
- vLLM-Ascend-HUST: `ac2b94f1536090e2cd0d6c2f8bc8087e336193d5`
- BidKV: `945972fa936b12bc91a8850edfbbd97f9cce3fbb`
- Engine Python: `/usr/local/python3.12.13/bin/python` (Python 3.12.13)
- CANN: 9.1.0; driver: 26.0.rc1; torch_npu: 2.10.0.post4
- Model: `/data/shared_models/Qwen2.5-3B-Instruct`; per-file hashes are in
  `docs/evidence/issue-40-20260819/model-SHA256SUMS`（已迁至
  [benchmark 归档索引](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/evidence-devhub-20261020-v1/archive/dev-hub-20261020/manifest.json)；
  本文证据路径均为归档成员名）
- Hardware: 8 x Ascend 910B2; all devices had no running NPU processes at
  preflight. The recorded runs used the physical device reported as NPU 0.
- Port: 19146
- Graph mode: enabled (`enforce_eager=False`); graph capture completed.

## Matched acceptance paths

### Missing entry point and BidKV custom-group startup

The launcher installed BidKV 0.1.0 with the engine Python into a
launch-unique `/tmp/vllm-hust-engine.*.optimization` target. It then resolved
`vllm.victim_selector:bidkv` to
`bidkv.adapters.vllm_hust.selector:BidkvVictimSelector`, API version 1, from
that isolated target.

The real EngineCore allocated NPU memory, loaded Qwen2.5-3B-Instruct, captured
the graph, logged `[BidKV] INIT`, and served an authenticated chat request. The
response was exactly `PR46_NPU_OK` with HTTP 200. After a normal interrupt,
the listener, vLLM/EngineCore processes, temporary source snapshot, and
temporary install target were absent, and `npu-smi` reported no processes.

### Immutable/preinstalled refusal

With `VLLM_OPTIMIZATION_AUTO_INSTALL=false` and no installed BidKV entry
point, the launcher exited with status 2 before creating an install target or
starting the engine. The diagnostic included the Python environment contract,
entry-point group/name, and the no-mutation reason. No listener, temporary
install, engine process, or NPU process remained.

### Failure after real NPU allocation

The failure fixture installed and resolved BidKV through the same path, then
allocated a 256 MiB bfloat16 tensor on a real NPU and emitted
`VLLM_TEST_NPU_ALLOCATION_READY`. During the observation window, `npu-smi`
showed the fixture process using 377 MiB and the launch-unique optimization
target existed. The fixture then exited deliberately with status 42. The
launcher's cleanup removed the listener, full managed process tree, copied
launcher, source snapshot, and install target; the after-sample showed no NPU
processes on any of the eight devices.

## Repository verification

- Full merged test suite: 92 passed.
- `bash -n scripts/run_vllm_hust_engine.sh`: passed.
- Python compilation for the added helpers and fixture: passed.
- `git diff --check`: passed.

Raw logs and machine-readable manifests are stored under
`docs/evidence/issue-40-20260819/`. `SHA256SUMS` covers the evidence files.
These results establish only the stated single-host, single-NPU entry-point
installation/startup/cleanup contract; they are not throughput or production
performance claims.
