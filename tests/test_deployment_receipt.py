import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deployment_receipt.py"
SPEC = importlib.util.spec_from_file_location("deployment_receipt", SCRIPT)
assert SPEC and SPEC.loader
receipt_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt_module)


def payload() -> dict[str, object]:
    return {
        "status": "active",
        "model": {
            "served_name": "org/example-w8a8",
            "checkpoint_family": "example_moe",
            "architecture": "ExampleForCausalLM",
        },
        "engine": {
            "name": "vLLM-HUST",
            "core_commit": "0123456789abcdef",
            "plugin_name": "vllm-ascend-hust",
            "plugin_commit": "fedcba9876543210",
            "image": "registry.example/runtime:v1",
        },
        "hardware": {
            "accelerator_kind": "Ascend NPU",
            "accelerator_model": "910B",
            "physical_device_ids": ["4", "5"],
            "logical_device_ids": ["0", "1"],
        },
        "parallelism": {
            "tensor_parallel_size": 2,
            "data_parallel_size": 1,
            "expert_parallel_enabled": True,
        },
        "execution": {
            "quantization": "w8a8",
            "graph_mode": "graph",
            "prefix_caching_enabled": True,
            "prefix_caching_required": True,
            "prefix_cache_mode": "mamba-align",
            "chunked_prefill_enabled": True,
        },
        "speculative": {
            "requested_method": "dspark",
            "resolved_method": "none",
            "active": False,
            "reason": "proposer unavailable",
        },
        "provenance": {
            "source_uri": "vllm-hust-dev-hub://deployment/test",
            "import_origins": {
                "vllm": "/workspace/vllm-hust/vllm/__init__.py",
                "vllm_ascend": "/workspace/vllm-ascend-hust/vllm_ascend/__init__.py",
            },
        },
    }


def test_create_and_verify_receipt() -> None:
    receipt = receipt_module.create_receipt(payload(), generated_at="2026-08-15T00:00:00+00:00")

    assert receipt["schema_version"] == receipt_module.SCHEMA_VERSION
    assert receipt["receipt_id"].startswith("deploy-")
    assert receipt["integrity"]["algorithm"] == "sha256"
    assert receipt_module.validate_receipt(receipt) == receipt


def test_v1_receipts_remain_valid_rollback_evidence() -> None:
    receipt = receipt_module.create_receipt(payload())
    receipt["schema_version"] = "vllm-hust.deployment-receipt/v1"
    receipt["execution"] = {
        "quantization": receipt["execution"]["quantization"],
        "graph_mode": receipt["execution"]["graph_mode"],
    }
    receipt["integrity"]["content_sha256"] = receipt_module._content_hash(receipt)

    assert receipt_module.validate_receipt(receipt) == receipt


def test_required_prefix_cache_cannot_be_recorded_disabled() -> None:
    value = payload()
    value["execution"]["prefix_caching_enabled"] = False

    with pytest.raises(
        receipt_module.ReceiptValidationError,
        match="required prefix caching cannot be recorded as disabled",
    ):
        receipt_module.create_receipt(value)


@pytest.mark.parametrize("status", ["active", "superseded", "failed"])
def test_all_lifecycle_states_are_supported(status: str) -> None:
    value = payload()
    value["status"] = status
    assert receipt_module.create_receipt(value)["status"] == status


def test_tampering_and_unknown_fields_are_rejected() -> None:
    receipt = receipt_module.create_receipt(payload())
    tampered = copy.deepcopy(receipt)
    tampered["model"]["served_name"] = "org/other"
    with pytest.raises(receipt_module.ReceiptValidationError, match="hash mismatch"):
        receipt_module.validate_receipt(tampered)

    unknown = payload()
    unknown["model"]["private_path"] = "/private/checkpoint"
    with pytest.raises(receipt_module.ReceiptValidationError, match="fields mismatch"):
        receipt_module.create_receipt(unknown)


@pytest.mark.parametrize("key", ["api_key", "access_token", "private_key", "password"])
def test_sensitive_keys_are_rejected_at_any_depth(key: str) -> None:
    value = payload()
    value["provenance"][key] = "do-not-store"
    with pytest.raises(receipt_module.ReceiptValidationError, match="sensitive field"):
        receipt_module.create_receipt(value)


def test_cli_writes_private_atomic_receipt_and_verifies_it(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    target = tmp_path / "receipt.json"
    source.write_text(json.dumps(payload()), encoding="utf-8")

    subprocess.run(
        [sys.executable, str(SCRIPT), "create", "--input", str(source), "--output", str(target)],
        check=True,
    )
    subprocess.run([sys.executable, str(SCRIPT), "verify", str(target)], check=True)

    assert target.stat().st_mode & 0o777 == 0o600
