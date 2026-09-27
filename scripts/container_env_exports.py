#!/usr/bin/env python3
"""Render the allowlisted host environment for the container engine."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping


EXPLICIT_KEYS = frozenset(
    {
        "COMPILE_CUSTOM_KERNELS",
        "HF_HUB_OFFLINE",
        "HF_ENDPOINT",
        "HF_HOME",
        "HF_HUB_CACHE",
        "HUGGINGFACE_HUB_CACHE",
        "HF_DATASETS_CACHE",
        "HCCL_OP_EXPANSION_MODE",
        "HCCL_BUFFSIZE",
        "HCCL_CONNECT_TIMEOUT",
        "HCCL_EXEC_TIMEOUT",
        "OMP_NUM_THREADS",
        "OMP_PROC_BIND",
        "PYTORCH_NPU_ALLOC_CONF",
        "TASK_QUEUE_ENABLE",
        "TORCH_DEVICE_BACKEND_AUTOLOAD",
        "TRANSFORMERS_OFFLINE",
        "VLLM_ASCEND_ENABLE_MLAPO",
        "VLLM_ASCEND_KV_CACHE_FREE_MEMORY_FRACTION",
        "VLLM_ASCEND_TORCH_PREFLIGHT",
        "VLLM_ENGINE_CONTAINER_HOME",
        "VLLM_ENGINE_EXTRA_ARGS_JSON",
        "VLLM_ENGINE_INSTALLED_MODULES_JSON",
        "VLLM_ENABLE_RESPONSES_API_STORE",
        "VLLM_OPENAI_MODELS_CATALOG_JSON",
        "VLLM_RESPONSES_API_STORE_MAX_ENTRIES",
        "VLLM_RESPONSES_API_STORE_TTL_SECONDS",
        "VLLM_USE_SIMPLE_KV_OFFLOAD",
        "VLLM_USE_V1",
        "VLLM_WORKER_MULTIPROC_METHOD",
    }
)
SAFE_TOKEN_KEYS = frozenset(
    {
        "MAX_NUM_BATCHED_TOKENS",
        "VLLM_ENGINE_MAX_NUM_BATCHED_TOKENS",
    }
)
NUMERIC_TOKEN_NAME = re.compile(
    r"(?:^|_)(?:MAX|MIN|NUM)_[A-Z0-9_]*TOKENS$"
    r"|(?:^|_)TOKEN_(?:BUDGET|LIMIT|THRESHOLD|COUNT)(?:_|$)"
)


def _csv_items(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def is_sensitive_name(key: str) -> bool:
    upper = key.upper()
    if "KEY" in upper or "SECRET" in upper:
        return True
    if "TOKEN" not in upper or key in SAFE_TOKEN_KEYS:
        return False
    return NUMERIC_TOKEN_NAME.search(upper) is None


def render_exports(environment: Mapping[str, str]) -> list[str]:
    extra_keys = frozenset(
        _csv_items(environment.get("VLLM_ENGINE_EXTRA_ENV_KEYS", ""))
    )
    extra_prefixes = _csv_items(
        environment.get("VLLM_ENGINE_EXTRA_ENV_PREFIXES", "")
    )
    keys = []
    for key in environment:
        if is_sensitive_name(key):
            continue
        if (
            key in EXPLICIT_KEYS
            or key in extra_keys
            or key.startswith(extra_prefixes)
        ):
            keys.append(key)
    return [f"export {key}={shlex.quote(environment[key])}" for key in sorted(keys)]


def main() -> None:
    print("\n".join(render_exports(os.environ)))


if __name__ == "__main__":
    main()
