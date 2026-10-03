from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
        (ROOT / "config" / "szyn-swebench-qwen35-execution-v1.json").read_text()
    )
    assert contract["declared_denominator"] == 500
    assert contract["preserved_qualification_instance"] == "django__django-15104"
    assert contract["collector"]["automatic_agent_retries"] == 0
    assert contract["model"]["thinking"] is False
    assert contract["sandbox"]["process_uid_base"] == 65000
    assert contract["sandbox"]["process_uid_count"] == 4
    assert contract["sandbox"]["host_root_credentials_readable"] is False
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
    pristine = tmp_path / "pristine"
    case = tmp_path / "case"
    pristine.mkdir()
    case.mkdir()
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
