import os
import shlex
import subprocess
from pathlib import Path

from .doctor import build_shell_env_exports, collect_report
from .setup import setup_environment


def _append_once(args: list[str], value: str) -> None:
    if value not in args:
        args.append(value)


def _apply_prefill_compat_args(
    extra_args: list[str],
    enable_prefill_compat_mode: bool,
) -> list[str]:
    cleaned_extra = list(extra_args)
    if cleaned_extra and cleaned_extra[0] == "--":
        cleaned_extra = cleaned_extra[1:]

    if not enable_prefill_compat_mode:
        return cleaned_extra

    user_controls_prefill = any(
        arg in cleaned_extra
        for arg in (
            "--enable-prefix-caching",
            "--no-enable-prefix-caching",
            "--enable-chunked-prefill",
            "--no-enable-chunked-prefill",
        )
    )
    if user_controls_prefill:
        return cleaned_extra

    _append_once(cleaned_extra, "--no-enable-prefix-caching")
    _append_once(cleaned_extra, "--no-enable-chunked-prefill")
    return cleaned_extra


def _resolve_local_snapshot(model_ref: str) -> str:
    p = Path(model_ref)
    if p.is_dir():
        return str(p)

    if "/" not in model_ref:
        return model_ref

    org, model = model_ref.split("/", 1)
    snapshot_root = Path.home() / ".cache/huggingface/hub" / f"models--{org}--{model}" / "snapshots"
    if snapshot_root.is_dir():
        snapshots = sorted([x for x in snapshot_root.iterdir() if x.is_dir()])
        if snapshots:
            return str(snapshots[-1])
    return model_ref


def _served_model_name(model_ref: str) -> str:
    base = Path(model_ref).name
    cleaned = "".join(ch if (ch.isalnum() or ch in ".-") else "-" for ch in base.replace("/", "-").replace("_", "-"))
    return cleaned or "model"


def launch_vllm(
    model_ref: str,
    manifest_path: str | None,
    apply_system: bool,
    install_python_stack: bool,
    skip_setup: bool,
    host: str,
    port: int,
    served_model_name: str | None,
    enable_prefill_compat_mode: bool,
    non_interactive: bool,
    extra_args: list[str],
) -> int:
    if not skip_setup:
        rc = setup_environment(
            manifest_path=manifest_path,
            apply_system=apply_system,
            install_python_stack=install_python_stack,
            dry_run=False,
            non_interactive=non_interactive,
        )
        if rc != 0:
            return rc

    exports = build_shell_env_exports()
    report = collect_report()
    npugraph_ready = bool(report["ascend"]["has_aclrt_set_stream_attribute"])

    resolved_model = _resolve_local_snapshot(model_ref)
    run_offline = Path(resolved_model).is_dir()

    args = [
        "vllm",
        "serve",
        resolved_model,
        "--host",
        host,
        "--port",
        str(port),
        "--trust-remote-code",
        "--served-model-name",
        served_model_name or _served_model_name(model_ref),
    ]

    cleaned_extra = _apply_prefill_compat_args(
        extra_args,
        enable_prefill_compat_mode=enable_prefill_compat_mode,
    )

    if not npugraph_ready and "--enforce-eager" not in cleaned_extra:
        args.append("--enforce-eager")

    args.extend(cleaned_extra)

    shell_lines = [exports]
    if run_offline:
        shell_lines.append("export HF_HUB_OFFLINE=1")
        shell_lines.append("export TRANSFORMERS_OFFLINE=1")
    shell_lines.append("export VLLM_PLUGINS=${VLLM_PLUGINS:-ascend}")
    shell_lines.append("if [[ -n \"${HUST_ATB_SET_ENV:-}\" && -f \"${HUST_ATB_SET_ENV}\" ]]; then set +u; source \"${HUST_ATB_SET_ENV}\" --cxx_abi=1; set -u; fi")
    shell_lines.append("exec " + " ".join(shlex.quote(x) for x in args))

    return subprocess.run(["bash", "-lc", "\n".join(shell_lines)]).returncode
