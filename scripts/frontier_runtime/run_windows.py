"""Durable, task-owned SWE windows with metrics and outer-finally server release."""

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path("/home/coder/frontier-mods-qwen35-20260925")
CTL = [
    "/usr/local/python3.12.13/bin/supervisorctl",
    "-c",
    str(ROOT / "supervisord.conf"),
]


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def device_owners():
    owners = set()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) in ("/dev/davinci0", "/dev/davinci1"):
                        owners.add(int(proc.name))
                except OSError:
                    pass
        except OSError:
            pass
    return sorted(owners)


def metrics(path):
    with urllib.request.urlopen("http://127.0.0.1:33781/metrics", timeout=10) as r:
        path.write_bytes(r.read())


def interrupted(signum, frame):
    raise InterruptedError(f"Controller received signal {signum}")


def main(args):
    os.chdir(ROOT)
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=False)
    # Bind cleanup to exactly the dedicated supervisor program and admitted PID.
    pid = int(subprocess.check_output(CTL + ["pid", args.program], text=True).strip())
    if pid != args.pid or pid <= 1:
        raise RuntimeError("Supervisor server identity mismatch")
    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    if str(ROOT) not in cmdline or "vllm" not in cmdline:
        raise RuntimeError("Unexpected server command")
    write(
        out / "custody.json",
        {
            "server_pid": pid,
            "program": args.program,
            "controller_pid": os.getpid(),
            "controller_parent": os.getppid(),
            "command": cmdline,
            "kind": "real-online",
            "pod_npu_quota": 8,
            "participating_deployment_chips": 2,
        },
    )
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    state = {"passed": False, "windows": []}
    child = None
    try:
        gate = json.loads((ROOT / args.retrieval / "summary.json").read_text())
        if not gate["passed"]:
            raise RuntimeError("Retrieval qualification failed")
        for name, concurrency, duration in [
            ("qualification", 2, 60),
            ("c4", 4, 900),
            ("c16", 16, 900),
        ]:
            metrics(out / f"{name}-before.prom")
            command = [
                str(ROOT / ".venv/bin/swe-prefix-reuse"),
                "run",
                "--workload",
                str(ROOT / "prepared/qwen35.json"),
                "--endpoint",
                "http://127.0.0.1:33781/v1/completions",
                "--model",
                "frontier-qwen35",
                "--concurrency",
                str(concurrency),
                "--duration",
                str(duration),
                "--chips",
                "2",
                "--server-max-context",
                "262144",
                "--server-metadata",
                str(ROOT / args.metadata),
                "--output",
                str(out / name),
            ]
            write(out / f"{name}-command.json", command)
            with (out / f"{name}.log").open("w") as log:
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                code = child.wait(timeout=duration + 1900)
                child = None
            metrics(out / f"{name}-after.prom")
            summary = json.loads((out / name / "summary.json").read_text())
            state["windows"].append(
                {"name": name, "exit_code": code, "summary": summary}
            )
            write(out / "status.json", state)
            if code or not summary["valid"] or summary["aborted"]:
                raise RuntimeError(f"{name} failed protocol qualification")
            if name == "qualification":
                from prometheus_client.parser import text_string_to_metric_families

                def hits(path):
                    return sum(
                        sample.value
                        for family in text_string_to_metric_families(path.read_text())
                        for sample in family.samples
                        if sample.name == "vllm:prefix_cache_hits_total"
                    )

                delta = hits(out / f"{name}-after.prom") - hits(
                    out / f"{name}-before.prom"
                )
                write(
                    out / "prefix-reuse.json",
                    {"hit_token_delta": delta, "passed": delta > 0},
                )
                if delta <= 0:
                    raise RuntimeError("No measured prefix-cache reuse")
        state["passed"] = True
    except BaseException as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        stop = subprocess.run(
            CTL + ["stop", args.program], capture_output=True, text=True, timeout=110
        )
        end = time.monotonic() + 30
        owners = device_owners()
        while owners and time.monotonic() < end:
            time.sleep(1)
            owners = device_owners()
        state["release"] = {
            "supervisor_exit": stop.returncode,
            "message": stop.stdout,
            "device_fd_owners_after": owners,
            "released": not owners,
        }
        if owners or stop.returncode:
            state["passed"] = False
        write(out / "status.json", state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", choices=["native", "bidkv"], required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--retrieval", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--output", required=True)
    main(parser.parse_args())
