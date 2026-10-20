import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "data_policy",
    Path(__file__).resolve().parents[1] / "scripts/check_benchmark_only_data.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_removal_allowed():
    assert (
        MODULE.check([[{"filename": "results/run.json", "status": "removed"}]], 1) == []
    )


def test_added_results_blocked():
    assert MODULE.check([[{"filename": "results/run.json", "status": "added"}]], 1)


@pytest.mark.parametrize("path", sorted(MODULE.MEASURED_RECORDS))
def test_embedded_measured_records_cannot_return(path):
    assert MODULE.check([[{"filename": path, "status": "added"}]], 1) == [path]
    assert MODULE.check([[{"filename": path, "status": "removed"}]], 1) == []


def test_renamed_results_blocked():
    assert MODULE.check(
        [
            [
                {
                    "filename": "misc/renamed.txt",
                    "previous_filename": "results/run.json",
                    "status": "renamed",
                }
            ]
        ],
        1,
    )


def test_incomplete_listing_fails_closed():
    with pytest.raises(ValueError, match="Incomplete"):
        MODULE.check([[]], 1)


def test_code_and_synthetic_fixture_allowed():
    assert not MODULE.prohibited("tests/fixtures/synthetic.jsonl")
    assert not MODULE.prohibited("scripts/benchmark.py")
    assert MODULE.prohibited("other/raw.jsonl")
