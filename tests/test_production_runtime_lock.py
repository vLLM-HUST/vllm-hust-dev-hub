import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_runtime_lock_is_complete_and_immutable() -> None:
    lock = json.loads((ROOT / "config/vllm-ascend-production-lock.json").read_text())

    assert lock["schema"] == "vllm-hust.production-runtime-lock/v2"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", lock["base_image"]["digest"])
    assert re.fullmatch(r"[0-9a-f]{40}", lock["vllm_core"]["commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", lock["vllm_ascend"]["commit"])
    assert lock["vllm_core"]["repository"] == "git@github.com:vLLM-HUST/vllm-hust.git"
    assert lock["vllm_ascend"]["repository"] == "git@github.com:vLLM-HUST/vllm-ascend-hust.git"
    assert lock["vllm_core"]["source_channel"] == "hust-main-upstream-synchronized-snapshot"
    assert lock["vllm_ascend"]["source_channel"] == "hust-main-upstream-synchronized-snapshot"
    assert lock["vllm_ascend"]["source_tag"].startswith("v0.25.1rc1+hust.")
    assert lock["vllm_core"]["commit"][:9] in lock["vllm_core"]["package_version"]
    assert lock["vllm_ascend"]["commit"][:9] in lock["vllm_ascend"]["package_version"]
    assert lock["compatibility"]["stable_release_baseline"] == "v0.23.0"
    assert lock["compatibility"]["source_profile"] == "hust-latest-main-production"
    assert lock["compatibility"]["cann"] == "9.1.0"
    assert lock["compatibility"]["torch_npu"] == "2.13.0rc1"
    for component in (lock["vllm_core"], lock["vllm_ascend"]):
        assert re.fullmatch(r"[0-9a-f]{64}", component["artifact"]["sha256"])
        assert component["artifact"]["filename"].endswith(".whl")
    for component in lock["python_stack"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", component["sha256"])
        assert component["filename"].endswith(".whl")
    for component in lock["runtime_dependencies"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", component["sha256"])
        assert component["filename"].endswith(".whl")
    assert lock["runtime"]["cann"] == "9.1.0"
    assert lock["runtime"]["graph_mode"] is True
    assert lock["runtime"]["prefix_caching"] is True
    assert lock["runtime"]["prefix_cache_mode"] == "mamba-align"
    assert lock["runtime"]["chunked_prefill"] is True
    assert lock["runtime"]["install_mode"] == "immutable-wheels"


def test_locked_image_and_launcher_enforce_identity() -> None:
    dockerfile = (ROOT / "images/vllm-ascend-production/Dockerfile").read_text()
    metadata_installer = (
        ROOT / "images/vllm-ascend-production/install_runtime_metadata.py"
    ).read_text()
    builder = (ROOT / "scripts/build_locked_vllm_ascend_image.sh").read_text()
    launcher = (ROOT / "scripts/run_vllm_hust_engine.sh").read_text()

    assert "ARG BASE_IMAGE" in dockerfile
    assert "FROM ${BASE_IMAGE}" in dockerfile
    assert "ai.vllm-hust.vllm-core.commit" in dockerfile
    assert "ai.vllm-hust.vllm-ascend.commit" in dockerfile
    assert "ai.vllm-hust.compatibility.base" in dockerfile
    assert "ai.vllm-hust.compatibility.stable-release" in dockerfile
    assert "ai.vllm-hust.compatibility.source-profile" in dockerfile
    assert "install_runtime_metadata.py" in dockerfile
    assert 'assert "ascend" in' in dockerfile
    assert "vllm-hust.runtime-receipt/v2" in metadata_installer
    assert "protected runtime dependency mismatch" in metadata_installer
    assert "sitecustomize" not in metadata_installer
    assert "dist-info" not in metadata_installer
    assert "TORCH_DEVICE_BACKEND_AUTOLOAD=0 python3" in dockerfile
    assert "git -C \"$root\" status --porcelain" in builder
    assert "plugin verifies core=" in builder
    assert "artifact hash mismatch" in builder
    assert "mktemp -d" in builder
    assert "--pull=false" in builder
    assert 'expected_image_id="${VLLM_ENGINE_EXPECTED_IMAGE_ID:-}"' in launcher
    assert "image identity mismatch" in launcher
    assert "runs $running_image_id, expected $expected_image_id" in launcher
