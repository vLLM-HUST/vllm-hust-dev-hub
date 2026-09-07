#!/usr/bin/env python3
"""Produce non-empty per-cell A/B summaries from BidKV matrix evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path


SAMPLE = re.compile(
    r"^(?P<name>[^#\s{]+)(?P<labels>\{[^}]*\})?\s+(?P<value>[-+0-9.eE]+)$"
)
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "config/bidkv-tp4-graph-matrix.json"
SPECIAL_TOKEN_MARKERS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>")


def metric(path: Path, name: str, label: str | None = None) -> float:
    values = []
    for line in path.read_text().splitlines():
        match = SAMPLE.match(line)
        if not match or match["name"] != name:
            continue
        if label and label not in (match["labels"] or ""):
            continue
        values.append(float(match["value"]))
    if len(values) != 1:
        raise ValueError(f"expected one {name}/{label} in {path}, got {len(values)}")
    return values[0]


def delta(directory: Path, name: str, label: str | None = None) -> float:
    return metric(directory / "metrics-after.prom", name, label) - metric(
        directory / "metrics-before.prom", name, label
    )


def arm(directory: Path, candidate: bool) -> dict[str, object]:
    payload = json.loads((directory / "workload.json").read_text())
    result = {
        key: value
        for key, value in payload.items()
        if key not in {"requests", "recovery"}
    }
    result["output_hashes_by_index"] = {
        str(item["index"]): item["output_sha256"]
        for item in payload["requests"]
        if item["status_code"] == 200 and not item["error"] and not item["cancelled"]
    }
    completed = [
        item
        for item in payload["requests"]
        if item["status_code"] == 200 and not item["error"] and not item["cancelled"]
    ]
    full_outputs_retained = all("output_text" in item for item in completed)
    semantic_results = []
    for item in completed:
        inspected = item.get("output_text", item.get("output_prefix", ""))
        leaks = [marker for marker in SPECIAL_TOKEN_MARKERS if marker in inspected]
        semantic_results.append(
            {
                "index": item["index"],
                "scope": "full-output" if "output_text" in item else "prefix-only",
                "special_token_leaks": leaks,
                "semantic_valid": item.get("semantic_valid"),
            }
        )
    result["long_output_validity"] = {
        "status": (
            "passed"
            if full_outputs_retained
            and semantic_results
            and all(item["semantic_valid"] is True for item in semantic_results)
            else "failed"
            if full_outputs_retained
            else "incomplete-retained-prefix-only"
        ),
        "full_outputs_retained": full_outputs_retained,
        "requests": semantic_results,
    }
    recovery = payload.get("recovery")
    result["recovery_ok"] = recovery is None or (
        recovery["status_code"] == 200
        and not recovery["error"]
        and not recovery["cancelled"]
        and "BIDKV_MATRIX_CANCEL_RECOVERY_OK" in recovery["output_prefix"]
    )
    result["preemptions"] = delta(directory, "vllm:num_preemptions_total")
    local = delta(
        directory, "vllm:prompt_tokens_by_source_total", 'source="local_compute"'
    )
    result["local_compute_prompt_tokens"] = local
    result["recomputed_prompt_tokens"] = local - int(payload["total_prompt_tokens"])
    runtime = (
        (directory / "runtime.log").read_text(errors="replace")
        if (directory / "runtime.log").exists()
        else ""
    )
    result["graph_capture_finished"] = "Graph capturing finished" in runtime
    result["graph_replay_hits"] = runtime.count("Replaying aclgraph")
    result["tp_ranks_observed"] = sorted(
        {int(rank) for rank in re.findall(r"Worker_TP([0-3])", runtime)}
    )
    result["unexpected_tracebacks"] = runtime.count("Traceback (most recent call last)")
    if candidate:
        for event in (
            "calls",
            "selections",
            "abstentions",
            "failures",
            "invalid_selections",
        ):
            result[f"policy_{event}"] = delta(
                directory, "vllm:preemption_policy_events", f'event="{event}"'
            )
        result["policy_enabled"] = metric(
            directory / "metrics-after.prom", "vllm:preemption_policy_enabled"
        )
        result["utility_hits"] = runtime.count("[BidKV] UTILITY_ACTIVE")
        result["liveness_fallback_hits"] = runtime.count(
            "[BidKV] LIVENESS_FALLBACK"
        ) + runtime.count("[BidKV] LIVENESS_ABSTAIN")
        result["liveness_throttle_hits"] = runtime.count("[BidKV] LIVENESS_THROTTLE")
        result["cascade_abstention_hits"] = runtime.count("[BidKV] CASCADE_ABSTAIN")
        result["selector_reported_tokens_freed"] = sum(
            int(value) for value in re.findall(r"\br=(\d+) tok\b", runtime)
        )
    return result


def relative(
    candidate: float | int | None, baseline: float | int | None
) -> float | None:
    if candidate is None or baseline in (None, 0):
        return None
    return (float(candidate) / float(baseline) - 1) * 100


def paired_interval(values: list[float]) -> dict[str, float | int | None]:
    """Return a paired mean and 95% t interval (n=3 is the qualification floor)."""
    count = len(values)
    mean = statistics.fmean(values) if values else None
    if count < 2 or mean is None:
        return {"n": count, "mean": mean, "ci95_low": None, "ci95_high": None}
    critical = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262)
    t_value = critical[count - 2] if count <= 10 else 1.96
    margin = t_value * statistics.stdev(values) / math.sqrt(count)
    return {
        "n": count,
        "mean": mean,
        "ci95_low": mean - margin,
        "ci95_high": mean + margin,
    }


def run_directories(root: Path) -> list[tuple[int, Path]]:
    repetitions = sorted(path for path in root.glob("repeat-*") if path.is_dir())
    if repetitions:
        return [
            (index + 1, cell)
            for index, repetition in enumerate(repetitions)
            for cell in sorted(path for path in repetition.iterdir() if path.is_dir())
        ]
    return [
        (1, path) for path in sorted(path for path in root.iterdir() if path.is_dir())
    ]


def short_gate(cell_dir: Path) -> dict[str, object]:
    arms = {}
    for arm_name in ("baseline", "candidate"):
        request = json.loads((cell_dir / arm_name / "warmup.json").read_text())[
            "requests"
        ][0]
        inspected = request.get("output_text", request.get("output_prefix", ""))
        leaks = [marker for marker in SPECIAL_TOKEN_MARKERS if marker in inspected]
        expected = request.get("exact_expected")
        arms[arm_name] = {
            "hash": request["output_sha256"],
            "scope": "full-output" if "output_text" in request else "prefix-only",
            "exact_expected": expected,
            "exact_match": request.get("exact_match"),
            "special_token_leaks": leaks,
        }
    cross_arm_equal = arms["baseline"]["hash"] == arms["candidate"]["hash"]
    legacy_leak = bool(
        arms["baseline"]["special_token_leaks"]
        or arms["candidate"]["special_token_leaks"]
    )
    if legacy_leak:
        status = "invalid-workload-special-token-leak"
    elif all(arms[name]["exact_match"] is True for name in arms):
        status = "passed"
    elif all(arms[name]["exact_match"] is None for name in arms):
        status = "incomplete-legacy-hash-only"
    else:
        status = "failed"
    return {"status": status, "cross_arm_hash_equal": cross_arm_equal, "arms": arms}


def determinism(repeats: list[dict[str, object]], arm_name: str) -> dict[str, object]:
    by_index: dict[str, list[str]] = {}
    for run in repeats:
        arm_data = run[arm_name]
        assert isinstance(arm_data, dict)
        hashes = arm_data["output_hashes_by_index"]
        assert isinstance(hashes, dict)
        for index, value in hashes.items():
            by_index.setdefault(index, []).append(str(value))
    per_index = {
        index: {
            "samples": len(values),
            "unique_hashes": len(set(values)),
            "deterministic": len(values) > 1 and len(set(values)) == 1,
        }
        for index, values in sorted(by_index.items(), key=lambda item: int(item[0]))
    }
    eligible = [item for item in per_index.values() if item["samples"] > 1]
    return {
        "status": (
            "passed"
            if eligible and all(item["deterministic"] for item in eligible)
            else "failed"
            if eligible
            else "insufficient-repetitions"
        ),
        "deterministic_indices": sum(bool(item["deterministic"]) for item in eligible),
        "eligible_indices": len(eligible),
        "per_index": per_index,
    }


def analyze(root: Path, matrix_path: Path = DEFAULT_MATRIX) -> dict[str, object]:
    samples: dict[str, list[dict[str, object]]] = {}
    for repetition, cell_dir in run_directories(root):
        if (
            not (cell_dir / "baseline/workload.json").exists()
            or not (cell_dir / "candidate/workload.json").exists()
        ):
            continue
        baseline = arm(cell_dir / "baseline", False)
        candidate = arm(cell_dir / "candidate", True)
        paired_hashes = sorted(
            set(baseline["output_hashes_by_index"])
            & set(candidate["output_hashes_by_index"])
        )
        changes = {
            name: relative(candidate.get(name), baseline.get(name))
            for name in (
                "output_throughput_tokens_s",
                "goodput_requests_s",
                "ttft_p50_s",
                "slo_goodput_requests_s",
                "ttft_p95_s",
                "ttft_p99_s",
                "tpot_p50_s",
                "tpot_p95_s",
                "tpot_p99_s",
                "latency_p50_s",
                "latency_p95_s",
                "latency_p99_s",
                "jain_output_rate_fairness",
                "preemptions",
                "recomputed_prompt_tokens",
            )
        }
        samples.setdefault(cell_dir.name, []).append(
            {
                "repetition": repetition,
                "cell": cell_dir.name,
                "baseline": baseline,
                "candidate": candidate,
                "candidate_relative_percent": changes,
                "short_exact_match_gate": short_gate(cell_dir),
                "long_output_hash_pairs": len(paired_hashes),
                "long_output_hash_matches": sum(
                    baseline["output_hashes_by_index"][index]
                    == candidate["output_hashes_by_index"][index]
                    for index in paired_hashes
                ),
            }
        )
    matrix = json.loads(matrix_path.read_text())
    declared_cells = {cell["id"]: cell for cell in matrix["cells"]}
    cells = []
    for cell in declared_cells:
        repeats = samples.get(cell, [])
        if not repeats:
            cells.append(
                {
                    "cell": cell,
                    "execution_status": "blocked-protected-resource",
                    "execution_reason": (
                        "not present in retained suite; re-execution is blocked while "
                        "NPU0-3 serve unchanged Sage Mate production and NPU4-7 are reserved"
                    ),
                    "declared_configuration": declared_cells[cell],
                    "repetitions": [],
                    "effectiveness_qualification": "pending",
                    "qualification_reason": "no real-online paired run exists",
                }
            )
            continue
        throughput = [
            float(run["candidate_relative_percent"]["output_throughput_tokens_s"])
            for run in repeats
        ]
        p95_latency = [
            float(run["candidate_relative_percent"]["latency_p95_s"]) for run in repeats
        ]
        throughput_interval = paired_interval(throughput)
        p95_latency_interval = paired_interval(p95_latency)
        policy_exercised = all(
            float(run["candidate"]["policy_calls"]) > 0 for run in repeats
        )
        runtime_safety_clean = all(
            int(run["baseline"]["failed_or_starved"]) == 0
            and int(run["candidate"]["failed_or_starved"]) == 0
            and bool(run["baseline"]["recovery_ok"])
            and bool(run["candidate"]["recovery_ok"])
            and bool(run["baseline"]["graph_capture_finished"])
            and bool(run["candidate"]["graph_capture_finished"])
            and int(run["baseline"]["graph_replay_hits"]) > 0
            and int(run["candidate"]["graph_replay_hits"]) > 0
            and run["baseline"]["tp_ranks_observed"] == [0, 1, 2, 3]
            and run["candidate"]["tp_ranks_observed"] == [0, 1, 2, 3]
            and int(run["baseline"]["unexpected_tracebacks"]) == 0
            and int(run["candidate"]["unexpected_tracebacks"]) == 0
            and float(run["candidate"]["policy_failures"]) == 0
            and float(run["candidate"]["policy_invalid_selections"]) == 0
            and float(run["candidate"]["policy_enabled"]) == 1
            for run in repeats
        )
        qualification = "inconclusive"
        reason = (
            "fewer than three paired repetitions; interval qualification is not allowed"
        )
        if len(repeats) >= 3 and not runtime_safety_clean:
            reason = (
                "runtime/policy-safety gates failed; effectiveness is not classifiable"
            )
        elif len(repeats) >= 3 and not policy_exercised:
            reason = "the workload did not invoke the policy in every repeat; no BidKV effectiveness claim is allowed"
        elif len(repeats) >= 3:
            throughput_low = throughput_interval["ci95_low"]
            throughput_high = throughput_interval["ci95_high"]
            latency_low = p95_latency_interval["ci95_low"]
            latency_high = p95_latency_interval["ci95_high"]
            if (
                throughput_low is not None
                and throughput_low > 0
                and latency_high is not None
                and latency_high <= 5
            ):
                qualification = "beneficial"
                reason = "paired throughput 95% interval is above zero and P95 latency regression bound is at most 5%"
            elif (throughput_high is not None and throughput_high < 0) or (
                latency_low is not None and latency_low > 5
            ):
                qualification = "not-beneficial-in-tested-cell"
                reason = "paired throughput is significantly lower or the P95 latency regression interval is above 5%"
            else:
                reason = "paired intervals do not satisfy the conservative beneficial or not-beneficial rule"
        cells.append(
            {
                "cell": cell,
                "execution_status": "completed",
                "repetitions": repeats,
                "paired_intervals_percent": {
                    "output_throughput": throughput_interval,
                    "latency_p95": p95_latency_interval,
                },
                "runtime_safety_clean": runtime_safety_clean,
                "short_exact_match_gate": {
                    "status": (
                        "passed"
                        if all(
                            run["short_exact_match_gate"]["status"] == "passed"
                            for run in repeats
                        )
                        else "invalid-workload-special-token-leak"
                        if any(
                            run["short_exact_match_gate"]["status"]
                            == "invalid-workload-special-token-leak"
                            for run in repeats
                        )
                        else "incomplete"
                    ),
                    "per_repetition": [
                        run["short_exact_match_gate"] for run in repeats
                    ],
                },
                "long_semantic_validity_gate": {
                    arm_name: {
                        "status": (
                            "passed"
                            if all(
                                run[arm_name]["long_output_validity"]["status"]
                                == "passed"
                                for run in repeats
                            )
                            else "incomplete-retained-prefix-only"
                            if any(
                                run[arm_name]["long_output_validity"]["status"]
                                == "incomplete-retained-prefix-only"
                                for run in repeats
                            )
                            else "failed"
                        )
                    }
                    for arm_name in ("baseline", "candidate")
                },
                "long_output_determinism": {
                    arm_name: determinism(repeats, arm_name)
                    for arm_name in ("baseline", "candidate")
                },
                "policy_exercised_in_every_repeat": policy_exercised,
                "effectiveness_qualification": qualification,
                "qualification_reason": reason,
            }
        )
    completed = sum(cell["execution_status"] == "completed" for cell in cells)
    return {
        "schema": "sage-mate.bidkv-matrix-analysis/v3",
        "matrix_completion": {
            "declared_cells": len(cells),
            "completed_cells": completed,
            "blocked_or_pending_cells": len(cells) - completed,
            "complete": completed == len(cells),
        },
        "correctness_contract": {
            "short_output": "exact expected text with no special-token leakage",
            "long_output": "per-arm semantic validity and special-token scan; cross-arm hash equality is diagnostic only",
            "cross_arm_long_exact_match_is_required": False,
        },
        "cells": cells,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    args = parser.parse_args()
    result = analyze(args.root, args.matrix)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (args.output or args.root / "analysis.json").write_text(serialized)
    print(serialized, end="")


if __name__ == "__main__":
    main()
