"""Build Frontier points only from released, matched 900-second observations."""

import argparse
import copy
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontier_dla"))
from import_website import (
    prefix_hits,
    read,
    released,
    validate_requests,
    validate_window,
)
from transfer_receipt import receipt


def normalized_launch(custody, arm):
    args = list(custody["serving_child"]["argv"])
    for flag, expected in {
        "--tensor-parallel-size": "2",
        "--pipeline-parallel-size": "1",
        "--dtype": "bfloat16",
        "--kv-cache-dtype": "auto",
        "--max-model-len": "262144",
        "--max-num-seqs": "16",
        "--max-num-batched-tokens": "4096",
        "--kv-cache-memory-bytes": "26038239232",
        "--mamba-cache-mode": "align",
    }.items():
        if args.count(flag) != 1 or args[args.index(flag) + 1] != expected:
            raise ValueError(f"Frontier setting changed: {flag}")
    if not {"--enable-prefix-caching", "--async-scheduling"}.issubset(args) or any(
        flag in args
        for flag in (
            "--enforce-eager",
            "--no-enable-prefix-caching",
            "--no-async-scheduling",
        )
    ):
        raise ValueError("Frontier execution features changed")
    speculative = json.loads(args[args.index("--speculative-config") + 1])
    graph = json.loads(args[args.index("--compilation-config") + 1])
    if speculative != {"method": "mtp", "num_speculative_tokens": 2} or graph != {
        "cudagraph_mode": "FULL_AND_PIECEWISE",
        "cudagraph_capture_sizes": [3, 6, 12, 24, 48],
        "max_cudagraph_capture_size": 48,
    }:
        raise ValueError("Frontier MTP/graph configuration changed")
    if args.count("--kv-transfer-config") != (1 if arm == "tiering" else 0):
        raise ValueError("Unexpected connector in actual serving argv")
    connector = None
    if arm == "tiering":
        index = args.index("--kv-transfer-config")
        connector = json.loads(args[index + 1])
        if (
            connector["kv_connector"] != "HustAscendTieringConnector"
            or connector["kv_connector_module_path"]
            != "vllm_hust_kv_tiering.ascend_connector"
            or connector["kv_connector_extra_config"]["ascend_copy_backend"]
            != "torch_sync"
            or connector["kv_connector_extra_config"]["cpu_bytes_to_use"] != 8 * 1024**3
        ):
            raise ValueError("Unexpected tiering treatment")
        del args[index : index + 2]
    return args, connector


