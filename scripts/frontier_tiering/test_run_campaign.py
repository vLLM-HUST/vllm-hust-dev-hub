"""Ensure a failed software gate or partial start cannot advance the campaign."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(tmp_path, monkeypatch):
    root = Path(__file__).parent
    for name, filename in (
        ("qualify", "qualify.py"),
        ("tiering_campaign", "run_campaign.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, root / filename)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    (tmp_path / "receipts").mkdir()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "verify_parent", lambda: None)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    gate = tmp_path.parent / "serving-r2/receipts/tiering-qualify-r1/status.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(
        json.dumps(
            {"stage": "completed", "passed": True, "release": {"exit": 0, "owners": []}}
        )
    )
    return module


def test_incomplete_runtime_tests_never_start(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"software_tests_passed": False})
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: pytest.fail("must not start")
    )
    with pytest.raises(RuntimeError, match="integration tests"):
        module.main()
    assert (
        json.loads((tmp_path / "receipts/matched-curves-r1/status.json").read_text())[
            "passed"
        ]
        is False
    )


def test_failed_native_start_is_stopped_without_candidate(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    (tmp_path / "manifest.json").write_text(json.dumps({"software_tests_passed": True}))
    monkeypatch.setattr(module, "owners", lambda: [])
    monkeypatch.setattr(module, "controller_pid", lambda _: 0)
    calls = []

    def run(command, **kwargs):
        calls.append(command[-2:])
        if command[-2] == "start":
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        module.main()
    assert calls == [["start", "measure-native"], ["stop", "measure-native"]]


def test_failed_candidate_qualification_never_starts_measurements(
    tmp_path, monkeypatch
):
    module = load(tmp_path, monkeypatch)
    gate = tmp_path.parent / "serving-r2/receipts/tiering-qualify-r1/status.json"
    gate.write_text(
        json.dumps(
            {"stage": "failed", "passed": False, "release": {"exit": 0, "owners": []}}
        )
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: pytest.fail("must not start")
    )
    with pytest.raises(RuntimeError, match="qualification did not pass"):
        module.main()
