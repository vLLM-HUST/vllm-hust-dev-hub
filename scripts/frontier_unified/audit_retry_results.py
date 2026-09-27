"""Audit candidate retries against the one passed Native from the retained capsule."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load("contract", HERE / "contract.py")
unified = load("unified_retry_base_audit", HERE / "audit_results.py")
read = unified.read
CELLS = unified.CELLS
ARMS = ("mooncake", "tiering")


def local_manifest_digest(root: Path, manifest: dict, name: str) -> str:
    matches = [
        value
        for path, value in manifest["sha256"].items()
        if Path(path).parent.name == "phase9-unified-retry-r1"
        and Path(path).name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Retry manifest does not identify exactly one {name}")
    actual = unified.digest_bytes((root / name).read_bytes())
    if actual != matches[0]:
        raise ValueError(f"Retry capsule changed: {name}")
    return actual


def audit(retry_root: Path, native_root: Path) -> dict:
    retry_root, native_root = Path(retry_root), Path(native_root)
    native_status = read(native_root / "receipts/native-measured-r1/status.json")
    if (
        native_status.get("passed") is not True
        or native_status.get("stage") != "completed"
        or native_status.get("release", {}).get("exit") != 0
        or native_status.get("release", {}).get("owners")
    ):
        raise ValueError("The retained Native is incomplete or unreleased")
    retry = read(retry_root / "receipts/shared-native-retry-r1/status.json")
    if (
        retry.get("passed") is not True
        or retry.get("active_arm") is not None
        or retry.get("error")
        or [row["arm"] for row in retry.get("arms", [])] != list(ARMS)
        or not all(row["passed"] for row in retry["arms"])
    ):
        raise ValueError("Candidate-only retry is incomplete")
    manifest = read(retry_root / "manifest.json")
    if (
        manifest.get("software_tests_passed") is not True
        or manifest.get("baseline_id") != "qwen35-unified-native-20260927"
    ):
        raise ValueError("Retry software admission or baseline identity is missing")
    required = (
        "common-contract.json",
        "contract.py",
        "manager-plans.json",
        "metadata-native.json",
        "metadata-mooncake.json",
        "metadata-tiering.json",
        "launch-mooncake.sh",
        "launch-tiering.sh",
        "qualify.py",
        "run_campaign.py",
        "supervisord.conf",
    )
    for name in required:
        local_manifest_digest(retry_root, manifest, name)
    plans = read(retry_root / "manager-plans.json")
    contract.validate_plans(plans)
    native_plans = read(native_root / "manager-plans.json")
    if plans != native_plans:
        raise ValueError("Retry manager plans differ from the Native contract")
    native = unified.checked_arm(native_root, "native", native_plans)
    candidates = {
        "mooncake": unified.checked_arm(
            retry_root, "mooncake", plans, "mooncake-measured-r2"
        ),
        "tiering": unified.checked_arm(retry_root, "tiering", plans),
    }
    common = read(native_root / "common-contract.json")
    common_sha = unified.digest_bytes(
        (native_root / "common-contract.json").read_bytes()
    )
    if common_sha != unified.digest_bytes(
        (retry_root / "common-contract.json").read_bytes()
    ):
        raise ValueError("Retry changed the shared Native contract")
    previous_release = native["state"]["hbm_after_stop"]["observed_unix"]
    seen_pids = {native["custody"]["server_pid"]}
    for arm in ARMS:
        checked = candidates[arm]
        metadata = checked["metadata"]
        if (
            metadata.get("shared_native_baseline_id") != common["baseline_id"]
            or metadata.get("shared_native_contract_sha256") != common_sha
            or metadata.get("runtime_source_files") != common["runtime_source_files"]
            or metadata.get("prepared_workload_sha256") != common["workload_sha256"]
            or contract.normalize(checked["custody"]["serving_child"]["argv"], arm)
            != common["native_command"]
        ):
            raise ValueError(f"{arm} is not bound to the one retained Native")
        started = checked["windows"]["qualification"][0]["started_at_unix"]
        if started < previous_release:
            raise ValueError(
                "Candidate began before the prior service released devices"
            )
        previous_release = checked["state"]["hbm_after_stop"]["observed_unix"]
        pid = checked["custody"]["server_pid"]
        if pid in seen_pids:
            raise ValueError("Service lifecycle was reused")
        seen_pids.add(pid)
    rows = []
    all_arms = {"native": native, **candidates}
    for arm, checked in all_arms.items():
        for concurrency in CELLS:
            config, summary = checked["windows"][f"c{concurrency}"]
            baseline_config, baseline = native["windows"][f"c{concurrency}"]
            rows.append(
                {
                    "arm": arm,
                    "concurrency": concurrency,
                    "run_id": config["run_id"],
                    "baseline_run_id": baseline_config["run_id"],
                    "output_tps": summary["output_tokens_per_second"],
                    "native_output_tps": baseline["output_tokens_per_second"],
                    "throughput_change_percent": 100
                    * (
                        summary["output_tokens_per_second"]
                        / baseline["output_tokens_per_second"]
                        - 1
                    ),
                    "decode_p90_tps": summary["decode_tokens_per_second_p90"],
                    "ttft_p95_ms": summary["ttft_seconds_p95"] * 1000,
                }
            )
    if (
        len(rows) != 15
        or len({row["run_id"] for row in rows}) != 15
        or len({row["baseline_run_id"] for row in rows}) != 5
    ):
        raise ValueError("Retry did not preserve one five-point Native series")
    return {
        "passed": True,
        "evidence_kind": "derived-artifact",
        "source_kind": "real-online",
        "baseline_id": common["baseline_id"],
        "contract_sha256": common_sha,
        "native_series_count": 1,
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1]), Path(sys.argv[2])), indent=2))
