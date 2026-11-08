#!/usr/bin/env python3
"""Validate and seal paired real-online DSpark acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import sys
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

ARM_SCHEMA = "vllm-hust.dspark-online-arm/v1"
PAIR_SCHEMA = "vllm-hust.dspark-online-pair/v1"
ARM_FIELDS = frozenset(
    {
        "schema_version",
        "arm",
        "profile_id",
        "engine_start_id",
        "stack",
        "workload",
        "benchmark",
        "hbm",
        "cancellation",
        "capability",
    }
)
STACK_FIELDS = frozenset(
    {
        "model",
        "model_revision",
        "core_commit",
        "ascend_commit",
        "image_digest",
        "hardware",
        "tensor_parallel_size",
        "graph_mode",
    }
)


class AcceptanceError(ValueError):
    """Evidence does not satisfy the public acceptance contract."""


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{name} must be a JSON object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcceptanceError(f"{name} must be non-empty text")
    return value


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AcceptanceError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise AcceptanceError(f"{name} must be >= {minimum:g}")
    return result


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AcceptanceError(f"{name} must be an integer >= {minimum}")
    return value


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: pathlib.Path) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"cannot read {path}: {exc}") from exc


def _require_exact_fields(
    payload: Mapping[str, Any], expected: frozenset[str], name: str
) -> None:
    missing = expected.difference(payload)
    extra = set(payload).difference(expected)
    if missing or extra:
        raise AcceptanceError(
            f"{name} field mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )


def _validate_stack(stack: dict[str, Any], arm: str) -> None:
    _require_exact_fields(stack, STACK_FIELDS, f"{arm}.stack")
    for field in (
        "model",
        "hardware",
    ):
        _text(stack[field], f"{arm}.stack.{field}")
    for field in ("model_revision", "core_commit", "ascend_commit"):
        value = _text(stack[field], f"{arm}.stack.{field}")
        if len(value) != 40 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise AcceptanceError(
                f"{arm}.stack.{field} must be a lowercase 40-hex commit"
            )
    image_digest = _text(stack["image_digest"], f"{arm}.stack.image_digest")
    image_hash = image_digest.removeprefix("sha256:")
    if len(image_hash) != 64 or any(
        character not in "0123456789abcdef" for character in image_hash
    ):
        raise AcceptanceError(
            f"{arm}.stack.image_digest must be an immutable SHA-256 digest"
        )
    _integer(
        stack["tensor_parallel_size"],
        f"{arm}.stack.tensor_parallel_size",
        minimum=1,
    )
    if stack["graph_mode"] is not True:
        raise AcceptanceError(
            f"{arm} must run in graph mode; eager fallback is invalid"
        )


def _validate_benchmark(benchmark: dict[str, Any], arm: str) -> dict[str, float]:
    completed = _integer(benchmark.get("completed"), f"{arm}.benchmark.completed")
    failed = _integer(benchmark.get("failed"), f"{arm}.benchmark.failed")
    _integer(benchmark.get("num_warmups"), f"{arm}.benchmark.num_warmups", minimum=1)
    if completed < 10:
        raise AcceptanceError(f"{arm} requires at least 10 measured warm repetitions")
    if failed != 0:
        raise AcceptanceError(f"{arm} contains {failed} failed requests")
    errors = benchmark.get("errors")
    if not isinstance(errors, list) or len(errors) != completed:
        raise AcceptanceError(f"{arm}.benchmark.errors must cover every repetition")
    if any(error not in (None, "") for error in errors):
        raise AcceptanceError(f"{arm} contains non-empty request errors")
    for series_name in ("ttfts", "latencies", "output_lens"):
        series = benchmark.get(series_name)
        if not isinstance(series, list) or len(series) != completed:
            raise AcceptanceError(
                f"{arm}.benchmark.{series_name} must cover every repetition"
            )
    metrics = {
        name: _number(benchmark.get(name), f"{arm}.benchmark.{name}")
        for name in (
            "p50_ttft_ms",
            "p95_ttft_ms",
            "p50_tpot_ms",
            "p95_tpot_ms",
            "output_throughput",
        )
    }
    if any(value <= 0 for value in metrics.values()):
        raise AcceptanceError(f"{arm} latency and throughput metrics must be positive")
    return metrics


def _validate_hbm(hbm: dict[str, Any], arm: str, expected_devices: int) -> float:
    if hbm.get("unit") != "MiB":
        raise AcceptanceError(f"{arm}.hbm.unit must be MiB")
    if (
        _integer(hbm.get("device_count"), f"{arm}.hbm.device_count", minimum=1)
        != expected_devices
    ):
        raise AcceptanceError(f"{arm}.hbm.device_count must match tensor parallel size")
    samples = hbm.get("used_mib_samples")
    if not isinstance(samples, list) or len(samples) < 2:
        raise AcceptanceError(f"{arm}.hbm requires at least two used-memory samples")
    values = [_number(value, f"{arm}.hbm.used_mib_samples") for value in samples]
    return max(values)


def _validate_cancellation(cancellation: dict[str, Any], arm: str) -> float:
    if cancellation.get("client_disconnect_observed") is not True:
        raise AcceptanceError(f"{arm} lacks a client-disconnect observation")
    cleanup = _number(
        cancellation.get("cleanup_window_seconds"),
        f"{arm}.cancellation.cleanup_window_seconds",
    )
    if (
        _integer(
            cancellation.get("active_tasks_after"),
            f"{arm}.cancellation.active_tasks_after",
        )
        != 0
    ):
        raise AcceptanceError(f"{arm} left an active engine/proposer task")
    if cancellation.get("engine_healthy_after") is not True:
        raise AcceptanceError(f"{arm} engine was unhealthy after cancellation")
    if cancellation.get("post_cancel_request_completed") is not True:
        raise AcceptanceError(f"{arm} lacks a successful post-cancellation request")
    return cleanup


def _validate_capability(capability: dict[str, Any], arm: str) -> None:
    if capability.get("schema_version") != "vllm-hust.dspark-capability/v1":
        raise AcceptanceError(f"{arm} has an unsupported capability receipt")
    if capability.get("method") != "dspark":
        raise AcceptanceError(f"{arm} capability method must be dspark")
    sources = _object(capability.get("sources"), f"{arm}.capability.sources")
    for source_name in ("registry", "proposer"):
        source = _object(
            sources.get(source_name), f"{arm}.capability.sources.{source_name}"
        )
        digest = _text(
            source.get("sha256"),
            f"{arm}.capability.sources.{source_name}.sha256",
        )
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise AcceptanceError(
                f"{arm}.capability.sources.{source_name}.sha256 must be lowercase SHA-256"
            )
    expected_requested = arm == "dspark"
    if capability.get("requested") is not expected_requested:
        raise AcceptanceError(f"{arm} capability requested state is inconsistent")
    expected_verdict = "admitted" if expected_requested else "not-requested"
    if capability.get("verdict") != expected_verdict:
        raise AcceptanceError(f"{arm} capability verdict must be {expected_verdict}")
    if expected_requested and capability.get("supported") is not True:
        raise AcceptanceError("DSpark capability was not supported")


def validate_arm(payload: dict[str, Any], expected_arm: str) -> dict[str, Any]:
    _require_exact_fields(payload, ARM_FIELDS, expected_arm)
    if payload["schema_version"] != ARM_SCHEMA:
        raise AcceptanceError(f"{expected_arm} has an unsupported schema")
    if payload["arm"] != expected_arm:
        raise AcceptanceError(f"expected {expected_arm} arm, got {payload['arm']!r}")
    _text(payload["profile_id"], f"{expected_arm}.profile_id")
    _text(payload["engine_start_id"], f"{expected_arm}.engine_start_id")
    stack = _object(payload["stack"], f"{expected_arm}.stack")
    _validate_stack(stack, expected_arm)
    workload = _object(payload["workload"], f"{expected_arm}.workload")
    _text(workload.get("id"), f"{expected_arm}.workload.id")
    digest = _text(workload.get("sha256"), f"{expected_arm}.workload.sha256")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise AcceptanceError(
            f"{expected_arm}.workload.sha256 must be lowercase SHA-256"
        )
    metrics = _validate_benchmark(
        _object(payload["benchmark"], f"{expected_arm}.benchmark"), expected_arm
    )
    peak_hbm = _validate_hbm(
        _object(payload["hbm"], f"{expected_arm}.hbm"),
        expected_arm,
        stack["tensor_parallel_size"],
    )
    cleanup = _validate_cancellation(
        _object(payload["cancellation"], f"{expected_arm}.cancellation"),
        expected_arm,
    )
    _validate_capability(
        _object(payload["capability"], f"{expected_arm}.capability"), expected_arm
    )
    benchmark = payload["benchmark"]
    if expected_arm == "baseline":
        if benchmark.get("spec_decode_draft_tokens", 0) != 0:
            raise AcceptanceError("baseline arm unexpectedly drafted tokens")
    else:
        draft = _integer(
            benchmark.get("spec_decode_draft_tokens"),
            "dspark.benchmark.spec_decode_draft_tokens",
            minimum=1,
        )
        accepted = _integer(
            benchmark.get("spec_decode_accepted_tokens"),
            "dspark.benchmark.spec_decode_accepted_tokens",
            minimum=1,
        )
        acceptance = _number(
            benchmark.get("spec_decode_acceptance_rate"),
            "dspark.benchmark.spec_decode_acceptance_rate",
        )
        if accepted > draft or not 0 < acceptance <= 100:
            raise AcceptanceError("DSpark acceptance counters are inconsistent")
        metrics["spec_decode_acceptance_rate"] = acceptance
    metrics["peak_hbm_mib"] = peak_hbm
    metrics["cleanup_window_seconds"] = cleanup
    return metrics


def build_pair(
    baseline_path: pathlib.Path, dspark_path: pathlib.Path
) -> dict[str, Any]:
    baseline = _load(baseline_path)
    dspark = _load(dspark_path)
    baseline_metrics = validate_arm(baseline, "baseline")
    dspark_metrics = validate_arm(dspark, "dspark")
    if baseline["stack"] != dspark["stack"]:
        raise AcceptanceError("baseline and DSpark stacks are not identical")
    if baseline["workload"] != dspark["workload"]:
        raise AcceptanceError("baseline and DSpark workloads are not identical")
    if baseline["engine_start_id"] == dspark["engine_start_id"]:
        raise AcceptanceError("baseline and DSpark require distinct engine starts")
    if baseline["profile_id"] == dspark["profile_id"]:
        raise AcceptanceError("baseline and DSpark require distinct profile IDs")
    pair = {
        "schema_version": PAIR_SCHEMA,
        "status": "VERIFIED",
        "stack": baseline["stack"],
        "workload": baseline["workload"],
        "arms": {
            "baseline": {
                "sha256": _file_sha256(baseline_path),
                "metrics": baseline_metrics,
            },
            "dspark": {
                "sha256": _file_sha256(dspark_path),
                "metrics": dspark_metrics,
            },
        },
        "comparison": {
            "output_throughput_ratio": dspark_metrics["output_throughput"]
            / baseline_metrics["output_throughput"],
            "p50_tpot_ratio": dspark_metrics["p50_tpot_ms"]
            / baseline_metrics["p50_tpot_ms"],
            "peak_hbm_delta_mib": dspark_metrics["peak_hbm_mib"]
            - baseline_metrics["peak_hbm_mib"],
        },
    }
    canonical = json.dumps(pair, sort_keys=True, separators=(",", ":")).encode()
    pair["content_sha256"] = _sha256_bytes(canonical)
    return pair


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=pathlib.Path, required=True)
    parser.add_argument("--dspark", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    try:
        pair = build_pair(args.baseline, args.dspark)
        _atomic_write(args.output, pair)
        print(
            json.dumps(
                {
                    "status": pair["status"],
                    "content_sha256": pair["content_sha256"],
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
        return 0
    except AcceptanceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
