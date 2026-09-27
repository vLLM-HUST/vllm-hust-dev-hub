"""Validate follow-up MODs against the already measured single Native command."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ARMS = ("bidkv", "dla")
BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
NATIVE_ROOT = BASE / "phase9-unified-r3"


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manager_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "command" in value:
            return value
    raise ValueError("Manager output has no generated command")


def normalized(command: list[str], arm: str) -> list[str]:
    result = list(command)
    expected_policy = {
        "bidkv": "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy",
        "dla": "dla.preemption.DeclaredBudgetPreemptionPolicy",
    }[arm]
    if result.count("--preemption-policy") != 1:
        raise ValueError(f"{arm} requires exactly one preemption policy")
    index = result.index("--preemption-policy")
    if result[index + 1] != expected_policy:
        raise ValueError(f"{arm} selected an unexpected preemption policy")
    del result[index : index + 2]
    if arm == "dla":
        if result.count("--scheduler-reserve-output-budget") != 1:
            raise ValueError("DLA requires declared output-budget reservation")
        result.remove("--scheduler-reserve-output-budget")
        index = result.index("--additional-config")
        config = json.loads(result[index + 1])
        if config.pop("dla_exact_output_budgets", None) is not True:
            raise ValueError("DLA exact output-budget adapter is missing")
        result[index + 1] = json.dumps(config, separators=(",", ":"), sort_keys=True)
    elif "--scheduler-reserve-output-budget" in result:
        raise ValueError("BidKV cannot enable DLA output-budget reservation")
    return result


def validate_plans(
    plans: dict[str, list[str]], native_command: list[str] | None = None
) -> None:
    native = (
        native_command
        or json.loads((NATIVE_ROOT / "common-contract.json").read_text())[
            "native_command"
        ]
    )
    native_normalized = list(native)
    index = native_normalized.index("--additional-config")
    native_normalized[index + 1] = json.dumps(
        json.loads(native_normalized[index + 1]), separators=(",", ":"), sort_keys=True
    )
    for arm in ARMS:
        if normalized(plans[arm], arm) != native_normalized:
            raise ValueError(f"{arm} differs from the single Native beyond its MOD")
    if "--enforce-eager" in native:
        raise ValueError("Eager execution is forbidden")


def verify(root: str | Path) -> None:
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    native_manifest = json.loads((NATIVE_ROOT / "manifest.json").read_text())
    if native_manifest.get("software_tests_passed") is not True:
        raise RuntimeError("Shared Native software contract is not qualified")
    for path, expected in manifest["external_sha256"].items():
        if digest(path) != expected:
            raise RuntimeError(f"External runtime source changed: {path}")
    validate_plans(json.loads((root / "manager-plans.json").read_text()))
    if manifest["baseline_id"] != "qwen35-unified-native-20260927":
        raise RuntimeError("Unexpected Native baseline identity")
