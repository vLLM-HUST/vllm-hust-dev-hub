import argparse
import sys

from .container import ContainerConfig
from .container import DEFAULT_CONTAINER_NAME
from .container import DEFAULT_CONTAINER_WORKSPACE_ROOT
from .container import DEFAULT_IMAGE
from .container import DEFAULT_SHM_SIZE
from .container import run_container_action
from .doctor import build_shell_env_exports, collect_report, print_human, print_json
from .launch import launch_vllm
from .setup import setup_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hust-ascend-manager", description="Ascend runtime manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Collect runtime compatibility report")
    p_doctor.add_argument("--json", action="store_true", help="Output JSON format")

    p_setup = sub.add_parser("setup", help="Reconcile Ascend runtime dependencies")
    p_setup.add_argument("--manifest", default=None, help="Path to manager manifest JSON")
    p_setup.add_argument("--apply-system", action="store_true", help="Apply system-level install steps")
    p_setup.add_argument("--install-python-stack", action="store_true", help="Install torch/torch-npu from manifest targets")
    p_setup.add_argument("--dry-run", action="store_true", help="Plan only, do not execute")
    p_setup.add_argument("--non-interactive", action="store_true", help="Fail fast instead of prompting for sudo/sg passwords")

    p_env = sub.add_parser("env", help="Emit shell exports for a unified Ascend runtime")
    p_env.add_argument("--ascend-root", default=None, help="Explicit Ascend runtime root")
    p_env.add_argument("--shell", action="store_true", help="Emit shell export statements")

    p_launch = sub.add_parser("launch", help="Run vllm serve with manager-controlled Ascend env")
    p_launch.add_argument("model", help="Model ID or local model path")
    p_launch.add_argument("--manifest", default=None, help="Path to manager manifest JSON")
    p_launch.add_argument("--skip-setup", action="store_true", help="Skip manager setup step")
    p_launch.add_argument("--host", default="0.0.0.0", help="Host for vllm serve")
    p_launch.add_argument("--port", type=int, default=8000, help="Port for vllm serve")
    p_launch.add_argument("--served-model-name", default=None, help="Served model name")
    p_launch.add_argument("--install-python-stack", action="store_true", help="Install torch/torch-npu before launch")
    p_launch.add_argument("--apply-system", dest="apply_system", action="store_true", help="Apply system-level setup before launch")
    p_launch.add_argument("--no-apply-system", dest="apply_system", action="store_false", help="Skip system-level setup before launch")
    p_launch.add_argument("--non-interactive", action="store_true", help="Fail fast instead of prompting for sudo/sg passwords during setup")
    p_launch.add_argument(
        "--prefill-compat-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "By default, disable prefix caching and chunked prefill during "
            "Ascend launches to avoid known npu_fused_infer_attention_score "
            "dimension crashes on some models."
        ),
    )
    p_launch.set_defaults(apply_system=True)

    p_container = sub.add_parser("container", help="Manage the official Ascend vLLM container")
    p_container.add_argument(
        "action",
        choices=["install", "start", "shell", "exec", "ssh-enable", "ssh-deploy", "status", "stop", "rm", "pull"],
        help="Container action to run",
    )
    p_container.add_argument("--image", default=None, help="Container image to use")
    p_container.add_argument("--container-name", default=None, help="Persistent container name")
    p_container.add_argument(
        "--host-workspace-root",
        default=None,
        help="Host path to mount into the container workspace root",
    )
    p_container.add_argument(
        "--container-workspace-root",
        default=None,
        help="Container path that receives the mounted workspace",
    )
    p_container.add_argument(
        "--container-workdir",
        default=None,
        help="Working directory inside the container after startup",
    )
    p_container.add_argument("--host-cache-dir", default=None, help="Host cache directory to mount to /root/.cache")
    p_container.add_argument("--shm-size", default=None, help="Container shared memory size")
    return parser


def main() -> int:
    parser = build_parser()
    args, unknown_args = parser.parse_known_args()

    if args.cmd == "doctor":
        report = collect_report()
        if args.json:
            print_json(report)
        else:
            print_human(report)
        return 0

    if args.cmd == "setup":
        return setup_environment(
            manifest_path=args.manifest,
            apply_system=args.apply_system,
            install_python_stack=args.install_python_stack,
            dry_run=args.dry_run,
            non_interactive=args.non_interactive,
        )

    if args.cmd == "env":
        exports = build_shell_env_exports(ascend_root=args.ascend_root)
        if args.shell:
            print(exports)
        else:
            print(exports)
        return 0

    if args.cmd == "launch":
        return launch_vllm(
            model_ref=args.model,
            manifest_path=args.manifest,
            apply_system=bool(args.apply_system),
            install_python_stack=bool(args.install_python_stack),
            skip_setup=bool(args.skip_setup),
            host=args.host,
            port=args.port,
            served_model_name=args.served_model_name,
            enable_prefill_compat_mode=bool(args.prefill_compat_mode),
            non_interactive=bool(args.non_interactive),
            extra_args=list(unknown_args),
        )

    if args.cmd == "container":
        config = ContainerConfig(
            image=args.image or DEFAULT_IMAGE,
            container_name=args.container_name or DEFAULT_CONTAINER_NAME,
            host_workspace_root=args.host_workspace_root or "",
            container_workspace_root=args.container_workspace_root or DEFAULT_CONTAINER_WORKSPACE_ROOT,
            container_workdir=args.container_workdir or "",
            host_cache_dir=args.host_cache_dir or "",
            shm_size=args.shm_size or DEFAULT_SHM_SIZE,
        )
        return run_container_action(args.action, config, command=list(unknown_args))

    if unknown_args:
        parser.error("unrecognized arguments: " + " ".join(unknown_args))

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
