"""Supervised TP2 Native/BidKV/DLA qualification with owned-server release."""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
ROOT = BASE / "phase4"
PYTHON = BASE / ".venv/bin/python"
CTL = [
    "/usr/local/python3.12.13/bin/supervisorctl",
    "-c",
    str(ROOT / "supervisord.conf"),
]


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


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


def capture_metrics(path):
    with urllib.request.urlopen(
        "http://127.0.0.1:33783/metrics", timeout=10
    ) as response:
        path.write_bytes(response.read())


def interrupted(signum, frame):
    raise InterruptedError(f"Qualification received signal {signum}")


def server_command(pid, program):
    """Wait for the exact owned launcher to exec after environment setup."""
    deadline = time.monotonic() + 30
    while True:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        tokens = [v.decode() for v in argv if v]
        if str(BASE / ".venv/bin/vllm") in tokens:
            return " ".join(tokens)
        if tokens != ["/bin/bash", str(ROOT / f"launch-{program}.sh")]:
            raise RuntimeError("Supervised server command identity mismatch")
        if time.monotonic() >= deadline:
            raise TimeoutError("Owned launcher did not exec within 30 seconds")
        time.sleep(0.1)


def preflight():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    for relative, expected in manifest["sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Source identity changed: {relative}")
    if not manifest["software_tests_passed"]:
        raise RuntimeError("Software tests have not passed")
    parent = Path(f"/proc/{os.getppid()}/cmdline").read_bytes()
    if b"supervisord" not in parent or str(ROOT).encode() not in parent:
        raise RuntimeError("Controller is not owned by its dedicated supervisor")
    if owners():
        raise RuntimeError("Participating devices are busy")
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 33783))


