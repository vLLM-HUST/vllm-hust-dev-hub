"""Validate the exact generated capsule without starting any service."""

import json
import subprocess
import sys
from pathlib import Path

from contract import digest, verify

ROOT = Path("/home/coder/frontier-mods-qwen35-20260925/phase9-unified-r3")
HERE = Path(__file__).resolve().parent


def main():
    command = [sys.executable, "-m", "pytest", str(HERE / "test_contract.py"), "-q"]
    run = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (ROOT / "software-tests.log").write_text(run.stdout + run.stderr)
    if run.returncode or "10 passed" not in run.stdout or "skipped" in run.stdout:
        raise RuntimeError("Generated-capsule software tests incomplete")
    verify(ROOT)
    receipt = {
        "passed": True,
        "command": command,
        "exit_code": run.returncode,
        "tests_stdout": run.stdout,
        "sources": {
            str(p): digest(p)
            for p in [
                HERE / "contract.py",
                HERE / "test_contract.py",
                ROOT / "contract.py",
                ROOT / "qualify.py",
                ROOT / "run_campaign.py",
                ROOT / "common-contract.json",
            ]
        },
    }
    (ROOT / "software-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    manifest = json.loads((ROOT / "manifest.json").read_text())
    manifest["software_tests_passed"] = True
    manifest["sha256"][str(ROOT / "software-receipt.json")] = digest(
        ROOT / "software-receipt.json"
    )
    manifest["software_receipt"] = str(ROOT / "software-receipt.json")
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": True,
                "contract": digest(ROOT / "common-contract.json"),
                "arms": ["native", "mooncake", "tiering"],
                "native_series_count": 1,
            }
        )
    )


if __name__ == "__main__":
    main()
