"""Prepare a supervised candidate-only retry that reuses phase9's passed Native."""

from __future__ import annotations

import hashlib
import json
import shutil
import socket
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
SOURCE = BASE / "phase9-unified-r3"
ROOT = BASE / "phase9-unified-retry-r1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def main() -> None:
    if socket.gethostname() != "coder-admin-shuhao-evaluation-664b765847-wfh7z":
        raise RuntimeError("Wrong assigned container")
    if ROOT.exists():
        raise FileExistsError(ROOT)
    native = json.loads(
        (SOURCE / "receipts/native-measured-r1/status.json").read_text()
    )
    if (
        native.get("passed") is not True
        or native.get("stage") != "completed"
        or native.get("release", {}).get("exit") != 0
        or native.get("release", {}).get("owners")
    ):
        raise RuntimeError("The single phase9 Native is not complete and released")
    ROOT.mkdir()
    (ROOT / "receipts").mkdir()
    files = (
        "common-contract.json",
        "contract.py",
        "launch-master.sh",
        "launch-mooncake.sh",
        "launch-tiering.sh",
        "managed_custody.py",
        "manager-mooncake.json",
        "manager-tiering.json",
        "manager-plans.json",
        "measurement_support.py",
        "metadata-native.json",
        "metadata-mooncake.json",
        "metadata-tiering.json",
        "qualify.py",
        "transfer_receipt.py",
    )
    for name in files:
        shutil.copy2(SOURCE / name, ROOT / name)
    campaign = (SOURCE / "run_campaign.py").read_text()
    campaign = (
        campaign.replace(
            'def main(pair_attempt="shared-native-r1"):',
            'def main(pair_attempt="shared-native-retry-r1"):',
        )
        .replace(
            'for arm in ("native", "mooncake", "tiering"):',
            'for arm in ("mooncake", "tiering"):',
        )
        .replace(
            'attempt = f"{arm}-measured-r1"',
            'attempt = "mooncake-measured-r2" if arm == "mooncake" else "tiering-measured-r1"',
        )
        .replace(
            "        from qualify import preflight\n        preflight()",
            "        from qualify import preflight\n"
            "        preflight()\n"
            "        baseline = json.loads((Path("
            + repr(str(SOURCE / "receipts/native-measured-r1/status.json"))
            + ")).read_text())\n"
            "        if (baseline.get('passed') is not True or baseline.get('stage') != 'completed'\n"
            "                or baseline.get('release', {}).get('exit') != 0\n"
            "                or baseline.get('release', {}).get('owners')):\n"
            "            raise RuntimeError('Single phase9 Native is not released')",
        )
        .replace(
            'parser.add_argument("--attempt", default="shared-native-r1")',
            'parser.add_argument("--attempt", default="shared-native-retry-r1")',
        )
    )
    compile(campaign, "run_campaign.py", "exec")
    (ROOT / "run_campaign.py").write_text(campaign)

    source_header = (
        (SOURCE / "supervisord.conf").read_text().split("[program:native]")[0]
    )
    header = source_header.replace(str(SOURCE), str(ROOT))
    template = """
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
    commands = [
        ("mooncake", f"/bin/bash {ROOT}/launch-mooncake.sh", "false", 90, True),
        (
            "measure-mooncake",
            f"{BASE}/phase7-env/venv/bin/python {ROOT}/qualify.py --attempt mooncake-measured-r2 --program mooncake --measure --metadata metadata-mooncake.json",
            "false",
            360,
            False,
        ),
        ("tiering", f"/bin/bash {ROOT}/launch-tiering.sh", "false", 90, True),
        (
            "measure-tiering",
            f"{BASE}/phase7-env/venv/bin/python {ROOT}/qualify.py --attempt tiering-measured-r1 --program tiering --measure --metadata metadata-tiering.json",
            "false",
            360,
            False,
        ),
        ("master", f"/bin/bash {ROOT}/launch-master.sh", "false", 90, True),
        (
            "campaign",
            f"{BASE}/phase7-env/venv/bin/python {ROOT}/run_campaign.py",
            "true",
            360,
            False,
        ),
    ]
    (ROOT / "supervisord.conf").write_text(
        header
        + "".join(
            template.format(
                name=name,
                command=command,
                root=ROOT,
                autostart=autostart,
                wait=wait,
                group="stopasgroup=true\nkillasgroup=true" if group else "",
            )
            for name, command, autostart, wait, group in commands
        )
    )
    source_manifest = json.loads((SOURCE / "manifest.json").read_text())
    external = {
        path: expected
        for path, expected in source_manifest["sha256"].items()
        if not path.startswith(str(SOURCE) + "/")
    }
    local = {
        str(path): digest(path)
        for path in ROOT.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    write(
        ROOT / "manifest.json",
        {
            "schema_version": "unified-native-candidate-retry/v1",
            "software_tests_passed": True,
            "sha256": external | local,
            "baseline_id": "qwen35-unified-native-20260927",
            "baseline_receipt": str(SOURCE / "receipts/native-measured-r1/status.json"),
            "previous_failure": str(
                SOURCE / "receipts/mooncake-measured-r1/status.json"
            ),
        },
    )
    print(json.dumps({"root": str(ROOT), "arms": ["mooncake", "tiering"]}))


if __name__ == "__main__":
    main()
