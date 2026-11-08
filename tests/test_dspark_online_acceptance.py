from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "dspark_online_acceptance.py"
SPEC = importlib.util.spec_from_file_location("dspark_online_acceptance", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


def arm(name: str) -> dict:
    candidate = name == "dspark"
    benchmark = {
        "completed": 10,
        "failed": 0,
        "num_warmups": "2",
        "errors": [""] * 10,
        "ttfts": [0.1] * 10,
        "latencies": [1.0] * 10,
        "output_lens": [32] * 10,
        "p50_ttft_ms": 100.0 if not candidate else 102.0,
        "p95_ttft_ms": 120.0 if not candidate else 123.0,
        "p50_tpot_ms": 20.0 if not candidate else 15.0,
        "p95_tpot_ms": 25.0 if not candidate else 18.0,
        "output_throughput": 50.0 if not candidate else 70.0,
    }
    if candidate:
        benchmark.update(
            {
                "spec_decode_draft_tokens": 500,
                "spec_decode_accepted_tokens": 300,
                "spec_decode_acceptance_rate": 60.0,
            }
        )
    return {
        "schema_version": "vllm-hust.dspark-online-arm/v1",
        "arm": name,
        "profile_id": f"deepseek-v4-flash-{name}",
        "engine_start_id": f"start-{name}",
        "stack": {
            "model": "DeepSeek-V4-Flash-W8A8",
            "model_revision": "a" * 40,
            "core_commit": "b" * 40,
            "ascend_commit": "c" * 40,
            "image_digest": f"sha256:{'d' * 64}",
            "hardware": "8xAscend-910B2",
            "tensor_parallel_size": 8,
            "graph_mode": True,
        },
        "workload": {"id": "dspark-online-v1", "sha256": "e" * 64},
        "benchmark": benchmark,
        "hbm": {
            "unit": "MiB",
            "device_count": 8,
            "used_mib_samples": [60000, 61000] if candidate else [58000, 59000],
        },
        "cancellation": {
            "client_disconnect_observed": True,
            "cleanup_window_seconds": 5.0,
            "active_tasks_after": 0,
            "engine_healthy_after": True,
            "post_cancel_request_completed": True,
        },
        "capability": {
            "schema_version": "vllm-hust.dspark-capability/v1",
            "method": "dspark",
            "requested": candidate,
            "supported": True,
            "verdict": "admitted" if candidate else "not-requested",
            "sources": {
                "registry": {"sha256": "1" * 64},
                "proposer": {"sha256": "2" * 64},
            },
        },
    }


def write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def pair(tmp_path: Path, baseline: dict | None = None, dspark: dict | None = None):
    baseline_path = write(tmp_path / "baseline.json", baseline or arm("baseline"))
    dspark_path = write(tmp_path / "dspark.json", dspark or arm("dspark"))
    return acceptance.build_pair(baseline_path, dspark_path)


def test_valid_pair_is_verified_and_content_addressed(tmp_path: Path) -> None:
    receipt = pair(tmp_path)

    assert receipt["status"] == "VERIFIED"
    assert receipt["comparison"] == {
        "output_throughput_ratio": 1.4,
        "p50_tpot_ratio": 0.75,
        "peak_hbm_delta_mib": 2000.0,
    }
    assert len(receipt["content_sha256"]) == 64


def test_requires_ten_measured_warm_repetitions(tmp_path: Path) -> None:
    baseline = arm("baseline")
    baseline["benchmark"]["completed"] = 9
    for field in ("errors", "ttfts", "latencies", "output_lens"):
        baseline["benchmark"][field] = baseline["benchmark"][field][:9]

    with pytest.raises(acceptance.AcceptanceError, match="at least 10"):
        pair(tmp_path, baseline=baseline)


def test_rejects_stack_drift_and_eager_fallback(tmp_path: Path) -> None:
    dspark = arm("dspark")
    dspark["stack"]["core_commit"] = "f" * 40
    with pytest.raises(acceptance.AcceptanceError, match="stacks are not identical"):
        pair(tmp_path, dspark=dspark)

    baseline = arm("baseline")
    baseline["stack"]["graph_mode"] = False
    with pytest.raises(acceptance.AcceptanceError, match="graph mode"):
        pair(tmp_path, baseline=baseline)


def test_rejects_missing_dspark_activity(tmp_path: Path) -> None:
    dspark = arm("dspark")
    dspark["benchmark"]["spec_decode_draft_tokens"] = 0

    with pytest.raises(acceptance.AcceptanceError, match="integer >= 1"):
        pair(tmp_path, dspark=dspark)


def test_rejects_cancellation_leak(tmp_path: Path) -> None:
    dspark = arm("dspark")
    dspark["cancellation"]["active_tasks_after"] = 1

    with pytest.raises(acceptance.AcceptanceError, match="active engine/proposer"):
        pair(tmp_path, dspark=dspark)


def test_requires_distinct_engine_starts(tmp_path: Path) -> None:
    dspark = arm("dspark")
    dspark["engine_start_id"] = "start-baseline"

    with pytest.raises(acceptance.AcceptanceError, match="distinct engine starts"):
        pair(tmp_path, dspark=dspark)


def test_cli_writes_owner_only_receipt(tmp_path: Path) -> None:
    baseline_path = write(tmp_path / "baseline.json", arm("baseline"))
    dspark_path = write(tmp_path / "dspark.json", arm("dspark"))
    output = tmp_path / "pair.json"

    assert (
        acceptance.main(
            [
                "--baseline",
                str(baseline_path),
                "--dspark",
                str(dspark_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())["status"] == "VERIFIED"
