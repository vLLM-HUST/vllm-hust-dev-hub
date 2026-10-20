"""Reject new experimental data in dev-hub; removal-only migration is allowed."""

import json
import sys
from pathlib import PurePosixPath

PREFIXES = (
    "results/",
    "docs/evidence/",
    "Ascend-Machine/results/",
    "Ascend-Machine/910B2/results/",
    "datasets/",
    "data/",
)
SUFFIXES = (
    ".csv",
    ".tsv",
    ".jsonl",
    ".ndjson",
    ".parquet",
    ".arrow",
    ".tar.gz",
    ".tgz",
    ".zip",
    ".prom",
    ".log",
    ".log.gz",
)
MEASURED_RECORDS = {
    "scripts/frontier_pipeline/RESULTS.json",
    "scripts/frontier_pipeline/ecpa/receipt.json",
}


def prohibited(path):
    if path.startswith("tests/fixtures/"):
        return False
    return (
        path in MEASURED_RECORDS
        or path.startswith(PREFIXES)
        or path.lower().endswith(SUFFIXES)
    )


def check(pages, expected):
    rows = [row for page in pages for row in page]
    if len(rows) != expected or len({row["filename"] for row in rows}) != expected:
        raise ValueError("Incomplete PR file list; cannot verify data policy")
    return [
        row["filename"]
        for row in rows
        if row["status"] != "removed"
        and (
            prohibited(row["filename"])
            or (
                row["status"] == "renamed"
                and prohibited(row.get("previous_filename", ""))
            )
        )
    ]


if __name__ == "__main__":
    with open(sys.argv[1]) as handle:
        pages = json.load(handle)
    violations = check(pages, int(sys.argv[2]))
    for path in violations:
        print(f"Submit experimental data to vllm-hust-benchmark: {PurePosixPath(path)}")
    raise SystemExit(bool(violations))
