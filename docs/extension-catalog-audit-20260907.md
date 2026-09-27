# Organization extension catalog audit (2026-09-07)

This audit covers the exact 19 entries exported to Workstation. Repository
identity and default-branch heads were read from GitHub after the Pipeline and
Extension Manager integration PRs merged. A repository being visible is not an
activation qualification: missing function or recovery evidence always means
`preview`, while negative performance only scopes the recommendation of a
functionally qualified entry.

| Extension | Canonical default head | License/risk | Functional qualification | Workload/config cell |
| --- | --- | --- | --- | --- |
| Adaptive Quantized KV | `main@ddd306fce8d885b9b9cfeb8c947ed576c5269e66` | Apache-2.0 metadata; quantization quality/operator risk | Preview; current worker correctness/recovery unverified | Dynamic KV quantization under capacity pressure |
| BidKV | `main@ba700cb69ed5c84f012e5103eb115aa22cdbc1f5` | Apache-2.0 package declaration but LICENSE text missing | Passed: Qwen3.8-27B, TP4 FULL_DECODE_ONLY graph, cancellation/recovery | Qualified cells retained; heterogeneous high-pressure/SLO/priority cell unverified |
| CLM Lifecycle | `main@7657592806b76d8436458c9ac06a292a5e76e048` | Apache-2.0 metadata; ownership/fencing race risk | Preview; no executable manifest or recovery evidence | Cache/model resource lifecycle management |
| DiffSpec | `main@42e5909fc6fe276ba0defe1901257a523653aefb` | Apache-2.0 metadata; draft identity and rank-consistency risk | Passed: Qwen3.8-27B + exact Eagle3 draft, TP4 graph, cancellation/recovery | Measured acceptance 19.29%; high-acceptance/long-output/depth 1-3 sweep unverified |
| KNorm | `main@e0e872abfc9fa88659b3e83c1c8b8b2b3de88fc0` | No LICENSE/package; documentation-only scaffold | Preview; no runnable release | Normalization and KV-compression interaction |
| KV Tiering | `main@3a73c7e1628801ea5d4f585bcc9d06260161a78c` | No LICENSE/package; storage consistency/lifecycle risk | Preview; no runnable release | Device/CPU/storage KV tier migration |
| KV Transfer Observability | `main@70d1fdc05c7a56e29b452aa11ee00f701749cb94` | Apache-2.0 metadata; metric cardinality/overhead risk | Preview; exporter completeness/recovery unverified | KV transfer failure and recovery observability |
| KVCompress | `master@db18568aa8ce01c6d66d4e96b9357fdf766fdcde` | Apache-2.0 metadata; quality/attention-backend risk | Preview; current model graph correctness/recovery unverified | Long-context KV compression |
| LatchMoE | `main@9b2d4acdbfbe6463a22dd0bb8e6ca5bfda47e2c1` | Apache-2.0 metadata; host/device transfer and throughput cost | Passed: Qwen3-30B-A3B TP4 PIECEWISE graph, mapping/swap/address/recovery | Dense Qwen3.8 Not Applicable; capacity-first HBM/throughput sweep unverified |
| Mapped KV Offload | `main@8d4dc47063f164d5cb5859f35bf9d5087544648d` | Apache-2.0 metadata; NUMA/native operator/isolation risk | Preview; worker adapter and recovery unverified | Host-memory-assisted KV offload |
| PegaFlow | `main@a3c574b8526969b70654715d86976474a4cc1b58` | Apache-2.0 metadata; externally owned storage/lifecycle | External; Workstation has no install/start/delete authority | Connect to an independently operated PegaFlow service |
| Pipeline Microbatch | `main@a15a22961a0e4858da74a0ab806575c82cb254e6` | Apache-2.0 metadata; calibration and long-tail imbalance risk | Passed: Qwen3.8-27B PP2 x TP2 graph, 908 calls, 757/757 admissions/completions, recovery | Available but not recommended for measured C8 uniform/mixed cells |
| Prefix Router | `main@4e007c4fc1bd376a6dccfefbc1fd851019c8ceb6` | No LICENSE/package; documentation-only scaffold, failover/skew risk | Preview; no runnable release | Multi-replica prefix-affinity routing |
| PyramidKV | `main@77b0862c1e5be8c883fda934cdb383c57cf7ad0d` | Apache-2.0 metadata; model quality and graph-shape risk | Preview; model/graph/recovery unverified | Layered KV retention for long context |
| QoS Scheduler | `main@13d376a7d8990c4dcf5c0903cb6fbf2398ef0fb0` | Apache-2.0 metadata; fairness/starvation/throughput risk | Preview; API attachment, cancellation, recovery unverified | Multi-tenant priority and SLO isolation |
| Quantized KV Cache | `main@8dd24cdce248519c173710993f6c633a96107c0d` | Apache-2.0 metadata; quality/operator overhead risk | Preview; INT8/KIVI correctness and recovery unverified | Long-context KV capacity/quality/performance tradeoff |
| Scheduler Policy Lab | `main@215bdab44fb572f125e1426f78103e4d4ac7b833` | Apache-2.0 metadata; experimental policy safety risk | Preview; every policy requires separate qualification | Scheduler policy A/B and behavior observation |
| SimLLM | `main@dcdc6edf7bdcc68bdf35058888ebfd9752ae3566` | Apache-2.0 metadata; simulation/modeling error | Preview; simulation is not production-worker evidence | Serving-strategy simulation and design screening |
| SliceGPT | `main@6acf19d9cbb3ed6caa3f5e6341b1da41941f9f2e` | No LICENSE/package; compressed model asset absent | Preview; no runnable release or quality/recovery evidence | Compressed-model capacity/quality/performance tradeoff |

## Pipeline evidence boundary

The Pipeline artifact is available because its integration path and manifest
now exist on organization default branches and GitHub Actions is enabled. Core
#12 merged as `88e606d0f0cd...` and Ascend #10 as `d92617b00240...`; those new
main merge artifacts still require their own live runtime witness. Existing
compatibility evidence remains scoped to exact tested heads `3e57b2f75cff...`
and `1cf88e9e6e51...`, Qwen3.8-27B, PP2 x TP2,
FULL_DECODE_ONLY graph on NPU0-3. It recorded 908 policy calls, 757 admissions,
757 completions, and zero failures, invalid results, or fallbacks; five exact
outputs and cancellation recovery passed. Performance is explicitly not a
recommendation: uniform C8 throughput was -4.37%; fixed-work mixed C8 throughput
was -26.33% and P95 latency was +80.16%.

NPU4-7 were excluded from the qualification campaign and remain outside this
catalog publication work.
