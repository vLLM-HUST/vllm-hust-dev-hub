"""Stage a shared-runtime campaign; no service launch or accelerator allocation."""

import copy
import json
import shutil
import socket
import subprocess
import zipfile
from pathlib import Path
from contract import ARMS, digest, manager_json, validate_plans

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
ROOT = BASE / "phase9-unified-r3"
OLD = BASE / "phase8"
HERE = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    if socket.gethostname() != "coder-admin-shuhao-evaluation-664b765847-wfh7z":
        raise RuntimeError("Wrong assigned container")
    ROOT.mkdir(exist_ok=False)
    (ROOT / "receipts").mkdir()
    overlay = ROOT / "bundles"
    overlay.mkdir()
    wheel = BASE / "phase6/wheels-r7/vllm_hust_kv_tiering-0.1.1.dev0-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        if any(
            Path(n).is_absolute() or ".." in Path(n).parts for n in archive.namelist()
        ):
            raise ValueError("Invalid wheel path")
        archive.extractall(overlay)
    for name in ("measurement_support.py", "managed_custody.py"):
        shutil.copy2(OLD / name, ROOT / name)
    shutil.copy2(HERE / "contract.py", ROOT / "contract.py")
    shutil.copy2(
        BASE / "phase6/serving-r8/transfer_receipt.py", ROOT / "transfer_receipt.py"
    )
    original = json.loads((OLD / "manifest.json").read_text())
    hashes = {str((OLD / k).resolve()): v for k, v in original["sha256"].items()}
    for path, expected in hashes.items():
        if digest(path) != expected:
            raise RuntimeError(f"Frozen source changed: {path}")
    profiles = {
        arm: json.loads((BASE / "phase7" / f"manager-{arm}.json").read_text())
        for arm in ("native", "mooncake")
    }
    profiles["tiering"] = json.loads(
        (BASE / "phase6/serving-r8/manager-tiering.json").read_text()
    )
    profiles["tiering"]["extensions"]["org.vllm-hust.kv-tiering"]["configuration"][
        "storage_directory"
    ] = str(ROOT / "tiering-storage")
    profiles["mooncake"]["extensions"]["org.vllm-hust.mooncake-provider"][
        "configuration"
    ]["kv_connector_extra_config"]["lookup_rpc_port"] = "frontier_phase9_unified"
    common = (
        (OLD / "launch-native.sh")
        .read_text()
        .replace("cd " + str(OLD), "cd " + str(ROOT))
        .replace("frontier-qwen35-mooncake", "frontier-qwen35-unified")
        .replace('export PYTHONPATH="', 'export PYTHONPATH="' + str(overlay) + ":")
    )
    plans = {}
    for arm in ARMS:
        write(ROOT / f"manager-{arm}.json", profiles[arm])
        launch = common.replace(
            str(BASE / "phase7/manager-native.json"), str(ROOT / f"manager-{arm}.json")
        )
        (ROOT / f"launch-{arm}.sh").write_text(launch)
        query = launch.replace(" run -- ", " run --dry-run -- ")
        if arm == "mooncake":
            query = (
                launch.split("exec ", 1)[0]
                + "exec "
                + str(BASE / "phase7-env/venv/bin/vllm-hust-ext")
                + " extension plan org.vllm-hust.mooncake-provider\n"
            )
        result = subprocess.run(
            ["/bin/bash", "-c", query], capture_output=True, text=True, timeout=120
        )
        (ROOT / f"plan-{arm}.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"{arm} manager plan failed: {result.stderr[-1500:]}")
        plan = manager_json(result.stdout)
        write(ROOT / f"plan-{arm}.json", plan)
        if arm == "mooncake":
            plans[arm] = plans["native"] + [
                "--kv-transfer-config",
                json.dumps(
                    plan["generated_config"]["kv_transfer_config"],
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ]
        else:
            plans[arm] = plan["command"]
    validate_plans(plans)
    write(ROOT / "manager-plans.json", plans)
    # Every arm sees the same frozen overlay, packages and common runtime paths.
    for p in overlay.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            hashes[str(p)] = digest(p)
    contract = dict(
        schema_version="frontier-shared-native/v1",
        baseline_id="qwen35-unified-native-20260927",
        native_command=plans["native"],
        runtime_source_files=hashes,
        workload=str(BASE / "prepared/qwen35.json"),
        workload_sha256=digest(BASE / "prepared/qwen35.json"),
        concurrencies=[1, 2, 4, 8, 16],
        seconds_per_cell=900,
        shared_environment_launcher=str(ROOT / "launch-native.sh"),
        model="Qwen3.5-35B-A3B BF16",
        candidate_changes="Only the declared plugin and its configuration; one shared Native, no per-MOD controls",
    )
    write(ROOT / "common-contract.json", contract)
    controller = (
        (OLD / "qualify.py")
        .read_text()
        .replace("frontier-qwen35-mooncake", "frontier-qwen35-unified")
    )
    controller = controller.replace(
        "    from measurement_support import verify_qualification\n    verify_qualification(ROOT)",
        "    from contract import verify\n    from measurement_support import require_idle_memory\n    verify(ROOT)\n    require_idle_memory()",
    )
    controller = controller.replace(
        'choices=["native", "mooncake"]', 'choices=["native", "mooncake", "tiering"]'
    )
    controller = controller.replace(
        'elif program == "mooncake":', 'elif program in ("mooncake", "tiering"):'
    ).replace(
        "from measurement_support import transfer_receipt as receipt",
        'from measurement_support import transfer_receipt as generic_receipt\n                    from transfer_receipt import receipt as tiering_receipt\n                    receipt = tiering_receipt if program == "tiering" else generic_receipt',
    )
    controller = controller.replace(
        "        started = True\n",
        '        launch = (ROOT / f"launch-{program}.sh").read_text()\n        dry = subprocess.run(["/bin/bash", "-c", launch.replace(" run -- ", " run --dry-run -- ")], capture_output=True, text=True, timeout=120)\n        (out / "manager-live-dry-run.log").write_text(dry.stdout + dry.stderr)\n        expected = json.loads((ROOT / "manager-plans.json").read_text())[program]\n        from contract import manager_json\n        if dry.returncode or manager_json(dry.stdout)["command"] != expected:\n            raise RuntimeError("Manager live health/plan differs from frozen common-Native contract")\n        started = True\n',
    )
    compile(controller, "qualify.py", "exec")
    (ROOT / "qualify.py").write_text(controller)
    campaign = (
        (OLD / "run_campaign.py")
        .read_text()
        .replace(
            'for arm in ("mooncake", "native"):',
            'for arm in ("native", "mooncake", "tiering"):',
        )
        .replace("matched-curves-r1", "shared-native-r1")
    )
    (ROOT / "run_campaign.py").write_text(campaign)
    shutil.copy2(OLD / "launch-master.sh", ROOT / "launch-master.sh")
    header = (
        (OLD / "supervisord.conf")
        .read_text()
        .split("[program:native]")[0]
        .replace(str(OLD), str(ROOT))
    )
    program_template = """\n[program:{name}]\ncommand={command}\ndirectory={root}\nautostart=false\nautorestart=false\nstartsecs=1\nstartretries=0\nstopwaitsecs={wait}\nredirect_stderr=true\nstdout_logfile={root}/receipts/{name}.log\nstdout_logfile_maxbytes=0\n{group}\n"""
    commands = []
    for arm in ARMS:
        commands.append((arm, f"/bin/bash {ROOT}/launch-{arm}.sh", 90, True))
        commands.append(
            (
                f"measure-{arm}",
                f"{BASE}/phase7-env/venv/bin/python {ROOT}/qualify.py --attempt {arm}-measured-r1 --program {arm} --measure --metadata metadata-{arm}.json",
                360,
                False,
            )
        )
    commands.extend(
        [
            ("master", f"/bin/bash {ROOT}/launch-master.sh", 90, True),
            (
                "campaign",
                f"{BASE}/phase7-env/venv/bin/python {ROOT}/run_campaign.py",
                360,
                False,
            ),
        ]
    )
    (ROOT / "supervisord.conf").write_text(
        header
        + "".join(
            program_template.format(
                name=n,
                command=c,
                root=ROOT,
                wait=w,
                group="stopasgroup=true\nkillasgroup=true" if g else "",
            )
            for n, c, w, g in commands
        )
    )
    for arm in ARMS:
        metadata = copy.deepcopy(json.loads((OLD / "metadata-native.json").read_text()))
        metadata.update(
            campaign="qwen35-unified-native-20260927",
            mods=[] if arm == "native" else [arm],
            comparison="ONE shared Native series for every MOD",
            shared_native_baseline_id=contract["baseline_id"],
            shared_native_contract_sha256=digest(ROOT / "common-contract.json"),
            runtime_source_files=hashes.copy(),
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
    all_hashes = hashes.copy()
    for p in ROOT.iterdir():
        if p.is_file():
            all_hashes[str(p)] = digest(p)
    write(
        ROOT / "manifest.json",
        dict(
            schema_version="unified-native-preparation/v1",
            software_tests_passed=False,
            sha256=all_hashes,
            baseline_id=contract["baseline_id"],
        ),
    )
    print(
        json.dumps(
            {
                "root": str(ROOT),
                "baseline_id": contract["baseline_id"],
                "arms": list(ARMS),
                "contract_sha256": digest(ROOT / "common-contract.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
