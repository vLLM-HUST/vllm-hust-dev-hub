from __future__ import annotations

from unittest.mock import patch

from hust_ascend_manager import launch
from hust_ascend_manager.launch import _apply_prefill_compat_args


def test_apply_prefill_compat_args_appends_safe_defaults():
    args = _apply_prefill_compat_args([], enable_prefill_compat_mode=True)

    assert "--no-enable-prefix-caching" in args
    assert "--no-enable-chunked-prefill" in args


def test_apply_prefill_compat_args_respects_user_prefill_flags():
    args = _apply_prefill_compat_args(
        ["--enable-prefix-caching", "--no-enable-chunked-prefill"],
        enable_prefill_compat_mode=True,
    )

    assert args == ["--enable-prefix-caching", "--no-enable-chunked-prefill"]


def test_apply_prefill_compat_args_can_be_disabled():
    args = _apply_prefill_compat_args([], enable_prefill_compat_mode=False)

    assert args == []


def test_launch_passes_noninteractive_to_setup(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    fake_report = {"ascend": {"has_aclrt_set_stream_attribute": False}}

    with (
        patch("hust_ascend_manager.launch.setup_environment", return_value=0) as setup_mock,
        patch("hust_ascend_manager.launch.build_shell_env_exports", return_value="export FOO=bar"),
        patch("hust_ascend_manager.launch.collect_report", return_value=fake_report),
        patch("hust_ascend_manager.launch.subprocess.run") as run_mock,
    ):
        run_mock.return_value.returncode = 0
        rc = launch.launch_vllm(
            model_ref=str(model_dir),
            manifest_path="manifest.json",
            apply_system=True,
            install_python_stack=True,
            skip_setup=False,
            host="0.0.0.0",
            port=8000,
            served_model_name=None,
            enable_prefill_compat_mode=True,
            non_interactive=True,
            extra_args=[],
        )

    assert rc == 0
    assert setup_mock.call_args.kwargs["non_interactive"] is True
