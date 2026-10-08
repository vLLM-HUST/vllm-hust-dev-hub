"""Check controller custody and failure cleanup without launching a server."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

spec = importlib.util.spec_from_file_location(
    "windows", Path(__file__).with_name("run_windows.py")
)
windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(windows)


def test_identity_mismatch_never_stops_other_server(tmp_path):
    args = SimpleNamespace(output="run", program="native", pid=4242)
    with (
        patch.object(windows, "ROOT", tmp_path),
        patch.object(windows.os, "chdir"),
        patch.object(windows.subprocess, "check_output", return_value="9001"),
        patch.object(windows.subprocess, "run") as stop,
    ):
        with pytest.raises(RuntimeError, match="identity mismatch"):
            windows.main(args)
        stop.assert_not_called()


def test_failed_gate_releases_owned_server_without_traffic(tmp_path):
    gate = tmp_path / "gate"
    gate.mkdir()
    (gate / "summary.json").write_text(json.dumps({"passed": False}))
    args = SimpleNamespace(output="run", program="native", pid=4242, retrieval="gate")

    def path(value):
        if str(value) == "/proc/4242/cmdline":
            return Mock(read_bytes=lambda: f"{tmp_path}/.venv/bin/vllm\0serve".encode())
        return Path(value)

    with (
        patch.object(windows, "ROOT", tmp_path),
        patch.object(windows, "Path", side_effect=path),
        patch.object(windows.os, "chdir"),
        patch.object(windows.signal, "signal"),
        patch.object(windows.subprocess, "check_output", return_value="4242"),
        patch.object(windows.subprocess, "Popen") as client,
        patch.object(
            windows.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="stopped"),
        ) as stop,
        patch.object(windows, "device_owners", return_value=[]),
    ):
        with pytest.raises(RuntimeError, match="Retrieval qualification failed"):
            windows.main(args)
        client.assert_not_called()
        assert stop.call_args.args[0][-2:] == ["stop", "native"]
    status = json.loads((tmp_path / "run/status.json").read_text())
    assert not status["passed"]
    assert status["release"]["released"]
