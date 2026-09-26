"""Software-only phase8 gate, provenance, receipt and owned-release checks."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


support = load("measurement_support")
prepare = load("prepare_measurements")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare.socket, "gethostname", lambda: prepare.HOST)
    idle = dict(devices={0: {"used_mb": 3439, "total_mb": 65536}, 1: {"used_mb": 3433, "total_mb": 65536}}, processes=[])
    monkeypatch.setattr(prepare, "require_idle_memory", lambda: idle)
    monkeypatch.setattr(support, "require_idle_memory", lambda: idle)
    old = tmp_path / "phase7"
    native = ["python", "-m", "vllm.entrypoints.cli.main", "serve", "model"]
    options = {
        "--tensor-parallel-size": "2", "--pipeline-parallel-size": "1",
        "--dtype": "bfloat16", "--kv-cache-dtype": "auto", "--max-model-len": "262144",
        "--max-num-seqs": "16", "--max-num-batched-tokens": "4096",
        "--kv-cache-memory-bytes": "26038239232", "--port": "33783",
        "--served-model-name": "frontier-qwen35-mooncake",
        "--compilation-config": json.dumps(dict(cudagraph_mode="FULL_AND_PIECEWISE", cudagraph_capture_sizes=[3, 6, 12, 24, 48], max_cudagraph_capture_size=48)),
        "--speculative-config": json.dumps(dict(method="mtp", num_speculative_tokens=2)),
    }
    for key, value in options.items():
        native.extend([key, value])
    native += ["--enable-prefix-caching", "--async-scheduling"]
    candidate = native + ["--kv-transfer-config", json.dumps(dict(kv_connector="AscendStoreConnector", kv_role="kv_both", kv_load_failure_policy="fail", kv_connector_extra_config={"backend": "mooncake"}))]
    plans = dict(native=native, mooncake=candidate)
    write(old / "manager-plans.json", plans)
    receipts = {}
    for arm in plans:
        receipt = old / "receipts" / f"{arm}-retrieval-r2" / "status.json"
        write(receipt, dict(passed=True, stage="completed", release=dict(exit=0, owners=[]), master_release_exit=0))
        write(receipt.parent / "custody.json", dict(program=arm, serving_child={"argv": plans[arm]}))
        write(receipt.parent / "retrieval/summary.json", dict(passed=True, completed_requests=26))
        (old / "receipts" / f"{arm}.log").write_text("clean shutdown\n")
        receipts[arm] = receipt
        write(old / f"manager-{arm}.json", {})
        (old / f"launch-{arm}.sh").write_text(f"#!/bin/bash\ncd {old}\nexec {tmp_path}/phase7-env/venv/bin/vllm-hust-ext run -- python serve\n")
    (old / "launch-master.sh").write_text("#!/bin/bash\nexit 0\n")
    write(old / "manifest.json", dict(software_tests_passed=True, sha256={"manager-plans.json": support.sha(old / "manager-plans.json")}))
    write(tmp_path / "phase4/metadata-native.json", dict(serving_chips=2, serving_devices=[0, 1], packages={"old-only": "x"}, source_archives={"dla": "stale"}, ascend_commit="stale", runtime_common_changes="DLA"))
    # Test fixture explicitly replaces hardware-owner discovery with a pure
    # function; the production renderer uses the unmodified reviewed harness.
    harness = tmp_path / "harness"
    harness.mkdir()
    source = (HERE.parent / "frontier_tiering/qualify.py").read_text()
    begin, end = source.index("def owners():"), source.index("def capture_metrics(")
    source = source[:begin] + "def owners():\n    return []\n\n\n" + source[end:]
    (harness / "qualify.py").write_text(source)
    (harness / "run_campaign.py").write_bytes((HERE.parent / "frontier_tiering/run_campaign.py").read_bytes())
    write(tmp_path / "release-addendum.json", dict(passed=True, owned_processes=[], npu_processes=[], hbm_used_mb={"0": 3439, "1": 3433}, qualification_receipt_sha256={arm: support.sha(path) for arm, path in receipts.items()}))
    source_hashes = {name: support.sha(HERE / name) for name in ("prepare_measurements.py", "measurement_support.py", "managed_custody.py", "test_prepare_measurements.py")}
    source_hashes.update({"frontier_tiering/" + name: support.sha(harness / name) for name in ("qualify.py", "run_campaign.py")})
    write(tmp_path / "software.json", dict(passed=True, exit_code=0, command=["pytest", "software-only-fixture"], source_sha256=source_hashes))
    return old, receipts, harness


def test_capsule_preserves_launch_and_runs_original_windows(tmp_path, monkeypatch):
    old, receipts, harness = fixture(tmp_path, monkeypatch)
    root = prepare.prepare(tmp_path, harness=harness, receipts=receipts, release_addendum=tmp_path / "release-addendum.json", software_receipt=tmp_path / "software.json")
    manifest = json.loads((root / "manifest.json").read_text())
    support.verify_qualification(root)
    for name, expected in manifest["sha256"].items():
        assert support.sha(Path(name)) == expected
    for arm in ("native", "mooncake"):
        assert (root / f"launch-{arm}.sh").read_text().replace("cd " + str(root), "cd " + str(old)) == (old / f"launch-{arm}.sh").read_text()
    metadata = json.loads((root / "metadata-mooncake.json").read_text())
    assert "source_archives" not in metadata and "ascend_commit" not in metadata
    assert "runtime_common_changes" not in metadata
    assert metadata["campaign"] == "qwen35-managed-mooncake-20260926"
    controller = (root / "qualify.py").read_text()
    assert 'gate["completed_requests"] != 26' in controller
    assert '(f"c{c}", c, 900) for c in (1, 2, 4, 8, 16)' in controller
    assert 'if delta <= 0:' in controller
    assert 'from transfer_receipt import' not in controller
    assert 'program == "tiering"' not in controller
    assert 'capture(manager_pid, program, ROOT)' in controller
    assert 'master_started = True\n            start_master(CTL)' in controller
    compile(controller, "qualify.py", "exec")
    compile((root / "run_campaign.py").read_text(), "run_campaign.py", "exec")
    with pytest.raises(FileExistsError):
        prepare.prepare(tmp_path, harness=harness, receipts=receipts, release_addendum=tmp_path / "release-addendum.json", software_receipt=tmp_path / "software.json")


@pytest.mark.parametrize("change", ["failed", "owner", "fatal", "wrong-arm", "partial", "tamper"])
def test_qualification_gate_blocks_preparation(tmp_path, monkeypatch, change):
    old, receipts, harness = fixture(tmp_path, monkeypatch)
    path = receipts["native"]
    state = json.loads(path.read_text())
    if change == "failed":
        state["passed"] = False
    elif change == "owner":
        state["release"]["owners"] = [123]
    elif change == "fatal":
        (old / "receipts/native.log").write_text("malloc(): invalid size")
    elif change == "wrong-arm":
        receipts["native"] = receipts["mooncake"]
    elif change == "partial":
        write(path.parent / "retrieval/summary.json", dict(passed=True, completed_requests=25))
    else:
        (old / "manager-plans.json").write_text("tampered")
    write(path, state)
    with pytest.raises(RuntimeError):
        prepare.prepare(tmp_path, harness=harness, receipts=receipts, release_addendum=tmp_path / "release-addendum.json", software_receipt=tmp_path / "software.json")
    assert not (tmp_path / "phase8").exists()


def test_release_stops_only_owned_names_even_if_server_stop_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "memory_state", lambda: {"devices": {0: {"used_mb": 3439}, 1: {"used_mb": 3433}}, "processes": []})
    calls = []
    def run(command, **kwargs):
        calls.append(command[-2:])
        if command[-1] == "mooncake":
            raise TimeoutError("stop timed out")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(support.subprocess, "run", run)
    state = dict(passed=True)
    errors = support.release_owned(tmp_path, ["owned-ctl"], "mooncake", True, True, state, lambda: [])
    assert calls == [["stop", "mooncake"], ["stop", "master"]]
    assert errors and state["passed"] is False
    assert state["master_release_exit"] == 0


def test_missing_counters_are_not_zero_and_reset_is_unknown(tmp_path):
    before, after = tmp_path / "before.prom", tmp_path / "after.prom"
    before.write_text("# TYPE vllm:prefix_cache_hits_total counter\nvllm:prefix_cache_hits_total 12\n")
    after.write_bytes(before.read_bytes())
    result = support.transfer_receipt(before, after)
    assert result["status"] == "unavailable" and result["transfer_bytes"] is None
    before.write_text('# TYPE mooncake_bytes_total counter\nmooncake_bytes_total{rank="0"} 12\n')
    after.write_text('# TYPE mooncake_bytes_total counter\nmooncake_bytes_total{rank="0"} 4\n')
    assert support.transfer_receipt(before, after)["series"][0]["delta"] is None
    after.write_text('# TYPE mooncake_bytes_total counter\nmooncake_bytes_total{rank="0"} 15\n')
    assert support.transfer_receipt(before, after)["series"][0]["delta"] == 3


SMI = '''| NPU Name | Health | HBM-Usage(MB) |
| 0 910B2 | OK | 100 |
| 0 | 0000:C1:00.0 | 0 | 0 / 0 | 3439/ 65536 |
| 1 910B2 | OK | 100 |
| 0 | 0000:C2:00.0 | 0 | 0 / 0 | 3433/ 65536 |
| NPU Chip | Process id | Process name | Process memory(MB) |
'''


def test_hbm_parser_and_live_gate_fail_closed(monkeypatch):
    parsed = support.parse_npu_smi(SMI)
    assert parsed["devices"][0]["used_mb"] == 3439 and parsed["processes"] == []
    with pytest.raises(RuntimeError):
        support.parse_npu_smi(SMI.replace("3439/ 65536", "unknown"))
    busy = support.parse_npu_smi(SMI + '| 0 0 | 358569 | VLLMWorker_TP | 60178 |\n')
    monkeypatch.setattr(support, "memory_state", lambda: busy)
    with pytest.raises(RuntimeError, match="HBM gate"):
        support.require_idle_memory()
    leaked = support.parse_npu_smi(SMI.replace("3439/ 65536", "63578/ 65536"))
    monkeypatch.setattr(support, "memory_state", lambda: leaked)
    with pytest.raises(RuntimeError, match="HBM gate"):
        support.require_idle_memory()


def test_addendum_must_bind_selected_retry_receipts(tmp_path, monkeypatch):
    old, receipts, harness = fixture(tmp_path, monkeypatch)
    path = tmp_path / "release-addendum.json"
    record = json.loads(path.read_text())
    record["qualification_receipt_sha256"]["native"] = "old-retry-sha"
    write(path, record)
    with pytest.raises(RuntimeError, match="bind both"):
        prepare.prepare(tmp_path, harness=harness, receipts=receipts, release_addendum=path, software_receipt=tmp_path / "software.json")
    assert not (tmp_path / "phase8").exists()


def test_reparented_orphan_group_detected_without_device_fd(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    def process(pid, parent, group, ticks):
        directory = proc / str(pid)
        directory.mkdir(exist_ok=True)
        fields = ["S", str(parent), str(group)] + ["0"] * 16 + [str(ticks)]
        (directory / "stat").write_text(f"{pid} (VLLMWorker TP) " + " ".join(fields))
    process(358001, 1, 358001, 10)
    process(358569, 358001, 358001, 11)
    snapshot = support.owned_process_snapshot(358001, proc)
    (proc / "358001/stat").unlink()
    (proc / "358001").rmdir()
    process(358569, 1, 358001, 11)
    survivors = support.surviving_owned(snapshot, proc)
    assert [row["pid"] for row in survivors] == [358569]


def test_owned_group_cleanup_and_delayed_hbm_release(tmp_path, monkeypatch):
    row = dict(pid=777001, ppid=1, pgid=777001, start_ticks=42)
    alive = [True]
    signals = []
    monkeypatch.setattr(support, "process_table", lambda *args: {777001: row} if alive[0] else {})
    monkeypatch.setattr(support, "surviving_owned", lambda snapshot: [row] if alive[0] else [])
    monkeypatch.setattr(support.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    def killpg(group, sig):
        assert group == 777001
        signals.append((group, sig))
        alive[0] = False
    monkeypatch.setattr(support.os, "killpg", killpg)
    monkeypatch.setattr(support.time, "sleep", lambda _: None)
    readings = [63310, 3439]
    def memory():
        return dict(raw="preserved", devices={0: {"used_mb": readings.pop(0)}, 1: {"used_mb": 3433}}, processes=[])
    monkeypatch.setattr(support, "memory_state", memory)
    state = dict(passed=True, owned_server_processes=dict(pgid=777001, processes=[row]))
    assert not support.release_owned(tmp_path, ["owned-ctl"], "mooncake", True, False, state, lambda: [])
    assert signals == [(777001, support.signal.SIGTERM)]
    assert state["hbm_after_stop"]["raw"] == "preserved"
    assert state["hbm_after_stop"]["devices"][0]["used_mb"] == 3439


def test_software_source_drift_blocks_capsule(tmp_path, monkeypatch):
    old, receipts, harness = fixture(tmp_path, monkeypatch)
    with (harness / "run_campaign.py").open("a") as output:
        output.write("\n# drift after tests\n")
    with pytest.raises(RuntimeError, match="Software receipt"):
        prepare.prepare(tmp_path, harness=harness, receipts=receipts,
                        release_addendum=tmp_path / "release-addendum.json",
                        software_receipt=tmp_path / "software.json")
    assert not (tmp_path / "phase8").exists()
