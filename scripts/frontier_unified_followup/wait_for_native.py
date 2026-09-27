"""Start follow-up candidates only after phase9 fully passes and releases devices."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from qualify import CTL, ROOT, owners, write

NATIVE_STATUS = (
    Path("/home/coder/frontier-mods-qwen35-20260925")
    / "phase9-unified-r3/receipts/shared-native-r1/status.json"
)


def main() -> None:
    status_path = ROOT / "receipts/followup-waiter-status.json"
    state = {"passed": False, "stage": "waiting-for-shared-native"}
    write(status_path, state)
    deadline = time.monotonic() + 24 * 3600
    while time.monotonic() < deadline:
        source = json.loads(NATIVE_STATUS.read_text())
        if source.get("error"):
            raise RuntimeError(f"Shared Native campaign failed: {source['error']}")
        if source.get("passed") is True:
            if source.get("active_arm") is not None or owners():
                raise RuntimeError("Shared Native passed without releasing devices")
            break
        time.sleep(30)
    else:
        raise TimeoutError("Shared Native did not complete within 24 hours")
    state["stage"] = "starting-followup"
    write(status_path, state)
    subprocess.run(CTL + ["start", "campaign"], check=True, timeout=20)
    state.update(passed=True, stage="followup-started")
    write(status_path, state)


if __name__ == "__main__":
    main()
