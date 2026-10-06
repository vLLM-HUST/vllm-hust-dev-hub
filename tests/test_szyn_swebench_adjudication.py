from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evaluation_machine/adjudicate_szyn_swebench_timeout.py"


def load_module():
    spec = importlib.util.spec_from_file_location("szyn_adjudication", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(tmp_path: Path):
    module = load_module()
    instance_id = "sphinx-doc__sphinx-7590"
    formal = tmp_path / "formal"
    result = formal / instance_id
    control = tmp_path / "control"
    baseline = control / instance_id
    patch = result / "attempt-1/agent.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text(
        "+                if self.current_char and (self.current_char.isalpha()\n"
        "+                    while self.current_char and (self.current_char.isalnum()\n"
    )
    patch_hash = module.sha256(patch)
    candidate = {
        "instance_id": instance_id,
        "execution_id": "test-execution",
        "status": "grader_timeout",
        "grader_runtime_seconds": 1800.01,
        "image": {"digest": "sha256:pinned", "executed_architecture": "arm64"},
        "execution_backend": "native-proot",
        "patch_normalization": {"raw_patch_sha256": patch_hash},
    }
    current_path = result / "grader-terminal.json"
    first_path = result / "infrastructure-retry-1/grader-attempt/grader-terminal.json"
    control_path = baseline / "grader-terminal.json"
    write_json(current_path, candidate)
    write_json(first_path, candidate)
    write_json(
        control_path,
        {
            **candidate,
            "status": "unresolved",
            "grader_runtime_seconds": 17.0,
        },
    )
    write_json(
        baseline / "collection-terminal.json",
        {
            "diagnostic_control": "synthetic empty patch; not a model attempt or formal result"
        },
    )
    (baseline / "attempt-1").mkdir()
    (baseline / "attempt-1/agent.patch").write_bytes(b"")
    (result / "test-output.txt").write_text("tests/test_domain_cpp.py .")
    (baseline / "test-output.txt").write_text("tests/test_domain_cpp.py 1 failed")
    raw_path = tmp_path / "raw.json"
    write_json(
        raw_path,
        {
            "execution_id": "test-execution",
            "asset_id": "SZYN-OPENCODE-SWEBENCH-VERIFIED-500",
            "declared_denominator": 500,
            "formal_terminal_count": 500,
            "complete": True,
            "publishable": False,
            "resolved": 232,
            "resolution_rate": 232 / 500,
            "formal_status_counts": {
                "resolved": 232,
                "unresolved": 267,
                "grader_timeout": 1,
            },
            "publication_blockers": {
                "missing": 0,
                "invalid": 0,
                "grader_error": 0,
                "grader_timeout": 1,
            },
        },
    )
    manifest = {
        "schema_version": "szyn-candidate-timeout-adjudication/v1",
        "raw_summary_sha256": module.sha256(raw_path),
        "adjudications": [
            {
                "instance_id": instance_id,
                "reason_code": "candidate_infinite_loop_at_eof",
                "causal_explanation": "The added suffix loop consumes the EOF sentinel forever.",
                "eof_sentinel": "EOF",
                "current_terminal_sha256": module.sha256(current_path),
                "first_terminal_sha256": module.sha256(first_path),
                "control_terminal_sha256": module.sha256(control_path),
                "agent_patch_sha256": patch_hash,
                "current_test_output_sha256": module.sha256(result / "test-output.txt"),
                "control_test_output_sha256": module.sha256(
                    baseline / "test-output.txt"
                ),
            }
        ],
    }
    return module, raw_path, manifest, formal, control


def run_case(module, raw_path, manifest, formal, control):
    return module.adjudicate(
        contract={
            "execution_id": "test-execution",
            "scoring": {"grader_timeout_seconds": 1800},
        },
        raw_summary_path=raw_path,
        manifest=manifest,
        formal_results=formal,
        control_results=control,
    )


def test_candidate_timeout_is_adjudicated_without_changing_resolved(
    tmp_path: Path,
) -> None:
    module, raw_path, manifest, formal, control = fixture(tmp_path)
    result = run_case(module, raw_path, manifest, formal, control)
    assert result["raw_publishable"] is False
    assert result["adjudicated_publishable"] is True
    assert result["raw_status_counts"]["grader_timeout"] == 1
    assert result["adjudicated_status_counts"] == {"resolved": 232, "unresolved": 268}
    assert result["resolved"] == 232
    assert result["resolution_rate"] == 232 / 500


def test_control_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    module, raw_path, manifest, formal, control = fixture(tmp_path)
    (control / "sphinx-doc__sphinx-7590/grader-terminal.json").write_text("{}")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        run_case(module, raw_path, manifest, formal, control)


def test_control_timeout_is_not_adjudicable(tmp_path: Path) -> None:
    module, raw_path, manifest, formal, control = fixture(tmp_path)
    terminal = control / "sphinx-doc__sphinx-7590/grader-terminal.json"
    value = json.loads(terminal.read_text())
    value["status"] = "grader_timeout"
    write_json(terminal, value)
    manifest["adjudications"][0]["control_terminal_sha256"] = module.sha256(terminal)
    with pytest.raises(ValueError, match="control evidence"):
        run_case(module, raw_path, manifest, formal, control)


def test_incomplete_raw_run_is_not_adjudicable(tmp_path: Path) -> None:
    module, raw_path, manifest, formal, control = fixture(tmp_path)
    value = json.loads(raw_path.read_text())
    value["formal_terminal_count"] = 499
    write_json(raw_path, value)
    manifest["raw_summary_sha256"] = module.sha256(raw_path)
    with pytest.raises(ValueError, match="not a complete"):
        run_case(module, raw_path, manifest, formal, control)
