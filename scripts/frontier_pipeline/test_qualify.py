import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(tmp_path, monkeypatch):
    path = Path(__file__).with_name("qualify.py")
    spec = importlib.util.spec_from_file_location("pp_qualify", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "receipts").mkdir()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    monkeypatch.chdir(tmp_path)
    return module


def test_preflight_refusal_never_starts_or_stops_a_server(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)

    def refuse():
        raise RuntimeError("Participating devices are busy")

    def unexpected(*args, **kwargs):
        pytest.fail("No supervisor mutation is allowed after a preflight refusal")

    monkeypatch.setattr(module, "preflight", refuse)
    monkeypatch.setattr(module.subprocess, "run", unexpected)
    with pytest.raises(RuntimeError, match="devices are busy"):
        module.main(SimpleNamespace(attempt="busy"))
    state = json.loads((tmp_path / "receipts/busy/status.json").read_text())
    assert state["passed"] is False
    assert "release" not in state
    assert (tmp_path / "receipts/busy/FAILED.txt").is_file()


def test_partial_start_failure_still_stops_exact_owned_program(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(module, "preflight", lambda: None)
    monkeypatch.setattr(module, "owners", lambda: [])

    def supervisor(command, **kwargs):
        calls.append(command[-2:])
        if command[-2] == "start":
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", supervisor)
    with pytest.raises(subprocess.CalledProcessError):
        module.main(SimpleNamespace(attempt="startup-failed"))
    assert calls == [["start", "nativepp"], ["stop", "nativepp"]]
    state = json.loads((tmp_path / "receipts/startup-failed/status.json").read_text())
    assert state["passed"] is False
    assert state["release"] == {"exit": 0, "owners": []}


def test_measurement_refuses_debug_launcher_before_start(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "preflight", lambda: None)
    (tmp_path / "launch-nativepp.sh").write_text(
        "vllm --worker-cls debug_worker.Worker"
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Diagnostic launcher cannot start for a performance claim")

    monkeypatch.setattr(module.subprocess, "run", unexpected)
    args = SimpleNamespace(
        attempt="bad-measure",
        program="nativepp",
        measure=True,
        qualification_only=False,
        metadata="metadata.json",
    )
    with pytest.raises(ValueError, match="cannot measure"):
        module.main(args)
    assert (tmp_path / "receipts/bad-measure/FAILED.txt").exists()


def test_owned_launcher_can_finish_environment_setup(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    commands = iter(
        [
            f"/bin/bash\0{tmp_path}/launch-nativepp.sh\0".encode(),
            f"/python\0{module.BASE}/.venv/bin/vllm\0serve\0".encode(),
        ]
    )
    monkeypatch.setattr(Path, "read_bytes", lambda p: next(commands))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    assert "vllm serve" in module.server_command(123, "nativepp")


def test_unrelated_launcher_is_rejected_immediately(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    monkeypatch.setattr(Path, "read_bytes", lambda p: b"/bin/bash\0/other/launch.sh\0")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        module.server_command(123, "nativepp")


def test_owned_launcher_deadline_is_bounded(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda p: f"/bin/bash\0{tmp_path}/launch-nativepp.sh\0".encode(),
    )
    ticks = iter([0, 31])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError, match="30 seconds"):
        module.server_command(123, "nativepp")
