"""Stage BidKV and DLA follow-ups without launching a service or using an NPU."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import shutil
import socket
import subprocess
import zipfile
from pathlib import Path

from contract import ARMS, BASE, NATIVE_ROOT, digest, manager_json, validate_plans

ROOT = BASE / "phase10-followup-r1"
HERE = Path(__file__).resolve().parent


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def add_adapter(
    overlay: Path,
    name: str,
    bundle_id: str,
    implementation: str,
    *,
    environment: dict[str, str] | None = None,
    additional_config: dict[str, object] | None = None,
) -> None:
    module, object_name = implementation.rsplit(".", 1)
    package = overlay / f"frontier_{name}_adapter" / "manifests"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    manifest_path = package / "vllm-hust-extension-v0.2.json"
    manifest = {
        "schema_version": "0.2-experimental",
        "extension_id": bundle_id,
        "extension_version": "0.1.0",
        "kind": "scheduler_policy",
        "host": {
            "provider": "vllm",
            "name": "vllm",
            "version_range": ">=0.25.1,<0.26",
            "api_range": ">=1,<2",
        },
        "runtime": {
            "type": "python",
            "process_scope": "scheduler",
            "isolation": "trusted_in_process",
        },
        "lifecycle_owner": "vllm",
        "protocols": [{"name": "vllm.preemption-policy", "version_range": ">=1,<2"}],
        "implementation": [
            {
                "type": "python_module",
                "module": module,
                "object": object_name,
                "status": "active",
            }
        ],
        "requires_services": [],
        "components": [
            {
                "component_id": "preemption-policy",
                "contracts": ["vllm.preemption-policy.v1"],
                "execution_planes": ["scheduler"],
                "isolation": "trusted_in_process",
                "implementation_ref": f"{module}:{object_name}",
                "permissions": [],
            }
        ],
        "activation": {
            "entry_points": [],
            "environment": environment or {},
            "additional_config": additional_config or {},
        },
    }
    write(manifest_path, manifest)
    dist_info = overlay / f"frontier_{name}_adapter-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: frontier-{name}-adapter\nVersion: 0.1.0\n"
    )
    (dist_info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nGenerator: frontier-followup\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    (dist_info / "entry_points.txt").write_text(
        "[vllm_hust.extension_bundles]\n"
        f"{bundle_id} = frontier_{name}_adapter.manifests\n"
    )
    relative = manifest_path.relative_to(overlay)
    with (dist_info / "RECORD").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow((str(relative), "", ""))


def main(manager_wheel: Path) -> None:
    if socket.gethostname() != "coder-admin-shuhao-evaluation-664b765847-wfh7z":
        raise RuntimeError("Wrong assigned container")
    if ROOT.exists():
        raise FileExistsError(ROOT)
    native_status = json.loads(
        (NATIVE_ROOT / "receipts/native-measured-r1/status.json").read_text()
    )
    if native_status.get("stage") not in {"measurement", "completed"}:
        raise RuntimeError("Shared Native has not reached real measurement")
    ROOT.mkdir()
    (ROOT / "receipts").mkdir()
    overlay = ROOT / "bundles"
    shutil.copytree(NATIVE_ROOT / "bundles", overlay)
    with zipfile.ZipFile(manager_wheel) as archive:
        if any(
            Path(name).is_absolute() or ".." in Path(name).parts
            for name in archive.namelist()
        ):
            raise ValueError("Invalid manager wheel path")
        archive.extractall(overlay)
    add_adapter(
        overlay,
        "bidkv",
        "org.vllm-hust.bidkv-frontier-adapter",
        "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy",
        environment={"BIDKV_UTILITY_ENABLE": "1", "BIDKV_UTILITY_STRATEGY": "bidkv"},
    )
    add_adapter(
        overlay,
        "dla",
        "org.vllm-hust.dla-frontier-adapter",
        "dla.preemption.DeclaredBudgetPreemptionPolicy",
        additional_config={"dla_exact_output_budgets": True},
    )
    for name in ("measurement_support.py", "managed_custody.py"):
        shutil.copy2(NATIVE_ROOT / name, ROOT / name)
    shutil.copy2(HERE / "contract.py", ROOT / "contract.py")
    states = {
        "bidkv": {
            "schema_version": 2,
            "extensions": {
                "org.vllm-hust.bidkv-frontier-adapter": {
                    "enabled": True,
                    "configuration": {},
                }
            },
        },
        "dla": {
            "schema_version": 2,
            "extensions": {
                "org.vllm-hust.dla-frontier-adapter": {
                    "enabled": True,
                    "configuration": {
                        "launch_options": {"scheduler_reserve_output_budget": True}
                    },
                }
            },
        },
    }
    common = (NATIVE_ROOT / "launch-native.sh").read_text()
    common = common.replace(f"cd {NATIVE_ROOT}", f"cd {ROOT}")
    common = common.replace(
        f'export PYTHONPATH="{NATIVE_ROOT}/bundles:',
        f'export PYTHONPATH="{overlay}:{NATIVE_ROOT}/bundles:',
    )
    plans: dict[str, list[str]] = {}
    for arm in ARMS:
        write(ROOT / f"manager-{arm}.json", states[arm])
        launch = common.replace(
            f'export VLLM_HUST_EXT_CONFIG="{NATIVE_ROOT}/manager-native.json"',
            f'export VLLM_HUST_EXT_CONFIG="{ROOT}/manager-{arm}.json"',
        )
        (ROOT / f"launch-{arm}.sh").write_text(launch)
        dry = subprocess.run(
            ["/bin/bash", "-c", launch.replace(" run -- ", " run --dry-run -- ")],
            capture_output=True,
            text=True,
            timeout=180,
        )
        (ROOT / f"plan-{arm}.log").write_text(dry.stdout + dry.stderr)
        if dry.returncode:
            raise RuntimeError(f"{arm} manager dry-run failed: {dry.stderr[-1500:]}")
        plans[arm] = manager_json(dry.stdout)["command"]
    validate_plans(plans)
    write(ROOT / "manager-plans.json", plans)

    qualify = (NATIVE_ROOT / "qualify.py").read_text()
    qualify = qualify.replace(
        'choices=["native", "mooncake", "tiering"]', 'choices=["bidkv", "dla"]'
    )
    compile(qualify, "qualify.py", "exec")
    (ROOT / "qualify.py").write_text(qualify)
    campaign = (NATIVE_ROOT / "run_campaign.py").read_text()
    campaign = campaign.replace(
        'for arm in ("native", "mooncake", "tiering"):',
        'for arm in ("bidkv", "dla"):',
    ).replace("shared-native-r1", "shared-native-followup-r1")
    (ROOT / "run_campaign.py").write_text(campaign)
    (ROOT / "wait_for_native.py").write_text((HERE / "wait_for_native.py").read_text())

    native_metadata = json.loads((NATIVE_ROOT / "metadata-native.json").read_text())
    external = json.loads((NATIVE_ROOT / "common-contract.json").read_text())[
        "runtime_source_files"
    ]
    for path in (BASE / "bidkv/src/bidkv").rglob("*.py"):
        external[str(path)] = digest(path)
    for path in (BASE / "phase4/plugin/src/dla").rglob("*.py"):
        external[str(path)] = digest(path)
    for path in overlay.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            external[str(path)] = digest(path)
    contract_sha = digest(NATIVE_ROOT / "common-contract.json")
    for arm in ARMS:
        metadata = copy.deepcopy(native_metadata)
        metadata.update(
            campaign="qwen35-unified-native-followup-20260927",
            mods=[arm],
            comparison="ONE phase9 shared Native series; no candidate-specific Native",
            shared_native_baseline_id="qwen35-unified-native-20260927",
            shared_native_contract_sha256=contract_sha,
            runtime_source_files=external.copy(),
            launch_script_sha256=digest(ROOT / f"launch-{arm}.sh"),
            launch_environment_source={
                "path": str(ROOT / f"launch-{arm}.sh"),
                "sha256": digest(ROOT / f"launch-{arm}.sh"),
            },
            manager={
                "state_path": str(ROOT / f"manager-{arm}.json"),
                "state_sha256": digest(ROOT / f"manager-{arm}.json"),
                "qualified_command": plans[arm],
            },
            qualification_root=str(ROOT),
        )
        write(ROOT / f"metadata-{arm}.json", metadata)

    header = (NATIVE_ROOT / "supervisord.conf").read_text().split("[program:native]")[0]
    header = header.replace(str(NATIVE_ROOT), str(ROOT))
    program = """
