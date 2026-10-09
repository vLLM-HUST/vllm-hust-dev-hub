import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).with_name("ecpa")


def _load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_ecpa_adapter_and_receipt_bind_the_measured_policy() -> None:
    manifest = _load("frontier_pipeline_adapter/manifests/vllm-hust-extension-v0.3.json")
    manager = _load("manager.json")
    receipt = _load("receipt.json")

    assert manifest["extension_id"] == "org.vllm-hust.pipeline-frontier-adapter"
    assert manifest["schema_version"] == "0.3-experimental"
    assert manifest["requires_extensions"] == []
    assert manifest["resource_claims"] == [
        {
            "resource": "vllm.scheduler.batch-admission-policy",
            "scope": "vllm-process",
            "mode": "exclusive",
        }
    ]
    component = manifest["components"][0]
    assert component["implementation_ref"] == (
        "vllm_hust_pipeline_microbatch.policy:PipelineMicrobatchPolicy"
    )
    configured = manager["extensions"][manifest["extension_id"]]
    assert configured["enabled"] is True
    profile = configured["configuration"]["launch_options"][
        "batch_admission_policy_config"
    ]
    assert profile["mode"] == "calibrated"
    assert profile["pipeline_parallel_size"] == 2
    assert profile["tensor_parallel_size"] == 2
    assert len(profile["cost_models"]) == 4

    assert receipt["performance_claim"] is False
    assert receipt["probe"]["policy_enabled"] == 1.0
    events = receipt["probe"]["policy_events"]
    assert events["calls"] > 0
    assert events["admissions"] == events["completions"] > 0
    for key in ("aborts", "failures", "invalid_admissions", "builtin_fallbacks"):
        assert events[key] == 0
    assert receipt["release"]["released"] is True
    assert receipt["release"]["owners_after"] == {}


def test_adapter_files_are_stable_json() -> None:
    for name in (
        "frontier_pipeline_adapter/manifests/vllm-hust-extension-v0.3.json",
        "manager.json",
        "receipt.json",
    ):
        data = (ROOT / name).read_bytes()
        assert data.endswith(b"\n")
        assert hashlib.sha256(data).hexdigest()
        json.loads(data)
