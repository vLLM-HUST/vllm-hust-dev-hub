import json
from pathlib import Path

import pyarrow as pa
from pyarrow import parquet

from scripts.evaluation_machine.prepare_suzhou_yunneng_opencode_dataset import build

CONFIG = Path("config/suzhou-yunneng-opencode-oss-issue-workload.json")


def test_suzhou_yunneng_opencode_contract_freezes_tool_and_source() -> None:
    contract = json.loads(CONFIG.read_text())
    assert contract["owner_and_producer"] == "中国移动苏州（苏州云能）"
    assert contract["purpose"] == "production_optimization"
    assert contract["task_source"]["records"] == 500
    assert contract["collector"]["version"] == "1.18.19"
    assert contract["collector"]["platform"] == "linux-arm64"
    assert contract["execution"]["status"] == "SINGLE_CASE_QUALIFICATION_PASSED_BATCH_NOT_STARTED"
    assert contract["execution"]["collection_model"].startswith("Qwen3.5-35B-A3B@")
    assert contract["execution"]["qualification"]["attempted"] == 1
    assert contract["execution"]["qualification"]["resolved"] == 1
    assert contract["trace_contract"]["gold_patch_visible_to_agent"] is False
    assert contract["trace_contract"]["retain_all_attempts"] is True


def test_task_builder_orders_cases_and_hides_gold_from_agent_input(
    tmp_path: Path,
) -> None:
    rows = []
    for suffix in ("2", "1"):
        rows.append(
            {
                "repo": "example/repo",
                "instance_id": f"example__repo-{suffix}",
                "base_commit": "a" * 40,
                "patch": f"SECRET_GOLD_{suffix}",
                "test_patch": f"SECRET_TEST_{suffix}",
                "problem_statement": f"Fix behavior {suffix}",
                "hints_text": "",
                "created_at": "2026-01-01",
                "version": "1.0",
                "FAIL_TO_PASS": "[]",
                "PASS_TO_PASS": "[]",
                "environment_setup_commit": "b" * 40,
                "difficulty": "easy",
            }
        )
    source = tmp_path / "tasks.parquet"
    parquet.write_table(pa.Table.from_pylist(rows), source)
    output = tmp_path / "out"
    result = build(source, output)

    tasks = [json.loads(line) for line in (output / "ordered-tasks.jsonl").read_text().splitlines()]
    assert result["task_count"] == 2
    assert [task["case_key"] for task in tasks] == sorted(
        task["case_key"] for task in tasks
    )
    task_text = (output / "ordered-tasks.jsonl").read_text()
    assert "SECRET_GOLD" not in task_text
    assert "SECRET_TEST" not in task_text
    assert all("Do not look up or reconstruct the reference patch" in task["opencode_prompt"] for task in tasks)
