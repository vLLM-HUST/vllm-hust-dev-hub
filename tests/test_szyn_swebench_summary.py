from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
