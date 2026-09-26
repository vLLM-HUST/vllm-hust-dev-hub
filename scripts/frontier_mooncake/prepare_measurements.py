"""Prepare phase8 only; never launch processes, configure managers or use devices.

Consumes completed phase7 qualifications. Reuses its exact manager state, plans,
runtime and master configuration; only the serving working directory changes.
The generated supervised pair runs fresh arms with retrieval, prefix and curves.
"""

import argparse
import json
import shlex
import socket
from pathlib import Path

from measurement_support import check_release_addendum, qualified_sources, require_idle_memory, sha

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
HOST = "coder-admin-shuhao-evaluation-664b765847-wfh7z"


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError(f"Harness contract drift: {before!r}")
    return text.replace(before, after, 1)


def validate_plans(plans):
    native, candidate = plans["native"], list(plans["mooncake"])
    index = candidate.index("--kv-transfer-config")
    connector = json.loads(candidate[index + 1])
    if (connector.get("kv_connector") != "AscendStoreConnector"
            or connector.get("kv_role") != "kv_both"
            or connector.get("kv_load_failure_policy") != "fail"
            or connector.get("kv_connector_extra_config", {}).get("backend") != "mooncake"):
        raise RuntimeError("Unexpected qualified Mooncake connector")
    del candidate[index:index + 2]
    if native != candidate:
        raise RuntimeError("Qualified manager arms differ beyond connector")
    def option(name):
        if native.count(name) != 1:
            raise RuntimeError(f"Missing or repeated Frontier option: {name}")
        return native[native.index(name) + 1]
    expected = {
        "--tensor-parallel-size": "2", "--pipeline-parallel-size": "1",
        "--dtype": "bfloat16", "--kv-cache-dtype": "auto", "--max-model-len": "262144",
        "--max-num-seqs": "16", "--max-num-batched-tokens": "4096",
        "--kv-cache-memory-bytes": "26038239232", "--port": "33783",
    }
    for name, value in expected.items():
        if option(name) != value:
            raise RuntimeError(f"Qualified plan differs from Frontier: {name}")
    for name in ("--enable-prefix-caching", "--async-scheduling"):
        if native.count(name) != 1:
            raise RuntimeError(f"Missing Frontier flag: {name}")
    if "--enforce-eager" in native:
        raise RuntimeError("Eager launch is not the original Frontier")
    graph = json.loads(option("--compilation-config"))
    if (graph.get("cudagraph_mode") != "FULL_AND_PIECEWISE"
            or graph.get("cudagraph_capture_sizes") != [3, 6, 12, 24, 48]
            or graph.get("max_cudagraph_capture_size") != 48):
        raise RuntimeError("Frontier graph configuration changed")
    spec = json.loads(option("--speculative-config"))
    if spec.get("method") != "mtp" or spec.get("num_speculative_tokens") != 2:
        raise RuntimeError("Frontier MTP configuration changed")
    return option("--served-model-name")


def render_qualify(source, venv, model):
    source = replace_once(source, 'BASE = Path("/home/coder/frontier-mods-qwen35-20260925")', f"BASE = Path({str(venv.parent.parent)!r})")
    source = source.replace("phase6/.venv-r7", "phase7-env/venv")
    source = source.replace("frontier-qwen35-dla", model)
    source = source.replace('choices=["native", "tiering"]', 'choices=["native", "mooncake"]')
    start = source.index("def launched_arguments(")
    end = source.index("\ndef preflight():", start)
    source = source[:start] + '''def launched_arguments(manager_pid, program):
    from managed_custody import launched_arguments as capture
    return capture(manager_pid, program, ROOT)

''' + source[end:]
    source = replace_once(source, "def preflight():\n", '''def preflight():
    from measurement_support import verify_qualification
    verify_qualification(ROOT)
    for port in (33894, 33895, 33896):
        with socket.socket() as reserved:
            reserved.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reserved.bind(("127.0.0.1", port))
''')
    source = replace_once(source, "    started = False\n", "    started = False\n    master_started = False\n")
    source = replace_once(source, "        started = True\n", '''        if program == "mooncake":
            from measurement_support import start_master
            master_started = True
            start_master(CTL)
        started = True
''')
    source = replace_once(source, "        command_line = server_command(pid, program)\n", "        from measurement_support import owned_process_snapshot\n        state[\"owned_server_processes\"] = owned_process_snapshot(pid)\n        command_line = server_command(pid, program)\n")
    source = replace_once(source, '        capture_metrics(out / "retrieval-before.prom")', '        state["owned_server_processes"] = owned_process_snapshot(pid)\n        capture_metrics(out / "retrieval-before.prom")')
    source = replace_once(source, 'elif program == "tiering":', 'elif program == "mooncake":')
    source = replace_once(source, "from transfer_receipt import receipt", "from measurement_support import transfer_receipt as receipt")
    start = source.index("        if started:\n", source.index("    finally:\n"))
    end = source.index('\n\n\nif __name__', start)
    source = source[:start] + '''        from measurement_support import release_owned
        errors = release_owned(ROOT, CTL, program, started, master_started, state, owners)
        if errors:
            (out / "FAILED.txt").write_text("\\n".join(errors) + "\\n")
        write(out / "status.json", state)
        if errors:
            raise RuntimeError("Owned release/fatal-log gate failed: " + str(errors))
''' + source[end:]
    compile(source, "qualify.py", "exec")
    return source


