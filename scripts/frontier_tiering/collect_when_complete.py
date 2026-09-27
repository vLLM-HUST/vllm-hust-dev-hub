"""Collect and validate the completed pair; leave publication for visual review."""

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

REMOTE = "/home/coder/frontier-mods-qwen35-20260925/phase6/serving-r8"
SSH = [
    "ssh",
    "-p",
    "31769",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "root@223.92.35.180",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(site, output):
    state = {"stage": "waiting", "passed": False}

    def write():
        temporary = output / "status.tmp"
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(output / "status.json")

    try:
        lock = json.loads((output / "manifest.json").read_text())
        for name, expected in lock["source_sha256"].items():
            if sha(output / name) != expected:
                raise RuntimeError(f"Collector source changed: {name}")
        deadline = time.monotonic() + 6 * 3600
        write()
        while True:
            result = subprocess.run(
                SSH + [f"cat {REMOTE}/receipts/matched-curves-r1/status.json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            result.check_returncode()
            pair = json.loads(result.stdout)
            state["pair"] = pair
            write()
            if pair.get("error"):
                raise RuntimeError("Measured pair failed; nothing was imported")
            if pair.get("passed") is True:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Measured pair did not complete within six hours")
            time.sleep(30)
        state["stage"] = "collecting"
        write()
        archive = output / "serving-r8.tar.gz"
        with archive.open("xb") as stream:
            subprocess.run(
                SSH
                + [
                    f"tar -C {REMOTE.rsplit('/', 1)[0]} --exclude='*.log' "
                    "--exclude='*.log.*' --exclude='*.sock' --exclude='__pycache__' "
                    "-czf - serving-r8"
                ],
                stdout=stream,
                check=True,
                timeout=180,
            )
        state["archive_sha256"] = sha(archive)
        with tarfile.open(archive) as source:
            members = source.getmembers()
            for member in members:
                path = Path(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or path.parts[0] != "serving-r8"
                    or not (member.isfile() or member.isdir())
                ):
                    raise ValueError("Unexpected archive member")
            source.extractall(output, members=members)
        for name, expected in lock["site_inputs_sha256"].items():
            if sha(site / name) != expected:
                raise RuntimeError(f"Website input changed during measurement: {name}")
        state["stage"] = "validating-and-rendering"
        write()
        scripts = Path(__file__).parent
        subprocess.run(
            [
                sys.executable,
                str(scripts / "import_results.py"),
                "--site",
                str(site),
                "--artifacts",
                str(output / "serving-r8"),
                "--evidence-url",
                "https://github.com/vLLM-HUST/vllm-hust-website/blob/main/docs/FRONTIER-KV-TIERING-20260926.md",
                "--artifact-base-url",
                "https://vllm-hust.sage.org.ai/reports/frontier-managed-tiering-20260926",
            ],
            check=True,
        )
        subprocess.run(
            [sys.executable, str(scripts / "render_report.py"), "--site", str(site)],
            check=True,
        )
        evidence = json.loads(
            (site / "data/leaderboard_frontier_swe_evidence.json").read_text()
        )
        archive_root = site / "reports/frontier-managed-tiering-20260926"
        for row in evidence["runs"]:
            if "managed-tiering" not in row.get("point_id", ""):
                continue
            path = archive_root / row["requests_artifact_url"].rsplit("/", 1)[1]
            if (
                sha(path) != row["requests_artifact_sha256"]
                or hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest()
                != row["requests_content_sha256"]
            ):
                raise ValueError("Published request artifact hash mismatch")
        state.update(passed=True, stage="ready-for-visual-review", published=False)
    except BaseException as exc:
        state.update(stage="failed", error=f"{type(exc).__name__}: {exc}")
        (output / "FAILED.txt").write_text(state["error"] + "\n")
        raise
    finally:
        write()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.site, args.output)
