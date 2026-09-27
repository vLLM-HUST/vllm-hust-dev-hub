"""Independently recompute the plotted latency metrics from raw stream times."""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


def close(actual, expected, name):
    if (
        not math.isfinite(actual)
        or not math.isfinite(expected)
        or not math.isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-8)
    ):
        raise ValueError(f"{name} differs from raw timestamps: {actual} != {expected}")


def verify(window):
    raw = (window / "requests.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    summary = json.loads((window / "summary.json").read_text())
    config = json.loads((window / "config.json").read_text())
    if config["duration"] != 900 or summary["measurement_seconds"] != 900:
        raise ValueError("Not a complete 900-second window")
    speeds, ttfts = [], []
    for row in rows:
        if not row["success"] or row["error"]:
            raise ValueError("Failed request")
        chunks = [(stamp, count) for stamp, count in row["chunks"] if count > 0]
        first, last = chunks[0][0], chunks[-1][0]
        close(first, row["first_token"], "first token")
        close(last, row["last_token"], "last token")
        ttft = first - row["start"]
        close(ttft, row["ttft_seconds"], "TTFT")
        close(last - row["start"], row["e2e_seconds"], "stream latency")
        count = len(row["token_ids"])
        speed = (count - 1) / (last - first) if count > 1 and last > first else None
        if speed is not None:
            close(speed, row["decode_tokens_per_second"], "decode speed")
        elif row["decode_tokens_per_second"] is not None:
            raise ValueError("Undefined decode speed was assigned a value")
        if row["end"] <= 900:
            ttfts.append(ttft)
            if speed is not None:
                speeds.append(speed)
    if len(speeds) != summary["decode_speed_samples"]:
        raise ValueError("Decode percentile sample count mismatch")
    p90 = statistics.quantiles(speeds, n=100, method="inclusive")[89]
    p95 = statistics.quantiles(ttfts, n=100, method="inclusive")[94]
    close(p90, summary["decode_tokens_per_second_p90"], "P90 decode")
    close(p95, summary["ttft_seconds_p95"], "P95 TTFT")
    tokens = sum(
        count for row in rows for stamp, count in row["chunks"] if 0 <= stamp < 900
    )
    if tokens != summary["observed_output_tokens_in_window"]:
        raise ValueError("Window token count mismatch")
    close(tokens / 900, summary["output_tokens_per_second"], "throughput")
    mean_inflight = sum(min(900, row["end"]) - row["start"] for row in rows) / 900
    close(mean_inflight, summary["mean_client_inflight"], "mean client concurrency")
    return {
        "run_id": config["run_id"],
        "raw_requests_sha256": hashlib.sha256(raw).hexdigest(),
        "passed": True,
        "output_tps": tokens / 900,
        "decode_p90_tps": p90,
        "ttft_p95_seconds": p95,
        "decode_speed_samples": len(speeds),
        "mean_client_inflight": mean_inflight,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("windows", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = [verify(window) for window in args.windows]
    args.output.write_text(
        json.dumps(
            {"kind": "derived-artifact", "passed": True, "windows": records}, indent=2
        )
        + "\n"
    )
    print(
        f"Recomputed throughput, latency and concurrency for {len(records)} real windows"
    )
