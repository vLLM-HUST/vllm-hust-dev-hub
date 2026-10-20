import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).with_name("ecpa")
RECEIPT_URL = (
    "https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/"
    "09e0587302387b522f87575fc26cf5f08b8dd0cc/"
    "archive/dev-hub-pipeline-20261020/ecpa-receipt.json"
)
RECEIPT_SHA256 = "ccbf5f4a7849803ad606538cd72f790fbcf658ec024e911132e945a8f52ea5f4"


@pytest.fixture(scope="module")
def receipt_bytes():
    with urlopen(RECEIPT_URL, timeout=60) as response:
        data = response.read()
    assert len(data) == 2251
    assert hashlib.sha256(data).hexdigest() == RECEIPT_SHA256
    return data


def _load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_ecpa_adapter_and_receipt_bind_the_measured_policy(receipt_bytes) -> None:
    manifest = _load("frontier_pipeline_adapter/manifests/vllm-hust-extension-v0.3.json")
    manager = _load("manager.json")
    receipt = json.loads(receipt_bytes)

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


def test_adapter_files_are_stable_json(receipt_bytes) -> None:
    for name in (
        "frontier_pipeline_adapter/manifests/vllm-hust-extension-v0.3.json",
        "manager.json",
    ):
        data = (ROOT / name).read_bytes()
        assert data.endswith(b"\n")
        assert hashlib.sha256(data).hexdigest()
        json.loads(data)
    assert receipt_bytes.endswith(b"\n")
    json.loads(receipt_bytes)
