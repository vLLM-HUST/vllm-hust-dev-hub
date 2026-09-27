"""Durable continuation: wait for native release, qualify and measure BidKV."""

import datetime
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from run_windows import CTL, ROOT, device_owners, write


def stop_signal(signum, frame):
    raise InterruptedError(f"Continuation received signal {signum}")


def main():
    os.chdir(ROOT)
    state_path = ROOT / "receipts/bidkv-continuation.json"
    if state_path.exists():
        raise RuntimeError("Refuse to overwrite continuation receipt")
    state = {
        "stage": "waiting-for-native-release",
        "controller_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    write(state_path, state)
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    child = None
    started = False
    try:
        deadline = time.monotonic() + 7200
        while True:
            p = ROOT / "runs/native-r1/status.json"
            if p.exists():
                try:
                    native = json.loads(p.read_text())
                except json.JSONDecodeError:
                    native = {}  # The active writer may be between truncate and write.
                if "release" in native:
                    if not native["passed"] or not native["release"]["released"]:
                        raise RuntimeError("Native arm failed or not released")
                    break
            if time.monotonic() >= deadline:
                raise TimeoutError("Native release deadline")
            time.sleep(5)
        if device_owners():
            raise RuntimeError("Selected devices still owned")
        with socket.socket() as sock:
            # Match the server's bind semantics while still rejecting a live listener.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 33781))
        admitted = json.loads((ROOT / "receipts/native-admission-r6.json").read_text())
        for name, expected in admitted["feedback_patch_files"].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Shared runtime changed: {name}")
        if (
            hashlib.sha256((ROOT / "frontier_worker.py").read_bytes()).hexdigest()
            != admitted["worker_bridge_sha256"]
        ):
            raise RuntimeError("Worker bridge changed")
        admitted["utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        admitted["launch_script_sha256"] = hashlib.sha256(
            (ROOT / "launch-bidkv.sh").read_bytes()
        ).hexdigest()
        admitted["environment"]["BIDKV_UTILITY_ENABLE"] = "1"
        write(ROOT / "receipts/bidkv-admission-r1.json", admitted)
        state["stage"] = "starting-bidkv"
        write(state_path, state)
        # Mark ownership before start so startup timeout still reaches cleanup.
        started = True
        subprocess.run(CTL + ["start", "bidkv"], check=True, timeout=20)
        pid = int(subprocess.check_output(CTL + ["pid", "bidkv"], text=True).strip())
        if pid <= 1:
            raise RuntimeError("Missing supervised BidKV PID")
        state["server_pid"] = pid
        deadline = time.monotonic() + 900
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("BidKV health deadline")
            if not Path(f"/proc/{pid}").exists():
                raise RuntimeError("BidKV exited before health")
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:33781/health", timeout=min(2, remaining)
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        state["stage"] = "qualifying-bidkv"
        write(state_path, state)
        command = [
            str(ROOT / ".venv/bin/python"),
            "frontier_qualify.py",
            "--endpoint",
            "http://127.0.0.1:33781/v1/completions",
            "--model",
            "frontier-qwen35",
            "--tokenizer",
            "model",
            "--output",
            "receipts/bidkv-retrieval-r1",
        ]
        with (ROOT / "receipts/bidkv-retrieval-r1.log").open("x") as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            result = child.wait(timeout=1800)
            child = None
            if result:
                raise RuntimeError("BidKV retrieval qualification failed")
        state["stage"] = "measuring-bidkv"
        write(state_path, state)
        command = [
            str(ROOT / ".venv/bin/python"),
            "run_windows.py",
            "--program",
            "bidkv",
            "--pid",
            str(pid),
            "--retrieval",
            "receipts/bidkv-retrieval-r1",
            "--metadata",
            "receipts/bidkv-metadata-r6.json",
            "--output",
            "runs/bidkv-r1",
        ]
        child = subprocess.Popen(command)
        result = child.wait(timeout=6000)
        child = None
        if result:
            raise RuntimeError("BidKV windows failed")
        result = json.loads((ROOT / "runs/bidkv-r1/status.json").read_text())
        if not result["passed"] or not result["release"]["released"]:
            raise RuntimeError("BidKV run or release not valid")
        state["stage"] = "completed"
    except BaseException as exc:
        state["stage"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=150)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if started:
            subprocess.run(CTL + ["stop", "bidkv"], capture_output=True, timeout=110)
            state["device_fd_owners_after"] = device_owners()
        write(state_path, state)


if __name__ == "__main__":
    main()
