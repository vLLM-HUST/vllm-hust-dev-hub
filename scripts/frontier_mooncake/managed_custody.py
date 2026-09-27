"""Capture the actual manager child and compare it with the recorded launch plan."""

import json
import time
from pathlib import Path


def launched_arguments(manager_pid, program, root, proc=Path("/proc"), timeout=45):
    expected = json.loads((root / "manager-plans.json").read_text())[program]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        children = proc / str(manager_pid) / "task" / str(manager_pid) / "children"
        for pid in children.read_text().split():
            try:
                argv = [
                    value.decode()
                    for value in (proc / pid / "cmdline").read_bytes().split(b"\0")
                    if value
                ]
            except FileNotFoundError:
                continue
            if "vllm.entrypoints.cli.main" not in argv:
                continue
            if argv != expected:
                raise RuntimeError(
                    "Actual manager child differs from the qualified plan"
                )
            return {"pid": int(pid), "argv": argv}
        time.sleep(0.1)
    raise TimeoutError("Could not capture the manager serving child")
