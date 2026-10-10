import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def test_v54_projection_is_fail_closed() -> None:
    contract = json.loads(
        (ROOT / "config/v5.4-test-plan-contract.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "config/v5.4-test-plan-contract.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(contract)
    assert contract["test_plan_version"] == "V5.4"
    assert contract["mandatory_delivery"]["model"] == "Qwen/Qwen3.5-35B-A3B"
    assert contract["mandatory_delivery"]["precision"] == "BF16"
    assert contract["mandatory_delivery"]["dtype"] == "bfloat16"
    assert contract["baseline_roles"] == ["B0", "B1"]
    assert contract["b1_freeze"]["predeclared_core_id"] is None
    assert contract["b1_freeze"]["predeclared_plugin_id"] is None
    assert contract["b1_freeze"]["predeclared_image_id"] is None
    assert all(item["active"] is False for item in contract["optional_deliveries"])
    assert contract["formal_optional_targets"] == []
    assert contract["formal_optional_config_ids"] == []
    assert contract["formal_optional_measurement_queue"] == []


def test_v54_projection_has_fixed_a3_a4_and_no_embedded_prompt() -> None:
    contract = json.loads(
        (ROOT / "config/v5.4-test-plan-contract.json").read_text(encoding="utf-8")
    )
    assert contract["a3_slo"]["ttft_seconds"] == {
        "mean_max": 30,
        "p95_max": 45,
        "p99_max": 60,
    }
    assert contract["a3_slo"]["tpot_ms_per_token"] == {
        "mean_max": 40,
        "p95_max": 60,
        "p99_max": 80,
    }
    assert contract["a3_slo"]["prefill_30720_role"] == "diagnostic-only"
    assert contract["prompt_policy"]["natural_language_prompt_embedded"] is False
    assert "B2" not in contract["baseline_roles"]
