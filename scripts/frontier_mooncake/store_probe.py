"""Exercise real Mooncake multi-buffer storage across two NPU clients."""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from transfer_probe import call, emit, owners, receive

SIZES = [2 * 1024 * 1024, 1024 * 1024]
MASTER = "127.0.0.1:33894"


def worker(device):
    import torch
    import torch_npu  # noqa: F401
    from mooncake.store import MooncakeDistributedStore

    torch.npu.set_device(device)
    store = MooncakeDistributedStore()
    result = store.setup(
        local_hostname=f"127.0.0.1:{33920 + device}",
        metadata_server="P2PHANDSHAKE",
        global_segment_size=1073741824,
        local_buffer_size=0,
        protocol="ascend",
        rdma_devices="",
        master_server_addr=MASTER,
    )
    assert result == 0, result
    tensors, allocations, registered = [], [], []
    try:
        for size in SIZES:
            allocation = torch.empty(
                size + 2097152, dtype=torch.uint8, device=f"npu:{device}"
            )
            offset = (-allocation.data_ptr()) % 2097152
            tensor = allocation[offset : offset + size]
            allocations.append(allocation)
            tensors.append(tensor)
            assert store.register_buffer(tensor.data_ptr(), size) == 0
            registered.append(tensor.data_ptr())
        emit(
            {
                "ready": True,
                "store_file": sys.modules["mooncake.store"].__file__,
                "setup_return": result,
            }
        )
        for line in sys.stdin:
            command = json.loads(line)
            op = command["op"]
            if op == "stop":
                break
            if op == "fill":
                hashes = []
                for i, (tensor, size) in enumerate(zip(tensors, SIZES)):
                    payload = bytes(
                        (j * 17 + command["seed"] + i) % 251 for j in range(size)
                    )
                    tensor.copy_(
                        torch.frombuffer(bytearray(payload), dtype=torch.uint8)
                    )
                    hashes.append(hashlib.sha256(payload).hexdigest())
                torch.npu.synchronize()
                emit({"hashes": hashes})
            elif op == "hash":
                torch.npu.synchronize()
                emit(
                    {
                        "hashes": [
                            hashlib.sha256(t.cpu().numpy().tobytes()).hexdigest()
                            for t in tensors
                        ]
                    }
                )
            elif op == "put":
                emit(
                    {
                        "returns": store.batch_put_from_multi_buffers(
                            [command["key"]], [registered], [SIZES]
                        )
                    }
                )
            elif op == "get":
                result = store.batch_get_into_multi_buffers(
                    [command["key"]], [registered], [SIZES]
                )
                torch.npu.synchronize()
                emit({"returns": result})
            elif op == "exists":
                emit({"returns": store.batch_is_exist([command["key"]])})
            elif op == "remove":
                emit({"return": store.remove(command["key"], True)})
            else:
                raise ValueError(op)
    finally:
        for address in registered:
            assert store.unregister_buffer(address) == 0
        assert store.close() == 0
    emit({"stopped": True})


def probe(output, binary):
    before = owners()
    if before:
        raise RuntimeError(f"Assigned devices occupied: {before}")
    for port in [33894, 33895, 33896]:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    output.mkdir(exist_ok=False)
    processes, logs = [], []
    receipt = {
        "kind": "real-store-multibuffer-correctness-not-serving-performance",
        "owners_before": before,
        "buffer_sizes": SIZES,
        "passed": False,
    }
    master = None
    try:
        log = (output / "master.log").open("w")
        logs.append(log)
        command = [
            str(binary),
            "--rpc_address=127.0.0.1",
            "--rpc_port=33894",
            "--metrics_host=127.0.0.1",
            "--metrics_port=33895",
            "--http_metadata_server_host=127.0.0.1",
            "--http_metadata_server_port=33896",
            "--rpc_thread_num=2",
            "--max_threads=2",
        ]
        master = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        receipt["master_command"] = command
        receipt["master_pid"] = master.pid
        deadline = time.monotonic() + 30
        while True:
            if master.poll() is not None:
                raise RuntimeError(f"Master exited: {master.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", 33894), timeout=1):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("Owned master did not listen")
                time.sleep(0.2)
        receipt["clients"] = []
        for device in [0, 1]:
            log = (output / f"device-{device}.log").open("w")
            logs.append(log)
            p = subprocess.Popen(
                [sys.executable, __file__, "--worker", str(device)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                start_new_session=True,
            )
            processes.append(p)
            receipt["clients"].append({"pid": p.pid, **receive(p)})
        source, target = processes
        key = f"frontier-store-probe-{os.getpid()}"
        receipt["key"] = key
        assert call(target, {"op": "exists", "key": key})["returns"] == [0]
        expected = call(source, {"op": "fill", "seed": 73})["hashes"]
        receipt["put"] = call(source, {"op": "put", "key": key})
        assert receipt["put"]["returns"] == [0]
        assert call(target, {"op": "exists", "key": key})["returns"] == [1]
        assert call(source, {"op": "fill", "seed": 0})["hashes"] != expected
        assert call(target, {"op": "fill", "seed": 29})["hashes"] != expected
        receipt["get"] = call(target, {"op": "get", "key": key})
        assert len(receipt["get"]["returns"]) == 1 and receipt["get"]["returns"][0] >= 0
        receipt["expected_hashes"] = expected
        receipt["received_hashes"] = call(target, {"op": "hash"})["hashes"]
        assert receipt["received_hashes"] == expected
        receipt["remove"] = call(source, {"op": "remove", "key": key})
        assert receipt["remove"]["return"] == 0
        assert call(target, {"op": "exists", "key": key})["returns"] == [0]
        for p in processes:
            assert call(p, {"op": "stop"})["stopped"]
        for p in processes:
            assert p.wait(timeout=30) == 0
        receipt["passed"] = True
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        for p in [*processes, *([master] if master else [])]:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait(timeout=15)
        for log in logs:
            log.close()
        receipt["client_exits"] = [p.returncode for p in processes]
        receipt["master_exit"] = master.returncode if master else None
        receipt["owners_after"] = owners()
        receipt["passed"] = (
            receipt["passed"]
            and not receipt["owners_after"]
            and receipt["master_exit"] in [0, -signal.SIGTERM]
        )
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    emit(receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=int, choices=(0, 1))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--master", type=Path)
    args = parser.parse_args()
    if args.worker is not None:
        worker(args.worker)
    elif args.output and args.master:
        probe(args.output, args.master)
    else:
        parser.error("--output and --master required")
