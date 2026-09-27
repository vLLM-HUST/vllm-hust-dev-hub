#!/usr/bin/env python3
"""Fail fast when a deployment identity contract mixes different source SHAs."""

from __future__ import annotations

import json
import os


COMPONENTS = (
    ("core", "vllm", "VLLM_ENGINE_CORE_COMMIT", "VLLM_ENGINE_CORE_SOURCE_VERSION"),
    (
        "plugin",
        "vllm_ascend",
        "VLLM_ENGINE_PLUGIN_COMMIT",
        "VLLM_ENGINE_PLUGIN_SOURCE_VERSION",
    ),
)


def main() -> None:
    raw_contract = os.environ.get("VLLM_ENGINE_INSTALLED_MODULES_JSON", "")
    if not raw_contract:
        return
    try:
        installed = json.loads(raw_contract)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ERROR: invalid VLLM_ENGINE_INSTALLED_MODULES_JSON: {exc}"
        ) from exc
    if not isinstance(installed, dict):
        raise SystemExit("ERROR: VLLM_ENGINE_INSTALLED_MODULES_JSON must be an object")

    for label, module_name, commit_key, source_version_key in COMPONENTS:
        commit = os.environ.get(commit_key, "").strip().lower()
        if not commit:
            continue
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
            raise SystemExit(f"ERROR: {commit_key} must be a full 40-character Git SHA")

        short_commit = commit[:9]
        source_version = os.environ.get(source_version_key, "").strip().lower()
        if source_version and short_commit not in source_version:
            raise SystemExit(
                f"ERROR: {label} identity mismatch: {source_version_key} "
                f"does not contain {commit_key} prefix {short_commit}"
            )

        module_contract = installed.get(module_name)
        if not isinstance(module_contract, dict):
            continue
        installed_version = module_contract.get("version")
        if isinstance(installed_version, str) and short_commit not in installed_version.lower():
            raise SystemExit(
                f"ERROR: {label} identity mismatch: installed {module_name} version "
                f"does not contain {commit_key} prefix {short_commit}"
            )


if __name__ == "__main__":
    main()
