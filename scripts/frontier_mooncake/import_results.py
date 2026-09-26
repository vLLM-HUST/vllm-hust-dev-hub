"""Validate a whole phase8 pair and export review artifacts; never edit a site."""

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import math
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Reuse the reviewed raw-stream/window validators and strict Frontier argv check.
sys.path.insert(0, str(HERE.parent / "frontier_tiering"))
spec = importlib.util.spec_from_file_location("_mooncake_tiering_validators", HERE.parent / "frontier_tiering/import_results.py")
tiering = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tiering)
spec = importlib.util.spec_from_file_location("_mooncake_measurement_support", HERE / "measurement_support.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
read = tiering.read
CELLS = (1, 2, 4, 8, 16)
MOD = "mooncake-vllm-connectors"
CAMPAIGN = "qwen35-managed-mooncake-20260926"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized_launch(custody, arm):
    args = list(custody["serving_child"]["argv"])
    if arm not in ("native", "mooncake"):
        raise ValueError("Unknown arm")
    expected = 1 if arm == "mooncake" else 0
    if args.count("--kv-transfer-config") != expected:
        raise ValueError("Unexpected Mooncake connector count")
    connector = None
    if expected:
        index = args.index("--kv-transfer-config")
        connector = json.loads(args[index + 1])
        extra = connector.get("kv_connector_extra_config", {})
        if (connector.get("kv_connector") != "AscendStoreConnector"
                or connector.get("kv_role") != "kv_both"
                or connector.get("kv_load_failure_policy") != "fail"
                or extra.get("backend") != "mooncake"
                or extra.get("use_layerwise") is not False):
            raise ValueError("Unexpected Mooncake treatment")
        del args[index:index + 2]
    tiering.normalized_launch({"serving_child": {"argv": args}}, "native")
    return args, connector


def validate_release(state, arm):
    tiering.released(state)
    if state.get("stage") != "completed" or state.get("kind") != "real-online":
        raise ValueError("Incomplete real-online measurement")
    if (state.get("owned_processes_after_stop") != []
            or state.get("release", {}).get("owned_processes") != []
            or state.get("shutdown_errors") or state.get("error")):
        raise ValueError("Owned process release not proven")
    if arm == "mooncake" and state.get("master_release_exit") != 0:
        raise ValueError("Mooncake master release not proven")
    memory = state["hbm_after_stop"]
    parsed = support.parse_npu_smi(memory["raw"])
    recorded = {int(k): v for k, v in memory["devices"].items()}
    if (parsed["devices"] != recorded or parsed["processes"] != memory["processes"]
            or parsed["processes"] or any(row["used_mb"] > 4500 for row in recorded.values())
            or memory.get("command") != ["npu-smi", "info"]
            or not math.isfinite(memory["observed_unix"])):
        raise ValueError("HBM/process release evidence invalid")


def verify_capsule(root, metadata):
    manifest = read(root / "manifest.json")
    if manifest.get("software_tests_passed") is not True:
        raise ValueError("Capsule software gate incomplete")
    sources = manifest["sha256"]
    if not sources:
        raise ValueError("Missing source identities")
    for meta in metadata:
        remote = Path(meta["launch_environment_source"]["path"]).parent
        for filename in ("metadata-native.json", "metadata-mooncake.json", "manager-plans.json",
                         "launch-native.sh", "launch-mooncake.sh", "launch-master.sh",
                         "qualify.py", "run_campaign.py", "measurement_support.py",
                         "managed_custody.py", "supervisord.conf", "software-evidence.json"):
            expected = sources.get(str(remote / filename))
            if expected != sha((root / filename).read_bytes()):
                raise ValueError(f"Frozen capsule source mismatch: {filename}")
        if not meta["runtime_source_files"] or any(sources.get(path) != digest for path, digest in meta["runtime_source_files"].items()):
            raise ValueError("Runtime metadata disagrees with frozen source manifest")
        if meta.get("campaign") != CAMPAIGN or not meta.get("core_patch") or not meta.get("ascend_provenance"):
            raise ValueError("Missing phase8 runtime provenance")
    software = read(root / "software-evidence.json")
    if software.get("passed") is not True or software.get("exit_code") != 0:
        raise ValueError("Generated-capsule software tests missing")
    return manifest


def checked_arm(root, arm, plans):
    run = root / "receipts" / f"{arm}-measured-r1"
    if (run / "FAILED.txt").exists():
        raise ValueError("Failed arm marker exists")
    state, custody = read(run / "status.json"), read(run / "custody.json")
    validate_release(state, arm)
    meta = read(root / f"metadata-{arm}.json")
    if (custody.get("kind") != "real-online" or custody.get("program") != arm
            or custody["serving_child"]["argv"] != plans[arm]
            or meta["manager"]["qualified_command"] != plans[arm]
            or custody["server_pid"] != state["server_pid"]
            or state["owned_server_processes"]["pgid"] != custody["server_pid"]
            or "vllm-hust-ext" not in custody["command"]):
        raise ValueError("Manager actual argv or process custody mismatch")
    if meta["mods"] != ([] if arm == "native" else ["mooncake"]):
        raise ValueError("Arm MOD identity mismatch")
    if sha((root / f"launch-{arm}.sh").read_bytes()) != meta["launch_script_sha256"]:
        raise ValueError("Launcher metadata identity mismatch")
    log = (root / "receipts" / f"{arm}.log").read_text(errors="replace")
    if any(marker in log for marker in support.FATAL):
        raise ValueError("Fatal arm log")
    gate = read(run / "retrieval/summary.json")
    if gate.get("passed") is not True or gate.get("completed_requests") != 26:
        raise ValueError("Incomplete retrieval gate")
    prefix = read(run / "prefix-reuse.json")
    hits = tiering.prefix_hits(run / "qualification-after.prom") - tiering.prefix_hits(run / "qualification-before.prom")
    if prefix.get("passed") is not True or hits <= 0 or prefix.get("hit_token_delta") != hits:
        raise ValueError("Prefix gate lacks observed reuse")
    entries = state["windows"]
    if [entry["name"] for entry in entries] != ["qualification"] + [f"c{c}" for c in CELLS] or any(entry["exit_code"] != 0 for entry in entries):
        raise ValueError("Full ordered six-window protocol missing")
    windows, previous_end = {}, None
    for index, cell in enumerate(["qualification"] + [f"c{c}" for c in CELLS]):
        config, summary = read(run / cell / "config.json"), read(run / cell / "summary.json")
        if entries[index]["summary"] != summary or config["server_metadata"] != meta:
            raise ValueError("Window receipt or metadata mismatch")
        if cell == "qualification":
            if (config["duration"] != 60 or config["concurrency"] != 2 or config["chips"] != 2
                    or summary["measurement_seconds"] != 60 or not summary["valid"]
                    or summary["failed_requests"] or summary["aborted"]):
                raise ValueError("Invalid 60-second prefix gate")
        else:
            tiering.validate_window(config, summary)
            if config["concurrency"] != int(cell[1:]):
                raise ValueError("Concurrency cell mismatch")
        tiering.validate_requests(run / cell / "requests.jsonl", summary)
        if previous_end is not None and config["started_at_unix"] < previous_end:
            raise ValueError("Windows overlap or are out of order")
        previous_end = config["started_at_unix"] + config["duration"]
        numeric = ("output_tokens_per_second",) if cell == "qualification" else ("output_tokens_per_second", "decode_tokens_per_second_p90", "ttft_seconds_p95")
        if any(not math.isfinite(summary[key]) or summary[key] < 0 for key in numeric):
            raise ValueError("Invalid numeric performance metric")
        windows[cell] = (config, summary)
    if state["hbm_after_stop"]["observed_unix"] < previous_end:
        raise ValueError("Release sample predates completed measurement")
    return dict(state=state, custody=custody, metadata=meta, windows=windows,
                gate=gate, prefix=prefix, run=run)


def validate_pair(root):
    pair = read(root / "receipts/matched-curves-r1/status.json")
    if (pair.get("passed") is not True or pair.get("active_arm") is not None
            or pair.get("error") or [a["arm"] for a in pair.get("arms", [])] != ["mooncake", "native"]
            or not all(a.get("passed") is True for a in pair["arms"])):
        raise ValueError("Paired campaign incomplete")
    master_log = (root / "receipts/master.log").read_text(errors="replace")
    if any(marker in master_log for marker in support.FATAL):
        raise ValueError("Fatal Mooncake master log")
    plans = read(root / "manager-plans.json")
    arms = {arm: checked_arm(root, arm, plans) for arm in ("mooncake", "native")}
    if normalized_launch(arms["native"]["custody"], "native")[0] != normalized_launch(arms["mooncake"]["custody"], "mooncake")[0]:
        raise ValueError("Actual serving arguments differ beyond Mooncake")
    first, second = arms["mooncake"], arms["native"]
    if first["custody"]["server_pid"] == second["custody"]["server_pid"]:
        raise ValueError("Fresh distinct service per arm not proven")
    if second["windows"]["qualification"][0]["started_at_unix"] < first["state"]["hbm_after_stop"]["observed_unix"]:
        raise ValueError("Native began before candidate release")
    for key in ("packages", "runtime_source_files", "prepared_workload_sha256", "model_manifest_sha256",
                "core_commit", "core_patch", "ascend_provenance", "mooncake_provenance"):
        if first["metadata"][key] != second["metadata"][key]:
            raise ValueError(f"Matched source mismatch: {key}")
    manifest = verify_capsule(root, [first["metadata"], second["metadata"]])
    return arms, manifest


def build(template, root, arm, cell, checked, evidence_url, artifact_url):
    config, summary = checked["windows"][cell]
    meta, custody, run = checked["metadata"], checked["custody"], checked["run"]
    _, connector = normalized_launch(custody, arm)
    hits = tiering.prefix_hits(run / f"{cell}-after.prom") - tiering.prefix_hits(run / f"{cell}-before.prom")
    if hits <= 0:
        raise ValueError("No measured window prefix hits")
    effect = support.transfer_receipt(run / f"{cell}-before.prom", run / f"{cell}-after.prom") if connector else None
    if connector and read(run / f"{cell}-transfer-effectiveness.json") != effect:
        raise ValueError("Recorded transfer receipt differs from raw counters")
    c = config["concurrency"]
    point = copy.deepcopy(template)
    point.update(id=f"qwen35-sweprefix-managed-mooncake-{arm}-tp2-c{c}-r1-20260926",
                 label=f"{'Mooncake' if connector else 'Native'} · TP2 · C{c} · r1")
    cfg = point["configuration"]
    cfg.pop("experiment_group", None)
    cfg["mods"] = [MOD] if connector else []
    cfg["hardware"]["accelerator_count"] = 2
    cfg["engine_version"] = "Frozen qualified phase8 runtime; exact source hashes in runtime receipt"
    cfg["mod_sources"] = []
    if connector:
        base_revision = meta["ascend_provenance"]["tracker_fix"]["base"]
        if not re.fullmatch(r"[0-9a-f]{40}", base_revision):
            raise ValueError("Ascend source base revision is missing or malformed")
        cfg["mod_sources"] = [dict(id=MOD, revision=base_revision,
            local_adaptations={"tracker_fix": meta["ascend_provenance"]["tracker_fix"], "core_patch": meta["core_patch"]}, repository="https://github.com/vLLM-HUST/vllm-ascend-hust",
            source_capsule=CAMPAIGN, scope="AscendStoreConnector with managed Mooncake backend; not the official MooncakeStoreConnector",
            provenance=meta["ascend_provenance"])]
    # Keep model/hardware/protocol fields from the matched Native template; remove
    # previous MOD policy/runtime claims rather than appending contradictory ones.
    params = cfg["parameters"]
    for key in ("batch_admission_policy", "preemption_policy", "calibration", "mod_runtime_effectiveness",
                "runtime_base_commits", "length_source", "host_kv_budget_gib", "host_memory_policy", "kv_transfer_config"):
        params.pop(key, None)
    params.update(runtime_receipt=tiering.compact_metadata(meta, f"{artifact_url}/metadata-{arm}.json.gz", (root / f"metadata-{arm}.json").read_bytes()),
        server_command=shlex.join(custody["serving_child"]["argv"]), source_capsule=CAMPAIGN,
        pipeline_parallel_size=1, physical_devices=[0, 1], participating_deployment_chips=2,
        scheduler_reserve_output_budget=False, pod_npu_quota=meta["container_allocated_npus"],
        capacity_policy="Same explicit 26038239232-byte KV per chip; Mooncake backend as recorded in frozen manager/runtime sources",
        comparison_scope="One matched 900s observation per cell, candidate then Native; no repeatability or isolated-transfer speedup claim",
        window_cache_lifecycle="Fresh service per arm; 26 retrieval requests, 60s prefix gate, then serial C1/2/4/8/16 without resets",
        observed_max_prompt_tokens=summary["max_prompt_tokens_observed"],
        measured_mean_client_inflight=summary["mean_client_inflight"],
        full_client_concurrency_fraction=summary["full_concurrency_fraction"])
    if connector:
        params.update(kv_transfer_config=connector, mod_runtime_effectiveness=effect)
    point["load"].update(concurrency=c, concurrency_series=f"swe-managed-mooncake-{arm}-20260926-r1")
    point["metrics"] = dict(output_tps=summary["output_tokens_per_second"], decode_p90_tps=summary["decode_tokens_per_second_p90"],
                            ttft_p95_ms=summary["ttft_seconds_p95"] * 1000, completed_requests=summary["requests_completed_in_window"])
    point["evidence"].update(url=evidence_url, run_ids=[config["run_id"]], sampling_date_utc=datetime.fromtimestamp(config["started_at_unix"], timezone.utc).date().isoformat())
    point["evidence"]["benchmark_protocol"]["campaign"] = CAMPAIGN
    client = copy.deepcopy(config)
    client.pop("endpoint", None)
    client.pop("server_metadata")
    client["tokenizer"].pop("path", None)
    raw = (run / cell / "requests.jsonl").read_bytes()
    row = dict(run_id=config["run_id"], point_id=point["id"], summary=summary, client=client, metrics=point["metrics"],
        retrieval_qualification=checked["gate"], requests_artifact_sha256=sha(gzip.compress(raw, mtime=0)),
        requests_content_sha256=sha(raw), requests_artifact_encoding="gzip",
        requests_artifact_url=f"{artifact_url}/{arm}-{cell}-requests.jsonl.gz",
        validation=dict(owned_server_stop_command_exit_zero=True, selected_devices_released=True,
                        owned_process_group_released=True, hbm_release_observed=True, exact_token_budgets=True,
                        prefix_cache_observed=True, prefix_hit_token_delta=hits, manager_actual_argv_matches_plan=True),
        scope="One unpooled real 900s observation; unavailable counters do not imply zero transfer or prove backend effectiveness.")
    if connector:
        row["transfer_effectiveness"] = effect
    return point, row


def main(args):
    root, output, site = args.artifacts.resolve(), args.output.resolve(), args.site.resolve()
    if output.exists() or output.is_relative_to(site) or output.is_relative_to(root):
        raise ValueError("Output must be a new directory outside input capsule and website")
    arms, manifest = validate_pair(root)
    ecosystem = read(site / "data/ecosystem.json")
    component = next(c for c in ecosystem["components"] if c["id"] == MOD)
    if component["artifact_type"] != "bridge":
        raise ValueError("Canonical Mooncake integration MOD identity changed")
    data = read(site / "data/leaderboard_frontier.json")
    template = next(p for p in data["points"] if p["id"] == "qwen35-sweprefix-budget-capsule-native-tp2-c4-r1-20260925")
    configuration = template["configuration"]
    if (configuration["hardware"]["accelerator_count"] != 2
            or configuration["context_capacity_tokens"] != 262144
            or configuration["parameters"].get("tensor_parallel_size") != 2
            or configuration["parameters"].get("pipeline_parallel_size") != 1):
        raise ValueError("Website Native template is not the original TP2/PP1 Frontier")
    additions = [build(template, root, arm, f"c{c}", arms[arm], args.evidence_url, args.artifact_base_url.rstrip("/"))
                 for arm in ("native", "mooncake") for c in CELLS]
    if {p["id"] for p, _ in additions} & {p["id"] for p in data["points"]}:
        raise ValueError("Observations already present in website input")
    if len({row["run_id"] for _, row in additions}) != 10:
        raise ValueError("Duplicate observation run IDs")
    # All semantic gates pass before any output directory is created.
    output.mkdir(parents=True)
    archive = output / "artifacts"
    archive.mkdir()
    (output / "points.json").write_text(json.dumps({"points": [p for p, _ in additions]}, indent=2, ensure_ascii=False) + "\n")
    (output / "evidence.json").write_text(json.dumps({"runs": [r for _, r in additions]}, indent=2, ensure_ascii=False) + "\n")
    (archive / "manifest.json").write_bytes((root / "manifest.json").read_bytes())
    (archive / "pair-status.json").write_bytes((root / "receipts/matched-curves-r1/status.json").read_bytes())
    for arm, checked in arms.items():
        run = checked["run"]
        (archive / f"metadata-{arm}.json.gz").write_bytes(gzip.compress((root / f"metadata-{arm}.json").read_bytes(), mtime=0))
        (archive / f"{arm}-qualification.json").write_text(json.dumps({key: checked[key] for key in ("state", "custody", "gate", "prefix")}, indent=2) + "\n")
        for cell in ("qualification",) + tuple(f"c{c}" for c in CELLS):
            for name in ("requests.jsonl", "config.json", "summary.json"):
                (archive / f"{arm}-{cell}-{name}.gz").write_bytes(gzip.compress((run / cell / name).read_bytes(), mtime=0))
            for phase in ("before", "after"):
                (archive / f"{arm}-{cell}-{phase}.prom").write_bytes((run / f"{cell}-{phase}.prom").read_bytes())
        (archive / f"{arm}-retrieval.json.gz").write_bytes(gzip.compress(json.dumps({p.name: read(p) for p in sorted((run / "retrieval").glob("*.json"))}).encode(), mtime=0))
    (output / "export-receipt.json").write_text(json.dumps(dict(kind="derived-artifact", input_manifest_sha256=sha((root / "manifest.json").read_bytes()),
        canonical_mod=MOD, points=10, files={str(p.relative_to(output)): sha(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()},
        source_scope="Capsule/metadata identities verified; remote runtime sources are represented by the frozen manifest checked by completed controllers, not re-read from hardware."), indent=2) + "\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True, help="Read-only website template/catalog")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-url", required=True)
    parser.add_argument("--artifact-base-url", required=True)
    print(main(parser.parse_args()))
