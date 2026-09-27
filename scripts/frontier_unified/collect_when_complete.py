"""Durably collect and audit the one-Native campaign; never launch or publish."""

import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE = "/home/coder/frontier-mods-qwen35-20260925/phase9-unified-r3"
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


def write(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output):
    output = Path(output).resolve()
    output.mkdir(exist_ok=False, parents=True)
    status = {
        "passed": False,
        "stage": "waiting",
        "remote": REMOTE,
        "baseline_series_count": 1,
    }
    sources = [
        p
        for d in [
            "frontier_unified",
            "frontier_mooncake",
            "frontier_tiering",
            "frontier_dla",
            "frontier_pipeline",
            "frontier_runtime",
        ]
        for p in (HERE.parent / d).glob("*.py")
    ]
    frozen = {str(p): sha(p) for p in sources}
    write(output / "collector-source-lock.json", frozen)
    deadline = time.monotonic() + 24 * 3600
    try:
        while time.monotonic() < deadline:
            result = subprocess.run(
                SSH + ["cat " + REMOTE + "/receipts/shared-native-r1/status.json"],
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
            raise TimeoutError("Campaign collection deadline")
        status["stage"] = "collecting"
        write(output / "status.json", status)
        archive_remote = REMOTE + "-results.tar.gz"
        command = (
            "tar --exclude=./bundles --exclude=./__pycache__ --exclude=./supervisor.sock --exclude=./tiering-storage -C "
            + REMOTE
            + " -czf "
            + archive_remote
            + " ."
        )
        subprocess.run(SSH + [command], check=True, capture_output=True, timeout=600)
        expected = subprocess.check_output(
            SSH + ["sha256sum " + archive_remote], text=True, timeout=30
        ).split()[0]
        archive = output / "results.tar.gz"
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
        if sha(archive) != expected:
            raise ValueError("Transferred archive hash differs")
        root = output / "capsule"
        root.mkdir()
        with tarfile.open(archive, "r:gz") as handle:
            for member in handle.getmembers():
                target = (root / member.name).resolve()
                if not target.is_relative_to(root) or not (
                    member.isfile() or member.isdir()
                ):
                    raise ValueError("Unexpected archive member")
            handle.extractall(root)
        status["archive_sha256"] = expected
        if not state.get("passed"):
            raise RuntimeError(
                "Campaign failed; evidence collected without performance claims"
            )
        if any(sha(Path(p)) != digest for p, digest in frozen.items()):
            raise RuntimeError("Collector/auditor sources changed while waiting")
        result = subprocess.run(
            [sys.executable, str(HERE / "audit_results.py"), str(root)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        (output / "audit.log").write_text(result.stderr)
        if result.returncode:
            raise RuntimeError("Unified raw-data audit failed")
        audit = json.loads(result.stdout)
        write(output / "unified-audit.json", audit)
        status.update(
            passed=True,
            stage="ready-for-publication-review",
            published=False,
            points=len(audit["rows"]),
        )
    except BaseException as exc:
        status.update(stage="failed", error=f"{type(exc).__name__}: {exc}")
        (output / "FAILED.txt").write_text(status["error"] + "\n")
        raise
    finally:
        write(output / "status.json", status)


if __name__ == "__main__":
    main(sys.argv[1])
