#!/usr/bin/env python3
"""Managed Sage Mate A/B orchestrator for the bounded BidKV matrix.

The orchestrator changes only systemd manager environment overrides and invokes
Sage Mate's own manage.sh. Its finally block removes every override and restores
the original production service. NPU4-7 are checked, never selected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAGE = Path("/home/shuhao/sage-mate")
MANAGE = SAGE / "manage.sh"
WORKLOAD = ROOT / "scripts/bidkv_matrix_workload.py"
ANALYZER = ROOT / "scripts/analyze_bidkv_matrix.py"
INDEXER = ROOT / "scripts/index_bidkv_evidence.py"
MATRIX = ROOT / "config/bidkv-tp4-graph-matrix.json"
UNIT = "sage-mate-vllm-engine.service"
CONTAINER_LOG = Path(
    "/home/shuhao/sage-mate-runtime-private/logs/sage-mate-vllm-engine.redacted.log"
)
BASELINE_IMAGE = "sage-mate/bidkv-main-requal:baseline-a4d6aa0-2c8c722-r2"
CANDIDATE_IMAGE = "sage-mate/bidkv-main-requal:candidate-a4d6aa0-2c8c722-199e0bd-r1"
BASELINE_IMAGE_ID = (
    "sha256:80f05c0d0c49c139f94922ae6057e3edb21251b8e8a332c1df35fb3d555d60d8"
)
CANDIDATE_IMAGE_ID = (
    "sha256:a4e042e304507b3fa03f51c319098edb8173d32ebd5d5a5704ff842ef0a1ed77"
)
OVERRIDE_KEYS = (
    "VLLM_ENGINE_IMAGE",
    "VLLM_ENGINE_EXPECTED_IMAGE_ID",
    "VLLM_ENGINE_RECREATE_CONTAINER",
    "VLLM_ENGINE_VLLM_VERSION",
    "VLLM_ENGINE_INSTALLED_MODULES_JSON",
    "VLLM_ENGINE_KV_CACHE_MEMORY_BYTES",
    "VLLM_ENGINE_EXTRA_ARGS_JSON",
    "VLLM_ENGINE_EXTRA_ENV_PREFIXES",
    "BIDKV_UTILITY_ENABLE",
    "BIDKV_UTILITY_STRATEGY",
    "BIDKV_UTILITY_LIVENESS_PREEMPTIONS",
    "BIDKV_UTILITY_COMPLETION_WEIGHT",
    "BIDKV_UTILITY_PREEMPT_WEIGHT",
    "BIDKV_UTILITY_KV_GATE",
    "BIDKV_UTILITY_COOLDOWN_S",
    "BIDKV_UTILITY_MIN_RUNNING",
    "BIDKV_UTILITY_CASCADE_GAIN_RATIO",
)


def run(
    command: list[str], *, check: bool = True, output: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, cwd=SAGE, text=True, capture_output=True, check=False
    )
    if output:
        output.write_text(result.stdout + result.stderr)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {shlex.join(command)}\n{result.stderr[-2000:]}"
        )
    return result


def nonsecret_env_value(name: str) -> str:
    for line in (SAGE / ".env").read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1]
    raise RuntimeError(f"missing {name} in managed Sage Mate environment")


def manager_environment(values: dict[str, str]) -> None:
    run(["systemctl", "--user", "unset-environment", *OVERRIDE_KEYS])
    if values:
        run(
            [
                "systemctl",
                "--user",
                "set-environment",
                *[f"{key}={value}" for key, value in values.items()],
            ]
        )


def health_ready(timeout_s: int = 900) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8001/health", timeout=3
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("managed engine did not become healthy before timeout")


def snapshot(command: list[str], path: Path) -> None:
    result = run(command, check=False)
    path.write_text(result.stdout + result.stderr)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot() -> dict[str, object]:
    files = (
        "scripts/bidkv_matrix_workload.py",
        "scripts/run_bidkv_matrix.py",
        "config/bidkv-tp4-graph-matrix.json",
    )
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", *files],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    return {
        "status": "captured-at-suite-start",
        "commit": commit,
        "dirty_state": "dirty" if dirty else "clean",
        "dirty_paths": dirty,
        "files": {relative: file_sha256(ROOT / relative) for relative in files},
    }


def metrics(path: Path) -> None:
    with urllib.request.urlopen(
        "http://127.0.0.1:8001/metrics", timeout=10
    ) as response:
        path.write_bytes(response.read())


def image_id() -> str:
    result = run(
        [
            "sudo",
            "-n",
            "docker",
            "ps",
            "--filter",
            "name=sage-mate-vllm-",
            "--format",
            "{{.ID}} {{.Image}}",
        ]
    )
    rows = [row for row in result.stdout.splitlines() if row.strip()]
    if len(rows) != 1:
        raise RuntimeError(f"expected one Sage Mate engine container, got {rows}")
    return rows[0]


def warmup(output: Path) -> None:
    command = [
        sys.executable,
        str(WORKLOAD),
        "--cell",
        "warmup",
        "--arm",
        "baseline",
        "--workload",
        "correctness",
        "--concurrency",
        "1",
        "--max-tokens",
        "16",
        "--output",
        str(output),
    ]
    run(command, output=output.with_suffix(".stdout"))


def arm_values(
    cell: dict[str, object], arm: str, base_args: list[str]
) -> dict[str, str]:
    values = {
        "VLLM_ENGINE_IMAGE": BASELINE_IMAGE if arm == "baseline" else CANDIDATE_IMAGE,
        "VLLM_ENGINE_EXPECTED_IMAGE_ID": BASELINE_IMAGE_ID
        if arm == "baseline"
        else CANDIDATE_IMAGE_ID,
        "VLLM_ENGINE_RECREATE_CONTAINER": "true",
        "VLLM_ENGINE_VLLM_VERSION": "0.28.1rc1.dev391+ga4d6aa022",
        "VLLM_ENGINE_INSTALLED_MODULES_JSON": json.dumps(
            {
                "vllm": {
                    "distribution": "vllm",
                    "version": "0.28.1rc1.dev391+ga4d6aa022",
                },
                "vllm_ascend": {
                    "distribution": "vllm-ascend",
                    "version": "0.25.1rc1+hust.20260903.4",
                },
            },
            separators=(",", ":"),
        ),
        "VLLM_ENGINE_KV_CACHE_MEMORY_BYTES": str(cell["kv_cache_bytes"]),
    }
    args = list(base_args)
    if arm == "candidate":
        args += [
            "--preemption-policy",
            "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy",
        ]
        config = cell["config"]
        assert isinstance(config, dict)
        values.update(
            {
                "VLLM_ENGINE_EXTRA_ENV_PREFIXES": "BIDKV_UTILITY_",
                "BIDKV_UTILITY_ENABLE": "1",
                "BIDKV_UTILITY_STRATEGY": "bidkv",
                "BIDKV_UTILITY_LIVENESS_PREEMPTIONS": str(
                    config["liveness_preemptions"]
                ),
                "BIDKV_UTILITY_COMPLETION_WEIGHT": str(config["completion_weight"]),
                "BIDKV_UTILITY_PREEMPT_WEIGHT": str(config["preempt_weight"]),
                "BIDKV_UTILITY_KV_GATE": str(config["kv_gate"]),
                "BIDKV_UTILITY_COOLDOWN_S": str(config["cooldown_s"]),
                "BIDKV_UTILITY_MIN_RUNNING": str(config["min_running"]),
                "BIDKV_UTILITY_CASCADE_GAIN_RATIO": str(
                    config.get("cascade_gain_ratio", 1.25)
                ),
            }
        )
    values["VLLM_ENGINE_EXTRA_ARGS_JSON"] = json.dumps(args, separators=(",", ":"))
    return values


def run_arm(cell: dict[str, object], arm: str, root: Path) -> None:
    arm_dir = root / str(cell["id"]) / arm
    arm_dir.mkdir(parents=True, exist_ok=False)
    base_args = json.loads(nonsecret_env_value("VLLM_ENGINE_EXTRA_ARGS_JSON"))
    values = arm_values(cell, arm, base_args)
    (arm_dir / "configuration.json").write_text(json.dumps(values, indent=2) + "\n")
    started = time.time()
    log_offset = CONTAINER_LOG.stat().st_size if CONTAINER_LOG.exists() else 0
    manager_environment(values)
    run(
        [str(MANAGE), "restart", "--with-vllm-engine"],
        output=arm_dir / "managed-restart.log",
    )
    health_ready()
    (arm_dir / "container.txt").write_text(image_id() + "\n")
    snapshot(["npu-smi", "info"], arm_dir / "npu-ready.txt")
    if arm == "candidate":
        snapshot(
            [
                "sudo",
                "-n",
                "docker",
                "exec",
                "sage-mate-vllm-shuhao-sage-mate",
                "sh",
                "-c",
                'for p in /proc/[0-9]*; do tr "\\000" "\\n" < "$p/environ" 2>/dev/null | grep -q "^BIDKV_UTILITY_ENABLE=" || continue; echo pid=${p##*/}; tr "\\000" "\\n" < "$p/environ" | grep "^BIDKV_UTILITY_" | sort; done',
            ],
            arm_dir / "bidkv-child-environment.txt",
        )
    warmup(arm_dir / "warmup.json")
    metrics(arm_dir / "metrics-before.prom")
    command = [
        sys.executable,
        str(WORKLOAD),
        "--cell",
        str(cell["id"]),
        "--arm",
        arm,
        "--workload",
        str(cell["workload"]),
        "--concurrency",
        str(cell["concurrency"]),
        "--max-tokens",
        str(cell["max_tokens"]),
        "--output",
        str(arm_dir / "workload.json"),
    ]
    if cell.get("cancel_after_s") is not None:
        command += ["--cancel-after-s", str(cell["cancel_after_s"])]
    run(command, output=arm_dir / "workload-summary.txt")
    metrics(arm_dir / "metrics-after.prom")
    snapshot(
        [
            "journalctl",
            "--user",
            "-u",
            UNIT,
            "--since",
            f"@{int(started)}",
            "--no-pager",
        ],
        arm_dir / "engine.log",
    )
    if CONTAINER_LOG.exists():
        with CONTAINER_LOG.open("rb") as source:
            source.seek(log_offset)
            (arm_dir / "runtime.log").write_bytes(source.read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cells", help="comma-separated cell IDs; default is all stage-1 cells"
    )
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()
    matrix = json.loads(MATRIX.read_text())
    selected = set(args.cells.split(",")) if args.cells else None
    cells = [
        cell for cell in matrix["cells"] if selected is None or cell["id"] in selected
    ]
    if not cells or (selected and {cell["id"] for cell in cells} != selected):
        raise SystemExit("unknown or empty cell selection")
    if args.repetitions < 1:
        raise SystemExit("repetitions must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "matrix.json").write_text(
        json.dumps({**matrix, "cells": cells}, indent=2) + "\n"
    )
    (args.output / "started-at.txt").write_text(
        datetime.now(timezone.utc).isoformat() + "\n"
    )
    (args.output / "source-snapshot.json").write_text(
        json.dumps(source_snapshot(), indent=2) + "\n"
    )
    snapshot(["npu-smi", "info"], args.output / "npu-preflight.txt")
    snapshot(
        [str(MANAGE), "status", "--with-vllm-engine", "--json"],
        args.output / "production-status-before.txt",
    )
    (args.output / "production-image-before.txt").write_text(image_id() + "\n")
    try:
        for repetition in range(args.repetitions):
            repetition_root = (
                args.output
                if args.repetitions == 1
                else args.output / f"repeat-{repetition + 1:02d}"
            )
            repetition_root.mkdir(parents=True, exist_ok=args.repetitions == 1)
            for index, cell in enumerate(cells):
                order = (
                    ("baseline", "candidate")
                    if (index + repetition) % 2 == 0
                    else ("candidate", "baseline")
                )
                for arm in order:
                    run_arm(cell, arm, repetition_root)
        run(
            [sys.executable, str(ANALYZER), str(args.output)],
            output=args.output / "analysis-summary.txt",
        )
    finally:
        manager_environment({})
        run(
            [str(MANAGE), "restart", "--with-vllm-engine"],
            check=False,
            output=args.output / "production-restore.log",
        )
        try:
            health_ready()
            (args.output / "production-image-after.txt").write_text(image_id() + "\n")
        finally:
            snapshot(["npu-smi", "info"], args.output / "npu-after-restore.txt")
            (args.output / "finished-at.txt").write_text(
                datetime.now(timezone.utc).isoformat() + "\n"
            )
            run(
                [sys.executable, str(INDEXER), str(args.output)],
                check=False,
                output=args.output / "evidence-index.log",
            )


if __name__ == "__main__":
    main()
