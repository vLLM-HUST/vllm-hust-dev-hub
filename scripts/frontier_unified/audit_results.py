"""Audit one Native and all admitted candidates from raw real-online receipts."""

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

from contract import ARMS, normalize, validate_plans

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "frontier_mooncake"))
spec = importlib.util.spec_from_file_location(
    "unified_mooncake_validators", HERE.parent / "frontier_mooncake/import_results.py"
)
mooncake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mooncake)

CELLS = (1, 2, 4, 8, 16)
read = mooncake.read


def digest_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_arm(root, arm, plans, attempt=None):
    run = root / "receipts" / (attempt or f"{arm}-measured-r1")
    if (run / "FAILED.txt").exists():
        raise ValueError("Failed arm marker exists")
    state, custody = read(run / "status.json"), read(run / "custody.json")
    mooncake.validate_release(state, arm)
    meta = read(root / f"metadata-{arm}.json")
    if (
        custody.get("kind") != "real-online"
        or custody.get("program") != arm
        or custody["serving_child"]["argv"] != plans[arm]
        or meta["manager"]["qualified_command"] != plans[arm]
        or custody["server_pid"] != state["server_pid"]
        or state["owned_server_processes"]["pgid"] != custody["server_pid"]
        or "vllm-hust-ext" not in custody["command"]
    ):
        raise ValueError("Manager actual argv or process custody mismatch")
    if meta["mods"] != ([] if arm == "native" else [arm]):
        raise ValueError("Arm MOD identity mismatch")
    if (
        digest_bytes((root / f"launch-{arm}.sh").read_bytes())
        != meta["launch_script_sha256"]
    ):
        raise ValueError("Launcher metadata identity mismatch")
    log = (root / "receipts" / f"{arm}.log").read_text(errors="replace")
    if any(marker in log for marker in mooncake.support.FATAL):
        raise ValueError("Fatal arm log")
    gate = read(run / "retrieval/summary.json")
    if gate.get("passed") is not True or gate.get("completed_requests") != 26:
        raise ValueError("Incomplete retrieval gate")
    prefix = read(run / "prefix-reuse.json")
    hits = mooncake.tiering.prefix_hits(
        run / "qualification-after.prom"
    ) - mooncake.tiering.prefix_hits(run / "qualification-before.prom")
    if (
        prefix.get("passed") is not True
        or hits <= 0
        or prefix.get("hit_token_delta") != hits
    ):
        raise ValueError("Prefix gate lacks observed reuse")
    entries = state["windows"]
    if [entry["name"] for entry in entries] != ["qualification"] + [
        f"c{c}" for c in CELLS
    ] or any(entry["exit_code"] != 0 for entry in entries):
        raise ValueError("Full ordered six-window protocol missing")
    windows, previous_end = {}, None
    for index, cell in enumerate(["qualification"] + [f"c{c}" for c in CELLS]):
        config, summary = (
            read(run / cell / "config.json"),
            read(run / cell / "summary.json"),
        )
        if entries[index]["summary"] != summary or config["server_metadata"] != meta:
            raise ValueError("Window receipt or metadata mismatch")
        if cell == "qualification":
            if (
                config["duration"] != 60
                or config["concurrency"] != 2
                or config["chips"] != 2
                or summary["measurement_seconds"] != 60
                or not summary["valid"]
                or summary["failed_requests"]
                or summary["aborted"]
            ):
                raise ValueError("Invalid 60-second prefix gate")
        else:
            mooncake.tiering.validate_window(config, summary)
            if config["concurrency"] != int(cell[1:]):
                raise ValueError("Concurrency cell mismatch")
        mooncake.tiering.validate_requests(run / cell / "requests.jsonl", summary)
        if previous_end is not None and config["started_at_unix"] < previous_end:
            raise ValueError("Windows overlap or are out of order")
        previous_end = config["started_at_unix"] + config["duration"]
        numeric = (
            ("output_tokens_per_second",)
            if cell == "qualification"
            else (
                "output_tokens_per_second",
                "decode_tokens_per_second_p90",
                "ttft_seconds_p95",
            )
        )
        if any(not math.isfinite(summary[key]) or summary[key] < 0 for key in numeric):
            raise ValueError("Invalid numeric performance metric")
        windows[cell] = (config, summary)
    if state["hbm_after_stop"]["observed_unix"] < previous_end:
        raise ValueError("Release sample predates completed measurement")
    return dict(
        state=state,
        custody=custody,
        metadata=meta,
        windows=windows,
        gate=gate,
        prefix=prefix,
        run=run,
    )


