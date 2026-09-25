import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(tmp_path, monkeypatch):
    source = Path(__file__).with_name("run_pair.py")
    monkeypatch.syspath_prepend(str(source.parent))
    spec = importlib.util.spec_from_file_location("pp_run_pair", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "receipts/candidate-pass").mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "verify_parent", lambda: None)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    return module


def test_pair_rejects_failed_candidate_without_start(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    (tmp_path / "receipts/candidate-pass/status.json").write_text(
        json.dumps(dict(passed=False))
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not start")
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        module.main("candidate-pass")
    assert (tmp_path / "receipts/paired-measurement-r1/FAILED.txt").exists()


def test_pair_stops_partially_started_controller(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    (tmp_path / "receipts/candidate-pass/status.json").write_text(
        json.dumps(dict(passed=True, release=dict(exit=0, owners=[])))
    )
    monkeypatch.setattr(module, "owners", lambda: [])
    monkeypatch.setattr(module, "controller_pid", lambda program: 0)
    calls = []

    def run(command, **kwargs):
        calls.append(command[-2:])
        if command[-2] == "start":
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        module.main("candidate-pass")
    assert calls == [["start", "measure-nativepp"], ["stop", "measure-nativepp"]]


def test_supervisor_stopped_status_is_not_a_query_failure(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=7, stdout="0\n"),
    )
    assert module.controller_pid("measure-nativepp") == 0


def test_unknown_program_remains_an_error(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=7, stdout="ERROR: no such process"
        ),
    )
    with pytest.raises(RuntimeError, match="Cannot query"):
        module.controller_pid("wrong")
