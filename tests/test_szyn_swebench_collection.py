from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluation_machine" / "run_szyn_swebench_collection.py"


def load_module():
    spec = importlib.util.spec_from_file_location("szyn_collection", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execution_contract_freezes_denominator_and_runtime() -> None:
    contract = json.loads(
        (ROOT / "config" / "szyn-swebench-qwen35-execution-v3.json").read_text()
    )
    assert contract["declared_denominator"] == 500
    assert contract["preserved_qualification_instance"] is None
    assert contract["collector"]["automatic_agent_retries"] == 0
    assert contract["model"]["thinking"] is False
    assert contract["sandbox"]["process_uid_base"] == 65000
    assert contract["sandbox"]["process_uid_count"] == 4
    assert contract["sandbox"]["host_root_credentials_readable"] is False
    assert contract["sandbox"]["reference_tree_agent_readable"] is False
    assert contract["runtime"]["vllm_commit"] == (
        "0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665"
    )


def test_session_id_ignores_non_json_lines(tmp_path: Path) -> None:
    module = load_module()
    events = tmp_path / "events.jsonl"
    events.write_text(
        'not json\n{"type":"step_start","sessionID":"session-1"}\n',
        encoding="utf-8",
    )
    assert module.session_id_from_events(events) == "session-1"


def test_atomic_json_replaces_partial_output(tmp_path: Path) -> None:
    module = load_module()
    output = tmp_path / "terminal.json"
    module.atomic_json(output, {"status": "complete"})
    assert json.loads(output.read_text()) == {"status": "complete"}
    assert not output.with_suffix(".json.tmp").exists()


def test_create_patch_uses_repository_relative_paths(tmp_path: Path) -> None:
    module = load_module()
    pristine = tmp_path / "root-only-reference" / "pristine"
    case = tmp_path / "agent-work" / "case"
    pristine.mkdir(parents=True)
    case.mkdir(parents=True)
    (pristine / "module.py").write_text("old\n", encoding="utf-8")
    (case / "module.py").write_text("new\n", encoding="utf-8")
    (case / ".git").mkdir()
    (case / ".git" / "index").write_bytes(b"generated")
    output = tmp_path / "agent.patch"

    assert module.create_patch(pristine, case, output) == 1
    patch = output.read_text(encoding="utf-8")
    assert "diff --git a/module.py b/module.py" in patch
    assert "a/pristine/" not in patch
    assert "b/case/" not in patch
    assert "/.git/" not in patch


def test_sandbox_command_drops_root_identity() -> None:
    module = load_module()
    assert module.sandbox_command(["id"], 65534, 65534) == [
        "setpriv",
        "--reuid=65534",
        "--regid=65534",
        "--clear-groups",
        "--",
        "id",
    ]


def test_reference_tree_is_inaccessible_to_agent_uid(tmp_path: Path) -> None:
    module = load_module()
    reference = tmp_path / "pristine"
    reference.mkdir(mode=0o755)
    sentinel = reference / "sentinel.py"
    sentinel.write_text("frozen base\n", encoding="utf-8")

    module.seal_reference_tree(reference)

    assert stat.S_IMODE(reference.stat().st_mode) == 0o700
    if os.geteuid() != 0:
        pytest.skip("setpriv identity assertion requires root")
    completed = subprocess.run(
        module.sandbox_command(["test", "-r", str(sentinel)], 65534, 65534),
        check=False,
    )
    assert completed.returncode != 0


def test_reference_tree_is_outside_agent_workspace_hierarchy(tmp_path: Path) -> None:
    module = load_module()
    work_root = tmp_path / "agent-work"
    reference_root = tmp_path / "root-only-reference"

    temporary, reference_temporary = module.create_task_roots(
        work_root, reference_root, "example-task"
    )
    pristine = reference_temporary / "pristine"
    pristine.mkdir()
    module.seal_reference_tree(pristine)

    assert temporary.parent == work_root
    assert reference_temporary.parent == reference_root
    assert reference_root not in temporary.parents
    assert "pristine" not in {path.name for path in temporary.iterdir()}
    assert stat.S_IMODE(reference_root.stat().st_mode) == 0o700
