"""Collect candidate retries and audit them against the retained Native capsule."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE = "/home/coder/frontier-mods-qwen35-20260925/phase9-unified-retry-r1"
NATIVE_COLLECTION = Path(
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


def collector_sources() -> list[Path]:
    sources = [path for path in HERE.glob("*.py")]
    # frontier_tiering.import_results imports the shared Frontier importer from
    # frontier_dla at module load time. Freeze that transitive dependency too;
    # otherwise a standalone collector snapshot cannot even start its audit.
    sources.extend((HERE.parent / "frontier_dla").glob("*.py"))
    sources.extend((HERE.parent / "frontier_mooncake").glob("*.py"))
    sources.extend((HERE.parent / "frontier_tiering").glob("*.py"))
    return sources


def main(output: str) -> None:
    output = Path(output).resolve()
    output.mkdir(exist_ok=False, parents=True)
    status = {
        "passed": False,
        "stage": "waiting",
        "remote": REMOTE,
        "baseline_series_count": 1,
    }
    sources = collector_sources()
    frozen = {str(path): digest(path) for path in sources}
    write(output / "collector-source-lock.json", frozen)
    deadline = time.monotonic() + 24 * 3600
    state = None
    try:
        while time.monotonic() < deadline:
            result = subprocess.run(
                SSH
                + ["cat " + REMOTE + "/receipts/shared-native-retry-r1/status.json"],
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
            raise TimeoutError("Candidate retry collection deadline")
        status["stage"] = "collecting"
        write(output / "status.json", status)
        archive_remote = REMOTE + "-results.tar.gz"
        command = (
            "tar --exclude=./__pycache__ --exclude=./supervisor.sock -C "
            + REMOTE
            + " -czf "
            + archive_remote
            + " ."
        )
        subprocess.run(SSH + [command], check=True, capture_output=True, timeout=600)
        expected = subprocess.check_output(
            SSH + ["sha256sum " + archive_remote], text=True, timeout=30
        ).split()[0]
        archive = output / "retry-results.tar.gz"
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
            raise ValueError("Transferred retry archive hash differs")
        retry = output / "retry-capsule"
        retry.mkdir()
        with tarfile.open(archive, "r:gz") as handle:
            for member in handle.getmembers():
                target = (retry / member.name).resolve()
                if not target.is_relative_to(retry) or not (
                    member.isfile() or member.isdir()
                ):
                    raise ValueError("Unexpected retry archive member")
            handle.extractall(retry)
        status["archive_sha256"] = expected
        if state is None or not state.get("passed"):
            raise RuntimeError("Candidate retry failed; no performance claim allowed")
        native_status = json.loads((NATIVE_COLLECTION / "status.json").read_text())
        native_capsule = NATIVE_COLLECTION / "capsule"
        if (
            not native_capsule.is_dir()
            or not (
                native_capsule / "receipts/native-measured-r1/status.json"
            ).is_file()
            or not native_status.get("archive_sha256")
        ):
            raise RuntimeError("Retained Native capsule is unavailable")
        if any(
            digest(Path(path)) != digest_expected
            for path, digest_expected in frozen.items()
        ):
            raise RuntimeError("Collector/auditor sources changed while waiting")
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "audit_retry_results.py"),
                str(retry),
                str(native_capsule),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        (output / "audit.log").write_text(result.stderr)
        if result.returncode:
            raise RuntimeError("Candidate retry raw-data audit failed")
        audit = json.loads(result.stdout)
        write(output / "retry-audit.json", audit)
        status.update(
            passed=True,
            stage="ready-for-publication-review",
            published=False,
            points=len(audit["rows"]),
            native_collection=str(NATIVE_COLLECTION),
            native_archive_sha256=native_status["archive_sha256"],
        )
    except BaseException as exc:
        status.update(stage="failed", error=f"{type(exc).__name__}: {exc}")
        (output / "FAILED.txt").write_text(status["error"] + "\n")
        raise
    finally:
        write(output / "status.json", status)


if __name__ == "__main__":
    main(sys.argv[1])
