"""Fit actual PP rank observations; never synthesize missing calibration data."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np


def fit_nonnegative(x, y):
    """Exact active-set enumeration for the three nonnegative coefficients."""
    scale = np.maximum(np.linalg.norm(x, axis=0), 1)
    z = x / scale
    candidates = []
    for size in range(1, 4):
        for indices in itertools.combinations(range(3), size):
            values = np.linalg.lstsq(z[:, indices], y, rcond=None)[0]
            if np.any(values < 0):
                continue
            coefficients = np.zeros(3)
            coefficients[list(indices)] = values
            candidates.append(
                (np.linalg.norm(z @ coefficients - y), coefficients / scale)
            )
    if not candidates:
        raise ValueError("No nonnegative calibration fit")
    return min(candidates, key=lambda pair: pair[0])[1]


def fit_rank(path):
    steps = {}
    rank = None
    for line in path.read_text().splitlines():
        row = json.loads(line)
        identity = (row["pp_rank"], row["tp_rank"])
        if rank is not None and rank != identity:
            raise ValueError("Mixed ranks in one profile")
        rank = identity
        step = steps.setdefault(row["step"], {})
        if row["kind"] in step or row["kind"] not in ("execute", "sample"):
            raise ValueError("Invalid or duplicate step kind")
        step[row["kind"]] = row
    samples = []
    for step in sorted(steps):
        calls = steps[step]
        if set(calls) != {"execute", "sample"}:
            raise ValueError("Incomplete execute/sample observation")
        a, b = calls["execute"], calls["sample"]
        for key in ("request_num", "aggregated_ctx_length", "decode_only"):
            if a[key] != b[key]:
                raise ValueError("Feature mismatch within rank step")
        if a["decode_only"]:
            samples.append(
                [
                    a["request_num"],
                    a["aggregated_ctx_length"],
                    1,
                    a["elapsed_ms"] + b["elapsed_ms"],
                ]
            )
    rows = np.asarray(samples, dtype=float)
    if len(rows) < 40 or not np.all(np.isfinite(rows)) or np.any(rows <= 0):
        raise ValueError("Insufficient or invalid observed decode rows")
    cutoff = int(len(rows) * 0.7)
    coefficients = fit_nonnegative(rows[:cutoff, :3], rows[:cutoff, 3])
    predicted = rows[cutoff:, :3] @ coefficients
    ape = np.abs(predicted - rows[cutoff:, 3]) / rows[cutoff:, 3]
    median, p90 = np.quantile(ape, [0.5, 0.9])
    report = dict(
        pp_rank=rank[0],
        tp_rank=rank[1],
        rows=len(rows),
        holdout_rows=len(predicted),
        median_ape=float(median),
        p90_ape=float(p90),
        passed=bool(np.all(predicted > 0) and median <= 0.35 and p90 <= 0.75),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        request_range=[float(rows[:, 0].min()), float(rows[:, 0].max())],
        context_sum_range=[float(rows[:, 1].min()), float(rows[:, 1].max())],
    )
    return rank, fit_nonnegative(rows[:, :3], rows[:, 3]), report


def main(args):
    out = Path(args.output)
    out.mkdir(exist_ok=False)
    reports, models, ranks = [], [], set()
    try:
        for path in sorted(Path(args.input).glob("rank-*.jsonl")):
            rank, coefficients, report = fit_rank(path)
            if rank in ranks:
                raise ValueError("Duplicate rank")
            ranks.add(rank)
            reports.append(report)
            models.append(
                dict(
                    pp_rank=rank[0],
                    layer_num=args.layers_per_stage,
                    p0=0,
                    p1=float(coefficients[0]),
                    p2=0,
                    p3=float(coefficients[1]),
                    p4=0,
                    p5=float(coefficients[2]),
                )
            )
        passed = ranks == {(0, 0), (0, 1), (1, 0), (1, 1)} and all(
            r["passed"] for r in reports
        )
        report = dict(
            passed=passed,
            kind="measured-calibration-not-performance",
            method="Nonnegative least squares, chronological 70/30 holdout; median APE<=35%, p90<=75%, minimum40 decode rows per rank",
            identifiability="Fixed per-stage layer counts make the six-column model collinear; p0,p2,p4 structurally zero, fit request/context/intercept terms",
            scope="Observed execute+sample NPU event intervals include communication and synchronization gaps; profiling disabled in performance windows",
            ranks=reports,
        )
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
        if not passed:
            raise ValueError("Measured calibration failed predeclared validation")
        config = dict(
            mode="calibrated",
            model_ids=[args.model],
            pipeline_parallel_size=2,
            tensor_parallel_size=2,
            microbatch_count=2,
            cost_models=models,
        )
        (out / "policy.json").write_text(json.dumps(config, indent=2) + "\n")
    except Exception as exc:
        (out / "FAILED.txt").write_text(str(exc) + "\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--layers-per-stage", required=True, type=int)
    main(parser.parse_args())
