from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
VALIDATOR = ROOT / "scripts" / "validate_runtime_identity_contract.py"


def _run(**values: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], **values}
    return subprocess.run(
        ["python3", str(VALIDATOR)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_matching_core_and_plugin_receipt_passes() -> None:
    result = _run(
        VLLM_ENGINE_CORE_COMMIT="88e606d0f0cde63c412db456f3e92da2609e0438",
        VLLM_ENGINE_CORE_SOURCE_VERSION="0.28.1.dev31+g88e606d0f",
        VLLM_ENGINE_PLUGIN_COMMIT="c0d6294bc30f775151dba256d49a37a29ba939d7",
        VLLM_ENGINE_PLUGIN_SOURCE_VERSION="0.25.1.dev92+gc0d6294bc",
        VLLM_ENGINE_INSTALLED_MODULES_JSON=(
            '{"vllm":{"distribution":"vllm","version":"0.28.1.dev31+g88e606d0f.empty"},'
            '"vllm_ascend":{"distribution":"vllm-ascend",'
            '"version":"0.25.1.dev92+gc0d6294bc"}}'
        ),
    )

    assert result.returncode == 0, result.stderr


def test_stale_nested_plugin_receipt_fails_before_launch() -> None:
    result = _run(
        VLLM_ENGINE_PLUGIN_COMMIT="c0d6294bc30f775151dba256d49a37a29ba939d7",
        VLLM_ENGINE_PLUGIN_SOURCE_VERSION="0.25.1.dev92+gc0d6294bc",
        VLLM_ENGINE_INSTALLED_MODULES_JSON=(
            '{"vllm_ascend":{"distribution":"vllm-ascend",'
            '"version":"0.25.1.dev90+gd92617b00"}}'
        ),
    )

    assert result.returncode != 0
    assert "installed vllm_ascend version" in result.stderr
    assert "c0d6294bc" in result.stderr


def test_stale_source_version_fails_even_without_installed_receipt() -> None:
    result = _run(
        VLLM_ENGINE_PLUGIN_COMMIT="c0d6294bc30f775151dba256d49a37a29ba939d7",
        VLLM_ENGINE_PLUGIN_SOURCE_VERSION="0.25.1.dev90+gd92617b00",
        VLLM_ENGINE_INSTALLED_MODULES_JSON="{}",
    )

    assert result.returncode != 0
    assert "VLLM_ENGINE_PLUGIN_SOURCE_VERSION" in result.stderr


def test_contract_is_optional_for_source_checkout_workflows() -> None:
    result = _run()

    assert result.returncode == 0


def test_launcher_validates_identity_before_docker_access() -> None:
    launcher = (ROOT / "scripts" / "run_vllm_hust_engine.sh").read_text()

    validation = launcher.index("validate_runtime_identity_contract.py")
    docker_access = launcher.index("docker info")
    assert validation < docker_access
