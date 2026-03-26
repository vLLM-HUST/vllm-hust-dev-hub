from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from hust_ascend_manager.container import ContainerConfig
from hust_ascend_manager.container import build_container_ssh_setup_command
from hust_ascend_manager.container import build_volume_args
from hust_ascend_manager.container import container_has_expected_startup
from hust_ascend_manager.container import container_bootstrap_snippet
from hust_ascend_manager.container import container_runtime_script_path
from hust_ascend_manager.container import default_authorized_keys_source
from hust_ascend_manager.container import desired_container_cmd
from hust_ascend_manager.container import discover_device_args
from hust_ascend_manager.container import enable_container_ssh
from hust_ascend_manager.container import install_container
from hust_ascend_manager.container import parse_ssh_enable_options
from hust_ascend_manager.container import run_container_action


def test_build_volume_args_includes_workspace_and_cache(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    cache_dir = tmp_path / "cache"
    workspace_root.mkdir()
    cache_dir.mkdir()

    config = ContainerConfig(
        host_workspace_root=str(workspace_root),
        container_workspace_root="/workspace",
        host_cache_dir=str(cache_dir),
    )

    args = build_volume_args(config)

    assert f"{workspace_root}:/workspace" in args
    assert f"{cache_dir}:/root/.cache" in args


def test_container_bootstrap_snippet_sources_ascend_env():
    config = ContainerConfig(container_workdir="/workspace/vllm-hust-dev-hub")

    snippet = container_bootstrap_snippet(config)

    assert "/usr/local/Ascend/ascend-toolkit/set_env.sh" in snippet
    assert "/usr/local/Ascend/nnal/atb/set_env.sh" in snippet
    assert "cd /workspace/vllm-hust-dev-hub" in snippet


def test_default_authorized_keys_source_uses_workspace_root():
    config = ContainerConfig(container_workspace_root="/workspace")

    assert default_authorized_keys_source(config) == "/workspace/.ssh/authorized_keys"


def test_container_runtime_script_path_uses_repo_scripts_dir():
    config = ContainerConfig(container_workdir="/workspace/vllm-hust-dev-hub")

    assert container_runtime_script_path(config) == "/workspace/vllm-hust-dev-hub/scripts/ascend-container-runtime.sh"


def test_desired_container_cmd_uses_runtime_script():
    config = ContainerConfig(container_workdir="/workspace/vllm-hust-dev-hub")

    assert desired_container_cmd(config) == [
        "bash",
        "-lc",
        "bash /workspace/vllm-hust-dev-hub/scripts/ascend-container-runtime.sh",
    ]


def test_container_has_expected_startup_matches_inspected_cmd(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root), container_workdir="/workspace/vllm-hust-dev-hub")

    inspect_cmd = Mock(returncode=0, stdout='["bash", "-lc", "bash /workspace/vllm-hust-dev-hub/scripts/ascend-container-runtime.sh"]', stderr="")
    with patch("hust_ascend_manager.container.docker_capture", return_value=inspect_cmd):
        assert container_has_expected_startup(["docker"], config) is True


def test_build_container_ssh_setup_command_contains_expected_settings():
    config = ContainerConfig(container_workspace_root="/workspace")

    command = build_container_ssh_setup_command(
        config=config,
        ssh_user="shuhao",
        ssh_port=2222,
        authorized_keys_source="/workspace/.ssh/authorized_keys",
    )

    assert "apt-get install -y openssh-server" in command
    assert "Port $SSH_PORT" in command
    assert "AllowUsers $SSH_USER" in command
    assert "/workspace/.ssh/authorized_keys" in command


def test_discover_device_args_includes_special_devices(tmp_path: Path):
    fake_devices = [
        tmp_path / "davinci0",
        tmp_path / "davinci1",
        tmp_path / "davinci_manager",
        tmp_path / "devmm_svm",
        tmp_path / "hisi_hdc",
    ]
    for path in fake_devices:
        path.touch()

    with patch("hust_ascend_manager.container.Path.glob", return_value=[fake_devices[0], fake_devices[1]]), patch(
        "hust_ascend_manager.container.Path.exists",
        autospec=True,
        return_value=True,
    ):
        args = discover_device_args()

    assert args == [
        "--device",
        str(fake_devices[0]),
        "--device",
        str(fake_devices[1]),
        "--device",
        "/dev/davinci_manager",
        "--device",
        "/dev/devmm_svm",
        "--device",
        "/dev/hisi_hdc",
    ]


