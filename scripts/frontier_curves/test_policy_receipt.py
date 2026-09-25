import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pp_policy_receipt", Path(__file__).with_name("policy_receipt.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def metrics(path, **events):
    rows = [f'vllm:batch_admission_policy_enabled{{policy="{module.POLICY}"}} 1']
    rows += [
        f'vllm:batch_admission_policy_events{{policy="{module.POLICY}",event="{event}"}} {events.get(event, 0)}'
        for event in module.EVENTS
    ]
    path.write_text("\n".join(rows) + "\n")


def test_no_activity_cannot_be_reported_as_exercised(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a)
    metrics(b)
    with pytest.raises(ValueError, match="not exercised"):
        module.receipt(a, b)


def test_fallback_invalidates_even_with_successful_admissions(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a)
    metrics(b, calls=5, admissions=3, completions=3, builtin_fallbacks=1)
    with pytest.raises(ValueError, match="fell back"):
        module.receipt(a, b)


def test_matching_lifecycle_is_exercised(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a, calls=2, admissions=1, completions=1)
    metrics(b, calls=7, admissions=4, completions=4)
    report = module.receipt(a, b)
    assert report["admissions"] == 3 and report["status"] == "exercised"
