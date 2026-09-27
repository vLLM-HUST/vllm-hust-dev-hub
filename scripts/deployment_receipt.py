#!/usr/bin/env python3
"""Create and verify versioned vLLM-HUST deployment receipts.

The receipt is intentionally independent of any application. Launch/verify
wrappers provide a sanitized JSON payload after a deployment has passed its
health and dialogue gates; downstream systems can validate the same schema and
content digest before selecting public fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "vllm-hust.deployment-receipt/v2"
SUPPORTED_SCHEMA_VERSIONS = {"vllm-hust.deployment-receipt/v1", SCHEMA_VERSION}
VALID_STATES = {"active", "superseded", "failed"}
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
TOP_LEVEL_FIELDS = {
    "schema_version",
    "receipt_id",
    "generated_at",
    "status",
    "model",
    "engine",
    "hardware",
    "parallelism",
    "execution",
    "speculative",
    "provenance",
    "integrity",
}
SECTION_FIELDS = {
    "model": {"served_name", "checkpoint_family", "architecture"},
    "engine": {"name", "core_commit", "plugin_name", "plugin_commit", "image"},
    "hardware": {
        "accelerator_kind",
        "accelerator_model",
        "physical_device_ids",
        "logical_device_ids",
    },
    "parallelism": {"tensor_parallel_size", "data_parallel_size", "expert_parallel_enabled"},
    "execution": {
        "quantization",
        "graph_mode",
        "prefix_caching_enabled",
        "prefix_caching_required",
        "prefix_cache_mode",
        "chunked_prefill_enabled",
    },
    "speculative": {"requested_method", "resolved_method", "active", "reason"},
    "provenance": {"source_uri", "import_origins"},
    "integrity": {"algorithm", "content_sha256"},
}


class ReceiptValidationError(ValueError):
    """Raised when a receipt is unsafe, malformed, or tampered with."""


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _content_hash(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "integrity"}
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _require_exact_fields(name: str, value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptValidationError(f"{name} must be an object")
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        raise ReceiptValidationError(
            f"{name} fields mismatch: missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    return value


def _reject_sensitive_keys(value: object, *, path: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                raise ReceiptValidationError(f"sensitive field is forbidden: {path}.{key}")
            _reject_sensitive_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_keys(child, path=f"{path}[{index}]")


def _require_text(section: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = section[key]
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ReceiptValidationError(f"{key} must be a non-empty string")
    return value.strip()


def validate_receipt(receipt: object, *, verify_hash: bool = True) -> dict[str, Any]:
    payload = _require_exact_fields("receipt", receipt, TOP_LEVEL_FIELDS)
    _reject_sensitive_keys(payload)
    if payload["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise ReceiptValidationError(f"unsupported schema_version: {payload['schema_version']!r}")
    if payload["status"] not in VALID_STATES:
        raise ReceiptValidationError(f"invalid status: {payload['status']!r}")
    _require_text(payload, "receipt_id")
    generated_at = _require_text(payload, "generated_at")
    try:
        datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptValidationError("generated_at must be ISO-8601") from exc

    section_fields = dict(SECTION_FIELDS)
    if payload["schema_version"] == "vllm-hust.deployment-receipt/v1":
        section_fields["execution"] = {"quantization", "graph_mode"}
    sections = {
        name: _require_exact_fields(name, payload[name], fields)
        for name, fields in section_fields.items()
    }
    for key in SECTION_FIELDS["model"]:
        _require_text(sections["model"], key)
    for key in ("name", "core_commit", "plugin_name", "plugin_commit", "image"):
        _require_text(sections["engine"], key)
    for key in ("accelerator_kind", "accelerator_model"):
        _require_text(sections["hardware"], key)
    for key in ("physical_device_ids", "logical_device_ids"):
        ids = sections["hardware"][key]
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) and item for item in ids):
            raise ReceiptValidationError(f"hardware.{key} must be a non-empty string list")
    for key in ("tensor_parallel_size", "data_parallel_size"):
        value = sections["parallelism"][key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ReceiptValidationError(f"parallelism.{key} must be a positive integer")
    if not isinstance(sections["parallelism"]["expert_parallel_enabled"], bool):
        raise ReceiptValidationError("parallelism.expert_parallel_enabled must be boolean")
    for key in ("quantization", "graph_mode"):
        _require_text(sections["execution"], key)
    if payload["schema_version"] == SCHEMA_VERSION:
        for key in (
            "prefix_caching_enabled",
            "prefix_caching_required",
            "chunked_prefill_enabled",
        ):
            if not isinstance(sections["execution"][key], bool):
                raise ReceiptValidationError(f"execution.{key} must be boolean")
        _require_text(sections["execution"], "prefix_cache_mode")
        if (
            sections["execution"]["prefix_caching_required"]
            and not sections["execution"]["prefix_caching_enabled"]
        ):
            raise ReceiptValidationError(
                "required prefix caching cannot be recorded as disabled"
            )
    for key in ("requested_method", "resolved_method"):
        _require_text(sections["speculative"], key)
    if not isinstance(sections["speculative"]["active"], bool):
        raise ReceiptValidationError("speculative.active must be boolean")
    _require_text(sections["speculative"], "reason", allow_empty=True)
    _require_text(sections["provenance"], "source_uri")
    origins = sections["provenance"]["import_origins"]
    if not isinstance(origins, dict) or not origins or not all(
        isinstance(key, str) and key and isinstance(value, str) and value
        for key, value in origins.items()
    ):
        raise ReceiptValidationError("provenance.import_origins must be a non-empty string map")
    integrity = sections["integrity"]
    if integrity["algorithm"] != "sha256":
        raise ReceiptValidationError("integrity.algorithm must be sha256")
    digest = _require_text(integrity, "content_sha256")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ReceiptValidationError("integrity.content_sha256 must be lowercase SHA-256")
    if verify_hash and digest != _content_hash(payload):
        raise ReceiptValidationError("receipt content hash mismatch")
    return payload


def create_receipt(payload: object, *, generated_at: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ReceiptValidationError("input payload must be an object")
    forbidden = set(payload) & {"schema_version", "receipt_id", "generated_at", "integrity"}
    if forbidden:
        raise ReceiptValidationError(f"derived fields are forbidden in input: {sorted(forbidden)}")
    created_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": "pending",
        "generated_at": created_at,
        **payload,
        "integrity": {"algorithm": "sha256", "content_sha256": "0" * 64},
    }
    seed = {key: value for key, value in receipt.items() if key not in {"receipt_id", "integrity"}}
    receipt["receipt_id"] = f"deploy-{hashlib.sha256(_canonical_bytes(seed)).hexdigest()[:20]}"
    receipt["integrity"]["content_sha256"] = _content_hash(receipt)
    return validate_receipt(receipt)


def _read_json(path: str) -> object:
    if path == "-":
        return json.load(__import__("sys").stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create and sign a receipt from JSON")
    create.add_argument("--input", required=True, help="input JSON path or - for stdin")
    create.add_argument("--output", required=True, type=Path)
    verify = subparsers.add_parser("verify", help="verify schema and content hash")
    verify.add_argument("receipt", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "create":
            _write_json(arguments.output, create_receipt(_read_json(arguments.input)))
            print(arguments.output)
        else:
            validate_receipt(_read_json(str(arguments.receipt)))
            print(f"valid {arguments.receipt}")
    except (OSError, json.JSONDecodeError, ReceiptValidationError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
