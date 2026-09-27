"""Supervised sequential controls; stop on any failed gate or release receipt."""

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from qualify import CTL, ROOT, interrupted, owners, write


def verify_parent():
    parent = Path(f"/proc/{os.getppid()}/cmdline").read_bytes()
    if b"supervisord" not in parent or str(ROOT).encode() not in parent:
        raise RuntimeError("Pair controller lacks dedicated supervisor custody")


def controller_pid(program):
    result = subprocess.run(
        CTL + ["pid", program], capture_output=True, text=True, timeout=10
    )
    # supervisorctl returns NOT_RUNNING (7), not success, for a stopped program.
    if result.returncode == 7 and result.stdout.strip() == "0":
        return 0
    if result.returncode:
        raise RuntimeError(f"Cannot query owned controller {program}")
    return int(result.stdout.strip())


def main(gate_attempt, pair_attempt="paired-measurement-r1"):
    out = ROOT / "receipts" / pair_attempt
    out.mkdir(exist_ok=False)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    state = dict(
        passed=False, controller_pid=os.getpid(), parent_pid=os.getppid(), arms=[]
    )
    active = None
    try:
        verify_parent()
        gate = json.loads(
            (ROOT / "receipts" / gate_attempt / "status.json").read_text()
        )
        if not gate["passed"] or gate["release"]["exit"] or gate["release"]["owners"]:
            raise RuntimeError(
                "Calibrated candidate qualification/release is incomplete"
            )
        for arm in ("nativepp", "pipelinepp"):
            attempt = f"{arm}-measured-r1"
            program = f"measure-{arm}"
            if (ROOT / "receipts" / attempt).exists() or owners():
                raise RuntimeError("Existing output or occupied participating devices")
            if controller_pid(program) != 0:
                raise RuntimeError("Measurement controller already active")
            active = program
            state["active_arm"] = arm
            write(out / "status.json", state)
            subprocess.run(CTL + ["start", program], check=True, timeout=20)
            pid = controller_pid(program)
            command = Path(f"/proc/{pid}/cmdline").read_bytes()
            if str(ROOT).encode() not in command or attempt.encode() not in command:
                raise RuntimeError("Unexpected measurement controller identity")
            deadline = time.monotonic() + 6500
            while True:
                current = controller_pid(program)
                if current == 0:
                    break
                if current != pid:
                    raise RuntimeError("Measurement controller PID changed")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Measurement arm wall-clock deadline")
                time.sleep(10)
            active = None
            result = json.loads(
                (ROOT / "receipts" / attempt / "status.json").read_text()
            )
            state["arms"].append(
                dict(arm=arm, attempt=attempt, passed=result["passed"])
            )
            if (
                not result["passed"]
                or result["release"]["exit"]
                or result["release"]["owners"]
                or owners()
            ):
                raise RuntimeError(f"{arm} qualification, windows or release failed")
            write(out / "status.json", state)
        state.update(passed=True, active_arm=None)
    except BaseException as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"
        (out / "FAILED.txt").write_text(state["error"] + "\n")
        raise
    finally:
        if active:
            stopped = subprocess.run(
                CTL + ["stop", active], capture_output=True, text=True, timeout=360
            )
            state["controller_stop_exit"] = stopped.returncode
        write(out / "status.json", state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--attempt", default="paired-measurement-r1")
    args = parser.parse_args()
    main(args.gate, args.attempt)
