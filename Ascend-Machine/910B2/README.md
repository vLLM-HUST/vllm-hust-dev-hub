# Ascend 910B2 hardware baselines

This directory contains measurements made on the workspace's Ascend 910B2
cards. Keep these results separate from the 910B3 measurements in the parent
directory: the NPU identity and CANN/driver stack differ.

## Available results

### Single-card HBM bandwidth — 2026-07-19

- Environment: Ascend 910B2, 64 GiB HBM, driver 26.0.rc1, torch-npu 2.10.0
- Streaming-copy ceiling: approximately **1.275 TB/s** estimated HBM traffic
- BF16 vector-add roofline: approximately **1.14 TB/s** estimated HBM traffic

Read the complete methodology and interpretation in
[`HARDWARE_REPORT_20260719.md`](HARDWARE_REPORT_20260719.md).

Artifacts:

- Benchmark: [`benchmarks/single_npu_hbm.py`](benchmarks/single_npu_hbm.py)
- Raw JSON: [`results/20260719_single_npu_hbm_npu7/single_npu_hbm.json` (benchmark custody index)](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/evidence-devhub-20261020-v1/archive/dev-hub-20261020/manifest.json)

The 64 MiB result is cache-resident and is intentionally excluded from the HBM
ceiling. Use the 256 MiB through 4 GiB plateau for operator roofline analysis.

## Reproduce

Run inside an Ascend PyTorch container that exposes one idle NPU as logical
`npu:0`:

```bash
python3 Ascend-Machine/910B2/benchmarks/single_npu_hbm.py \
  --output Ascend-Machine/910B2/results/my_run/single_npu_hbm.json
```

The reported HBM rates are algorithmic traffic estimates: copy counts one read
and one write; add counts two reads and one write. They are not PMU readings.