[program:{name}]
command={command}
directory={root}
autostart={autostart}
autorestart=false
startsecs=1
startretries=0
stopwaitsecs={wait}
redirect_stderr=true
stdout_logfile={root}/receipts/{name}.log
stdout_logfile_maxbytes=0
{group}
"""
    entries = []
    for arm in ARMS:
        entries.append((arm, f"/bin/bash {ROOT}/launch-{arm}.sh", "false", 90, True))
        entries.append(
            (
                f"measure-{arm}",
                f"{BASE}/phase7-env/venv/bin/python {ROOT}/qualify.py --attempt {arm}-measured-r1 --program {arm} --measure --metadata metadata-{arm}.json",
                "false",
                360,
                False,
            )
        )
    entries.extend(
        [
            (
                "campaign",
                f"{BASE}/phase7-env/venv/bin/python {ROOT}/run_campaign.py",
                "false",
                360,
                False,
            ),
            (
                "waiter",
                f"{BASE}/phase7-env/venv/bin/python {ROOT}/wait_for_native.py",
                "true",
                360,
                False,
            ),
        ]
    )
    (ROOT / "supervisord.conf").write_text(
        header
        + "".join(
            program.format(
                name=name,
                command=command,
                root=ROOT,
                autostart=autostart,
                wait=wait,
                group="stopasgroup=true\nkillasgroup=true" if group else "",
            )
            for name, command, autostart, wait, group in entries
        )
    )
    local_files = {}
    for path in ROOT.iterdir():
        if path.is_file():
            local_files[path.name] = digest(path)
    write(
        ROOT / "manifest.json",
        {
            "schema_version": "frontier-shared-native-followup/v1",
            "software_tests_passed": False,
            "baseline_id": "qwen35-unified-native-20260927",
            "manager_revision": "5b6f7af447fd118ce0d5148d86cd4028f8c9ae59",
            "native_contract_sha256": contract_sha,
            "external_sha256": external,
            "sha256": local_files,
        },
    )
    print(json.dumps({"root": str(ROOT), "arms": list(ARMS), "plans": plans}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager-wheel", required=True, type=Path)
    args = parser.parse_args()
    main(args.manager_wheel)
