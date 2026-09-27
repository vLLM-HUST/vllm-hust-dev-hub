# Pipeline Microbatch ECPA launch receipt

This capsule records the **real-online smoke** that wrapped the already measured
Qwen3.5 PP2×TP2 Pipeline command with Extension Manager. It is lifecycle evidence,
not a new performance observation.

The Frontier runtime backports the batch-admission API onto vLLM 0.25.1, while the
standalone plugin manifest targets the newer host line. The narrow adapter manifest
therefore declares only the actual backported host and the same
`PipelineMicrobatchPolicy`; it adds no scheduling code. `manager.json` carries the
frozen rank-local profile used by the published measurements.

ECPA `validate`, `check`, `inspect`, `plan`, and `run --dry-run` succeeded. A dedicated
supervisor then used `vllm-hust-ext run` to start the exact Qwen3.5 configuration with
APC, MTP2, asynchronous scheduling, Mamba align and FULL_AND_PIECEWISE graphs. One
real completion returned eight tokens. Metrics recorded 10 policy calls, 5 admissions,
5 completions, 5 abstentions, and zero aborts, failures, invalid admissions or builtin
fallbacks. The supervisor stopped the service and all four selected devices had no
remaining FD owners.

See `receipt.json` for source hashes, the rendered command hash, counters and release
state. The published C1/C2/C4/C8/C16 values remain the performance evidence; this
smoke only upgrades the launch acceptance from an external-only harness to an
ECPA-managed launch.
