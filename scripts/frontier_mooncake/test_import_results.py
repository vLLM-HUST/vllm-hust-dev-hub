"""Synthetic evidence tests only; never produce real measurement claims."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mooncake_results", HERE / "import_results.py")
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def arguments():
    values = dict(zip(("--tensor-parallel-size", "--pipeline-parallel-size", "--dtype", "--kv-cache-dtype",
                       "--max-model-len", "--max-num-seqs", "--max-num-batched-tokens", "--kv-cache-memory-bytes", "--mamba-cache-mode"),
                      ("2", "1", "bfloat16", "auto", "262144", "16", "4096", "26038239232", "align")))
    values["--speculative-config"] = json.dumps(dict(method="mtp", num_speculative_tokens=2))
    values["--compilation-config"] = json.dumps(dict(cudagraph_mode="FULL_AND_PIECEWISE", cudagraph_capture_sizes=[3, 6, 12, 24, 48], max_cudagraph_capture_size=48))
    return ["python", "-m", "vllm.entrypoints.cli.main", "serve", "MODEL", "--enable-prefix-caching", "--async-scheduling"] + [item for pair in values.items() for item in pair]


SMI = '''| NPU Name | Health | HBM-Usage(MB) |
| 0 910B2 | OK | 100 |
| 0 | 0000:C1:00.0 | 0 0 / 0 3439/ 65536 |
| 1 910B2 | OK | 100 |
| 0 | 0000:C2:00.0 | 0 0 / 0 3433/ 65536 |
| NPU Chip | Process id | Process name | Process memory(MB) |
'''


def fixture(tmp_path):
    root, site, output = tmp_path / "phase8", tmp_path / "site", tmp_path / "export"
    root.mkdir()
    remote = Path("/frozen/phase8")
    plans = dict(native=arguments(), mooncake=arguments() + ["--kv-transfer-config", json.dumps(dict(kv_connector="AscendStoreConnector", kv_role="kv_both", kv_load_failure_policy="fail", kv_connector_extra_config={"backend": "mooncake", "use_layerwise": False}))])
    write(root / "manager-plans.json", plans)
    names = ("launch-native.sh", "launch-mooncake.sh", "launch-master.sh", "qualify.py", "run_campaign.py", "measurement_support.py", "managed_custody.py", "supervisord.conf")
    for name in names:
        (root / name).write_text("synthetic frozen source " + name)
    write(root / "software-evidence.json", dict(passed=True, exit_code=0))
    metadata = {}
    for arm in ("mooncake", "native"):
        meta = dict(campaign=importer.CAMPAIGN, mods=["mooncake"] if arm == "mooncake" else [],
            packages={}, core_commit="synthetic-base", core_patch={"revision": "synthetic-patch"},
            ascend_provenance={"kind": "synthetic", "tracker_fix": {"base": "1" * 40}}, mooncake_provenance={"kind": "synthetic"},
            serving_chips=2, serving_devices=[0, 1], container_allocated_npus=4,
            runtime_source_files={"/frozen/runtime.py": "a" * 64}, prepared_workload_sha256=importer.tiering.validate_window.__globals__["WORKLOAD"],
            model_manifest_sha256="synthetic-model", launch_script_sha256=importer.sha((root / f"launch-{arm}.sh").read_bytes()),
            manager={"qualified_command": plans[arm]}, launch_environment_source={"path": str(remote / f"launch-{arm}.sh")})
        metadata[arm] = meta
        write(root / f"metadata-{arm}.json", meta)
        run = root / "receipts" / f"{arm}-measured-r1"
        base, pid = (1000, 101) if arm == "mooncake" else (6000, 202)
        state = dict(passed=True, stage="completed", kind="real-online", server_pid=pid,
            release={"exit": 0, "owners": [], "owned_processes": []}, master_release_exit=0,
            owned_processes_after_stop=[], owned_server_processes={"pgid": pid},
            hbm_after_stop=dict(importer.support.parse_npu_smi(SMI), raw=SMI, command=["npu-smi", "info"], observed_unix=base + 4570), windows=[])
        write(run / "custody.json", dict(program=arm, kind="real-online", server_pid=pid, command="vllm-hust-ext run -- ...", serving_child={"argv": plans[arm]}))
        write(run / "retrieval/summary.json", dict(passed=True, completed_requests=26))
        write(run / "prefix-reuse.json", dict(passed=True, hit_token_delta=8))
        (root / "receipts" / f"{arm}.log").write_text("clean")
        for i, cell in enumerate(["qualification"] + [f"c{c}" for c in importer.CELLS]):
            duration, concurrency = (60, 2) if i == 0 else (900, int(cell[1:]))
            config = dict(duration=duration, concurrency=concurrency, chips=2, workload_sha256=meta["prepared_workload_sha256"], server_metadata=meta,
                started_at_unix=base if i == 0 else base + 60 + (i - 1) * 900,
                run_id=f"synthetic-{arm}-{cell}", endpoint="local", tokenizer={"path": "/model"})
            summary = dict(valid=True, aborted=False, failed_requests=0, measurement_seconds=duration, planned_measurement_seconds=duration,
                decode_tokens_per_second_p90=8, ttft_seconds_p95=1, requests_started=1, requests_completed_in_window=1, requests_drained=0,
                observed_output_tokens_in_window=8, output_tokens_per_second=8 / duration, output_tokens_per_second_per_chip=4 / duration,
                max_prompt_tokens_observed=100, mean_client_inflight=1, full_concurrency_fraction=1)
            row = dict(success=True, error=None, token_ids=list(range(8)), expected_output_tokens=8, usage={"completion_tokens": 8}, start=0, end=2, chunks=[[1, 4], [2, 4]])
            write(run / cell / "config.json", config)
            write(run / cell / "summary.json", summary)
            (run / cell / "requests.jsonl").write_text(json.dumps(row) + "\n")
            for phase, hits in (("before", 0), ("after", 8)):
                (run / f"{cell}-{phase}.prom").write_text(f'# TYPE vllm:prefix_cache_hits_total counter\nvllm:prefix_cache_hits_total{{model="x"}} {hits}\n')
            if arm == "mooncake" and i:
                write(run / f"{cell}-transfer-effectiveness.json", importer.support.transfer_receipt(run / f"{cell}-before.prom", run / f"{cell}-after.prom"))
            state["windows"].append(dict(name=cell, exit_code=0, summary=summary))
        write(run / "status.json", state)
    (root / "receipts/master.log").write_text("clean master shutdown")
    write(root / "receipts/matched-curves-r1/status.json", dict(passed=True, active_arm=None, arms=[dict(arm=arm, passed=True) for arm in ("mooncake", "native")]))
    hashes = {str(remote / path.name): importer.sha(path.read_bytes()) for path in root.iterdir() if path.is_file()}
    hashes["/frozen/runtime.py"] = "a" * 64
    write(root / "manifest.json", dict(software_tests_passed=True, sha256=hashes))
    template = dict(id="qwen35-sweprefix-budget-capsule-native-tp2-c4-r1-20260925", configuration=dict(mods=[], hardware={"accelerator_count": 2}, context_capacity_tokens=262144, parameters={"tensor_parallel_size": 2, "pipeline_parallel_size": 1}), load={}, metrics={}, evidence={"benchmark_protocol": {}})
    write(site / "data/leaderboard_frontier.json", dict(points=[template]))
    write(site / "data/ecosystem.json", dict(components=[dict(id=importer.MOD, artifact_type="bridge")]))
    args = SimpleNamespace(artifacts=root, site=site, output=output, evidence_url="https://example.test/evidence", artifact_base_url="https://example.test/artifacts")
    return args


def test_complete_pair_exports_ten_rows_without_touching_site(tmp_path):
    args = fixture(tmp_path)
    original = {p.name: p.read_bytes() for p in (args.site / "data").iterdir()}
    importer.main(args)
    points = json.loads((args.output / "points.json").read_text())["points"]
    rows = json.loads((args.output / "evidence.json").read_text())["runs"]
    assert len(points) == len(rows) == 10
    assert all(p["configuration"]["mods"] == [importer.MOD] for p in points[5:])
    assert all(r["transfer_effectiveness"]["status"] == "unavailable" and r["transfer_effectiveness"]["transfer_bytes"] is None for r in rows[5:])
    assert original == {p.name: p.read_bytes() for p in (args.site / "data").iterdir()}
    receipt = json.loads((args.output / "export-receipt.json").read_text())
    for name, digest in receipt["files"].items():
        assert importer.sha((args.output / name).read_bytes()) == digest


@pytest.mark.parametrize("failure", ["partial-pair", "missing-cell", "hbm", "orphan", "wrong-argv", "source", "raw-token", "fake-counter-zero", "prefix"])
def test_reject_incomplete_or_inconsistent_evidence_without_output(tmp_path, failure):
    args = fixture(tmp_path)
    root = args.artifacts
    run = root / "receipts/mooncake-measured-r1"
    if failure == "partial-pair":
        write(root / "receipts/matched-curves-r1/status.json", dict(passed=False, arms=[]))
    elif failure == "missing-cell":
        (run / "c16/requests.jsonl").unlink()
    elif failure in ("hbm", "orphan"):
        state = json.loads((run / "status.json").read_text())
        if failure == "hbm":
            state["hbm_after_stop"]["devices"]["0"]["used_mb"] = 63310
        else:
            state["release"]["owned_processes"] = [358569]
        write(run / "status.json", state)
    elif failure == "wrong-argv":
        custody = json.loads((run / "custody.json").read_text())
        custody["serving_child"]["argv"].remove("--async-scheduling")
        write(run / "custody.json", custody)
    elif failure == "source":
        (root / "qualify.py").write_text("tampered")
    elif failure == "raw-token":
        row = json.loads((run / "c4/requests.jsonl").read_text())
        row["token_ids"].pop()
        (run / "c4/requests.jsonl").write_text(json.dumps(row) + "\n")
    elif failure == "fake-counter-zero":
        path = run / "c1-transfer-effectiveness.json"
        effect = json.loads(path.read_text())
        effect["transfer_bytes"] = 0
        write(path, effect)
    else:
        write(run / "prefix-reuse.json", dict(passed=True, hit_token_delta=0))
    with pytest.raises((ValueError, FileNotFoundError)):
        importer.main(args)
    assert not args.output.exists()


def test_output_may_not_be_website_or_existing_directory(tmp_path):
    args = fixture(tmp_path)
    args.output = args.site / "reports/result"
    with pytest.raises(ValueError, match="Output must"):
        importer.main(args)


def test_synthetic_export_passes_real_website_model_validator(tmp_path):
    """Uses a read-only real template/model; exported observations stay synthetic."""
    import os
    import subprocess
    site = Path(os.environ.get("FRONTIER_TEST_SITE", "/home/shuhao/vllm-hust-website-tiering-frontier"))
    model = site / "assets/leaderboard-frontier-model.js"
    if not model.exists():
        pytest.skip("Set FRONTIER_TEST_SITE to an existing read-only Frontier website")
    args = fixture(tmp_path)
    args.site = site
    importer.main(args)
    script = '''const fs=require('fs'); const model=require(process.argv[1]);
const source=JSON.parse(fs.readFileSync(process.argv[2]));
const additions=JSON.parse(fs.readFileSync(process.argv[3])).points;
model.validate({...source, points:additions}); console.log('validated '+additions.length);'''
    result = subprocess.run(["node", "-e", script, str(model), str(site / "data/leaderboard_frontier.json"), str(args.output / "points.json")], capture_output=True, text=True, check=True)
    assert "validated 10" in result.stdout
