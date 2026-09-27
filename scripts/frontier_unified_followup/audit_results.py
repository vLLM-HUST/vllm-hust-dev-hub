"""Audit BidKV and DLA against phase9's one already measured Native series."""

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


load("contract", HERE.parent / "frontier_unified/contract.py")
unified = load(
    "phase9_unified_audit", HERE.parent / "frontier_unified/audit_results.py"
)
retry_auditor = load(
    "phase9_retry_audit", HERE.parent / "frontier_unified/audit_retry_results.py"
)
followup = load("phase10_followup_contract", HERE / "contract.py")
read = unified.read
CELLS = unified.CELLS


def audit(candidate_root: Path, retry_root: Path, native_root: Path) -> dict:
    candidate_root = Path(candidate_root)
    retry_root = Path(retry_root)
    native_root = Path(native_root)
    retry_audit = retry_auditor.audit(retry_root, native_root)
    campaign = read(candidate_root / "receipts/shared-native-followup-r1/status.json")
    if (
        campaign.get("passed") is not True
        or campaign.get("active_arm") is not None
        or campaign.get("error")
        or [row["arm"] for row in campaign["arms"]] != list(followup.ARMS)
        or not all(row["passed"] for row in campaign["arms"])
    ):
        raise ValueError("Follow-up campaign is incomplete")
    manifest = read(candidate_root / "manifest.json")
    if (
        manifest.get("software_tests_passed") is not True
        or manifest.get("baseline_id") != retry_audit["baseline_id"]
    ):
        raise ValueError("Follow-up software admission or Native identity is missing")
    for relative, expected in manifest["sha256"].items():
        if unified.digest_bytes((candidate_root / relative).read_bytes()) != expected:
            raise ValueError(f"Follow-up capsule changed: {relative}")
    native_contract = read(native_root / "common-contract.json")
    plans = read(candidate_root / "manager-plans.json")
    followup.validate_plans(plans, native_contract["native_command"])
    native_contract_sha = unified.digest_bytes(
        (native_root / "common-contract.json").read_bytes()
    )
    arms = {
        arm: unified.checked_arm(candidate_root, arm, plans) for arm in followup.ARMS
    }
    native = unified.checked_arm(
        native_root, "native", read(native_root / "manager-plans.json")
    )
    retry_tiering = unified.checked_arm(
        retry_root, "tiering", plans=read(retry_root / "manager-plans.json")
    )
    previous_release = retry_tiering["state"]["hbm_after_stop"]["observed_unix"]
    seen_pids: set[int] = {
        row["custody"]["server_pid"]
        for row in (
            unified.checked_arm(
                native_root, "native", read(native_root / "manager-plans.json")
            ),
            unified.checked_arm(
                retry_root,
                "mooncake",
                read(retry_root / "manager-plans.json"),
                "mooncake-measured-r2",
            ),
            retry_tiering,
        )
    }
    for arm in followup.ARMS:
        checked = arms[arm]
        metadata = checked["metadata"]
        if (
            metadata.get("shared_native_baseline_id") != retry_audit["baseline_id"]
            or metadata.get("shared_native_contract_sha256") != native_contract_sha
            or metadata.get("runtime_source_files") != manifest["external_sha256"]
            or metadata.get("prepared_workload_sha256")
            != native_contract["workload_sha256"]
            or followup.normalized(checked["custody"]["serving_child"]["argv"], arm)
            != native_contract["native_command"]
        ):
            raise ValueError(f"{arm} is not bound to the one phase9 Native")
        started = checked["windows"]["qualification"][0]["started_at_unix"]
        if started < previous_release:
            raise ValueError("Follow-up service started before prior release")
        previous_release = checked["state"]["hbm_after_stop"]["observed_unix"]
        pid = checked["custody"]["server_pid"]
        if pid in seen_pids:
            raise ValueError("Follow-up service lifecycle was reused")
        seen_pids.add(pid)
    rows = []
    for arm, checked in arms.items():
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
        len(rows) != 10
        or len({row["run_id"] for row in rows}) != 10
        or len({row["baseline_run_id"] for row in rows}) != 5
    ):
        raise ValueError("Follow-up does not reuse exactly one five-point Native")
    return {
        "passed": True,
        "evidence_kind": "derived-artifact",
        "source_kind": "real-online",
        "baseline_id": retry_audit["baseline_id"],
        "contract_sha256": native_contract_sha,
        "native_series_count": 1,
        "rows": rows,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            audit(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])), indent=2
        )
    )