def test_install_container_creates_container_when_missing(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    cache_dir = tmp_path / "cache"
    workspace_root.mkdir()

    config = ContainerConfig(
        image="image:latest",
        container_name="demo",
        host_workspace_root=str(workspace_root),
        container_workdir="/workspace/demo",
        host_cache_dir=str(cache_dir),
    )

    inspect_missing = Mock(returncode=1, stdout="", stderr="")
    image_present = Mock(returncode=0, stdout="", stderr="")
    run_success = Mock(returncode=0)

    with (
        patch("hust_ascend_manager.container.docker_capture", side_effect=[image_present, inspect_missing]),
        patch("hust_ascend_manager.container.discover_device_args", return_value=["--device", "/dev/davinci0"]),
        patch("hust_ascend_manager.container.run_docker", return_value=run_success) as run_mock,
    ):
        rc = install_container(["docker"], config)

    assert rc == 0
    docker_args = run_mock.call_args.args[1]
    assert docker_args[:2] == ["run", "-d"]
    assert "demo" in docker_args
    assert "image:latest" in docker_args
    assert docker_args[-3:] == ["bash", "-lc", "bash /workspace/demo/scripts/ascend-container-runtime.sh"]


def test_install_container_recreates_legacy_container_when_bootstrap_required(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(
        image="image:latest",
        container_name="demo",
        host_workspace_root=str(workspace_root),
        container_workdir="/workspace/demo",
    )

    with (
        patch("hust_ascend_manager.container.ensure_image_present", return_value=0),
        patch("hust_ascend_manager.container.container_exists", return_value=True),
        patch("hust_ascend_manager.container.ensure_container_image_matches", return_value=0),
        patch("hust_ascend_manager.container.container_has_expected_startup", return_value=False),
        patch("hust_ascend_manager.container.container_running", return_value=True),
        patch("hust_ascend_manager.container.discover_device_args", return_value=["--device", "/dev/davinci0"]),
        patch("hust_ascend_manager.container.run_docker", return_value=Mock(returncode=0)) as run_mock,
    ):
        rc = install_container(["docker"], config, require_runtime_bootstrap=True)

    assert rc == 0
    assert run_mock.call_args_list[0].args[1] == ["stop", "demo"]
    assert run_mock.call_args_list[1].args[1] == ["rm", "demo"]
    assert run_mock.call_args_list[2].args[1][0:2] == ["run", "-d"]


def test_enable_container_ssh_runs_setup_inside_container(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.install_container", return_value=0) as install_mock,
        patch("hust_ascend_manager.container.exec_container_shell", return_value=0) as exec_mock,
    ):
        rc = enable_container_ssh(
            ["docker"],
            config,
            ssh_user="shuhao",
            ssh_port=2222,
            authorized_keys_source="/workspace/.ssh/authorized_keys",
        )

    assert rc == 0
    assert install_mock.call_args.kwargs["require_runtime_bootstrap"] is True
    assert "openssh-server" in exec_mock.call_args.args[2]


def test_parse_ssh_enable_options_uses_defaults():
    parsed = parse_ssh_enable_options([])

    assert parsed == ("shuhao", 2222, None)


def test_parse_ssh_enable_options_parses_custom_values():
    parsed = parse_ssh_enable_options(["--ssh-user", "alice", "--ssh-port", "22022", "--authorized-keys-source", "/workspace/.ssh/authorized_keys"])

    assert parsed == ("alice", 22022, "/workspace/.ssh/authorized_keys")


def test_run_container_action_ssh_enable_forwards_custom_options(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.resolve_docker_command", return_value=["docker"]),
        patch("hust_ascend_manager.container.enable_container_ssh", return_value=0) as enable_mock,
    ):
        rc = run_container_action(
            "ssh-enable",
            config,
            command=["--ssh-user", "shuhao", "--ssh-port", "22022", "--authorized-keys-source", "/workspace/.ssh/authorized_keys"],
        )

    assert rc == 0
    assert enable_mock.call_args.kwargs["ssh_user"] == "shuhao"
    assert enable_mock.call_args.kwargs["ssh_port"] == 22022
    assert enable_mock.call_args.kwargs["authorized_keys_source"] == "/workspace/.ssh/authorized_keys"


def test_run_container_action_ssh_deploy_forwards_custom_options(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.resolve_docker_command", return_value=["docker"]),
        patch("hust_ascend_manager.container.enable_container_ssh", return_value=0) as enable_mock,
    ):
        rc = run_container_action(
            "ssh-deploy",
            config,
            command=["--ssh-user", "shuhao", "--ssh-port", "22022"],
        )

    assert rc == 0
    assert enable_mock.call_args.kwargs["ssh_user"] == "shuhao"
    assert enable_mock.call_args.kwargs["ssh_port"] == 22022


def test_run_container_action_exec_forwards_command(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.resolve_docker_command", return_value=["docker"]),
        patch("hust_ascend_manager.container.exec_in_container", return_value=0) as exec_mock,
    ):
        rc = run_container_action("exec", config, command=["python", "-V"])

    assert rc == 0
    assert exec_mock.call_args.args[2] == ["python", "-V"]