def compact_metadata(metadata, url, raw):
    result = copy.deepcopy(metadata)
    files = result.pop("runtime_source_files")
    result["runtime_source_files_sha256"] = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result["runtime_source_file_count"] = len(files)
    result["full_metadata"] = {
        "url": url,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return result


def build(template, root, arm, cell, evidence_url, artifact_base_url):
    run = root / "receipts" / f"{arm}-measured-r1"
    state = read(run / "status.json")
    released(state)
    if state["kind"] != "real-online":
        raise ValueError("Not a real measurement")
    gate = read(run / "retrieval/summary.json")
    if not gate["passed"] or gate["completed_requests"] != 26:
        raise ValueError("Incomplete correctness gate")
    if not read(run / "prefix-reuse.json")["passed"]:
        raise ValueError("Prefix reuse qualification failed")
    config, summary = (
        read(run / cell / "config.json"),
        read(run / cell / "summary.json"),
    )
    validate_window(config, summary)
    validate_requests(run / cell / "requests.jsonl", summary)
    meta = config["server_metadata"]
    metadata_path = root / f"metadata-{arm}.json"
    if meta != read(metadata_path):
        raise ValueError("Window metadata differs from the qualified launcher")
    mods = ["kv-tiering"] if arm == "tiering" else []
    if meta["mods"] != mods:
        raise ValueError("MOD metadata disagrees with campaign")
    custody = read(run / "custody.json")
    _, connector = normalized_launch(custody, arm)
    hits = prefix_hits(run / f"{cell}-after.prom") - prefix_hits(
        run / f"{cell}-before.prom"
    )
    if hits <= 0:
        raise ValueError("No measured prefix-cache reuse")
    effect = (
        receipt(run / f"{cell}-before.prom", run / f"{cell}-after.prom")
        if connector
        else None
    )
    c = config["concurrency"]
    point = copy.deepcopy(template)
    point["id"] = f"qwen35-sweprefix-managed-tiering-{arm}-tp2-c{c}-r1-20260926"
    point["label"] = f"{'KV Tiering' if connector else 'Native'} · TP2 · C{c} · r1"
    if effect and effect["status"] != "restore-observed":
        point["label"] += " · 未观察到缓存恢复"
    cfg = point["configuration"]
    cfg.pop("experiment_group", None)
    cfg["mods"] = mods
    cfg["engine_version"] = (
        "0.25.1+frontier.bidkv.empty / 0.25.1rc1; Extension Manager 0.2.0.dev0"
    )
    cfg["mod_sources"] = (
        [
            {
                "id": "kv-tiering",
                "repository": "https://github.com/vLLM-HUST/vllm-hust-kv-tiering",
                "revision": meta["plugin_revision"],
                "scope": "Experimental synchronous Ascend tiering adapter",
            }
        ]
        if connector
        else []
    )
    params = cfg["parameters"]
    for key in (
        "batch_admission_policy",
        "preemption_policy",
        "calibration",
        "mod_runtime_effectiveness",
        "runtime_base_commits",
        "length_source",
    ):
        params.pop(key, None)
    params.update(
        runtime_receipt=compact_metadata(
            meta,
            f"{artifact_base_url}/metadata-{arm}.json",
            metadata_path.read_bytes(),
        ),
        server_command=" ".join(custody["serving_child"]["argv"]),
        source_capsule="frontier-managed-tiering-20260926",
        scheduler_reserve_output_budget=False,
        host_kv_budget_gib=8 if connector else 0,
        host_memory_policy="8 GiB CPU tier plus fresh segment-file secondary tier"
        if connector
        else "No host KV offload",
        capacity_policy="Same explicit 26038239232-byte KV per chip; candidate additionally uses an 8 GiB CPU tier",
        comparison_scope="Matched runtime; candidate then Native, serial C1/2/4/8/16; one 900s observation per cell, not repeatability certification",
        window_cache_lifecycle="Fresh service per arm; retrieval and prefix qualification followed by serial windows without resets",
        worker_class="pipeline_worker.Worker (profiling disabled)",
        pod_npu_quota=meta["container_allocated_npus"],
        observed_max_prompt_tokens=summary["max_prompt_tokens_observed"],
        measured_mean_client_inflight=summary["mean_client_inflight"],
        full_client_concurrency_fraction=summary["full_concurrency_fraction"],
    )
    if connector:
        params["kv_transfer_config"] = connector
        params["mod_runtime_effectiveness"] = effect
    else:
        params.pop("kv_transfer_config", None)
    point["load"].update(
        concurrency=c, concurrency_series=f"swe-managed-tiering-{arm}-20260926-r1"
    )
    point["metrics"] = dict(
        output_tps=summary["output_tokens_per_second"],
        decode_p90_tps=summary["decode_tokens_per_second_p90"],
        ttft_p95_ms=summary["ttft_seconds_p95"] * 1000,
        completed_requests=summary["requests_completed_in_window"],
    )
    point["evidence"].update(
        url=evidence_url,
        run_ids=[config["run_id"]],
        sampling_date_utc=datetime.fromtimestamp(
            config["started_at_unix"], timezone.utc
        )
        .date()
        .isoformat(),
    )
    point["evidence"]["benchmark_protocol"]["campaign"] = (
        "qwen35-managed-tiering-20260926"
    )
    client = copy.deepcopy(config)
    client.pop("endpoint")
    client.pop("server_metadata")
    client["tokenizer"].pop("path", None)
    row = dict(
        run_id=config["run_id"],
        point_id=point["id"],
        summary=summary,
        client=client,
        metrics=point["metrics"],
        retrieval_qualification=gate,
        requests_artifact_sha256=hashlib.sha256(
            (run / cell / "requests.jsonl").read_bytes()
        ).hexdigest(),
        requests_artifact_url=f"{artifact_base_url}/{arm}-{cell}-requests.jsonl.gz",
        validation=dict(
            owned_server_exit_zero=True,
            selected_devices_released=True,
            exact_token_budgets=True,
            prefix_cache_observed=True,
            prefix_hit_token_delta=hits,
        ),
        scope="One unpooled real 900s observation. Transfer activity does not itself establish speedup or secondary-tier hits.",
    )
    if effect:
        row["transfer_effectiveness"] = effect
    return point, row


def main(args):
    root = args.artifacts
    pair = read(root / "receipts/matched-curves-r1/status.json")
    if (
        not pair["passed"]
        or [a["arm"] for a in pair["arms"]] != ["tiering", "native"]
        or not all(a["passed"] for a in pair["arms"])
    ):
        raise ValueError("Paired campaign incomplete")
    controls = []
    metadata = []
    for arm in ("tiering", "native"):
        run = root / "receipts" / f"{arm}-measured-r1"
        controls.append(normalized_launch(read(run / "custody.json"), arm)[0])
        metadata.append(read(root / f"metadata-{arm}.json"))
    if controls[0] != controls[1]:
        raise ValueError("Serving arguments differ beyond tiering")
    for key in (
        "packages",
        "runtime_source_files",
        "prepared_workload_sha256",
        "model_manifest_sha256",
        "core_commit",
        "source_archives",
    ):
        if metadata[0][key] != metadata[1][key]:
            raise ValueError(f"Runtime/source mismatch: {key}")
    data_path = args.site / "data/leaderboard_frontier.json"
    evidence_path = args.site / "data/leaderboard_frontier_swe_evidence.json"
    data, evidence = read(data_path), read(evidence_path)
    template = next(
        p
        for p in data["points"]
        if p["id"] == "qwen35-sweprefix-budget-capsule-native-tp2-c4-r1-20260925"
    )
    additions = [
        build(
            template,
            root,
            arm,
            f"c{c}",
            args.evidence_url,
            args.artifact_base_url.rstrip("/"),
        )
        for arm in ("native", "tiering")
        for c in (1, 2, 4, 8, 16)
    ]
    existing = {p["id"] for p in data["points"]}
    if any(p["id"] in existing for p, _ in additions):
        raise ValueError("Observation already exists")
    archive = args.site / "reports/frontier-managed-tiering-20260926"
    archive.mkdir(parents=True, exist_ok=False)
    for arm in ("native", "tiering"):
        (archive / f"metadata-{arm}.json").write_bytes(
            (root / f"metadata-{arm}.json").read_bytes()
        )
        run = root / "receipts" / f"{arm}-measured-r1"
        gates = {
            "status": read(run / "status.json"),
            "retrieval": read(run / "retrieval/summary.json"),
            "prefix_reuse": read(run / "prefix-reuse.json"),
            "custody": read(run / "custody.json"),
        }
        (archive / f"{arm}-qualification.json").write_text(
            json.dumps(gates, indent=2) + "\n"
        )
        for c in (1, 2, 4, 8, 16):
            raw = (run / f"c{c}/requests.jsonl").read_bytes()
            (archive / f"{arm}-c{c}-requests.jsonl.gz").write_bytes(
                gzip.compress(raw, mtime=0)
            )
            for phase in ("before", "after"):
                (archive / f"{arm}-c{c}-{phase}.prom").write_bytes(
                    (run / f"c{c}-{phase}.prom").read_bytes()
                )
    data["points"].extend(p for p, _ in additions)
    evidence["runs"].extend(row for _, row in additions)
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"imported": [p["id"] for p, _ in additions]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--evidence-url", required=True)
    parser.add_argument("--artifact-base-url", required=True)
    main(parser.parse_args())
