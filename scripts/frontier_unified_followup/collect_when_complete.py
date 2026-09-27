"""Durably collect and audit shared-Native BidKV/DLA follow-up results."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE = "/home/coder/frontier-mods-qwen35-20260925/phase10-followup-r1"
BASELINE_COLLECTION = Path(
    "/home/shuhao/vllm-hust-dev-hub/.planning/"
    "unified-native-frontier-20260927/collection-r1"
)
SSH = [
    "ssh",
    "-p",
    "31769",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
    "root@223.92.35.180",
]


def write(path: Path, data: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output: str) -> None:
    output = Path(output).resolve()
    output.mkdir(exist_ok=False, parents=True)
    status = {
        "passed": False,
        "stage": "waiting",
        "remote": REMOTE,
        "baseline_series_count": 1,
    }
    sources = [
        path
        for directory in (
            "frontier_unified",
            "frontier_unified_followup",
            "frontier_mooncake",
            "frontier_tiering",
            "frontier_dla",
            "frontier_pipeline",
            "frontier_runtime",
        )
        for path in (HERE.parent / directory).glob("*.py")
    ]
    frozen = {str(path): digest(path) for path in sources}
    write(output / "collector-source-lock.json", frozen)
    deadline = time.monotonic() + 24 * 3600
    state = None
    try:
        while time.monotonic() < deadline:
            result = subprocess.run(
                SSH
                + ["cat " + REMOTE + "/receipts/shared-native-followup-r1/status.json"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            if result.returncode:
                status["last_poll_error"] = result.stderr[-1000:]
            else:
                state = json.loads(result.stdout)
                status["campaign"] = state
                write(output / "remote-status.json", state)
                if state.get("passed") is True or state.get("error"):
                    break
            write(output / "status.json", status)
            time.sleep(60)
        else:
            raise TimeoutError("Follow-up collection deadline")
        status["stage"] = "collecting"
        write(output / "status.json", status)
        archive_remote = REMOTE + "-results.tar.gz"
        command = (
            "tar --exclude=./bundles --exclude=./__pycache__ "
            "--exclude=./supervisor.sock -C "
            + REMOTE
            + " -czf "
            + archive_remote
            + " ."
        )
        subprocess.run(SSH + [command], check=True, capture_output=True, timeout=600)
        expected = subprocess.check_output(
            SSH + ["sha256sum " + archive_remote], text=True, timeout=30
        ).split()[0]
        archive = output / "candidate-results.tar.gz"
        subprocess.run(
            [
                "scp",
                "-q",
                "-P",
                "31769",
                "root@223.92.35.180:" + archive_remote,
                str(archive),
            ],
            check=True,
            timeout=600,
        )
        if digest(archive) != expected:
            raise ValueError("Transferred follow-up archive hash differs")
        candidate = output / "candidate-capsule"
        candidate.mkdir()
        with tarfile.open(archive, "r:gz") as handle:
            for member in handle.getmembers():
                target = (candidate / member.name).resolve()
                if not target.is_relative_to(candidate) or not (
                    member.isfile() or member.isdir()
                ):
                    raise ValueError("Unexpected follow-up archive member")
            handle.extractall(candidate)
        status["archive_sha256"] = expected
        if state is None or not state.get("passed"):
            raise RuntimeError("Follow-up failed; collected without performance claims")
        while time.monotonic() < deadline:
            baseline_status_path = BASELINE_COLLECTION / "status.json"
            if baseline_status_path.exists():
                baseline_status = json.loads(baseline_status_path.read_text())
                if baseline_status.get("passed") is True:
                    break
                if baseline_status.get("stage") == "failed":
                    raise RuntimeError("Shared Native collection failed")
            time.sleep(30)
        else:
            raise TimeoutError("Shared Native collection deadline")
        if any(digest(Path(path)) != expected for path, expected in frozen.items()):
            raise RuntimeError("Collector/auditor sources changed while waiting")
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "audit_results.py"),
                str(candidate),
                str(BASELINE_COLLECTION / "capsule"),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        (output / "audit.log").write_text(result.stderr)
        if result.returncode:
            raise RuntimeError("Follow-up raw-data audit failed")
        audit = json.loads(result.stdout)
        write(output / "followup-audit.json", audit)
        status.update(
            passed=True,
            stage="ready-for-publication-review",
            published=False,
            points=len(audit["rows"]),
            baseline_collection=str(BASELINE_COLLECTION),
            baseline_archive_sha256=baseline_status["archive_sha256"],
        )
    except BaseException as exc:
        status.update(stage="failed", error=f"{type(exc).__name__}: {exc}")
        (output / "FAILED.txt").write_text(status["error"] + "\n")
        raise
    finally:
        write(output / "status.json", status)


if __name__ == "__main__":
    main(sys.argv[1])