def audit(root):
    root = Path(root)
    campaign = read(root / "receipts/shared-native-r1/status.json")
    if (
        campaign.get("passed") is not True
        or campaign.get("active_arm") is not None
        or campaign.get("error")
    ):
        raise ValueError("Shared-Native campaign incomplete")
    if [r["arm"] for r in campaign["arms"]] != list(ARMS) or not all(
        r["passed"] for r in campaign["arms"]
    ):
        raise ValueError(
            "Exactly one Native followed by admitted candidates is required"
        )
    manifest = read(root / "manifest.json")
    software = read(root / "software-receipt.json")
    if (
        manifest.get("software_tests_passed") is not True
        or software.get("passed") is not True
        or software.get("exit_code") != 0
    ):
        raise ValueError("Software admission is missing")
    contract = read(root / "common-contract.json")
    contract_sha = digest_bytes((root / "common-contract.json").read_bytes())
    plans = read(root / "manager-plans.json")
    validate_plans(plans)
    if plans["native"] != contract["native_command"]:
        raise ValueError("Native command changed")
    arms = {arm: checked_arm(root, arm, plans) for arm in ARMS}
    previous = None
    seen_pids = set()
    for arm, checked in arms.items():
        metadata = checked["metadata"]
        if (
            metadata.get("shared_native_contract_sha256") != contract_sha
            or metadata.get("shared_native_baseline_id") != contract["baseline_id"]
        ):
            raise ValueError("Candidate uses a different Native")
        if (
            metadata["runtime_source_files"] != contract["runtime_source_files"]
            or metadata["prepared_workload_sha256"] != contract["workload_sha256"]
        ):
            raise ValueError("Shared runtime/workload mismatch")
        remote = Path(metadata["launch_environment_source"]["path"]).parent
        filenames = [
            "common-contract.json",
            "manager-plans.json",
            "qualify.py",
            "run_campaign.py",
            "contract.py",
            "software-receipt.json",
            "supervisord.conf",
            f"metadata-{arm}.json",
            f"launch-{arm}.sh",
            f"manager-{arm}.json",
        ]
        for name in filenames:
            if manifest["sha256"].get(str(remote / name)) != digest_bytes(
                (root / name).read_bytes()
            ):
                raise ValueError(f"Frozen capsule changed: {name}")
        if (
            normalize(checked["custody"]["serving_child"]["argv"], arm)
            != contract["native_command"]
        ):
            raise ValueError("Actual launch is not bound to the one Native")
        pid = checked["custody"]["server_pid"]
        if pid in seen_pids:
            raise ValueError("Service lifecycle was reused")
        seen_pids.add(pid)
        if (
            previous is not None
            and checked["windows"]["qualification"][0]["started_at_unix"] < previous
        ):
            raise ValueError("Candidate started before prior resources were released")
        previous = checked["state"]["hbm_after_stop"]["observed_unix"]
    rows = []
    for arm, checked in arms.items():
        for c in CELLS:
            cfg, summary = checked["windows"][f"c{c}"]
            base = arms["native"]["windows"][f"c{c}"][1]
            rows.append(
                dict(
                    arm=arm,
                    concurrency=c,
                    run_id=cfg["run_id"],
                    baseline_run_id=arms["native"]["windows"][f"c{c}"][0]["run_id"],
                    output_tps=summary["output_tokens_per_second"],
                    native_output_tps=base["output_tokens_per_second"],
                    throughput_change_percent=100
                    * (
                        summary["output_tokens_per_second"]
                        / base["output_tokens_per_second"]
                        - 1
                    ),
                    decode_p90_tps=summary["decode_tokens_per_second_p90"],
                    ttft_p95_ms=summary["ttft_seconds_p95"] * 1000,
                )
            )
    if (
        len({row["run_id"] for row in rows}) != 15
        or len({row["baseline_run_id"] for row in rows}) != 5
    ):
        raise ValueError("Single five-point Native identity violated")
    return dict(
        passed=True,
        evidence_kind="derived-artifact",
        source_kind="real-online",
        baseline_id=contract["baseline_id"],
        contract_sha256=contract_sha,
        native_series_count=1,
        rows=rows,
    )


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1])), indent=2))
