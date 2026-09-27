"""Export only released, qualified900s campaign cells; never project performance."""

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def export(plan, run, cell, arm, evidence_url):
    status = read(run / "status.json")
    if not status.get("passed") or not status.get("release", {}).get("released"):
        raise ValueError("Require completed campaign arm and device release")
    if not read(run / "prefix-reuse.json")["passed"]:
        raise ValueError("Prefix reuse not demonstrated")
    summary = read(run / cell / "summary.json")
    config = read(run / cell / "config.json")
    if (
        not summary["valid"]
        or summary["aborted"]
        or summary["failed_requests"]
        or summary["measurement_seconds"] != 900
        or summary["planned_measurement_seconds"] != 900
        or summary["decode_tokens_per_second_p90"] is None
    ):
        raise ValueError("Invalid or incomplete900s observation")
    if config["workload_sha256"] != plan["prepared_workload"]["sha256"]:
        raise ValueError("Prepared workload identity mismatch")
    if config["duration"] != 900 or config["chips"] != 2:
        raise ValueError("Unexpected window duration or deployment chip count")
    reference = plan["lanes"][0]
    configuration = copy.deepcopy(reference["reference_configuration"])
    meta = config["server_metadata"]
    params = configuration["parameters"]
    for key in (
        "availability",
        "functional_limit",
        "checkpoint_revision",
        "deployment_note",
        "execution_host",
        "worker_class",
        "source_capsule",
        "benchmark_revision",
        "server_command",
        "observed_max_prompt_tokens",
        "measured_mean_client_inflight",
        "full_client_concurrency_fraction",
    ):
        params.pop(key, None)
    params.update(
        {
            "runtime_receipt": {
                key: meta[key]
                for key in (
                    "packages",
                    "cann",
                    "wheel_sha256",
                    "model_manifest_sha256",
                    "launch_script_sha256",
                    "worker_bridge_sha256",
                    "feedback_patch_files",
                    "core_commit",
                    "ascend_commit",
                    "shared_preemption_api_patch_sha256",
                    "environment",
                )
            },
            "worker_class": "frontier_worker.Worker",
            "model_provider": "ModelScope",
            "checkpoint_revision": "712cf74392b05026a6db2bf213d343747d1f6d45",
            "checkpoint_verification": "All 22 model files SHA256 and size match official revision tree",
            "functional_status": "passed",
            "functional_scope": "26 exact retrieval probes: cold/warm 1K..262080 and 16 concurrent; not general answer-quality certification",
            "qualification": {
                "concurrency": 2,
                "measurement_seconds": 60,
                "fresh_measured_session_salts": True,
                "capacity_gate": False,
            },
            "source_capsule": "frontier-container-20260925-common-feedback-r2",
            "comparison_scope": "Fresh Kubernetes native/BidKV matched pair; one 900s observation per point; not peak capacity or repeatability certification",
            "benchmark_revision": "6861242dbd9f17b707003191e4200b7752911d7c",
            "worker_abi_bridge_sha256": meta["worker_bridge_sha256"],
            "observed_max_prompt_tokens": summary["max_prompt_tokens_observed"],
            "measured_mean_client_inflight": summary["mean_client_inflight"],
            "full_client_concurrency_fraction": summary["full_concurrency_fraction"],
            "execution_host": "user-provided-kubernetes-container",
            "server_command": read(run / "custody.json")["command"],
            "pod_npu_quota": 8,
            "participating_deployment_chips": 2,
            "release_verified": True,
            "pod_memory_limit_gib": 128,
            "host_memory_policy": "Container memory limit 128GiB; no host KV offload",
            "capacity_policy": "Same explicit 24.25GiB KV per chip in native and BidKV; not a capacity maximum",
        }
    )
    configuration["engine_version"] = (
        "0.25.1+frontier.bidkv / 0.25.1rc1 + common Mamba feedback patch"
    )
    configuration["mods"] = [] if arm == "native" else ["bidkv"]
    configuration["experiment_group"] = (
        "Native · K8s" if arm == "native" else "BidKV · K8s"
    )
    if arm == "bidkv":
        configuration["mod_sources"] = [
            {
                "id": "bidkv",
                "repository": "https://github.com/vLLM-HUST/vllm-hust-bidkv",
                "revision": "a0cba97d9abdc99908e46616db622f0e0099127f",
                "source_capsule": "frontier-container-20260925-common-feedback-r2",
                "scope": "BidKV adapter on the common preemption API backport; policy counters determine whether the mechanism was exercised",
            }
        ]
        params["preemption_policy"] = (
            "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy"
        )
        params["mod_revision"] = "a0cba97d9abdc99908e46616db622f0e0099127f"
        params["mod_runtime_effectiveness"] = read(
            run / f"{cell}-policy-effectiveness.json"
        )
    c = config["concurrency"]
    inactive = (
        arm == "bidkv"
        and params["mod_runtime_effectiveness"]["status"] == "not-exercised"
    )
    label = f"{'Native' if arm == 'native' else 'BidKV'} · K8s · C{c} · r1"
    if inactive:
        label += " · 未触发预占"
    return {
        "id": f"qwen35-sweprefix-k8s-{arm}-tp2-c{c}-r1-20260925",
        "cohort_id": reference["cohort"]["id"],
        "label": label,
        "configuration": configuration,
        "load": {
            "concurrency": c,
            "unit": "continuously replenished in-flight HTTP request lanes",
            "concurrency_series": f"swe-k8s-20260925-{arm}-r1",
        },
        "metrics": {
            "output_tps": summary["output_tokens_per_second"],
            "decode_p90_tps": summary["decode_tokens_per_second_p90"],
            "ttft_p95_ms": summary["ttft_seconds_p95"] * 1000,
            "completed_requests": summary["requests_completed_in_window"],
        },
        "evidence": {
            "execution_kind": "real-online",
            "sampling_date_utc": datetime.fromtimestamp(
                config["started_at_unix"], timezone.utc
            ).date().isoformat(),
            "sampling_date_source": "Recorded SWE client started_at_unix (UTC)",
            "status": "measured",
            "profile": "smoke",
            "measurement_seconds": 900,
            "tuning_complete": False,
            "url": evidence_url,
            "run_ids": [config["run_id"]],
            "aggregation": "One unpooled 900s observation; count actual streamed output tokens inside window; drain excluded",
            "benchmark_protocol": {
                "protocol_id": "swe-prefix-reuse/v1",
                "campaign": "qwen35-mods-k8s-20260925",
                "repository": "https://github.com/vLLM-HUST/swe-prefix-reuse",
                "revision": "6861242dbd9f17b707003191e4200b7752911d7c",
                "prepared_workload_sha256": plan["prepared_workload"]["sha256"],
                "tokenizer_fingerprint": plan["prepared_workload"][
                    "tokenizer_fingerprint"
                ],
            },
        },
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--cell", choices=["c4", "c16"], required=True)
    p.add_argument("--arm", choices=["native", "bidkv"], required=True)
    p.add_argument("--evidence-url", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = export(read(a.plan), a.run, a.cell, a.arm, a.evidence_url)
    with a.output.open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
