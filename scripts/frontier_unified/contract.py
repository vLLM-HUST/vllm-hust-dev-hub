"""One immutable Native command and runtime contract for every admitted MOD."""

import hashlib
import json
from pathlib import Path

ARMS = ("native", "mooncake", "tiering")
CONNECTORS = {
    "mooncake": "AscendStoreConnector",
    "tiering": "HustAscendTieringConnector",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(command, arm):
    result = list(command)
    if arm not in ARMS:
        raise ValueError("Unadmitted MOD")
    if arm != "native":
        if result.count("--kv-transfer-config") != 1:
            raise ValueError("Exactly one declared connector treatment required")
        i = result.index("--kv-transfer-config")
        config = json.loads(result[i + 1])
        if config.get("kv_connector") != CONNECTORS[arm]:
            raise ValueError("Unexpected connector treatment")
        if (
            arm == "mooncake"
            and config.get("kv_connector_extra_config", {}).get("backend") != "mooncake"
        ):
            raise ValueError("Unexpected Mooncake backend")
        del result[i : i + 2]
    elif "--kv-transfer-config" in result:
        raise ValueError("Native cannot enable a MOD")
    return result


def validate_plans(plans):
    native = plans["native"]
    for arm, command in plans.items():
        if normalize(command, arm) != native:
            raise ValueError(f"{arm} differs from the SINGLE Native beyond its MOD")
    expected = {
        "--tensor-parallel-size": "2",
        "--pipeline-parallel-size": "1",
        "--dtype": "bfloat16",
        "--kv-cache-dtype": "auto",
        "--max-model-len": "262144",
        "--max-num-seqs": "16",
        "--max-num-batched-tokens": "4096",
        "--kv-cache-memory-bytes": "26038239232",
        "--seed": "17",
    }
    for flag, value in expected.items():
        if native.count(flag) != 1 or native[native.index(flag) + 1] != value:
            raise ValueError(f"Frozen Frontier setting violated: {flag}")
    for flag in ("--enable-prefix-caching", "--async-scheduling"):
        if native.count(flag) != 1:
            raise ValueError(f"Missing {flag}")
    if "--enforce-eager" in native:
        raise ValueError("Eager not permitted")
    graph = json.loads(native[native.index("--compilation-config") + 1])
    spec = json.loads(native[native.index("--speculative-config") + 1])
    if graph != {
        "cudagraph_mode": "FULL_AND_PIECEWISE",
        "cudagraph_capture_sizes": [3, 6, 12, 24, 48],
        "max_cudagraph_capture_size": 48,
    } or spec != {"method": "mtp", "num_speculative_tokens": 2}:
        raise ValueError("Graph/MTP configuration changed")


def verify(root):
    root = Path(root)
    contract = json.loads((root / "common-contract.json").read_text())
    for path, expected in contract["runtime_source_files"].items():
        if digest(path) != expected:
            raise RuntimeError(f"Shared runtime changed: {path}")
    plans = json.loads((root / "manager-plans.json").read_text())
    validate_plans(plans)
    if plans["native"] != contract["native_command"]:
        raise RuntimeError("Single Native identity changed")
    for arm in ARMS:
        metadata = json.loads((root / f"metadata-{arm}.json").read_text())
        if metadata["shared_native_contract_sha256"] != digest(
            root / "common-contract.json"
        ):
            raise RuntimeError("Candidate is not bound to the single Native contract")


def manager_json(text):
    """Retain logs separately; accept one complete JSON object after log lines."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() != "{":
            continue
        try:
            value = json.loads("".join(lines[index:]))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Manager output contains no complete JSON object")