def render_campaign(source):
    source = replace_once(source, 'for arm in ("tiering", "native"):', 'for arm in ("mooncake", "native"):')
    source = replace_once(source, "        verify_parent()\n", "        verify_parent()\n        from qualify import preflight\n        preflight()\n")
    source = replace_once(source, '                not result["passed"]\n', '                not result["passed"]\n                or result.get("stage") != "completed"\n                or (arm == "mooncake" and result.get("master_release_exit") != 0)\n')
    compile(source, "run_campaign.py", "exec")
    return source


def verify_software_receipt(path, here, harness):
    if path is None:
        raise ValueError("Explicit generated-harness software test receipt required")
    record = json.loads(Path(path).read_text())
    expected = {name: sha(here / name) for name in
                ("prepare_measurements.py", "measurement_support.py", "managed_custody.py", "test_prepare_measurements.py")}
    expected.update({"frontier_tiering/" + name: sha(harness / name) for name in
                     ("qualify.py", "run_campaign.py")})
    if (record.get("passed") is not True or record.get("exit_code") != 0
            or record.get("source_sha256") != expected or not record.get("command")):
        raise RuntimeError("Software receipt does not prove these exact preparation/harness sources")
    return record


def prepare(base=BASE, root_name="phase8", harness=None, receipts=None, release_addendum=None, software_receipt=None):
    if socket.gethostname() != HOST:
        raise RuntimeError("Wrong assigned experiment container")
    if root_name != "phase8":
        raise ValueError("Only new phase8 measurement capsule is supported")
    old, root = base / "phase7", base / root_name
    if root.exists():
        raise FileExistsError(root)
    receipts = receipts or {arm: old / "receipts" / f"{arm}-retrieval-r1" / "status.json" for arm in ("mooncake", "native")}
    hashes = qualified_sources(old, receipts)
    if release_addendum is None:
        raise ValueError("An explicit process/HBM release addendum is required")
    check_release_addendum(release_addendum, receipts)
    hashes[str(Path(release_addendum).resolve())] = sha(Path(release_addendum))
    # Preparation reads /proc but does not initialize an accelerator library.
    from importlib.util import module_from_spec, spec_from_file_location
    harness = harness or Path(__file__).resolve().parent.parent / "frontier_tiering"
    here = Path(__file__).resolve().parent
    software = verify_software_receipt(software_receipt, here, harness)
    hashes[str(Path(software_receipt).resolve())] = sha(Path(software_receipt))
    spec = spec_from_file_location("frontier_measurement_harness", harness / "qualify.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.owners():
        raise RuntimeError("Device owners present; wait for phase7 release")
    idle = require_idle_memory()
    venv = base / "phase7-env/venv"
    plans = json.loads((old / "manager-plans.json").read_text())
    model = validate_plans(plans)
    qualified = (harness / "qualify.py").read_text()
    campaign = (harness / "run_campaign.py").read_text()
    controller = render_qualify(qualified, venv, model)
    paired = render_campaign(campaign)
    payload = {"software-evidence.json": json.dumps(software, indent=2) + "\n", "hbm-preparation.json": json.dumps(idle, indent=2) + "\n", "qualify.py": controller, "run_campaign.py": paired,
               "manager-plans.json": (old / "manager-plans.json").read_text()}
    for arm in ("native", "mooncake"):
        launcher = (old / f"launch-{arm}.sh").read_text()
        # Exact qualified argv/env paths remain phase7. Its immutable manager
        # profile, namespace, model, wheel and Mooncake config are reused.
        launcher = replace_once(launcher, "cd " + str(old), "cd " + str(root))
        if str(venv / "bin/vllm-hust-ext") not in launcher or " run -- " not in launcher:
            raise RuntimeError("Qualified launcher must use the extension manager")
        payload[f"launch-{arm}.sh"] = launcher
    payload["launch-master.sh"] = (old / "launch-master.sh").read_text()
    here = Path(__file__).resolve().parent
    for name in ("measurement_support.py", "managed_custody.py", "prepare_measurements.py"):
        payload[name] = (here / name).read_text()
        hashes[str(here / name)] = sha(here / name)
    for name in ("qualify.py", "run_campaign.py"):
        hashes[str(harness / name)] = sha(harness / name)
    original_metadata = base / "phase4/metadata-native.json"
    hashes[str(original_metadata)] = sha(original_metadata)
    # Verify all preparation inputs even when an older manifest did not cover them.
    for name in ("manager-plans.json", "manager-native.json", "manager-mooncake.json",
                 "launch-native.sh", "launch-mooncake.sh", "launch-master.sh"):
        hashes[str(old / name)] = sha(old / name)
    root.mkdir()
    (root / "receipts").mkdir()
    for name, text in payload.items():
        (root / name).write_text(text)
    for arm in ("native", "mooncake"):
        metadata = json.loads(original_metadata.read_text())
        for stale in ("source_archives", "source_patches_sha256", "runtime_common_changes",
                      "source_revision_kinds", "source_commits_are_bases", "dla_commit", "bidkv_commit",
                      "ascend_commit", "plugin_revision", "worker_bridge_sha256", "environment"):
            metadata.pop(stale, None)
        metadata["base_wheel_sha256"] = metadata.pop("wheel_sha256", None)
        tracker_path = old / "tracker-fix.json"
        tracker = json.loads(tracker_path.read_text()) if tracker_path.exists() else None
        metadata.update(
            campaign="qwen35-managed-mooncake-20260926",
            core_commit="d0f22d2bda562156e4dbf433ce645e1769b4f804",
            core_commit_kind="base plus explicit core_patch and frozen file hashes",
            ascend_provenance={"kind": "frozen phase7 wheel files plus tracker fix",
                               "tracker_fix": tracker,
                               "files": {path: digest for path, digest in hashes.items() if "/ascend-wheel/" in path}},
            mooncake_provenance={"kind": "phase7 frozen built artifacts",
                                "files": {path: digest for path, digest in hashes.items() if "/mooncake-build/" in path}},
            launch_environment_source={"path": str(root / f"launch-{arm}.sh"), "sha256": sha(root / f"launch-{arm}.sh")},
            mods=[] if arm == "native" else ["mooncake"],
            comparison="Phase7 frozen manager/runtime; Mooncake versus Native; original Frontier TP2",
            serving_chips=2, serving_devices=[0, 1], python=str(venv / "bin/python"),
            launch_script_sha256=sha(root / f"launch-{arm}.sh"),
            runtime_source_files=hashes.copy(),
            manager={"state_path": str(old / f"manager-{arm}.json"),
                     "state_sha256": sha(old / f"manager-{arm}.json"),
                     "qualified_command": plans[arm]},
            qualification_root=str(old),
            core_patch=json.loads((old / "manifest.json").read_text()).get("core_patch"),
            effective_runtime_provenance="Phase7 manifest and runtime_source_files supersede historical phase4 metadata",
        )
        # Historical phase4 package versions are not claims about phase7.
        metadata["packages"] = {}
        metadata["package_provenance"] = "Frozen phase7 source hashes; do not infer versions from phase4"
        (root / f"metadata-{arm}.json").write_text(json.dumps(metadata, indent=2) + "\n")
    config = f'''[unix_http_server]
file={root}/supervisor.sock
chmod=0700
[supervisord]
logfile={root}/receipts/supervisord.log
pidfile={root}/supervisord.pid
childlogdir={root}/receipts
user=root
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix://{root}/supervisor.sock
'''
    programs = {name: f"/bin/bash {root}/launch-{name}.sh" for name in ("native", "mooncake", "master")}
    programs.update({f"measure-{arm}": shlex.join([str(venv / "bin/python"), str(root / "qualify.py"), "--attempt", f"{arm}-measured-r1", "--program", arm, "--measure", "--metadata", f"metadata-{arm}.json"]) for arm in ("mooncake", "native")})
    programs["campaign"] = shlex.join([str(venv / "bin/python"), str(root / "run_campaign.py")])
    for name, command in programs.items():
        server = name in ("native", "mooncake", "master")
        config += f'''
[program:{name}]
command={command}
directory={root}
autostart=false
autorestart=false
startsecs=1
startretries=0
stopwaitsecs={90 if server else 360}
redirect_stderr=true
stdout_logfile={root}/receipts/{name}.log
stdout_logfile_maxbytes=0
'''
        if server:
            config += "stopasgroup=true\nkillasgroup=true\n"
    (root / "supervisord.conf").write_text(config)
    for path in root.iterdir():
        if path.is_file():
            hashes[str(path)] = sha(path)
    (root / "manifest.json").write_text(json.dumps(dict(
        kind="measurement-preparation-not-measured-results", software_tests_passed=True,
        software_evidence="software-evidence.json",
        runtime_software_evidence="Verified frozen phase7 manifest",
        qualification_root=str(old), release_addendum=str(Path(release_addendum).resolve()),
        qualification_receipts={arm: str(Path(path).resolve()) for arm, path in receipts.items()}, sha256=hashes,
        protocol={"arms": ["mooncake", "native"], "fresh_server_per_arm": True,
                  "retrieval_requests": 26, "prefix_gate": {"concurrency": 2, "seconds": 60},
                  "concurrencies": [1, 2, 4, 8, 16], "seconds_per_window": 900,
                  "transfer_missing_policy": "unavailable/null, never assumed zero"},
    ), indent=2) + "\n")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--harness-dir", type=Path)
    parser.add_argument("--software-receipt", type=Path, required=True)
    parser.add_argument("--release-addendum", type=Path, required=True)
    parser.add_argument("--native-receipt", type=Path, required=True)
    parser.add_argument("--mooncake-receipt", type=Path, required=True)
    args = parser.parse_args()
    print("Prepared only:", prepare(args.base, harness=args.harness_dir, receipts={"native": args.native_receipt, "mooncake": args.mooncake_receipt}, release_addendum=args.release_addendum, software_receipt=args.software_receipt))
