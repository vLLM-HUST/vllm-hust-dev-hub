"""Import a fully qualified, released PP2 pair from actual 900-second records."""

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from policy_receipt import receipt

MOD = "pipeline-microbatch-migration"
WORKLOAD = "aa23f49e08a946d94eaab21307e9e015140cc8598adfbd5f7e244bdded7b17d0"


def read(path):
    return json.loads(path.read_text())


def released(status):
    if (
        not status.get("passed")
        or status.get("release", {}).get("exit") != 0
        or status["release"]["owners"]
    ):
        raise ValueError("Incomplete qualification, measurement or device release")


def validate_window(config, summary):
    if (
        config["duration"] != 900
        or config["chips"] != 4
        or config["concurrency"] not in (4, 16)
        or config["workload_sha256"] != WORKLOAD
        or not summary["valid"]
        or summary["aborted"]
        or summary["failed_requests"]
        or summary["measurement_seconds"] != 900
        or summary["planned_measurement_seconds"] != 900
        or summary["decode_tokens_per_second_p90"] is None
    ):
        raise ValueError("Invalid 900-second four-chip observation")
    meta = config["server_metadata"]
    if meta["serving_chips"] != 4 or meta["serving_devices"] != [0, 1, 2, 3]:
        raise ValueError("Deployment topology mismatch")


def prefix_hits(path):
    return sum(
        float(value)
        for value in re.findall(
            r"^vllm:prefix_cache_hits_total\{[^\n]*\} ([^\n]+)$",
            path.read_text(),
            re.M,
        )
    )


def validate_requests(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if not rows or any(
        not row["success"]
        or row["error"]
        or len(row["token_ids"]) != row["expected_output_tokens"]
        for row in rows
    ):
        raise ValueError("Raw requests failed or violated exact output budgets")


def build(template, root, arm, cell, evidence_url):
    run = root / "receipts" / f"{arm}-measured-r1"
    state = read(run / "status.json")
    released(state)
    if state["kind"] != "real-online":
        raise ValueError("Calibration and diagnostics are not performance")
    gate = read(run / "retrieval/summary.json")
    if not gate["passed"] or gate["completed_requests"] != 26:
        raise ValueError("Missing complete retrieval qualification")
    if not read(run / "prefix-reuse.json")["passed"]:
        raise ValueError("Prefix reuse qualification failed")
    config, summary = (
        read(run / cell / "config.json"),
        read(run / cell / "summary.json"),
    )
    validate_window(config, summary)
    validate_requests(run / cell / "requests.jsonl")
    meta = config["server_metadata"]
    hits = prefix_hits(run / f"{cell}-after.prom") - prefix_hits(
        run / f"{cell}-before.prom"
    )
    if hits <= 0:
        raise ValueError("No measured window prefix hits")
    candidate = arm == "pipelinepp"
    effect = (
        receipt(run / f"{cell}-before.prom", run / f"{cell}-after.prom")
        if candidate
        else None
    )
    c = config["concurrency"]
    point = copy.deepcopy(template)
    point["id"] = f"qwen35-sweprefix-k8s-{arm}-tp2-pp2-c{c}-r1-20260925"
    group = "Pipeline Microbatch · K8s PP2" if candidate else "Native · K8s PP2"
    point["label"] = f"{group} · C{c} · r1"
    cfg = point["configuration"]
    cfg["experiment_group"] = group
    cfg["mods"] = [MOD] if candidate else []
    cfg["hardware"]["accelerator_count"] = 4
    cfg["engine_version"] = (
        "0.25.1+frontier.bidkv.empty / 0.25.1rc1 + common PP hybrid-MTP capsule"
    )
    params = cfg["parameters"]
    params.update(
        pipeline_parallel_size=2,
        physical_devices=[0, 1, 2, 3],
        participating_deployment_chips=4,
        capacity_policy="Same explicit 26038239232-byte KV per chip in matched PP2 arms",
        comparison_scope="Fresh PP2×TP2 native/Pipeline matched pair; one serial 900s observation per cell; not a comparison with historical TP2-only baseline or a repeatability certificate",
        source_capsule="frontier-container-20260925-pp-hybrid-mtp",
        worker_class="pipeline_worker.Worker (profiling disabled)",
        runtime_receipt=meta,
        server_command=read(run / "custody.json")["command"],
        observed_max_prompt_tokens=summary["max_prompt_tokens_observed"],
        measured_mean_client_inflight=summary["mean_client_inflight"],
        full_client_concurrency_fraction=summary["full_concurrency_fraction"],
    )
    if candidate:
        cfg["mod_sources"] = [
            dict(
                id=MOD,
                repository="https://github.com/vLLM-HUST/vllm-hust-pipeline-microbatch",
                revision=meta["mod_revision"],
                scope="Calibrated batch admission on the common neutral API and PP hybrid-MTP correctness capsule",
            )
        ]
        params["batch_admission_policy"] = (
            "vllm_hust_pipeline_microbatch.policy.PipelineMicrobatchPolicy"
        )
        params["mod_runtime_effectiveness"] = effect
        params["calibration"] = meta["calibration"]
    point["load"].update(
        concurrency=c, concurrency_series=f"swe-k8s-pp2-20260925-{arm}-r1"
    )
    point["metrics"] = dict(
        output_tps=summary["output_tokens_per_second"],
        decode_p90_tps=summary["decode_tokens_per_second_p90"],
        ttft_p95_ms=summary["ttft_seconds_p95"] * 1000,
        completed_requests=summary["requests_completed_in_window"],
    )
    evidence = point["evidence"]
    evidence.update(
        url=evidence_url,
        run_ids=[config["run_id"]],
        sampling_date_utc=datetime.fromtimestamp(
            config["started_at_unix"], timezone.utc
        )
        .date()
        .isoformat(),
    )
    evidence["benchmark_protocol"]["campaign"] = "qwen35-pipeline-k8s-20260925"
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
        requests_artifact_sha256=hashlib.sha256(
            (run / cell / "requests.jsonl").read_bytes()
        ).hexdigest(),
        retrieval_qualification=gate,
        validation=dict(
            owned_server_exit_zero=True,
            selected_devices_released=True,
            exact_token_budgets=True,
            prefix_cache_observed=True,
            prefix_hit_token_delta=hits,
        ),
        scope="Metric-only extract of one unpooled 900s observation; original per-request timings and tokens retained by measurement owner; no general answer-quality certification",
    )
    if candidate:
        row["policy_effectiveness"] = effect
    return point, row


def main(args):
    root = args.artifacts
    pair = read(root / "receipts" / args.pair_attempt / "status.json")
    if not pair["passed"] or len(pair["arms"]) != 2:
        raise ValueError("Matched pair not complete")
    data_path = args.site / "data/leaderboard_frontier.json"
    evidence_path = args.site / "data/leaderboard_frontier_swe_evidence.json"
    data, evidence = read(data_path), read(evidence_path)
    template = next(
        p
        for p in data["points"]
        if p["id"] == "qwen35-sweprefix-k8s-native-tp2-c4-r1-20260925"
    )
    additions = [
        build(template, root, arm, cell, args.evidence_url)
        for arm in ("nativepp", "pipelinepp")
        for cell in ("c4", "c16")
    ]
    for point, row in additions:
        if any(p["id"] == point["id"] for p in data["points"]):
            raise ValueError("Refuse to duplicate or overwrite an observation")
        data["points"].append(point)
        evidence["runs"].append(row)
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"imported": [p["id"] for p, _ in additions]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--evidence-url", required=True)
    parser.add_argument("--pair-attempt", default="paired-measurement-r2")
    main(parser.parse_args())
