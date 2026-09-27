"""Publish audited unified-Native results into the Frontier website datasets."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CELLS = (1, 2, 4, 8, 16)
PUBLIC_IDS = {
    "mooncake": "mooncake-vllm-connectors",
    "tiering": "kv-tiering-migration",
    "bidkv": "bidkv",
    "dla": "dla",
}
SERIES = {
    "native": "swe-unified-native-20260927",
    **{
        arm: f"swe-unified-{public_id}-20260927"
        for arm, public_id in PUBLIC_IDS.items()
    },
}
COHORT_ID = "qwen35-35b-a3b-bf16-sweprefix-unified-v1"
TEMPLATE_POINT = "qwen35-sweprefix-capacity16-native-tp2-c1-20260924"
TEMPLATE_COHORT = "qwen35-35b-a3b-bf16-sweprefix-smoke-v1"


def read(path: Path):
    return json.loads(path.read_text())


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_runs(native_root: Path, retry_root: Path, followup_root: Path):
    load("contract", HERE / "contract.py")
    unified = load("publication_unified_audit", HERE / "audit_results.py")
    load("publication_retry_audit", HERE / "audit_retry_results.py").audit(
        retry_root, native_root
    )
    followup = load(
        "publication_followup_audit",
        HERE.parent / "frontier_unified_followup/audit_results.py",
    )
    followup.audit(followup_root, retry_root, native_root)
    native_plans = read(native_root / "manager-plans.json")
    retry_plans = read(retry_root / "manager-plans.json")
    followup_plans = read(followup_root / "manager-plans.json")
    return {
        "native": unified.checked_arm(native_root, "native", native_plans),
        "mooncake": unified.checked_arm(
            retry_root, "mooncake", retry_plans, "mooncake-measured-r2"
        ),
        "tiering": unified.checked_arm(retry_root, "tiering", retry_plans),
        "bidkv": unified.checked_arm(followup_root, "bidkv", followup_plans),
        "dla": unified.checked_arm(followup_root, "dla", followup_plans),
    }


def build_cohort(template: dict, native_root: Path) -> dict:
    result = copy.deepcopy(template)
    metadata = read(native_root / "metadata-native.json")
    contract = read(native_root / "common-contract.json")
    result["id"] = COHORT_ID
    result["model"] = {
        "id": "qwen35-35b-a3b-modelscope-6238348a",
        "label": "Qwen3.5-35B-A3B",
        "revision": metadata["model_manifest_sha256"],
    }
    result["workload"]["id"] = "sweprefix-qwen35-unified-900s-v1"
    result["workload"]["label"] = "SWE prefix reuse · 15 min unified Native"
    workload = result["workload"]["contract"]
    workload["prepared_workload_sha256"] = contract["workload_sha256"]
    workload["repository_url"] = "https://github.com/vLLM-HUST/swe-prefix-reuse"
    workload["revision"] = metadata["benchmark_revision"]
    workload["status"] = (
        "15-minute real-online observations under one shared Native contract"
    )
    return result


def build_point(
    template: dict,
    arm: str,
    checked: dict,
    concurrency: int,
    evidence_url: str,
    contract_sha: str,
) -> tuple[dict, dict]:
    config, summary = checked["windows"][f"c{concurrency}"]
    metadata = checked["metadata"]
    public_id = PUBLIC_IDS.get(arm)
    point = copy.deepcopy(template)
    point["id"] = (
        f"qwen35-unified-{public_id or 'native'}-tp2-c{concurrency}-r1-20260927"
    )
    point["cohort_id"] = COHORT_ID
    point["label"] = f"{public_id or 'Native'} · C{concurrency} · r1"
    configuration = point["configuration"]
    configuration["engine_version"] = "0.25.1+frontier.unified / 0.25.1rc1"
    configuration["mods"] = [] if arm == "native" else [public_id]
    configuration.pop("experiment_group", None)
    parameters = configuration["parameters"]
    for key in (
        "functional_limit",
        "deployment_note",
        "availability",
        "tpot_ms",
        "tpot_p95_ms",
    ):
        parameters.pop(key, None)
    ascend_revision = metadata["ascend_provenance"]["tracker_fix"]["revision"]
    parameters.update(
        runtime_base_commits={
            "vllm": metadata["core_commit"],
            "vllm-ascend": ascend_revision,
        },
        checkpoint_revision=metadata["model_manifest_sha256"],
        benchmark_revision=metadata["benchmark_revision"],
        source_capsule="qwen35-unified-native-20260927",
        comparison_scope=(
            "One serial 900s observation per cell; every MOD is paired with the "
            "same five-point Native series"
        ),
        worker_class=metadata["worker"],
        server_command=checked["custody"]["command"],
        observed_max_prompt_tokens=summary["max_prompt_tokens_observed"],
        measured_mean_client_inflight=summary["mean_client_inflight"],
        full_client_concurrency_fraction=summary["full_concurrency_fraction"],
        execution_host="user-provided Kubernetes container",
        physical_devices=metadata["serving_devices"],
        participating_deployment_chips=metadata["serving_chips"],
        pod_npu_quota=metadata["container_allocated_npus"],
        host_kv_budget_gib=8 if arm == "tiering" else 0,
        host_memory_policy=(
            "8 GiB candidate host KV tier"
            if arm == "tiering"
            else "No declared local host KV tier"
        ),
        capacity_policy=(
            "Same explicit 26038239232-byte device KV budget per chip in every arm; "
            "candidate storage is part of the MOD treatment"
        ),
        unified_native_contract_sha256=contract_sha,
    )
    configuration["mod_sources"] = []
    if public_id:
        configuration["mod_sources"].append(
            {
                "id": public_id,
                "scope": "The only candidate-specific treatment admitted by the unified audit",
            }
        )
    point["load"] = {
        "concurrency": concurrency,
        "unit": "continuously replenished in-flight HTTP request lanes",
        "concurrency_series": SERIES[arm],
    }
    point["metrics"] = {
        "output_tps": summary["output_tokens_per_second"],
        "decode_p90_tps": summary["decode_tokens_per_second_p90"],
        "ttft_p95_ms": summary["ttft_seconds_p95"] * 1000,
        "completed_requests": summary["requests_completed_in_window"],
    }
    point["evidence"] = {
        "execution_kind": "real-online",
        "sampling_date_utc": datetime.fromtimestamp(
            config["started_at_unix"], timezone.utc
        )
        .date()
        .isoformat(),
        "sampling_date_source": "Recorded SWE client started_at_unix (UTC)",
        "status": "measured",
        "profile": "smoke",
        "measurement_seconds": 900,
        "tuning_complete": False,
        "url": evidence_url,
        "run_ids": [config["run_id"]],
        "aggregation": "One unpooled 900s observation; drain excluded",
        "benchmark_protocol": {
            "protocol_id": "swe-prefix-reuse/v1",
            "campaign": "qwen35-unified-native-20260927",
            "repository": "https://github.com/vLLM-HUST/swe-prefix-reuse",
            "revision": metadata["benchmark_revision"],
            "prepared_workload_sha256": config["workload_sha256"],
            "tokenizer_fingerprint": config["tokenizer"]["fingerprint"],
        },
    }
    evidence = {
        "run_id": config["run_id"],
        "point_id": point["id"],
        "summary": summary,
        "metrics": point["metrics"],
        "requests_artifact_sha256": sha256(
            checked["run"] / f"c{concurrency}/requests.jsonl"
        ),
        "validation": {
            "real_online": True,
            "failed_requests": 0,
            "prefix_cache_observed": True,
            "selected_devices_released": True,
            "shared_native_contract_sha256": contract_sha,
        },
    }
    return point, evidence


def publish(args) -> dict:
    site = args.site.resolve()
    frontier_path = site / "data/leaderboard_frontier.json"
    evidence_path = site / "data/leaderboard_frontier_swe_evidence.json"
    performance_path = site / "data/plugin-performance.json"
    frontier, evidence, performance = map(
        read, (frontier_path, evidence_path, performance_path)
    )
    runs = checked_runs(args.native, args.retry, args.followup)
    contract_sha = sha256(args.native / "common-contract.json")
    point_template = next(
        point for point in frontier["points"] if point["id"] == TEMPLATE_POINT
    )
    cohort_template = next(
        cohort for cohort in frontier["cohorts"] if cohort["id"] == TEMPLATE_COHORT
    )
    if any(cohort["id"] == COHORT_ID for cohort in frontier["cohorts"]):
        raise ValueError(
            "Unified cohort already exists; refusing an in-place overwrite"
        )
    additions = [
        build_point(
            point_template, arm, checked, concurrency, args.evidence_url, contract_sha
        )
        for arm, checked in runs.items()
        for concurrency in CELLS
    ]
    new_ids = {point["id"] for point, _ in additions}
    if len(new_ids) != 25 or any(
        point["id"] in new_ids for point in frontier["points"]
    ):
        raise ValueError("Unified publication would duplicate a point")
    frontier["cohorts"].append(build_cohort(cohort_template, args.native))
    frontier["points"].extend(point for point, _ in additions)
    evidence["runs"].extend(row for _, row in additions)
    performance["baseline"]["series_id"] = SERIES["native"]
    for entry in performance["entries"]:
        arm = next(
            (
                candidate
                for candidate, public in PUBLIC_IDS.items()
                if public == entry["id"]
            ),
            None,
        )
        if arm:
            entry["series_id"] = SERIES[arm]
    for path, value in (
        (frontier_path, frontier),
        (evidence_path, evidence),
        (performance_path, performance),
    ):
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    return {"points": sorted(new_ids), "baseline_series": SERIES["native"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--retry", type=Path, required=True)
    parser.add_argument("--followup", type=Path, required=True)
    parser.add_argument("--evidence-url", required=True)
    print(json.dumps(publish(parser.parse_args()), indent=2))
