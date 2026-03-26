from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

from hust_ascend_manager import setup


def test_setup_environment_continues_when_runtime_report_is_incomplete(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"python_stack": {"torch": "2.9.0", "torch_npu": "2.9.0"}}',
        encoding="utf-8",
    )

    report = {
        "python_stack": {
            "torch": None,
            "torch_npu": None,
        }
    }

    with (
        patch("hust_ascend_manager.setup.collect_report", return_value=report),
        patch("hust_ascend_manager.setup._pip_install", return_value=0) as pip_install,
    ):
        rc = setup.setup_environment(
            manifest_path=str(manifest),
            apply_system=False,
            install_python_stack=True,
            dry_run=False,
        )

    assert rc == 0
    pip_install.assert_called_once_with(["torch==2.9.0", "torch-npu==2.9.0"])


def test_run_shell_fails_fast_when_group_membership_is_missing_in_noninteractive_mode():
    with patch("hust_ascend_manager.setup._user_in_group", return_value=False):
        rc = setup._run_shell(
            "echo test",
            requires_group="HwHiAiUser",
            non_interactive=True,
        )

    assert rc == setup.GROUP_MEMBERSHIP_REQUIRED_EXIT_CODE


def test_run_shell_uses_sudo_n_in_noninteractive_mode():
    fake_proc = Mock(returncode=0)

    with patch("hust_ascend_manager.setup.subprocess.run", return_value=fake_proc) as run_mock:
        rc = setup._run_shell("echo test", use_sudo=True, non_interactive=True)

    assert rc == 0
    assert run_mock.call_args.args[0] == ["bash", "-lc", "sudo -n echo test"]