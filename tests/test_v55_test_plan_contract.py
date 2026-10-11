import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def test_v55_projection_is_fail_closed() -> None:
    contract = json.loads(
        (ROOT / "config/v5.5-test-plan-contract.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "config/v5.5-test-plan-contract.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(contract)
    assert contract["test_plan_version"] == "V5.5"
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
    assert contract["authority"]["semantic_mirror_sha256"] == (
        "4f28cc44af069e3f2debd1f703926ba39bb3acee5ea64af899e05192c1a5bb41"
    )
    assert contract["authority"]["byte_identical"] is False


def test_v55_projection_has_fixed_a3_a4_and_no_embedded_prompt() -> None:
    contract = json.loads(
        (ROOT / "config/v5.5-test-plan-contract.json").read_text(encoding="utf-8")
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


def test_v55_projection_assigns_b0_receipts_to_release_engineering() -> None:
    contract = json.loads(
        (ROOT / "config/v5.5-test-plan-contract.json").read_text(encoding="utf-8")
    )
    gate = contract["b0_receipt_gate"]
    assert gate["owner"] == "release-and-evaluation-engineering"
    assert gate["owner_zh"] == "课题组（发布与评测工程）"
    assert gate["producer"] == "release-and-evaluation-engineering-process"
    assert gate["value_source"] == "actual-release-artifacts-and-actual-runtime"
    assert gate["prefill_actual_values"] is False
    assert gate["infer_actual_values"] is False
    assert {"b0_oci_repo_digest", "b1_oci_repo_digest"} <= set(
        gate["required_materials"]
    )
