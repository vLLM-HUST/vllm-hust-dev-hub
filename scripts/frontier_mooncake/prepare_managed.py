"""Prepare Mooncake qualification with explicit manager activation and Host fix.

Run only after the current campaign releases its devices. This prepares the
existing qualification-only controller; it does not authorize a performance row.
"""

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

from prepare_serving import BASE, prepare

ROOT = BASE / "phase7"
VENV = BASE / "phase7-env/venv"
CORE = BASE / "phase6/core-r6"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    previous = json.loads(
        (BASE / "phase6/serving-r8/receipts/matched-curves-r1/status.json").read_text()
    )
    if previous.get("passed") is not True:
        raise RuntimeError("The Tiering/Native campaign has not completed")
    patch = json.loads((BASE / "phase6/core-patch-r6.json").read_text())
    for relative, expected in patch["files"].items():
        if sha(CORE / relative) != expected:
            raise RuntimeError(f"Host patch identity mismatch: {relative}")
    tracker = (
        BASE / "phase5c/ascend-wheel/vllm_ascend/distributed/kv_transfer"
        "/kv_pool/ascend_store/pool_scheduler.py"
    )
    if not tracker.exists():
        raise RuntimeError("Missing previously qualified Ascend tracker fix")
    prepare("phase7", 16, tracker)
    (ROOT / "manager-native.json").write_text('{"schema_version":2,"extensions":{}}\n')
    profile = {
        "connector": "AscendStoreConnector",
        "kv_role": "kv_both",
        "device_backend": "ascend",
        "transport_protocol": "ascend",
        "health_url": "http://127.0.0.1:33895/metrics",
        "kv_connector_extra_config": {
            "backend": "mooncake",
            "use_layerwise": False,
            "lookup_rpc_port": "frontier_phase7",
        },
    }
    profile_path = ROOT / "mooncake-profile.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    environment = dict(
        os.environ, VLLM_HUST_EXT_CONFIG=str(ROOT / "manager-mooncake.json")
    )
    manager = str(VENV / "bin/vllm-hust-ext")
    bundle = "org.vllm-hust.mooncake-provider"
    subprocess.run(
        [manager, "extension", "configure", bundle, "--file", str(profile_path)],
        env=environment,
        check=True,
    )
    subprocess.run(
        [manager, "extension", "enable", bundle], env=environment, check=True
    )
    plans = {}
    for arm in ("native", "mooncake"):
        path = ROOT / f"launch-{arm}.sh"
        launcher = path.read_text().replace(str(BASE / "phase4/core"), str(CORE))
        launcher = launcher.replace(str(BASE / ".venv/bin"), str(VENV / "bin"))
        lines = launcher.splitlines()
        command = shlex.split(lines[-1])
        if command[:2] != ["exec", str(VENV / "bin/vllm")]:
            raise RuntimeError("Unexpected original serving launcher")
        if arm == "mooncake":
            index = command.index("--kv-transfer-config")
            del command[index : index + 2]
        command = [
            str(VENV / "bin/python"),
            "-m",
            "vllm.entrypoints.cli.main",
        ] + command[2:]
        environment["VLLM_HUST_EXT_CONFIG"] = str(ROOT / f"manager-{arm}.json")
        plan = json.loads(
            subprocess.check_output(
                [manager, "run", "--dry-run", "--", *command],
                env=environment,
                text=True,
            )
        )
        plans[arm] = plan["command"]
        lines[-1:] = [
            f'export VLLM_HUST_EXT_CONFIG="{environment["VLLM_HUST_EXT_CONFIG"]}"',
            "exec " + shlex.join([manager, "run", "--", *command]),
        ]
        path.write_text("\n".join(lines) + "\n")
    candidate = plans["mooncake"].copy()
    index = candidate.index("--kv-transfer-config")
    del candidate[index : index + 2]
    if candidate != plans["native"]:
        raise RuntimeError("Managed arms differ beyond the connector")
    (ROOT / "manager-plans.json").write_text(json.dumps(plans, indent=2) + "\n")
    controller = ROOT / "qualify.py"
    controller.write_text(
        controller.read_text().replace('str(BASE / ".venv/bin/vllm")', repr(manager))
    )
    # The original qualification controller and all its release gates remain;
    # only the expected supervised executable changes to the manager.
    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    hashes = manifest["sha256"]
    for relative, expected in list(hashes.items()):
        path = (ROOT / relative).resolve()
        if path.is_relative_to(BASE / "phase4/core"):
            source = str(path.relative_to(BASE / "phase4/core"))
            fixed = CORE / source
            target = patch["files"].get(source, expected)
            if sha(fixed) != target:
                raise RuntimeError(f"Unexpected Host change: {source}")
            hashes[str(fixed)] = target
    for package in ("vllm_hust_ext", "vllm_hust_mooncake_provider"):
        for path in (VENV / "lib/python3.12/site-packages" / package).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                hashes[str(path)] = sha(path)
    (ROOT / "prepare_managed.py").write_bytes(Path(__file__).read_bytes())
    for path in ROOT.iterdir():
        if path.is_file() and path != manifest_path:
            hashes[str(path)] = sha(path)
            hashes.pop(path.name, None)
    manifest["core_patch"] = patch
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared managed qualification", ROOT)


if __name__ == "__main__":
    main()
