import json
import grp
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .doctor import collect_report


GROUP_MEMBERSHIP_REQUIRED_EXIT_CODE = 32
SUDO_INTERACTION_REQUIRED_EXIT_CODE = 33


def _user_in_group(group_name: str) -> bool:
    try:
        target_gid = grp.getgrnam(group_name).gr_gid
    except KeyError:
        return False

    if os.getgid() == target_gid:
        return True

    return target_gid in os.getgroups()


def _run_shell(
    cmd: str,
    use_sudo: bool = False,
    requires_group: str | None = None,
    non_interactive: bool = False,
) -> int:
    shell_cmd = cmd
    if requires_group and not _user_in_group(requires_group):
        if non_interactive or not sys.stdin.isatty():
            print(
                f"[setup] current user is not in required group '{requires_group}'. "
                "Refusing to enter an interactive 'sg' password prompt in non-interactive mode."
            )
            print(
                f"[setup] add the user to '{requires_group}' and re-login, "
                "or run hust-ascend-manager setup manually from an interactive shell after switching groups."
            )
            return GROUP_MEMBERSHIP_REQUIRED_EXIT_CODE
        shell_cmd = f"sg {shlex.quote(requires_group)} -c {shlex.quote(shell_cmd)}"

    if use_sudo:
        if non_interactive or not sys.stdin.isatty():
            shell_cmd = f"sudo -n {shell_cmd}"
        else:
            shell_cmd = f"sudo {shell_cmd}"

    proc = subprocess.run(["bash", "-lc", shell_cmd])
    if proc.returncode != 0 and use_sudo and (non_interactive or not sys.stdin.isatty()):
        print("[setup] sudo authentication is required for a system step, but non-interactive mode is enabled.")
        return SUDO_INTERACTION_REQUIRED_EXIT_CODE
    return proc.returncode


def _pip_install(specs: list[str]) -> int:
    if not specs:
        return 0
    cmd = ["python", "-m", "pip", "install", "--upgrade", *specs]
    return subprocess.run(cmd).returncode


def _ensure_conda_env_metadata() -> None:
    conda_prefix = os.getenv("CONDA_PREFIX")
    if not conda_prefix:
        return

    prefix_path = Path(conda_prefix)
    conda_meta = prefix_path / "conda-meta"
    if not conda_meta.exists():
        return

    history = conda_meta / "history"
    if not history.exists():
        history.touch()


def load_manifest(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def setup_environment(
    manifest_path: str | None,
    apply_system: bool,
    install_python_stack: bool,
    dry_run: bool,
    non_interactive: bool = False,
) -> int:
    _ensure_conda_env_metadata()

    report = collect_report()
    manifest = load_manifest(manifest_path)

    target = manifest.get("python_stack", {}) if isinstance(manifest, dict) else {}
    target_torch = target.get("torch", "2.9.0")
    target_torch_npu = target.get("torch_npu", "2.9.0")

    print("[setup] start")
    print(f"[setup] manifest: {manifest_path or '<none>'}")

    if install_python_stack:
        current = report["python_stack"]
        specs: list[str] = []
        if current.get("torch") != target_torch:
            specs.append(f"torch=={target_torch}")
        if current.get("torch_npu") != target_torch_npu:
            specs.append(f"torch-npu=={target_torch_npu}")

        if specs:
            print(f"[setup] python stack reconcile needed: {specs}")
            if not dry_run:
                rc = _pip_install(specs)
                if rc != 0:
                    print("[setup] python stack install failed")
                    return rc
        else:
            print("[setup] python stack already aligned")

    steps = manifest.get("system_steps", []) if isinstance(manifest, dict) else []
    if steps:
        print(f"[setup] loaded {len(steps)} system steps")
    for step in steps:
        desc = step.get("description", step.get("id", "unnamed-step"))
        cmd = step.get("run")
        use_sudo = bool(step.get("requires_sudo", False))
        requires_group = step.get("requires_group")
        if not cmd:
            continue
        if not apply_system:
            print(f"[setup][plan] {desc}: {cmd}")
            continue
        print(f"[setup][run] {desc}")
        if requires_group:
            print(f"[setup][run] requires group: {requires_group}")
        if dry_run:
            continue
        rc = _run_shell(
            cmd,
            use_sudo=use_sudo,
            requires_group=requires_group,
            non_interactive=non_interactive,
        )
        if rc != 0:
            print(f"[setup] failed step: {desc}")
            return rc

    print("[setup] done")
    return 0
