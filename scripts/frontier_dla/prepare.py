"""Prepare matched Native/BidKV/DLA TP2 launchers after curve devices release."""

import hashlib
import json
import socket
import tarfile
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
ROOT = BASE / "phase4"
OLD = BASE / "phase2"
POD = "coder-admin-shuhao-evaluation-664b765847-wfh7z"
CORE = "d0f22d2bda562156e4dbf433ce645e1769b4f804"
DLA = "dc20d0f8ea8d09106f77571e1947b9a2f8702545"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    if socket.gethostname() != POD:
        raise RuntimeError("Wrong container")
    import qualify

    if qualify.owners():
        raise RuntimeError("Wait for the preceding campaign to release its devices")
    lock = json.loads((ROOT / "source-lock.json").read_text())
    for name, expected_revision in (("core", CORE), ("plugin", DLA)):
        item = lock[name]
        if (
            item["revision"] != expected_revision
            or digest(ROOT / item["archive"]) != item["sha256"]
        ):
            raise RuntimeError(f"Source archive identity mismatch: {name}")
        if (ROOT / name).exists():
            raise RuntimeError(
                f"Refuse to overwrite an existing source capsule: {name}"
            )
    for name in ("core", "plugin"):
        (ROOT / name).mkdir()
        with tarfile.open(ROOT / lock[name]["archive"], "r:gz") as archive:
            archive.extractall(ROOT / name, filter="data")
    for name, item in json.loads((BASE / "model-manifest.json").read_text()).items():
        path = BASE / "model" / name
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise RuntimeError(f"Model source mismatch: {name}")
    if (
        digest(BASE / "prepared/qwen35.json")
        != "aa23f49e08a946d94eaab21307e9e015140cc8598adfbd5f7e244bdded7b17d0"
    ):
        raise RuntimeError("Workload changed")
    # This preparation must be followed by the software integration suite; it
    # cannot itself authorize measurements by writing software_tests_passed.
    (ROOT / "receipts").mkdir(exist_ok=False)
    launch = (OLD / "launch-nativepp.sh").read_text()
    launch = launch.replace(f"cd {OLD}", f"cd {ROOT}")
    launch = launch.replace(
        "ASCEND_RT_VISIBLE_DEVICES=0,1,2,3", "ASCEND_RT_VISIBLE_DEVICES=0,1"
    )
    launch = launch.replace(str(OLD / "core"), str(ROOT / "core"))
    launch = launch.replace(str(OLD / "plugin/src"), str(ROOT / "plugin/src"))
    launch = launch.replace("33782", "33783").replace(
        "frontier-qwen35-pp2", "frontier-qwen35-dla"
    )
    launch = launch.replace("--pipeline-parallel-size 2", "--pipeline-parallel-size 1")
    old_manifest = json.loads((OLD / "manifest.json").read_text())
    shared_sources = {}
    for name, sha in old_manifest["sha256"].items():
        if name.startswith("ascend-wheel/") or name in {
            "pipeline_worker.py",
            "../frontier_worker.py",
        }:
            if digest(OLD / name) != sha:
                raise RuntimeError(f"Shared runtime source changed: {name}")
            shared_sources["../phase2/" + name] = sha
    bidkv_pth = (
        BASE
        / ".venv/lib/python3.12/site-packages/__editable__.vllm_hust_bidkv-0.2.1.pth"
    )
    if bidkv_pth.read_text().strip() != str(BASE / "bidkv/src"):
        raise RuntimeError("BidKV editable source path changed")
    bidkv_sources = list((BASE / "bidkv/src/bidkv").rglob("*.py"))
    if not bidkv_sources:
        raise RuntimeError("Missing BidKV source files")
    actual_bidkv = {
        str(path.relative_to(BASE / "bidkv")): digest(path) for path in bidkv_sources
    }
    if actual_bidkv != lock["bidkv"]["files"]:
        raise RuntimeError("Installed BidKV does not match the pinned source tree")
    for path in [bidkv_pth, *bidkv_sources]:
        shared_sources["../" + str(path.relative_to(BASE))] = digest(path)
    programs = []
    for arm in ("native", "bidkv", "dla"):
        command = launch.rstrip()
        if arm == "bidkv":
            command += " --preemption-policy bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy"
        elif arm == "dla":
            command = command.replace(
                '{"enable_cpu_binding":false}',
                '{"enable_cpu_binding":false,"dla_exact_output_budgets":true}',
            )
            command += " --preemption-policy dla.preemption.DeclaredBudgetPreemptionPolicy --scheduler-reserve-output-budget"
        (ROOT / f"launch-{arm}.sh").write_text(command + "\n")
        metadata = json.loads((OLD / "metadata-nativepp.json").read_text())
        metadata.update(
            pod=POD,
            pod_uid="19a77c6d-a27a-4c6e-b955-e016beca3a82",
            container_allocated_npus=4,
            serving_chips=2,
            serving_devices=[0, 1],
            port=33783,
            campaign="qwen35-dla-bidkv-curves-20260925",
            core_commit=CORE,
            dla_commit=DLA if arm == "dla" else None,
            bidkv_commit=lock["bidkv"]["revision"] if arm == "bidkv" else None,
            mods=[] if arm == "native" else [arm],
            launch_script_sha256=digest(ROOT / f"launch-{arm}.sh"),
            comparison="Fresh TP2 common output-budget-capable capsule; one900s observation per cell",
            output_budget_admission=arm == "dla",
            length_source="Declared exact ignore_eos output budget; no learned predictor",
            concurrency_sweep=[1, 2, 4, 8, 16],
        )
        metadata.pop("source_commits_are_bases", None)
        metadata["source_revision_kinds"] = {
            "core": "full pinned commit and exact archive",
            "ascend": "base commit plus qualified patch and exact shared files",
        }
        metadata["source_patches_sha256"].pop("core-qualified.patch.gz", None)
        metadata["source_patches_sha256"]["core-output-budget.patch.gz"] = digest(
            ROOT / "core-output-budget.patch.gz"
        )
        metadata["runtime_common_changes"] += (
            "; opt-in known-output-budget capacity admission and event metrics; "
            "disabled for Native/BidKV, enabled for DLA"
        )
        metadata["source_archives"] = lock
        metadata["environment"]["ASCEND_RT_VISIBLE_DEVICES"] = "0,1"
        metadata["runtime_source_files"] = {
            str(p.relative_to(ROOT)): digest(p)
            for sub in ("core/vllm", "plugin/src/dla")
            for p in (ROOT / sub).rglob("*.py")
        }
        metadata["runtime_source_files"].update(shared_sources)
        (ROOT / f"metadata-{arm}.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
        for name, cmd, stop in (
            (arm, f"/bin/bash {ROOT}/launch-{arm}.sh", 90),
            (
                f"measure-{arm}",
                f"{BASE}/.venv/bin/python {ROOT}/qualify.py --attempt {arm}-measured-r1 --program {arm} --measure --metadata metadata-{arm}.json",
                300,
            ),
        ):
            programs.append(
                f"""[program:{name}]
command={cmd}
directory={ROOT}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs={stop}
redirect_stderr=true
stdout_logfile={ROOT}/receipts/{name}.log
stdout_logfile_maxbytes=100MB
"""
                + ("stopasgroup=true\nkillasgroup=true\n" if name == arm else "")
            )
    programs.append(
        f"""[program:campaign]
command={BASE}/.venv/bin/python {ROOT}/run_campaign.py --attempt matched-curves-r1
directory={ROOT}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs=420
redirect_stderr=true
stdout_logfile={ROOT}/receipts/campaign.log
stdout_logfile_maxbytes=100MB
"""
    )
    prefix = (
        (OLD / "supervisord.conf")
        .read_text()
        .split("[program:")[0]
        .replace(str(OLD), str(ROOT))
    )
    (ROOT / "supervisord.conf").write_text(prefix + "\n".join(programs))
    manifest = {
        "software_tests_passed": False,
        "core_revision": CORE,
        "dla_revision": DLA,
        "sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in ROOT.rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.name != "manifest.json"
        },
    }
    manifest["sha256"].update(shared_sources)
    manifest["sha256"]["../prepared/qwen35.json"] = digest(
        BASE / "prepared/qwen35.json"
    )
    manifest["sha256"]["../frontier_qualify.py"] = (
        "9221d6e069d44051d5b54b2ce0962fe34542a136c8226bfb2907d0f605b44d70"
    )
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared inactive campaign; runtime integration tests are still required")


if __name__ == "__main__":
    main()
