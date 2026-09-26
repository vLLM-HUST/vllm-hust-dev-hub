"""Durable serial qualification after the measured Tiering pair releases."""

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
QUEUE = Path(__file__).resolve().parent
ROOT = BASE / "phase7"
VENV = BASE / "phase7-env/venv"
CTL = [
    "/usr/local/python3.12.13/bin/supervisorctl",
    "-c",
    str(ROOT / "supervisord.conf"),
]


def write(state):
    temporary = QUEUE / "status.tmp"
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(QUEUE / "status.json")


def interrupted(signum, frame):
    raise InterruptedError(f"Queue received signal {signum}")


def controller_pid(name):
    result = subprocess.run(
        CTL + ["pid", name], capture_output=True, text=True, timeout=10
    )
    if result.returncode == 7 and result.stdout.strip() == "0":
        return 0
    result.check_returncode()
    return int(result.stdout.strip())


def owners():
    found = set()
    devices = {f"/dev/davinci{i}" for i in range(4)}
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) in devices:
                        found.add(int(proc.name))
                except OSError:
                    pass
        except OSError:
            pass
    return sorted(found)


def main():
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    state = dict(
        passed=False, stage="waiting-for-tiering", kind="qualification-only", arms=[]
    )
    active = None
    try:
        if socket.gethostname() != "coder-admin-shuhao-evaluation-664b765847-wfh7z":
            raise RuntimeError("Wrong assigned container")
        parent = Path(f"/proc/{os.getppid()}/cmdline").read_bytes()
        if b"supervisord" not in parent or str(QUEUE).encode() not in parent:
            raise RuntimeError("Queue lacks dedicated supervisor custody")
        state.update(controller_pid=os.getpid(), parent_pid=os.getppid())
        manifest = json.loads((QUEUE / "manifest.json").read_text())
        for name, expected in manifest["sha256"].items():
            if hashlib.sha256((QUEUE / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Queue source identity mismatch: {name}")
        write(state)
        deadline = time.monotonic() + 6 * 3600
        previous_path = (
            BASE / "phase6/serving-r8/receipts/matched-curves-r1/status.json"
        )
        while True:
            previous = json.loads(previous_path.read_text())
            if previous.get("passed") is True:
                break
            if previous.get("error"):
                raise RuntimeError("Tiering pair failed; qualification was not started")
            if time.monotonic() >= deadline:
                raise TimeoutError("Tiering pair did not complete within six hours")
            time.sleep(30)
        for arm in ("tiering", "native"):
            path = previous_path.parents[1] / f"{arm}-measured-r1/status.json"
            result = json.loads(path.read_text())
            if (
                not result["passed"]
                or result["release"]["exit"]
                or result["release"]["owners"]
            ):
                raise RuntimeError("Previous arm has no successful release receipt")
        if ROOT.exists() or VENV.parent.exists():
            raise RuntimeError("Next capsule or environment already exists")
        if owners():
            raise RuntimeError("Devices acquired by another process after pair release")
        state["stage"] = "preparing"
        write(state)
        VENV.parent.mkdir()
        shutil.copytree(BASE / ".venv", VENV, symlinks=True)
        lock = json.loads((QUEUE / "managed-source-lock.json").read_text())
        wheels = []
        for name, expected in lock["wheels"].items():
            path = QUEUE / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Wheel identity mismatch: {name}")
            wheels.append(str(path))
        subprocess.run(
            [
                str(VENV / "bin/python"),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--ignore-installed",
                *wheels,
            ],
            check=True,
            timeout=120,
        )
        subprocess.run(
            [str(VENV / "bin/python"), str(QUEUE / "prepare_managed.py")],
            check=True,
            timeout=300,
        )
        compile((ROOT / "qualify.py").read_text(), str(ROOT / "qualify.py"), "exec")
        subprocess.run(
            [
                "/usr/local/python3.12.13/bin/supervisord",
                "-c",
                str(ROOT / "supervisord.conf"),
            ],
            check=True,
            timeout=20,
        )
        for arm in ("mooncake", "native"):
            program = f"qualify-{arm}"
            state.update(stage="qualifying", active_arm=arm)
            write(state)
            if controller_pid(program):
                raise RuntimeError("Qualification controller is already active")
            active = program
            subprocess.run(CTL + ["start", active], check=True, timeout=20)
            pid = controller_pid(active)
            if not pid:
                raise RuntimeError(
                    "Qualification controller exited before custody check"
                )
            command = Path(f"/proc/{pid}/cmdline").read_bytes()
            if (
                str(ROOT).encode() not in command
                or f"{arm}-retrieval-r1".encode() not in command
            ):
                raise RuntimeError("Unexpected qualification controller identity")
            deadline = time.monotonic() + 4000
            while True:
                current = controller_pid(active)
                if not current:
                    break
                if current != pid or time.monotonic() >= deadline:
                    raise RuntimeError("Qualification custody changed or timed out")
                time.sleep(10)
            active = None
            result = json.loads(
                (ROOT / f"receipts/{arm}-retrieval-r1/status.json").read_text()
            )
            state["arms"].append(dict(arm=arm, passed=result["passed"]))
            if (
                not result["passed"]
                or result["release"]["exit"]
                or result["release"]["owners"]
            ):
                raise RuntimeError(f"{arm} qualification or release failed")
            write(state)
        state.update(passed=True, stage="qualified-not-measured", active_arm=None)
    except BaseException as exc:
        state.update(stage="failed", error=f"{type(exc).__name__}: {exc}")
        (QUEUE / "FAILED.txt").write_text(state["error"] + "\n")
        raise
    finally:
        if active:
            result = subprocess.run(
                CTL + ["stop", active], capture_output=True, text=True, timeout=360
            )
            state["controller_stop_exit"] = result.returncode
        write(state)


if __name__ == "__main__":
    main()
