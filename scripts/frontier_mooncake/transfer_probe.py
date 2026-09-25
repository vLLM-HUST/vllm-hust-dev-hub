"""Bounded real Ascend transfers with independent remote payload validation."""

import argparse
import ctypes
import hashlib
import json
import os
import select
import signal
import subprocess
import sys
from pathlib import Path

SIZE = 2 * 1024 * 1024


def emit(value):
    print(json.dumps(value), flush=True)


def worker(device):
    import torch
    import torch_npu  # noqa: F401
    from mooncake.engine import TransferEngine

    torch.npu.set_device(device)
    engine = TransferEngine()
    assert (
        engine.initialize(f"127.0.0.1:{33910 + device}", "P2PHANDSHAKE", "ascend", "")
        == 0
    )
    host = ctypes.create_string_buffer(SIZE * 2)
    host_address = (ctypes.addressof(host) + SIZE - 1) // SIZE * SIZE
    allocation = torch.empty(SIZE * 2, dtype=torch.uint8, device=f"npu:{device}")
    offset = (-allocation.data_ptr()) % SIZE
    tensor = allocation[offset : offset + SIZE]
    addresses = {"host": host_address, "device": tensor.data_ptr()}
    registered = []
    try:
        for address in addresses.values():
            assert engine.register_memory(address, SIZE) == 0
            registered.append(address)
        emit(
            {
                "ready": True,
                "engine_file": sys.modules["mooncake.engine"].__file__,
                "peer": f"127.0.0.1:{engine.get_rpc_port()}",
                "addresses": addresses,
            }
        )
        for line in sys.stdin:
            command = json.loads(line)
            op = command["op"]
            if op == "stop":
                break
            kind = command["kind"]
            if op == "fill":
                payload = bytes((i * 17 + command["seed"]) % 251 for i in range(SIZE))
                if kind == "host":
                    ctypes.memmove(host_address, payload, SIZE)
                else:
                    tensor.copy_(
                        torch.frombuffer(bytearray(payload), dtype=torch.uint8)
                    )
                    torch.npu.synchronize()
                emit({"sha256": hashlib.sha256(payload).hexdigest()})
            elif op == "hash":
                torch.npu.synchronize()
                payload = (
                    ctypes.string_at(host_address, SIZE)
                    if kind == "host"
                    else tensor.cpu().numpy().tobytes()
                )
                emit({"sha256": hashlib.sha256(payload).hexdigest()})
            elif op in ("read", "write"):
                method = getattr(engine, f"transfer_sync_{op}")
                result = method(
                    command["peer"], addresses[kind], command["remote_address"], SIZE
                )
                emit({"return": result})
            else:
                raise ValueError(op)
    finally:
        for address in registered:
            assert engine.unregister_memory(address) == 0
    emit({"stopped": True})


def owners():
    result = set()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) in {f"/dev/davinci{i}" for i in range(4)}:
                        result.add(int(proc.name))
                except OSError:
                    pass
        except OSError:
            pass
    return sorted(result)


def receive(process):
    if not select.select([process.stdout], [], [], 60)[0]:
        raise TimeoutError(f"No response from owned worker {process.pid}")
    line = process.stdout.readline()
    if not line:
        raise RuntimeError(f"Owned worker {process.pid} closed its output")
    return json.loads(line)


def call(process, command):
    process.stdin.write(json.dumps(command) + "\n")
    process.stdin.flush()
    return receive(process)


def probe(output):
    before = owners()
    if before:
        raise RuntimeError(f"Assigned devices occupied: {before}")
    output.mkdir(exist_ok=False)
    processes = []
    logs = []
    receipt = {
        "kind": "real-transfer-correctness-not-performance",
        "owners_before": before,
        "bytes_per_transfer": SIZE,
        "cases": [],
        "passed": False,
    }
    try:
        ready = []
        for device in (0, 1):
            log = (output / f"device-{device}.log").open("w")
            logs.append(log)
            process = subprocess.Popen(
                [sys.executable, __file__, "--worker", str(device)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                start_new_session=True,
            )
            processes.append(process)
            ready.append(receive(process))
        receipt["workers"] = [
            {"pid": p.pid, **info} for p, info in zip(processes, ready)
        ]
        source, target = processes
        for source_kind, target_kind in [
            ("host", "host"),
            ("host", "device"),
            ("device", "host"),
            ("device", "device"),
        ]:
            case = {"source": source_kind, "target": target_kind}
            receipt["cases"].append(case)
            expected = call(source, {"op": "fill", "kind": source_kind, "seed": 73})[
                "sha256"
            ]
            initial = call(target, {"op": "fill", "kind": target_kind, "seed": 29})[
                "sha256"
            ]
            assert expected != initial
            transfer = {
                "kind": source_kind,
                "peer": ready[1]["peer"],
                "remote_address": ready[1]["addresses"][target_kind],
            }
            case["write"] = call(source, {"op": "write", **transfer})
            assert case["write"]["return"] == 0
            case["remote_sha256"] = call(target, {"op": "hash", "kind": target_kind})[
                "sha256"
            ]
            assert case["remote_sha256"] == expected
            cleared = call(source, {"op": "fill", "kind": source_kind, "seed": 0})[
                "sha256"
            ]
            assert cleared != expected
            case["read"] = call(source, {"op": "read", **transfer})
            assert case["read"]["return"] == 0
            case["readback_sha256"] = call(source, {"op": "hash", "kind": source_kind})[
                "sha256"
            ]
            assert case["readback_sha256"] == expected
            case["passed"] = True
        for process in processes:
            assert call(process, {"op": "stop"})["stopped"]
        for process in processes:
            assert process.wait(timeout=30) == 0
        receipt["passed"] = True
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=15)
        for log in logs:
            log.close()
        receipt["exits"] = [p.returncode for p in processes]
        receipt["owners_after"] = owners()
        receipt["passed"] = receipt["passed"] and not receipt["owners_after"]
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    emit(receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=int, choices=(0, 1))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker is not None:
        worker(args.worker)
    elif args.output:
        probe(args.output)
    else:
        parser.error("--output required")
