#!/usr/bin/env python3
"""Generate the reviewed organization extension catalog.

This inventory is deliberately static. Updating a repository SHA, qualification,
or recommendation is a reviewed source change; the generator performs no network
discovery and therefore cannot silently promote a repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CORE = "0.28.1rc1.dev319@762f85b311fbab0bcf8921dd216f5093cd58b9b8"
ASCEND = "0.25.1rc1@4e57439e58ed3d78e675f9fd7b4614fb183c5394"
SCHEMA_COMMIT = "cf1ea71e3e2cb81ab06267ef05eddb3e580ea20b"


def requirements(
    *,
    models: list[str],
    topologies: list[str],
    additional_models: list[dict[str, object]] | None = None,
    storage: str = "No additional persistent storage is required.",
    hbm: str = "No incremental HBM benefit is claimed.",
    environment: dict[str, str] | None = None,
    core: str = CORE,
    ascend: str = ASCEND,
) -> dict[str, object]:
    return {
        "models": models,
        "hardware": ["Ascend NPU"],
        "topologies": topologies,
        "core": core,
        "ascend": ascend,
        "additional_models": additional_models or [],
        "storage": storage,
        "hbm": hbm,
        "environment": environment or {},
    }


def install(
    repository: str,
    commit: str,
    manifest_sha256: str,
    source_subdir: str,
    group: str,
    name: str,
) -> dict[str, object]:
    return {
        "type": "python-source",
        "repository": repository,
        "commit": commit,
        "manifest_path": ".vllm-hust/optimization.json",
        "manifest_sha256": f"sha256:{manifest_sha256}",
        "source_subdir": source_subdir,
        "entrypoint": {"group": group, "name": name},
    }


def rollback(*steps: str) -> dict[str, object]:
    return {"owner": "operator", "steps": list(steps)}


def preview(
    identifier: str,
    name: str,
    repository: str,
    commit: str,
    *,
    branch: str = "main",
    models: list[str] | None = None,
    scope: str,
    scenario: str,
    benefit: str,
    cost: str,
) -> dict[str, object]:
    return {
        "id": identifier,
        "name": name,
        "repository": repository,
        "source": {"ref": branch, "commit": commit},
        "maturity": "preview",
        "availability": "preview",
        "installation": None,
        "enablement": {
            "allowed": False,
            "blocker": (
                "No current-baseline functional and recovery qualification "
                "with an immutable Extension Manager manifest."
            ),
        },
        "runtime_requirements": requirements(
            models=models or ["Model support unverified"],
            topologies=["Topology support unverified"],
        ),
        "functional_qualification": {
            "status": "unverified",
            "scope": scope,
            "recovery": "unverified",
            "evidence": [],
        },
        "tested_effects": [],
        "expected_scenarios": [
            {
                "id": f"{identifier}-target",
                "description": scenario,
                "status": "unverified",
                "evidence": [],
            }
        ],
        "recommendation": {
            "level": "experimental-preview",
            "reason": "Inspect only; do not prepare, configure, or enable.",
        },
        "resource_tradeoff": {"benefit": benefit, "cost": cost},
        "conflicts": [],
        "rollback": rollback("No activation is permitted; remove preview metadata only."),
    }


def qualified_entries() -> list[dict[str, object]]:
    bidkv_repo = "https://github.com/vLLM-HUST/vllm-hust-bidkv"
    diffspec_repo = "https://github.com/vLLM-HUST/vllm-ascend-hust-diffspec"
    latch_repo = "https://github.com/vLLM-HUST/vllm-ascend-hust-LatchMoE"
    pipeline_repo = (
        "https://github.com/vLLM-HUST/vllm-hust-pipeline-microbatch"
    )
    return [
        {
            "id": "bidkv",
            "name": "BidKV",
            "repository": bidkv_repo,
            "source": {
                "ref": "main",
                "commit": "ba700cb69ed5c84f012e5103eb115aa22cdbc1f5",
            },
            "maturity": "qualified",
            "availability": "available",
            "installation": install(
                bidkv_repo,
                "199e0bdc6fc38fc9b14b626515efdcbf81de0b62",
                "5c12035115b5d44ea0be48ac39d7d5c0414eade103d176d7e24dd6f0a2b17d23",
                "src",
                "vllm_hust.extension_bundles",
                "org.vllm-hust.bidkv",
            ),
            "enablement": {"allowed": True, "blocker": None},
            "runtime_requirements": requirements(
                models=["Qwen3.8-27B"], topologies=["TP4 FULL_DECODE_ONLY graph"]
            ),
            "functional_qualification": {
                "status": "passed",
                "scope": "Four-rank graph, output, cancellation, and recovery gates.",
                "recovery": "passed",
                "evidence": [
                    "https://github.com/vLLM-HUST/vllm-hust-bidkv/blob/ba700cb69ed5c84f012e5103eb115aa22cdbc1f5/docs/evidence/sage-mate-20260905-current-main-tp4-graph-r2.md"
                ],
            },
            "tested_effects": [
                {
                    "status": "inconclusive",
                    "cell": "ascending mixed, concurrency 4, 1-GiB KV pressure, n=3",
                    "summary": "Intervals overlap and one repeat did not invoke policy.",
                    "evidence": [
                        "docs/sage-mate-mod-compatibility-20260904.md"
                    ],
                },
                {
                    "status": "not-recommended-for-tested-cell",
                    "cell": "interactive, concurrency 8, 1-GiB KV pressure, n=3",
                    "summary": "Throughput -25.31%; P95 latency +34.57%.",
                    "evidence": [
                        "docs/sage-mate-mod-compatibility-20260904.md"
                    ],
                },
            ],
            "expected_scenarios": [
                {
                    "id": "high-kv-pressure-heterogeneous",
                    "description": (
                        "High KV pressure with heterogeneous remaining lengths, SLOs, "
                        "and priorities."
                    ),
                    "status": "unverified",
                    "evidence": [],
                }
            ],
            "recommendation": {
                "level": "not-recommended-for-tested-cell",
                "reason": "Functionally available; the measured interactive cell regressed.",
            },
            "resource_tradeoff": {
                "benefit": "May improve victim choice under sustained KV pressure.",
                "cost": "Scheduler scoring overhead; no HBM saving is claimed.",
            },
            "conflicts": [
                {"id": "bidkv-legacy", "reason": "Removed private victim-selector path."}
            ],
            "rollback": rollback(
                "Disable the preemption policy.",
                "Restart through the managed graph launcher and verify baseline output.",
            ),
        },
        {
            "id": "diffspec",
            "name": "DiffSpec",
            "repository": diffspec_repo,
            "source": {
                "ref": "main",
                "commit": "42e5909fc6fe276ba0defe1901257a523653aefb",
            },
            "maturity": "qualified",
            "availability": "available",
            "installation": install(
                diffspec_repo,
                "c78f55c7e4923da342f2fc52c2cb509c150e5363",
                "b791c8c3ade03c665f8fedd2285c260f390e88687373b64cd3dfde9b6ac70878",
                "",
                "vllm.general_plugins",
                "diffspec",
            ),
            "enablement": {"allowed": True, "blocker": None},
            "runtime_requirements": requirements(
                models=["Qwen3.8-27B"],
                topologies=["TP4 FULL_DECODE_ONLY graph"],
                additional_models=[
                    {
                        "model": "VirVen/Qwen3.5-27B-EAGLE3-v2",
                        "sha256": "sha256:a57cefc45874197a24dd2a092cfd0d0f7d6a2f2cca156d09f2d2f4a56dc4e5be",
                        "required": True,
                    }
                ],
                hbm="Target and exact draft model must both fit the qualified lane.",
            ),
            "functional_qualification": {
                "status": "passed",
                "scope": "Four-rank draft/KV metadata, graph, concurrency, cancel/recovery.",
                "recovery": "passed",
                "evidence": [
                    "https://github.com/vLLM-HUST/vllm-ascend-hust-diffspec/blob/c78f55c7e4923da342f2fc52c2cb509c150e5363/docs/evidence/sage-mate-20260904-checkpoint-gate.md"
                ],
            },
            "tested_effects": [
                {
                    "status": "not-recommended-for-tested-cell",
                    "cell": "qualified Eagle3 configuration",
                    "summary": "Acceptance 19.29%; output 14.00 versus 47.72 tok/s.",
                    "evidence": ["docs/sage-mate-mod-compatibility-20260904.md"],
                }
            ],
            "expected_scenarios": [
                {
                    "id": "high-acceptance-long-output-depth-sweep",
                    "description": (
                        "High draft acceptance, long output, reachable long-context "
                        "threshold, and draft depths 1/2/3."
                    ),
                    "status": "unverified",
                    "evidence": [],
                }
            ],
            "recommendation": {
                "level": "not-recommended-for-tested-cell",
                "reason": "Correct and available, but the exact draft is slower in this cell.",
            },
            "resource_tradeoff": {
                "benefit": "Can reduce target decode work when acceptance is high.",
                "cost": "Draft weights, draft forward passes, and rank synchronization.",
            },
            "conflicts": [
                {"id": "latchmoe", "reason": "The qualified activation plans conflict."}
            ],
            "rollback": rollback(
                "Disable speculative configuration.",
                "Restart target-only graph service and verify recovery output.",
            ),
        },
        {
            "id": "latchmoe",
            "name": "LatchMoE",
            "repository": latch_repo,
            "source": {
                "ref": "main",
                "commit": "9b2d4acdbfbe6463a22dd0bb8e6ca5bfda47e2c1",
            },
            "maturity": "qualified",
            "availability": "available",
            "installation": install(
                latch_repo,
                "63781f3dd0235f933735bfd8ce614d388093c0b5",
                "aa6d2b3ac6ed10add531448aa8c09c061ca898054c96b69eab1ab2509db35068",
                "",
                "vllm.general_plugins",
                "moe_offload_ascend",
            ),
            "enablement": {"allowed": True, "blocker": None},
            "runtime_requirements": requirements(
                models=["Qwen3-30B-A3B", "Qwen3.8-27B (not applicable: dense)"],
                topologies=["TP4 PIECEWISE graph"],
                hbm="Capacity mechanism; exact HBM saving curve remains unverified.",
            ),
            "functional_qualification": {
                "status": "passed",
                "scope": "MoE mapping, swap, address stability, concurrency, recovery.",
                "recovery": "passed",
                "evidence": [
                    "https://github.com/vLLM-HUST/vllm-ascend-hust-LatchMoE/blob/9b2d4acdbfbe6463a22dd0bb8e6ca5bfda47e2c1/docs/evidence/sage-mate-20260904-tp4-graph.md"
                ],
            },
            "tested_effects": [
                {
                    "status": "not-recommended-for-tested-cell",
                    "cell": "Qwen3-30B-A3B qualified offload configuration",
                    "summary": "Output 2.91 versus 23.57 tok/s baseline.",
                    "evidence": ["docs/sage-mate-mod-compatibility-20260904.md"],
                }
            ],
            "expected_scenarios": [
                {
                    "id": "capacity-first-moe-sweep",
                    "description": (
                        "Model does not fit HBM; sweep slots, resident experts, and "
                        "prefetch for HBM-saving/throughput curves."
                    ),
                    "status": "unverified",
                    "evidence": [],
                }
            ],
            "recommendation": {
                "level": "capacity-only-not-recommended-for-tested-cell",
                "reason": "Dense Qwen3.8 is not applicable; measured MoE cell regressed.",
            },
            "resource_tradeoff": {
                "benefit": "May make an otherwise non-fitting MoE model runnable.",
                "cost": "Host/device transfers and severe measured throughput loss.",
            },
            "conflicts": [
                {"id": "diffspec", "reason": "The qualified activation plans conflict."}
            ],
            "rollback": rollback(
                "Disable expert offload.",
                "Restart the baseline MoE graph service and verify stable health.",
            ),
        },
        {
            "id": "pipeline-microbatch",
            "name": "Pipeline Microbatch",
            "repository": pipeline_repo,
            "source": {
                "ref": "main",
                "commit": "a15a22961a0e4858da74a0ab806575c82cb254e6",
            },
            "maturity": "qualified",
            "availability": "available",
            "installation": install(
                pipeline_repo,
                "a15a22961a0e4858da74a0ab806575c82cb254e6",
                "43c96338d784ea77d471143dd4a9454aace645a6476630e8d08afb97f8e5982c",
                "src",
                "vllm_hust.extension_bundles",
                "org.vllm-hust.pipeline-microbatch",
            ),
            "enablement": {"allowed": True, "blocker": None},
            "runtime_requirements": requirements(
                models=["Qwen3.8-27B"],
                topologies=["PP2 x TP2 FULL_DECODE_ONLY graph"],
                core="0.28.1rc1.dev319@3e57b2f75cffffd26dda0df4d9bcac890cfe99fc",
                ascend="0.25.1rc1@1cf88e9e6e513282cf02dfc9b3e806967387125c",
            ),
            "functional_qualification": {
                "status": "passed",
                "scope": "Policy invocation, output, concurrency, cancellation, recovery.",
                "recovery": "passed",
                "evidence": [
                    "https://github.com/vLLM-HUST/vllm-hust-pipeline-microbatch/blob/a15a22961a0e4858da74a0ab806575c82cb254e6/docs/evidence/sage-mate-20260905-qwen38-pp2tp2-graph.md"
                ],
            },
            "tested_effects": [
                {
                    "status": "not-recommended-for-tested-cell",
                    "cell": "Qwen3.8 PP2 x TP2, concurrency 8",
                    "summary": (
                        "Uniform throughput -4.37%; mixed throughput -26.33%, "
                        "mixed P95 +80.16%."
                    ),
                    "evidence": [
                        "https://github.com/vLLM-HUST/vllm-hust-pipeline-microbatch/blob/a15a22961a0e4858da74a0ab806575c82cb254e6/docs/evidence/sage-mate-20260905-qwen38-pp2tp2-graph.md"
                    ],
                }
            ],
            "expected_scenarios": [
                {
                    "id": "fresh-rank-local-calibration",
                    "description": "Pipeline-parallel workload with fresh per-rank calibration.",
                    "status": "unverified",
                    "evidence": [],
                }
            ],
            "recommendation": {
                "level": "not-recommended-for-tested-cell",
                "reason": "Available after integration merge; measured balanced cell regressed.",
            },
            "resource_tradeoff": {
                "benefit": "May reduce pipeline bubbles after valid calibration.",
                "cost": "Admission overhead and severe long-request tail imbalance measured.",
            },
            "conflicts": [],
            "rollback": rollback(
                "Remove batch-admission policy arguments.",
                "Restart the built-in scheduler and verify recovery output.",
            ),
        },
    ]


def catalog() -> dict[str, object]:
    entries = qualified_entries()
    entries.extend(
        [
            preview(
                "adaptive-quantized-kv",
                "Adaptive Quantized KV",
                "https://github.com/vLLM-HUST/vllm-ascend-adaptive-quantized-kv-hust",
                "ddd306fce8d885b9b9cfeb8c947ed576c5269e66",
                scope="Model/KV dtype/operator correctness and rollback are unverified.",
                scenario="Dynamic KV quantization under capacity pressure.",
                benefit="Potential KV capacity reduction; unmeasured.",
                cost="Quantize/dequantize overhead and quality risk; unmeasured.",
            ),
            preview(
                "clm-lifecycle",
                "CLM Lifecycle",
                "https://github.com/vLLM-HUST/vllm-hust-clm-lifecycle",
                "7657592806b76d8436458c9ac06a292a5e76e048",
                scope="Resource ownership, fencing, cancellation, and recovery unverified.",
                scenario="Cache and model resource lifecycle management.",
                benefit="Potential resource reclamation; unmeasured.",
                cost="Lifecycle race and ownership risk.",
            ),
            preview(
                "knorm",
                "KNorm",
                "https://github.com/vLLM-HUST/vllm-hust-knorm",
                "e0e872abfc9fa88659b3e83c1c8b8b2b3de88fc0",
                scope="Documentation-only scaffold; no package, license file, or runtime.",
                scenario="Normalization and KV-compression interaction research.",
                benefit="No resource benefit demonstrated.",
                cost="Unknown operator, quality, and long-context risk.",
            ),
            preview(
                "kv-tiering",
                "KV Tiering",
                "https://github.com/vLLM-HUST/vllm-hust-kv-tiering",
                "3a73c7e1628801ea5d4f585bcc9d06260161a78c",
                scope="Documentation-only scaffold; storage consistency unverified.",
                scenario="KV migration across device, CPU, and storage tiers.",
                benefit="Potential effective KV capacity increase; unmeasured.",
                cost="Transfer latency, storage durability, and data-lifecycle risk.",
            ),
            preview(
                "kv-transfer-observability",
                "KV Transfer Observability",
                "https://github.com/vLLM-HUST/vllm-hust-kv-transfer-observability",
                "70d1fdc05c7a56e29b452aa11ee00f701749cb94",
                scope="Metric completeness, cardinality, overhead, and recovery unverified.",
                scenario="KV transfer failure and recovery observability.",
                benefit="Operational visibility rather than serving acceleration.",
                cost="Telemetry overhead and cardinality risk.",
            ),
            preview(
                "kvcompress",
                "KVCompress",
                "https://github.com/vLLM-HUST/vllm-ascend-kvcompress-hust",
                "db18568aa8ce01c6d66d4e96b9357fdf766fdcde",
                branch="master",
                scope="Current model, attention backend, quality, and recovery unverified.",
                scenario="Long-context KV compression.",
                benefit="Potential KV capacity reduction; unmeasured.",
                cost="Quality and latency tradeoff; unmeasured.",
            ),
            preview(
                "mapped-kv-offload",
                "Mapped KV Offload",
                "https://github.com/vLLM-HUST/vllm-ascend-mapped-kv-offload-hust",
                "8d4dc47063f164d5cb5859f35bf9d5087544648d",
                scope="Worker adapter, native operator, NUMA, isolation, recovery unverified.",
                scenario="Host-memory-assisted KV offload.",
                benefit="Potential effective KV capacity increase; unmeasured.",
                cost="Host/device transfer and NUMA placement cost.",
            ),
            preview(
                "prefix-router",
                "Prefix Router",
                "https://github.com/vLLM-HUST/vllm-hust-prefix-router",
                "4e007c4fc1bd376a6dccfefbc1fd851019c8ceb6",
                scope="Documentation-only scaffold; no package, license file, or failover.",
                scenario="Multi-replica prefix-affinity routing.",
                benefit="Potential prefix-cache hit increase; unmeasured.",
                cost="Load skew, stale cache events, and failover risk.",
            ),
            preview(
                "pyramidkv",
                "PyramidKV",
                "https://github.com/vLLM-HUST/vllm-ascend-pyramidkv-hust",
                "77b0862c1e5be8c883fda934cdb383c57cf7ad0d",
                scope="Layer policy, model structure, quality, graph, recovery unverified.",
                scenario="Layered KV retention for long context.",
                benefit="Potential KV capacity reduction; unmeasured.",
                cost="Quality and graph-shape risk.",
            ),
            preview(
                "qos-scheduler",
                "QoS Scheduler",
                "https://github.com/vLLM-HUST/vllm-hust-qos-scheduler",
                "13d376a7d8990c4dcf5c0903cb6fbf2398ef0fb0",
                scope="API attachment, fairness, starvation, cancellation, recovery unverified.",
                scenario="Multi-tenant priority and SLO isolation.",
                benefit="Potential tail-latency/SLO control; unmeasured.",
                cost="Fairness and aggregate throughput tradeoff.",
            ),
            preview(
                "quantized-kv-cache",
                "Quantized KV Cache",
                "https://github.com/vLLM-HUST/vllm-ascend-quantized-kv-cache-hust",
                "8dd24cdce248519c173710993f6c633a96107c0d",
                scope="INT8/KIVI INT4 quality, graph, concurrency, recovery unverified.",
                scenario="Long-context KV capacity and quantization tradeoff.",
                benefit="Potential KV capacity reduction; unmeasured.",
                cost="Quantization quality and operator overhead.",
            ),
            preview(
                "scheduler-policy-lab",
                "Scheduler Policy Lab",
                "https://github.com/vLLM-HUST/vllm-hust-scheduler-policy-lab",
                "215bdab44fb572f125e1426f78103e4d4ac7b833",
                scope="Each policy requires independent correctness and recovery evidence.",
                scenario="Scheduler policy A/B and behavior observation.",
                benefit="Research comparison infrastructure.",
                cost="Experimental policies may violate fairness or SLOs.",
            ),
            preview(
                "simllm",
                "SimLLM",
                "https://github.com/vLLM-HUST/vllm-ascend-simllm-hust",
                "dcdc6edf7bdcc68bdf35058888ebfd9752ae3566",
                scope="Simulation is not a production-worker qualification.",
                scenario="Serving strategy simulation and design screening.",
                benefit="Low-cost design exploration, not runtime acceleration.",
                cost="Modeling error; simulated results cannot be called measured.",
            ),
            preview(
                "slicegpt",
                "SliceGPT",
                "https://github.com/vLLM-HUST/vllm-hust-slicegpt",
                "6acf19d9cbb3ed6caa3f5e6341b1da41941f9f2e",
                scope="Documentation-only scaffold; compressed model artifact absent.",
                scenario="Compressed-model capacity, quality, and performance tradeoff.",
                benefit="Potential model HBM reduction; unmeasured.",
                cost="Model conversion, quality, loader, and missing-license risk.",
            ),
        ]
    )
    pegaflow_repo = "https://github.com/vLLM-HUST/pegaflow-hust"
    entries.append(
        {
            "id": "pegaflow",
            "name": "PegaFlow",
            "repository": pegaflow_repo,
            "source": {
                "ref": "main",
                "commit": "a3c574b8526969b70654715d86976474a4cc1b58",
            },
            "maturity": "external",
            "availability": "external",
            "installation": None,
            "enablement": {
                "allowed": False,
                "blocker": "Externally operated service; Workstation has no lifecycle authority.",
            },
            "runtime_requirements": requirements(
                models=["Service-defined"],
                topologies=["External endpoint"],
                storage="Owned and governed by the PegaFlow operator.",
            ),
            "functional_qualification": {
                "status": "external",
                "scope": "Endpoint health and data lifecycle are operator-owned.",
                "recovery": "not-applicable",
                "evidence": [],
            },
            "tested_effects": [],
            "expected_scenarios": [
                {
                    "id": "existing-pegaflow-service",
                    "description": "Connect to an independently operated PegaFlow KV service.",
                    "status": "unverified",
                    "evidence": [],
                }
            ],
            "recommendation": {
                "level": "scenario-dependent-external",
                "reason": "Use only with an owned endpoint and operator evidence.",
            },
            "resource_tradeoff": {
                "benefit": "External KV capacity and transfer services.",
                "cost": "Network, storage, consistency, and external lifecycle dependency.",
            },
            "conflicts": [],
            "rollback": {
                "owner": "external PegaFlow operator",
                "steps": ["Remove Workstation connection intent; do not delete external data."],
            },
        }
    )
    entries.sort(key=lambda item: str(item["id"]))
    return {
        "schema": "vllm-hust.extension-catalog/v1",
        "generated_at": "2026-09-07T00:00:00Z",
        "source": {"ref": "extension-manager/main", "commit": SCHEMA_COMMIT},
        "policy": {
            "availability": (
                "Passed function and recovery plus immutable installation determine availability."
            ),
            "performance": (
                "Negative performance is scoped to recommendation and does not hide a "
                "functionally qualified extension."
            ),
            "preview": "Unverified function or recovery is visible but never enableable.",
            "runtime_state": (
                "Installed, configured, enabled, and runtime effective are independent states."
            ),
        },
        "extensions": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/extension-catalog-v1.json"),
    )
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(catalog(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
