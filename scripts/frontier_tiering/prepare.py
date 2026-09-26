"""Prepare a manager-owned experiment without changing the qualified capsule."""

import hashlib
import importlib.metadata
import json
import socket
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
ROOT = BASE / "phase6/serving-r8"
OLD = BASE / "phase4"
VENV = BASE / "phase6/.venv-r7"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if socket.gethostname() != "coder-admin-shuhao-evaluation-664b765847-wfh7z":
        raise RuntimeError("wrong container")
    test_log = (BASE / "phase6/wheel-tests-r7-full.log").read_text()
    if "10 passed" not in test_log or "failed" in test_log:
        raise RuntimeError("Installed-wheel tests must pass before preparation")
    ROOT.mkdir(exist_ok=False)
    (ROOT / "receipts").mkdir()
    original = json.loads((OLD / "manifest.json").read_text())
    hashes = {str((OLD / p).resolve()): v for p, v in original["sha256"].items()}
    for p, expected in hashes.items():
        if sha(Path(p)) != expected:
            raise RuntimeError(f"Frozen capsule changed: {p}")
    # Preserve the original capsule; apply the same reviewed Host fix to both arms.
    core_patch = json.loads((BASE / "phase6/core-patch-r6.json").read_text())
    fixed_core = BASE / "phase6/core-r6"
    for old_path, expected in list(hashes.items()):
        old_file = Path(old_path)
        if old_file.is_relative_to(OLD / "core"):
            relative = str(old_file.relative_to(OLD / "core"))
            fixed_file = fixed_core / relative
            fixed_expected = core_patch["files"].get(relative, expected)
            if sha(fixed_file) != fixed_expected:
                raise RuntimeError(f"Unexpected Host change: {relative}")
            hashes[str(fixed_file)] = fixed_expected
    hashes[str(BASE / "phase6/core-patch-r6.json")] = sha(BASE / "phase6/core-patch-r6.json")
    (ROOT / "qualify.py").write_bytes((BASE / "phase6/qualify-managed.py").read_bytes())
    (ROOT / "manager-native.json").write_text('{"schema_version":2,"extensions":{}}\n')
    (ROOT / "manager-tiering.json").write_text(
        (BASE / "phase6/manager-tiering.json")
        .read_text()
        .replace("tiering-storage-r1", "tiering-storage-r8")
    )
    for name in ["run_campaign.py", "transfer_receipt.py"]:
        (ROOT / name).write_bytes((BASE / "phase6" / name).read_bytes())
    package_root = VENV / "lib/python3.12/site-packages"
    for module in ["vllm_hust_ext", "vllm_hust_kv_tiering", "vllm_ascend_split_batch"]:
        for p in (package_root / module).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                hashes[str(p)] = sha(p)
    common = (OLD / "launch-native.sh").read_text()
    common = common.replace(str(OLD) + "\n", str(ROOT) + "\n", 1)
    common = common.replace(str(BASE / ".venv/bin"), str(VENV / "bin"))
    common = common.replace(
        "unset FRONTIER_PP_CALIBRATION_DIR",
        "unset FRONTIER_PP_CALIBRATION_DIR\nexport VLLM_PLUGINS=ascend",
    )
    common = common.replace(
        "exec " + str(VENV / "bin/vllm") + " serve",
        "exec "
        + str(VENV / "bin/vllm-hust-ext")
        + " run -- "
        + str(VENV / "bin/python")
        + " -m vllm.entrypoints.cli.main serve",
    )
    common = common.replace(str(OLD / "core"), str(fixed_core))
    for arm in ["native", "tiering"]:
        launcher = common.replace(
            "exec ",
            f'export VLLM_HUST_EXT_CONFIG="{ROOT}/manager-{arm}.json"\nexec ',
            1,
        )
        (ROOT / f"launch-{arm}.sh").write_text(launcher)
        metadata = json.loads((OLD / "metadata-native.json").read_text())
        metadata["packages"].pop("vllm-hust-bidkv", None)
        for name in ["vllm-hust-ext", "vllm-hust-kv-tiering", "platformdirs"]:
            metadata["packages"][name] = importlib.metadata.version(name)
        metadata["core_patch"] = core_patch
        metadata["mods"] = [] if arm == "native" else ["kv-tiering"]
        metadata["comparison"] = (
            "Manager-launched TP2; identical Frontier options; synchronous Ascend tiering adapter"
        )
        metadata["python"] = str(VENV / "bin/python")
        metadata["manager"] = {
            "revision": "cf1ea71e3e2cb81ab06267ef05eddb3e580ea20b",
            "state_sha256": sha(ROOT / f"manager-{arm}.json"),
        }
        metadata["plugin_revision"] = (
            (BASE / "phase6/plugin-revision-r7.txt").read_text().strip()
        )
        metadata["launch_script_sha256"] = sha(ROOT / f"launch-{arm}.sh")
        metadata["runtime_source_files"] = hashes.copy()
        (ROOT / f"metadata-{arm}.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
    config = f"""[unix_http_server]
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
    for arm in ["native", "tiering"]:
        config += f"""
[program:{arm}]
command=/bin/bash {ROOT}/launch-{arm}.sh
directory={ROOT}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs=90
redirect_stderr=true
stdout_logfile={ROOT}/receipts/{arm}.log
stdout_logfile_maxbytes=100MB
stopasgroup=true
killasgroup=true

[program:qualify-{arm}]
command={VENV}/bin/python {ROOT}/qualify.py --attempt {arm}-qualify-r1 --program {arm} --qualification-only
directory={ROOT}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs=180
redirect_stderr=true
stdout_logfile={ROOT}/receipts/qualify-{arm}.log
stdout_logfile_maxbytes=100MB
"""
        config += f"""
[program:measure-{arm}]
command={VENV}/bin/python {ROOT}/qualify.py --attempt {arm}-measured-r1 --program {arm} --measure --metadata metadata-{arm}.json
directory={ROOT}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs=180
redirect_stderr=true
stdout_logfile={ROOT}/receipts/measure-{arm}.log
stdout_logfile_maxbytes=100MB
"""
    config += f"""
[program:campaign]
command={VENV}/bin/python {ROOT}/run_campaign.py
directory={ROOT}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs=360
redirect_stderr=true
stdout_logfile={ROOT}/receipts/campaign.log
stdout_logfile_maxbytes=100MB
"""
    (ROOT / "supervisord.conf").write_text(config)
    for p in ROOT.iterdir():
        if p.is_file():
            hashes[str(p)] = sha(p)
    (ROOT / "manifest.json").write_text(
        json.dumps(
            {
                "software_tests_passed": True,
                "software_receipt": str(BASE / "phase6/wheel-tests-r7-full.log"),
                "sha256": hashes,
            },
            indent=2,
        )
        + "\n"
    )
    print("Prepared", ROOT)


if __name__ == "__main__":
    main()