def main(args):
    os.chdir(ROOT)
    out = ROOT / "receipts" / args.attempt
    out.mkdir(exist_ok=False)
    state = {"passed": False, "stage": "preflight", "kind": "qualification-only"}
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    state.update(controller_pid=os.getpid(), parent_pid=os.getppid(), devices=[0, 1])
    write(out / "status.json", state)
    program = getattr(args, "program", "native")
    measure = getattr(args, "measure", False)
    started = False
    child = None
    try:
        preflight()
        if measure:
            if args.qualification_only or not args.metadata:
                raise ValueError("Measurement requires metadata and full qualification")
            launcher = (ROOT / f"launch-{program}.sh").read_text()
            if (
                "debug_worker" in launcher
                or "export FRONTIER_PP_CALIBRATION_DIR=" in launcher
            ):
                raise ValueError(
                    "Diagnostic/profiling launchers cannot measure performance"
                )
            metadata = json.loads((ROOT / args.metadata).read_text())
            if (
                metadata["launch_script_sha256"]
                != hashlib.sha256(launcher.encode()).hexdigest()
            ):
                raise ValueError("Metadata launcher identity mismatch")
            if metadata["serving_chips"] != 2 or metadata["serving_devices"] != [0, 1]:
                raise ValueError("Metadata deployment topology mismatch")
            state["kind"] = "real-online"
        started = True
        subprocess.run(CTL + ["start", program], check=True, timeout=20)
        pid = int(subprocess.check_output(CTL + ["pid", program], text=True))
        if pid <= 1:
            raise RuntimeError("Missing supervised server PID")
        command_line = server_command(pid, program)
        write(
            out / "custody.json",
            dict(
                server_pid=pid,
                program=program,
                controller_pid=os.getpid(),
                controller_parent=os.getppid(),
                command=command_line,
                kind=state["kind"],
                pod_npu_quota=4,
                participating_deployment_chips=2,
            ),
        )
        state.update(server_pid=pid, stage="starting")
        write(out / "status.json", state)
        deadline = time.monotonic() + 900
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Native PP2 health deadline")
            if not Path(f"/proc/{pid}").exists():
                raise RuntimeError("Native PP2 exited before health")
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:33783/health", timeout=min(2, remaining)
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        state["stage"] = "retrieval"
        write(out / "status.json", state)
        command = [
            str(PYTHON),
            str(BASE / "frontier_qualify.py"),
            "--endpoint",
            "http://127.0.0.1:33783/v1/completions",
            "--model",
            "frontier-qwen35-dla",
            "--tokenizer",
            str(BASE / "model"),
            "--output",
            str(out / "retrieval"),
        ]
        write(out / "retrieval-command.json", command)
        with (out / "retrieval.log").open("w") as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            code = child.wait(timeout=2400)
            child = None
        gate = json.loads((out / "retrieval/summary.json").read_text())
        if code or not gate["passed"] or gate["completed_requests"] != 26:
            raise RuntimeError("Full retrieval gate failed")
        if args.qualification_only:
            state.update(passed=True, stage="completed")
            return
        state["stage"] = "measurement" if measure else "calibration"
        write(out / "status.json", state)
        windows = [("qualification", 2, 60)] + [
            (f"c{c}", c, 900) for c in (1, 2, 4, 8, 16)
        ]
        state["windows"] = []
        for name, concurrency, duration in windows:
            if measure:
                capture_metrics(out / f"{name}-before.prom")
            command = [
                str(BASE / ".venv/bin/swe-prefix-reuse"),
                "run",
                "--workload",
                str(BASE / "prepared/qwen35.json"),
                "--endpoint",
                "http://127.0.0.1:33783/v1/completions",
                "--model",
                "frontier-qwen35-dla",
                "--concurrency",
                str(concurrency),
                "--duration",
                str(duration),
                "--chips",
                "2",
                "--server-max-context",
                "262144",
                "--output",
                str(out / name),
            ]
            if measure:
                command.extend(["--server-metadata", str(ROOT / args.metadata)])
            write(out / f"{name}-command.json", command)
            with (out / f"{name}.log").open("w") as log:
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                code = child.wait(timeout=duration + 1900)
                child = None
            summary = json.loads((out / name / "summary.json").read_text())
            state["windows"].append(dict(name=name, exit_code=code, summary=summary))
            write(out / "status.json", state)
            if (
                code
                or not summary["valid"]
                or summary["failed_requests"]
                or summary["aborted"]
            ):
                raise RuntimeError(f"{name} protocol failed")
            if measure:
                capture_metrics(out / f"{name}-after.prom")
                if name == "qualification":
                    from prometheus_client.parser import text_string_to_metric_families

                    def hits(path):
                        return sum(
                            sample.value
                            for family in text_string_to_metric_families(
                                path.read_text()
                            )
                            for sample in family.samples
                            if sample.name == "vllm:prefix_cache_hits_total"
                        )

                    delta = hits(out / f"{name}-after.prom") - hits(
                        out / f"{name}-before.prom"
                    )
                    write(
                        out / "prefix-reuse.json",
                        dict(hit_token_delta=delta, passed=delta > 0),
                    )
                    if delta <= 0:
                        raise RuntimeError("No measured prefix-cache reuse")
                elif program in {"bidkv", "dla"}:
                    from policy_receipt import receipt

                    write(
                        out / f"{name}-policy-effectiveness.json",
                        receipt(
                            out / f"{name}-before.prom",
                            out / f"{name}-after.prom",
                            program=program,
                        ),
                    )
        state.update(passed=True, stage="completed")
    except BaseException as exc:
        state.update(error=f"{type(exc).__name__}: {exc}", stage="failed")
        (out / "FAILED.txt").write_text(state["error"] + "\n")
        raise
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if started:
            stop = subprocess.run(
                CTL + ["stop", program], capture_output=True, text=True, timeout=110
            )
            deadline = time.monotonic() + 30
            while owners() and time.monotonic() < deadline:
                time.sleep(1)
            state["release"] = {"exit": stop.returncode, "owners": owners()}
            if stop.returncode or state["release"]["owners"]:
                state["passed"] = False
        write(out / "status.json", state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--qualification-only", action="store_true")
    parser.add_argument(
        "--program", choices=["native", "bidkv", "dla"], default="native"
    )
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--metadata")
    main(parser.parse_args())
