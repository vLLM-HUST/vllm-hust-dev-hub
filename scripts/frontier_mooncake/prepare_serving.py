"""Prepare an isolated Qwen3.5 Mooncake retrieval qualification, not measurements."""

import argparse
import hashlib
import json
import shlex
import shutil
import socket
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root_name="phase5", segment_gib=1, tracker_fix=None):
    if not root_name.replace("-", "").isalnum() or not 1 <= segment_gib <= 16:
        raise ValueError("Invalid isolated root or segment size")
    ROOT = BASE / root_name
    if socket.gethostname() != "coder-admin-shuhao-evaluation-664b765847-wfh7z":
        raise RuntimeError("Wrong assigned container")
    build = BASE / "mooncake-build"
    if not json.loads((build / "store-r1/receipt.json").read_text())["passed"]:
        raise RuntimeError("Store prerequisite failed")
    for filename in ("staged-import-r1.json", "transfer-r1/receipt.json"):
        if not json.loads((build / filename).read_text())["passed"]:
            raise RuntimeError(f"Failed prerequisite: {filename}")
    if json.loads((build / "build-r4-status.json").read_text()).get("exit") != 0:
        raise RuntimeError("Source build did not succeed")
    if not json.loads((BASE / "phase4/manifest.json").read_text())[
        "software_tests_passed"
    ]:
        raise RuntimeError("Common runtime integration did not pass")
    ROOT.mkdir(exist_ok=False)
    (ROOT / "receipts").mkdir()
    stage = build / "stage-build-r4"
    config = dict(
        metadata_server="P2PHANDSHAKE",
        protocol="ascend",
        device_name="",
        master_server_address="127.0.0.1:33894",
        global_segment_size=segment_gib * 1073741824,
        local_buffer_size=0,
        preferred_segment=False,
        prefer_alloc_in_same_node=True,
    )
    (ROOT / "mooncake.json").write_text(json.dumps(config, indent=2) + "\n")
    wheel = BASE / "phase2/ascend-wheel"
    if tracker_fix is not None:
        relative = Path(
            "vllm_ascend/distributed/kv_transfer/kv_pool/ascend_store/pool_scheduler.py"
        )
        before = "ccf9d0bab338dbf2012948513b52b35456df8f78312f0157649aa050b09194bd"
        after = "287fd133af2403e0831b0a5c0d3e01e2419fa7d3506fac5dc55fd824b7eb1024"
        if digest(wheel / relative) != before or digest(tracker_fix) != after:
            raise RuntimeError("Tracker source does not match pinned before/after")
        shutil.copytree(
            wheel,
            ROOT / "ascend-wheel",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        wheel = ROOT / "ascend-wheel"
        shutil.copyfile(tracker_fix, wheel / relative)
        (ROOT / "tracker-fix.json").write_text(
            json.dumps(
                {
                    "revision": "03766ac696fde5ab1980d80ca0b8543d3580c989",
                    "base": "66350e7b7d8ec68ad68a14fb841678054f2c0f98",
                    "file": str(relative),
                    "before_sha256": before,
                    "after_sha256": after,
                    "scope": "Single source change in copied qualified wheel; same runtime in both arms",
                },
                indent=2,
            )
            + "\n"
        )
    original = (
        (BASE / "phase4/launch-native.sh")
        .read_text()
        .replace(str(BASE / "phase2/ascend-wheel"), str(wheel))
    )
    common = original.replace("cd " + str(BASE / "phase4"), "cd " + str(ROOT)).replace(
        "frontier-qwen35-dla", "frontier-qwen35-mooncake"
    )
    common = common.replace(
        'export PYTHONPATH="', 'export PYTHONPATH="' + str(stage / "python") + ":", 1
    )
    extra = f'''export LD_LIBRARY_PATH="{stage}/python/mooncake:{build}/deps/usr/lib/aarch64-linux-gnu:${{LD_LIBRARY_PATH:-}}"
export PYTHONHASHSEED=0
export HCCL_INTRA_ROCE_ENABLE=1
export ASCEND_CONNECT_TIMEOUT=3000
export ASCEND_TRANSFER_TIMEOUT=10000
export MOONCAKE_CONFIG_PATH={ROOT}/mooncake.json
'''
    common = common.replace(
        "exec " + str(BASE / ".venv/bin/vllm"),
        extra + "exec " + str(BASE / ".venv/bin/vllm"),
    )
    (ROOT / "launch-native.sh").write_text(common)
    kv = dict(
        kv_connector="AscendStoreConnector",
        kv_role="kv_both",
        kv_load_failure_policy="fail",
        kv_connector_extra_config=dict(
            backend="mooncake",
            use_layerwise=False,
            lookup_rpc_port="frontier_" + root_name,
        ),
    )
    (ROOT / "launch-mooncake.sh").write_text(
        common.rstrip() + " --kv-transfer-config " + shlex.quote(json.dumps(kv)) + "\n"
    )
    master = f'''#!/bin/bash
set -eo pipefail
source /usr/local/Ascend/cann/set_env.sh
export LD_LIBRARY_PATH="{stage}/python/mooncake:{build}/deps/usr/lib/aarch64-linux-gnu:${{LD_LIBRARY_PATH:-}}"
exec {stage}/bin/mooncake_master --rpc_address=127.0.0.1 --rpc_port=33894 --metrics_host=127.0.0.1 --metrics_port=33895 --http_metadata_server_host=127.0.0.1 --http_metadata_server_port=33896 --rpc_thread_num=2 --max_threads=2 --default_kv_lease_ttl=11000
'''
    (ROOT / "launch-master.sh").write_text(master)
    controller = (
        (BASE / "phase4/qualify.py")
        .read_text()
        .replace('ROOT = BASE / "phase4"', f"ROOT = BASE / {json.dumps(root_name)}")
        .replace("frontier-qwen35-dla", "frontier-qwen35-mooncake")
        .replace('choices=["native", "bidkv", "dla"]', 'choices=["native", "mooncake"]')
    )
    controller = controller.replace(
        "        started = True\n",
        '        if not args.qualification_only:\n            raise ValueError("This capsule authorizes retrieval qualification only")\n        started = True\n        if program == "mooncake":\n            subprocess.run(CTL + ["start", "master"], check=True, timeout=20)\n',
    )
    controller = controller.replace(
        "            deadline = time.monotonic() + 30\n",
        '            if program == "mooncake":\n                master_stop = subprocess.run(CTL + ["stop", "master"], capture_output=True, text=True, timeout=30)\n                state["master_release_exit"] = master_stop.returncode\n                if master_stop.returncode:\n                    state["passed"] = False\n            deadline = time.monotonic() + 30\n',
    )
    controller = controller.replace(
        "    with socket.socket() as sock:\n",
        "    for reserved_port in (33894, 33895, 33896):\n"
        "        with socket.socket() as reserved_socket:\n"
        '            reserved_socket.bind(("127.0.0.1", reserved_port))\n'
        "    with socket.socket() as sock:\n",
        1,
    )
    (ROOT / "qualify.py").write_text(controller)
    header = f"""[unix_http_server]
file={ROOT}/supervisor.sock
chmod=0700
[supervisord]
logfile={ROOT}/receipts/supervisord.log
pidfile={ROOT}/supervisord.pid
childlogdir={ROOT}/receipts
user=root
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix://{ROOT}/supervisor.sock
"""
    programs = {
        "master": f"/bin/bash {ROOT}/launch-master.sh",
        "mooncake": f"/bin/bash {ROOT}/launch-mooncake.sh",
        "native": f"/bin/bash {ROOT}/launch-native.sh",
        "qualify-native": f"{BASE}/.venv/bin/python {ROOT}/qualify.py --attempt native-retrieval-r1 --program native --qualification-only",
        "qualify-mooncake": f"{BASE}/.venv/bin/python {ROOT}/qualify.py --attempt mooncake-retrieval-r1 --program mooncake --qualification-only",
    }
    for name, command in programs.items():
        header += f"""\n[program:{name}]
command={command}
directory={ROOT}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs={300 if name.startswith("qualify") else 90}
redirect_stderr=true
stdout_logfile={ROOT}/receipts/{name}.log
stdout_logfile_maxbytes=100MB
"""
        if not name.startswith("qualify"):
            header += "stopasgroup=true\nkillasgroup=true\n"
    (ROOT / "supervisord.conf").write_text(header)
    (ROOT / "prepare_serving.py").write_bytes(Path(__file__).read_bytes())
    old = json.loads((BASE / "phase4/manifest.json").read_text())
    hashes = {"../phase4/" + name: value for name, value in old["sha256"].items()}
    manifest = json.loads((stage / "manifest.json").read_text())
    for record in manifest["files"]:
        path = stage / record["staged"]
        assert digest(path) == record["sha256"]
        hashes[str(path)] = record["sha256"]
    for path in (build / "deps/usr/lib/aarch64-linux-gnu").glob("*.so*"):
        if path.is_file():
            hashes[str(path)] = digest(path)
    if tracker_fix is not None:
        for path in wheel.rglob("*"):
            if path.is_file():
                hashes[str(path.relative_to(ROOT))] = digest(path)
    for path in ROOT.iterdir():
        if path.is_file():
            hashes[path.name] = digest(path)
    result = {
        "kind": "retrieval-qualification-preparation-not-performance",
        "software_tests_passed": True,
        "prerequisites": [
            "pinned-build-exit0",
            "staged-imports-exit0",
            "real-four-path-transfer-pass",
            "real-cross-client-multibuffer-store-pass",
        ],
        "sha256": hashes,
    }
    (ROOT / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "prepared": str(ROOT),
                "tracked_files": len(hashes),
                "measurement_enabled": False,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-name", default="phase5")
    parser.add_argument("--segment-gib", type=int, default=1)
    parser.add_argument("--tracker-fix", type=Path)
    args = parser.parse_args()
    prepare(args.root_name, args.segment_gib, args.tracker_fix)
