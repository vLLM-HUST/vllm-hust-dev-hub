"""Start BidKV/DLA after the candidate retry passes and releases all devices."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
FOLLOWUP = BASE / "phase10-followup-r1"
RETRY_STATUS = (
    BASE / "phase9-unified-retry-r1/receipts/shared-native-retry-r1/status.json"
)
NATIVE_STATUS = BASE / "phase9-unified-r3/receipts/native-measured-r1/status.json"
CTL = [
    "/usr/local/python3.12.13/bin/supervisorctl",
    "-c",
    str(FOLLOWUP / "supervisord.conf"),
]


def write(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main() -> None:
    status_path = Path(__file__).resolve().parent / "status.json"
    state = {"passed": False, "stage": "waiting-for-candidate-retry"}
    write(status_path, state)
    deadline = time.monotonic() + 24 * 3600
    while time.monotonic() < deadline:
        retry = json.loads(RETRY_STATUS.read_text())
        if retry.get("error"):
            raise RuntimeError(f"Candidate retry failed: {retry['error']}")
        if retry.get("passed") is True:
            if retry.get("active_arm") is not None:
                raise RuntimeError("Candidate retry passed with an active arm")
            native = json.loads(NATIVE_STATUS.read_text())
            if native.get("passed") is not True or native.get("stage") != "completed":
                raise RuntimeError("The one Native baseline is no longer valid")
            sys.path.insert(0, str(FOLLOWUP))
            from qualify import owners

            if owners():
                raise RuntimeError("Candidate retry passed without releasing devices")
            break
        time.sleep(30)
    else:
        raise TimeoutError("Candidate retry did not finish within 24 hours")
    state["stage"] = "starting-followup"
    write(status_path, state)
    subprocess.run(CTL + ["start", "campaign"], check=True, timeout=20)
    state.update(passed=True, stage="followup-started")
    write(status_path, state)


if __name__ == "__main__":
    main()
