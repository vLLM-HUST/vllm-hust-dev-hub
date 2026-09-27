from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


REPO_ROOT = Path(__file__).parents[1]
SCRIPTS = (
    REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh",
    REPO_ROOT / "scripts" / "cleanup_vllm_hust_engine.sh",
)
CLEANUP_SCRIPT = SCRIPTS[1]


def _run_cleanup(
    *, info_rc: int = 0, inspect_rc: int = 0, running: str = "true", exec_rc: int = 0
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        docker = root / "docker"
        sudo = root / "sudo"
        docker.write_text(
            """#!/usr/bin/env bash
case "$1" in
  info) exit "${FAKE_INFO_RC}" ;;
  inspect)
    if [[ "${FAKE_INSPECT_RC}" != 0 ]]; then exit "${FAKE_INSPECT_RC}"; fi
    printf '%s\\n' "${FAKE_RUNNING}"
    ;;
  exec)
    if [[ "${FAKE_EXEC_RC}" == 0 ]]; then printf '%s\\n' '123 456'; fi
    exit "${FAKE_EXEC_RC}"
    ;;
  *) exit 64 ;;
esac
"""
        )
        sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n')
        docker.chmod(0o755)
        sudo.chmod(0o755)
        env = os.environ.copy()
        env.update(
            {
                "DOCKER_BIN": str(docker),
                "VLLM_ENGINE_DOCKER_SUDO": str(sudo),
                "VLLM_ENGINE_CONTAINER_NAME": "fixture-container",
                "VLLM_ENGINE_PORT": "8123",
                "FAKE_INFO_RC": str(info_rc),
                "FAKE_INSPECT_RC": str(inspect_rc),
                "FAKE_RUNNING": running,
                "FAKE_EXEC_RC": str(exec_rc),
            }
        )
        return subprocess.run(
            [str(CLEANUP_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


def test_in_progress_launcher_cleanup_is_scoped_to_requested_port() -> None:
    for script in SCRIPTS:
        source = script.read_text()
        assert 'grep -Fq -- "--port \\"$port\\"" "$launcher_script"' in source
        assert "launcher_script=${launcher_args#bash }" in source


def test_cleanup_no_longer_collects_every_in_progress_launcher() -> None:
    unconditional_filter = """/bash \\/tmp\\/vllm-hust-engine\\.[A-Za-z0-9]+\\.sh/ {
      print $1
    }"""
    for script in SCRIPTS:
        assert unconditional_filter not in script.read_text()


def test_cleanup_uses_bounded_term_kill_and_survivor_verification() -> None:
    source = CLEANUP_SCRIPT.read_text()

    assert "kill -TERM $initial" in source
    assert 'wait_for_exit "$term_attempts"' in source
    assert "kill -KILL $survivors" in source
    assert 'wait_for_exit "$kill_attempts"' in source
    assert "remain after SIGKILL" in source


def test_missing_or_stopped_container_is_idempotent_success() -> None:
    assert _run_cleanup(inspect_rc=1).returncode == 0
    assert _run_cleanup(running="false").returncode == 0


def test_docker_or_container_exec_failure_is_not_hidden() -> None:
    daemon_failure = _run_cleanup(info_rc=1)
    assert daemon_failure.returncode != 0
    assert "cannot contact" in daemon_failure.stderr

    exec_failure = _run_cleanup(exec_rc=17)
    assert exec_failure.returncode != 0
    assert "container vLLM cleanup failed" in exec_failure.stderr


def test_successful_cleanup_reports_scoped_processes() -> None:
    result = _run_cleanup()

    assert result.returncode == 0
    assert "on port 8123: 123 456" in result.stdout
