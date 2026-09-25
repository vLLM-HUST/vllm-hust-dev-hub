"""Import released campaign cells together with their measured evidence."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from export_point import export, read


def prefix_hits(path):
    return sum(
        float(value)
        for value in re.findall(
            r"^vllm:prefix_cache_hits_total\{[^\n]*\} ([^\n]+)$", path.read_text(), re.M
        )
    )


def main(args):
    data_path = args.site / "data/leaderboard_frontier.json"
    evidence_path = args.site / "data/leaderboard_frontier_swe_evidence.json"
    data, evidence, plan = read(data_path), read(evidence_path), read(args.plan)
    run = args.artifacts / "runs" / f"{args.arm}-r1"
    gate_name = "native-retrieval-r6" if args.arm == "native" else "bidkv-retrieval-r1"
    gate = read(args.artifacts / "receipts" / gate_name / "summary.json")
    if not gate["passed"] or gate["completed_requests"] != 26:
        raise ValueError("Full retrieval gate required")
    model = read(args.artifacts / "receipts/model-revision-verified.json")
    workload = read(args.artifacts / "receipts/workload-equivalence.json")
    if (
        not model["verified"]
        or model["files_checked"] != 22
        or not workload["verified"]
    ):
        raise ValueError("Model/workload identities not verified")
    additions, rows = [], []
    for cell in ("c4", "c16"):
        point = export(plan, run, cell, args.arm, args.evidence_url)
        if any(p["id"] == point["id"] for p in data["points"]):
            raise ValueError("Refuse to duplicate or overwrite an observation")
        client = read(run / cell / "config.json")
        client.pop("endpoint")
        client.pop("server_metadata")
        client["tokenizer"].pop("path", None)
        hits = prefix_hits(run / f"{cell}-after.prom") - prefix_hits(
            run / f"{cell}-before.prom"
        )
        if hits <= 0:
            raise ValueError("No per-cell prefix hits")
        status = read(run / "status.json")
        row = {
            "run_id": client["run_id"],
            "point_id": point["id"],
            "summary": read(run / cell / "summary.json"),
            "client": client,
            "metrics": point["metrics"],
            "requests_artifact_sha256": hashlib.sha256(
                (run / cell / "requests.jsonl").read_bytes()
            ).hexdigest(),
            "retrieval_qualification": gate,
            "model_verification": model,
            "prepared_workload_equivalence": workload,
            "validation": {
                "owned_server_exit_zero": status["release"]["supervisor_exit"] == 0,
                "selected_devices_released": status["release"]["released"],
                "exact_token_budgets": True,
                "prefix_cache_observed": True,
                "prefix_hit_token_delta": hits,
            },
            "scope": "Metric-only public extract; full original request token/timing artifacts and runtime sources retained by measurement owner; one serial900s observation, not an optimization-effect estimate",
        }
        if args.arm == "bidkv":
            row["policy_effectiveness"] = read(
                run / f"{cell}-policy-effectiveness.json"
            )
        additions.append(point)
        rows.append(row)
    cohort = next(c for c in data["cohorts"] if c["id"] == additions[0]["cohort_id"])
    contract = cohort["workload"]["contract"]
    if not any(
        v["sha256"] == plan["prepared_workload"]["sha256"]
        for v in contract["prepared_workload_variants"]
    ):
        contract["prepared_workload_variants"].append(
            {
                "sha256": plan["prepared_workload"]["sha256"],
                "transformers": "5.14.1",
                "equivalence": "Replacing only tokenizer.path with /workspace/models/Qwen3.5-35B-A3B and tokenizer.transformers with5.17.0 reconstructs original8044561f SHA256 exactly; fixed input-token deltas/output budgets/session order unchanged",
            }
        )
    data["points"].extend(additions)
    evidence["runs"].extend(rows)
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"imported": [p["id"] for p in additions]}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--arm", choices=["native", "bidkv"], required=True)
    p.add_argument("--evidence-url", required=True)
    main(p.parse_args())
