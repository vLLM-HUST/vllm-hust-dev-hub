from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluation_machine" / "summarize_szyn_swebench_results.py"


def load_module():
    spec = importlib.util.spec_from_file_location("szyn_summary", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tasks() -> list[dict[str, str]]:
    return [
        {"instance_id": "django__django-15104"},
        *({"instance_id": f"formal__task-{index:03d}"} for index in range(499)),
    ]


def test_real_preserved_qualification_is_task_zero_and_hash_valid() -> None:
    module = load_module()
    contract = module.load_json(
        ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json"
    )
    qualification_root = ROOT / contract["preserved_qualification"]["evidence_path"]
    result = module.summarize(
        contract=contract,
        tasks=tasks(),
        formal_results=ROOT / "does-not-exist",
        qualification_root=qualification_root,
    )
    assert result["declared_denominator"] == 500
    assert result["preserved_qualification"]["resolved"] == 1
    assert result["formal_expected"] == 499
    assert result["formal_terminal_count"] == 0
    assert len(result["missing_formal_instances"]) == 499
    assert result["complete"] is False
    assert result["publishable"] is False


def test_full_rerun_does_not_reuse_preserved_qualification(tmp_path: Path) -> None:
    module = load_module()
    contract = module.load_json(
        ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json"
    )
    contract = deepcopy(contract)
    contract["preserved_qualification_instance"] = None
    contract.pop("preserved_qualification")
    contract["execution_id"] = "sandbox-isolated-full-rerun"

    result = module.summarize(
        contract=contract,
        tasks=tasks(),
        formal_results=tmp_path,
        qualification_root=ROOT / "unused",
    )

    assert result["preserved_qualification"] is None
    assert result["formal_expected"] == 500
    assert result["formal_terminal_count"] == 0
    assert len(result["missing_formal_instances"]) == 500


def test_grader_error_blocks_publication(tmp_path: Path) -> None:
    module = load_module()
    contract = module.load_json(
        ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json"
    )
    task_rows = tasks()
    instance_id = task_rows[1]["instance_id"]
    result_dir = tmp_path / instance_id
    result_dir.mkdir()
    (result_dir / "grader-terminal.json").write_text(
        json.dumps(
            {
                "instance_id": instance_id,
                "execution_id": contract["execution_id"],
                "grader_harness_sha256": contract["grader"]["harness_script_sha256"],
                "status": "grader_error",
            }
        ),
        encoding="utf-8",
    )
    result = module.summarize(
        contract=contract,
        tasks=task_rows,
        formal_results=tmp_path,
        qualification_root=ROOT / contract["preserved_qualification"]["evidence_path"],
    )
    assert result["formal_status_counts"] == {"grader_error": 1}
    assert result["publication_blockers"]["grader_error"] == 1
    assert result["publishable"] is False


def test_grader_timeout_blocks_publication(tmp_path: Path) -> None:
    module = load_module()
    contract = module.load_json(
        ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json"
    )
    task_rows = tasks()
    for task in task_rows[1:]:
        instance_id = task["instance_id"]
        result_dir = tmp_path / instance_id
        result_dir.mkdir()
        status = (
            "grader_timeout"
            if instance_id == task_rows[1]["instance_id"]
            else "resolved"
        )
        (result_dir / "grader-terminal.json").write_text(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "execution_id": contract["execution_id"],
                    "grader_harness_sha256": contract["grader"][
                        "harness_script_sha256"
                    ],
                    "status": status,
                }
            ),
            encoding="utf-8",
        )
    result = module.summarize(
        contract=contract,
        tasks=task_rows,
        formal_results=tmp_path,
        qualification_root=ROOT / contract["preserved_qualification"]["evidence_path"],
    )
    assert result["complete"] is True
    assert result["publication_blockers"]["grader_timeout"] == 1
    assert result["publication_blockers"]["infrastructure_failure_total"] == 1
    assert result["publishable"] is False


def test_denominator_is_not_controlled_by_contract() -> None:
    module = load_module()
    contract = module.load_json(
        ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json"
    )
    contract = deepcopy(contract)
    contract["declared_denominator"] = 1
    with pytest.raises(ValueError, match="declared denominator must be 500"):
        module.summarize(
            contract=contract,
            tasks=tasks(),
            formal_results=ROOT / "does-not-exist",
            qualification_root=ROOT
            / contract["preserved_qualification"]["evidence_path"],
        )


def test_duplicate_instance_ids_are_rejected() -> None:
    module = load_module()
    contract = module.load_json(
        ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json"
    )
    task_rows = tasks()
    task_rows[-1]["instance_id"] = task_rows[-2]["instance_id"]
    with pytest.raises(ValueError, match="instance IDs must be unique"):
        module.summarize(
            contract=contract,
            tasks=task_rows,
            formal_results=ROOT / "does-not-exist",
            qualification_root=ROOT
            / contract["preserved_qualification"]["evidence_path"],
        )


def test_task_pool_hash_is_verified_before_parsing(tmp_path: Path) -> None:
    module = load_module()
    task_pool = tmp_path / "ordered-tasks.jsonl"
    task_pool.write_text('{"instance_id":"wrong"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="task pool hash mismatch"):
        module.load_task_pool(task_pool, "0" * 64)


def test_declared_compatible_grader_hash_is_accepted(tmp_path: Path) -> None:
    module = load_module()
    contract = module.load_json(
        ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json"
    )
    old_hash = contract["grader"]["compatible_harness_sha256s"][0]
    task_rows = tasks()
    instance_id = task_rows[1]["instance_id"]
    result_dir = tmp_path / instance_id
    result_dir.mkdir()
    (result_dir / "grader-terminal.json").write_text(
        json.dumps(
            {
                "instance_id": instance_id,
                "execution_id": contract["execution_id"],
                "grader_harness_sha256": old_hash,
                "status": "resolved",
            }
        ),
        encoding="utf-8",
    )
    result = module.summarize(
        contract=contract,
        tasks=task_rows,
        formal_results=tmp_path,
        qualification_root=ROOT / contract["preserved_qualification"]["evidence_path"],
    )
    assert instance_id not in result["invalid_formal_instances"]
    assert result["formal_status_counts"] == {"resolved": 1}
