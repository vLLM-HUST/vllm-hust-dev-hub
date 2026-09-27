import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "dla_receipt", Path(__file__).with_name("policy_receipt.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def metrics(path, program="dla", **changes):
    rows = [f'vllm:preemption_policy_enabled{{policy="{module.POLICIES[program]}"}} 1']
    for event in module.EVENTS:
        rows.append(
            f'vllm:preemption_policy_events{{policy="{module.POLICIES[program]}",event="{event}"}} {changes.get(event, 0)}'
        )
    for event in module.ADMISSION:
        rows.append(
            f'vllm:output_budget_admission_events{{event="{event}"}} {changes.get(event, 0)}'
        )
    path.write_text("\n".join(rows) + "\n")


def test_admission_cannot_be_inferred_from_configuration(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a)
    metrics(b)
    with pytest.raises(ValueError, match="not exercised"):
        module.receipt(a, b, program="dla")


def test_real_admission_does_not_imply_real_preemption(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a)
    metrics(b, checks=3, extended_checks=3, passed=3)
    result = module.receipt(a, b, program="dla")
    assert result["admission_status"] == "exercised"
    assert result["preemption_status"] == "not-exercised"
    assert result["admission_check_executed"] is True
    assert result["admission_deferral_observed"] is False
    assert result["status"] == "not-exercised"


def test_faults_fail_even_with_admission_activity(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a)
    metrics(b, checks=3, extended_checks=3, passed=3, failures=1)
    with pytest.raises(ValueError, match="failed"):
        module.receipt(a, b, program="dla")


def test_bidkv_control_rejects_admission_treatment(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a, "bidkv")
    metrics(b, "bidkv", checks=1)
    with pytest.raises(ValueError, match="must not enable"):
        module.receipt(a, b, program="bidkv")


def test_capacity_deferral_is_distinct_from_check_execution(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    metrics(a)
    metrics(b, checks=4, extended_checks=4, passed=3, deferred=1)
    result = module.receipt(a, b, program="dla")
    assert result["admission_check_executed"] is True
    assert result["admission_deferral_observed"] is True
    assert result["preemption_status"] == "not-exercised"
    assert result["status"] == "exercised"
