from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bidkv_matrix_workload", ROOT / "scripts/bidkv_matrix_workload.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ANALYZER_SPEC = importlib.util.spec_from_file_location(
    "analyze_bidkv_matrix", ROOT / "scripts/analyze_bidkv_matrix.py"
)
assert ANALYZER_SPEC and ANALYZER_SPEC.loader
ANALYZER = importlib.util.module_from_spec(ANALYZER_SPEC)
ANALYZER_SPEC.loader.exec_module(ANALYZER)
INDEX_SPEC = importlib.util.spec_from_file_location(
    "index_bidkv_evidence", ROOT / "scripts/index_bidkv_evidence.py"
)
assert INDEX_SPEC and INDEX_SPEC.loader
INDEXER = importlib.util.module_from_spec(INDEX_SPEC)
INDEX_SPEC.loader.exec_module(INDEXER)


def test_matrix_is_bounded_and_never_targets_reserved_devices() -> None:
    matrix = json.loads((ROOT / "config/bidkv-tp4-graph-matrix.json").read_text())
    assert 8 <= len(matrix["cells"]) <= 14
    assert matrix["lane"]["devices"] == [0, 1, 2, 3]
    assert matrix["lane"]["excluded_devices"] == [4, 5, 6, 7]
    assert matrix["lane"]["tensor_parallel_size"] == 4
    assert "graph" in matrix["lane"]["execution_mode"]
    assert set(matrix["method"]["qualification_values"]) == {
        "not-beneficial-in-tested-cell",
        "inconclusive",
        "beneficial",
    }
    assert all(cell["kv_cache_bytes"] >= 1073741824 for cell in matrix["cells"])


def test_workload_shapes_are_deterministic_and_interleaved() -> None:
    homogeneous, homogeneous_delays = MODULE.workload("homogeneous-long", 4)
    mixed, _ = MODULE.workload("mixed-length", 4)
    interactive, delays = MODULE.workload("interactive-batch", 8)
    assert len(set(map(len, homogeneous))) == 1
    assert len(set(map(len, mixed))) == 4
    assert min(map(len, mixed)) > len(MODULE.PARAGRAPH) * 300
    assert len(mixed[0]) > len(mixed[-1])
    assert homogeneous_delays == [0.0] * 4
    assert delays == sorted(delays) and delays[-1] > 0
    assert len(set(map(len, interactive))) > 2


def test_output_validity_separates_exact_and_semantic_gates() -> None:
    exact = MODULE.output_validity("BIDKV_MATRIX_WARMUP_0\n", "BIDKV_MATRIX_WARMUP_0")
    leaked = MODULE.output_validity(
        "BIDKV_MATRIX_WARMUP_0<|im_start|>", "BIDKV_MATRIX_WARMUP_0"
    )
    semantic = MODULE.output_validity(
        "Request progress remains fair when cache scheduling triggers preemption.",
        None,
    )

    assert exact["exact_match"] is True and exact["semantic_valid"] is True
    assert leaked["exact_match"] is False and leaked["semantic_valid"] is False
    assert leaked["special_token_leaks"] == ["<|im_start|>"]
    assert semantic["exact_match"] is True and semantic["semantic_valid"] is True


def test_matrix_exposes_cascade_guard_as_a_tuning_axis() -> None:
    matrix = json.loads((ROOT / "config/bidkv-tp4-graph-matrix.json").read_text())
    cascade = [
        cell for cell in matrix["cells"] if "cascade_gain_ratio" in cell["config"]
    ]
    assert {cell["workload"] for cell in cascade} == {
        "homogeneous-long",
        "mixed-length",
    }
    assert all(cell["config"]["cascade_gain_ratio"] == 1.0 for cell in cascade)


def test_runner_supports_alternating_stage_two_repetitions() -> None:
    source = (ROOT / "scripts/run_bidkv_matrix.py").read_text()
    assert 'parser.add_argument("--repetitions", type=int, default=1)' in source
    assert "(index + repetition) % 2" in source
    assert '"source-snapshot.json"' in source
    assert "str(INDEXER)" in source


def test_analyzer_requires_three_repeats_for_effectiveness_verdict() -> None:
    source = (ROOT / "scripts/analyze_bidkv_matrix.py").read_text()
    assert "len(repeats) >= 3" in source
    assert 'qualification = "beneficial"' in source
    assert 'qualification = "not-beneficial-in-tested-cell"' in source
    assert '"blocked-protected-resource"' in source
    assert '"sage-mate.bidkv-matrix-analysis/v3"' in source


def test_determinism_is_computed_within_each_arm() -> None:
    repeats = [
        {
            "baseline": {"output_hashes_by_index": {"0": "same", "1": value}},
            "candidate": {"output_hashes_by_index": {"0": "candidate"}},
        }
        for value in ("a", "b", "c")
    ]

    baseline = ANALYZER.determinism(repeats, "baseline")
    candidate = ANALYZER.determinism(repeats, "candidate")

    assert baseline["status"] == "failed"
    assert baseline["deterministic_indices"] == 1
    assert baseline["eligible_indices"] == 2
    assert candidate["status"] == "passed"


def test_paired_interval_is_conservative_at_three_repeats() -> None:
    stable = ANALYZER.paired_interval([2.0, 2.1, 1.9])
    noisy = ANALYZER.paired_interval([-2.0, 3.0, 1.0])
    single = ANALYZER.paired_interval([2.0])
    assert stable["ci95_low"] > 0
    assert noisy["ci95_low"] < 0 < noisy["ci95_high"]
    assert single["ci95_low"] is None


def test_indexer_alternates_arms_without_rewriting_raw_files(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    cell = suite / "cell-a"
    for arm in ("baseline", "candidate"):
        arm_dir = cell / arm
        arm_dir.mkdir(parents=True)
        (arm_dir / "configuration.json").write_text('{"safe":"value"}\n')
        (arm_dir / "raw.txt").write_text("immutable\n")
    (suite / "started-at.txt").write_text("2026-09-05T00:00:00+00:00\n")
    (suite / "finished-at.txt").write_text("2026-09-05T01:00:00+00:00\n")
    (suite / "matrix.json").write_text(
        json.dumps({"cells": [{"id": "cell-a", "config": {}}]})
    )

    raw_hash = INDEXER.sha256(cell / "baseline" / "raw.txt")
    index = INDEXER.write_index(suite, ROOT)

    assert [entry["arm"] for entry in index["entries"]] == [
        "baseline",
        "candidate",
    ]
    manifest = json.loads((cell / "candidate" / "run-manifest.json").read_text())
    assert manifest["runtime"]["bidkv_commit"] == INDEXER.BIDKV_CANDIDATE_COMMIT
    assert manifest["topology"]["tensor_parallel_ranks"] == [0, 1, 2, 3]
    assert manifest["workload_source"]["dirty_state"] == "unknown-not-captured"
    assert INDEXER.sha256(cell / "baseline" / "raw.txt") == raw_hash
