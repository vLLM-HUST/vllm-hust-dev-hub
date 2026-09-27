from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "container_env_exports.py"
SPEC = importlib.util.spec_from_file_location("container_env_exports", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
container_env_exports = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(container_env_exports)


def test_numeric_token_tuning_fields_are_forwarded_for_optimization_prefix() -> None:
    exports = container_env_exports.render_exports(
        {
            "VLLM_ENGINE_EXTRA_ENV_PREFIXES": "VLLM_KV_ADMISSION_",
            "VLLM_KV_ADMISSION_SERVICE_TIME_SHORT_BYPASS_MAX_OUTPUT_TOKENS": "64",
            "VLLM_KV_ADMISSION_SERVICE_TIME_SHORT_BYPASS_MIN_OUTPUT_SAVINGS_TOKENS": "256",
            "VLLM_KV_ADMISSION_PREFILL_TOKEN_BUDGET": "512",
        }
    )

    assert exports == [
        "export VLLM_KV_ADMISSION_PREFILL_TOKEN_BUDGET=512",
        "export VLLM_KV_ADMISSION_SERVICE_TIME_SHORT_BYPASS_MAX_OUTPUT_TOKENS=64",
        "export VLLM_KV_ADMISSION_SERVICE_TIME_SHORT_BYPASS_MIN_OUTPUT_SAVINGS_TOKENS=256",
    ]


def test_secret_token_and_key_fields_remain_filtered_even_when_prefix_matches() -> None:
    exports = container_env_exports.render_exports(
        {
            "VLLM_ENGINE_EXTRA_ENV_PREFIXES": "PLUGIN_",
            "PLUGIN_MAX_OUTPUT_TOKENS": "64",
            "PLUGIN_AUTH_TOKEN": "do-not-forward",
            "PLUGIN_API_KEY": "do-not-forward",
            "PLUGIN_CLIENT_SECRET": "do-not-forward",
        }
    )

    assert exports == ["export PLUGIN_MAX_OUTPUT_TOKENS=64"]


def test_current_explicit_allowlist_is_preserved_and_shell_quoted() -> None:
    exports = container_env_exports.render_exports(
        {
            "HCCL_BUFFSIZE": "128",
            "VLLM_ENGINE_CONTAINER_HOME": "/workspace/home with spaces",
            "VLLM_ENGINE_INSTALLED_MODULES_JSON": '{"plugin": "1.0"}',
        }
    )

    assert exports == [
        "export HCCL_BUFFSIZE=128",
        "export VLLM_ENGINE_CONTAINER_HOME='/workspace/home with spaces'",
        "export VLLM_ENGINE_INSTALLED_MODULES_JSON='{\"plugin\": \"1.0\"}'",
    ]


def test_responses_runtime_configuration_is_forwarded_without_product_glue() -> None:
    exports = container_env_exports.render_exports(
        {
            "VLLM_ENABLE_RESPONSES_API_STORE": "1",
            "VLLM_OPENAI_MODELS_CATALOG_JSON": "/runtime/model-catalog.json",
            "VLLM_RESPONSES_API_STORE_MAX_ENTRIES": "256",
            "VLLM_RESPONSES_API_STORE_TTL_SECONDS": "3600",
        }
    )

    assert exports == [
        "export VLLM_ENABLE_RESPONSES_API_STORE=1",
        "export VLLM_OPENAI_MODELS_CATALOG_JSON=/runtime/model-catalog.json",
        "export VLLM_RESPONSES_API_STORE_MAX_ENTRIES=256",
        "export VLLM_RESPONSES_API_STORE_TTL_SECONDS=3600",
    ]


def test_launcher_uses_the_testable_export_renderer() -> None:
    launcher = (Path(__file__).parents[1] / "scripts/run_vllm_hust_engine.sh").read_text()

    assert 'python3 "$repo_root/scripts/container_env_exports.py"' in launcher
    assert "safe_token_keys =" not in launcher


def test_qwen38_catalog_has_a_single_matching_slug_and_safe_compaction_limit() -> None:
    catalog_path = (
        Path(__file__).parents[1]
        / "config"
        / "model-catalogs"
        / "qwen3.8-27b.json"
    )
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert [model["slug"] for model in payload["models"]] == [
        "Qwen/Qwen3.8-27B"
    ]
    model = payload["models"][0]
    assert 0 < model["auto_compact_token_limit"] < model["context_window"]
    assert model["apply_patch_tool_type"] == "freeform"
