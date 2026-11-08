#!/usr/bin/env python3
"""Fail-closed DeepSeek DSpark deployment preflight.

The launcher uses this module twice: once on the host to normalize the selected
profile before Docker or NPU mutation, and once in the runtime container to
prove that the selected vLLM-Ascend source actually exposes the DSpark model
and proposer seams.  Runtime probing is source-only; it never imports a model
implementation or allocates an accelerator.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import sys
import tempfile
from collections.abc import Sequence
from typing import Any

SCHEMA_VERSION = "vllm-hust.dspark-capability/v1"
DSPARK_CONFIG_KEYS = frozenset(
    {"dspark_block_size", "dspark_target_layer_ids", "dspark_markov_rank"}
)
VALID_MODES = frozenset({"auto", "disabled", "dspark"})


class PreflightError(ValueError):
    """The requested deployment profile is unsafe or unsupported."""


def _load_object(path: pathlib.Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PreflightError(f"{path} must contain a JSON object")
    return payload


def _load_extra_args(raw: str) -> list[str]:
    try:
        args = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise PreflightError(f"VLLM_ENGINE_EXTRA_ARGS_JSON is invalid: {exc}") from exc
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise PreflightError(
            "VLLM_ENGINE_EXTRA_ARGS_JSON must be a JSON list of strings"
        )
    return list(args)


def _speculative_config(args: Sequence[str]) -> dict[str, Any] | None:
    values: list[str] = []
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--speculative-config":
            if index + 1 >= len(args):
                raise PreflightError("--speculative-config requires a JSON object")
            values.append(args[index + 1])
            index += 2
            continue
        if item.startswith("--speculative-config="):
            values.append(item.split("=", 1)[1])
        index += 1
    if len(values) > 1:
        raise PreflightError("multiple --speculative-config values are ambiguous")
    if not values:
        return None
    try:
        value = json.loads(values[0])
    except json.JSONDecodeError as exc:
        raise PreflightError(f"--speculative-config is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightError("--speculative-config must contain a JSON object")
    return value


def _is_dspark_checkpoint(config: dict[str, Any]) -> bool:
    return bool(DSPARK_CONFIG_KEYS.intersection(config))


def normalize_profile(
    *,
    model_config: dict[str, Any] | None,
    extra_args_raw: str,
    mode: str,
    dspark_tokens: int | None,
) -> list[str]:
    if mode not in VALID_MODES:
        raise PreflightError(
            f"VLLM_ENGINE_SPECULATIVE_MODE must be one of {sorted(VALID_MODES)}, got {mode!r}"
        )
    args = _load_extra_args(extra_args_raw)
    spec = _speculative_config(args)
    method = spec.get("method") if spec is not None else None
    checkpoint_is_dspark = bool(model_config and _is_dspark_checkpoint(model_config))

    if checkpoint_is_dspark and method == "mtp":
        raise PreflightError(
            "the checkpoint declares DSpark metadata but the profile requests legacy method=mtp"
        )
    if mode == "disabled" and spec is not None:
        raise PreflightError(
            "VLLM_ENGINE_SPECULATIVE_MODE=disabled forbids --speculative-config"
        )
    if mode == "dspark":
        if model_config is None:
            raise PreflightError(
                "DSpark validation requires a local checkpoint config.json before launch"
            )
        if not checkpoint_is_dspark:
            raise PreflightError(
                "VLLM_ENGINE_SPECULATIVE_MODE=dspark requires DSpark metadata in config.json"
            )
        if spec is None:
            if dspark_tokens is None or dspark_tokens < 1:
                raise PreflightError(
                    "VLLM_ENGINE_DSPARK_NUM_SPECULATIVE_TOKENS must be a positive integer"
                )
            generated = {
                "method": "dspark",
                "num_speculative_tokens": dspark_tokens,
            }
            args.extend(
                ["--speculative-config", json.dumps(generated, separators=(",", ":"))]
            )
            spec = generated
        elif method != "dspark":
            raise PreflightError(
                "the DSpark profile requires --speculative-config method=dspark"
            )
        tokens = spec.get("num_speculative_tokens")
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 1:
            raise PreflightError(
                "DSpark --speculative-config requires positive num_speculative_tokens"
            )
    return args


def dspark_requested(extra_args_raw: str) -> bool:
    spec = _speculative_config(_load_extra_args(extra_args_raw))
    return bool(spec and spec.get("method") == "dspark")


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _class_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _registered_dspark_target(registry_path: pathlib.Path) -> str | None:
    tree = ast.parse(
        registry_path.read_text(encoding="utf-8"), filename=str(registry_path)
    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        function = node.func
        if not isinstance(function, ast.Attribute) or function.attr != "register_model":
            continue
        first, second = node.args[:2]
        if not (
            isinstance(first, ast.Constant)
            and first.value == "DSparkDraftModel"
            and isinstance(second, ast.Constant)
            and isinstance(second.value, str)
        ):
            continue
        return second.value
    return None


def probe_runtime(ascend_root: pathlib.Path) -> dict[str, Any]:
    root = ascend_root.resolve()
    registry = root / "models" / "__init__.py"
    proposer = root / "spec_decode" / "dspark_proposer.py"
    expected_target = (
        "vllm_ascend.models.deepseek_v4.dspark:DSparkDeepseekV4ForCausalLM"
    )
    target = _registered_dspark_target(registry) if registry.is_file() else None
    proposer_classes = _class_names(proposer) if proposer.is_file() else set()
    supported = target == expected_target and "AscendDSparkProposer" in proposer_classes
    return {
        "schema_version": SCHEMA_VERSION,
        "method": "dspark",
        "supported": supported,
        "draft_architecture": "DSparkDraftModel",
        "draft_target": target or "",
        "proposer": "vllm_ascend.spec_decode.dspark_proposer:AscendDSparkProposer",
        "sources": {
            "registry": {
                "path": "vllm_ascend/models/__init__.py",
                "sha256": _sha256(registry) if registry.is_file() else "",
            },
            "proposer": {
                "path": "vllm_ascend/spec_decode/dspark_proposer.py",
                "sha256": _sha256(proposer) if proposer.is_file() else "",
            },
        },
    }


def _atomic_write(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _positive_integer(raw: str | None) -> int | None:
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise PreflightError(f"expected a positive integer, got {raw!r}") from exc
    if value < 1:
        raise PreflightError(f"expected a positive integer, got {raw!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize")
    normalize.add_argument("--model-config")
    normalize.add_argument("--extra-args-json", default="[]")
    normalize.add_argument("--mode", default="auto")
    normalize.add_argument("--dspark-tokens")

    probe = subparsers.add_parser("probe-runtime")
    probe.add_argument("--ascend-root", required=True)
    probe.add_argument("--extra-args-json", default="[]")
    probe.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "normalize":
            config = (
                _load_object(pathlib.Path(args.model_config))
                if args.model_config
                else None
            )
            normalized = normalize_profile(
                model_config=config,
                extra_args_raw=args.extra_args_json,
                mode=args.mode,
                dspark_tokens=_positive_integer(args.dspark_tokens),
            )
            print(json.dumps(normalized, separators=(",", ":")))
            return 0

        capability = probe_runtime(pathlib.Path(args.ascend_root))
        requested = dspark_requested(args.extra_args_json)
        capability["requested"] = requested
        capability["verdict"] = (
            "admitted"
            if requested and capability["supported"]
            else "not-requested"
            if not requested
            else "rejected"
        )
        if args.output:
            _atomic_write(pathlib.Path(args.output), capability)
        print(json.dumps(capability, sort_keys=True, separators=(",", ":")))
        if requested and not capability["supported"]:
            raise PreflightError(
                "DSpark was requested but the selected vLLM-Ascend source does not "
                "register DSparkDraftModel and AscendDSparkProposer"
            )
        return 0
    except PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
