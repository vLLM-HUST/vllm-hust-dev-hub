from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IGNORED_NAMES = {
    ".coverage",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def verify_inputs(task_pool: Path, contract: dict[str, Any], opencode: Path) -> None:
    expected = contract["task_pool"]
    paths = {
        "ordered_tasks_sha256": task_pool / "ordered-tasks.jsonl",
        "hidden_oracle_hashes_sha256": task_pool / "hidden-oracle-hashes.json",
        "task_pool_manifest_sha256": task_pool / "manifest.json",
    }
    for field, path in paths.items():
        actual = sha256(path)
        if actual != expected[field]:
            raise ValueError(f"{field} mismatch: {actual}")
    actual_binary = sha256(opencode)
    if actual_binary != contract["collector"]["binary_sha256"]:
        raise ValueError(f"OpenCode binary mismatch: {actual_binary}")
    actual_harness = sha256(Path(__file__))
    if actual_harness != contract["collector"]["harness_script_sha256"]:
        raise ValueError(f"collector harness mismatch: {actual_harness}")


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if len(tasks) != 500:
        raise ValueError(f"expected 500 frozen tasks, found {len(tasks)}")
    if len({task["instance_id"] for task in tasks}) != len(tasks):
        raise ValueError("frozen task IDs are not unique")
    return tasks


def mirror_path(mirror_root: Path, repo: str) -> Path:
    return mirror_root / f"{repo.replace('/', '__')}.git"


def ensure_mirror(mirror_root: Path, repo: str) -> Path:
    destination = mirror_path(mirror_root, repo)
    if destination.is_dir():
        subprocess.run(
            ["git", "--git-dir", str(destination), "fetch", "--prune", "origin"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--mirror",
                f"https://github.com/{repo}.git",
                str(destination),
            ],
            check=True,
        )
    return destination


def extract_commit(mirror: Path, commit: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    archive = subprocess.Popen(
        ["git", "--git-dir", str(mirror), "archive", "--format=tar", commit],
        stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
        tar.extractall(destination, filter="data")
    if archive.wait() != 0:
        raise subprocess.CalledProcessError(archive.returncode, archive.args)


def remove_generated_files(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.name not in IGNORED_NAMES:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def chown_tree(root: Path, uid: int, gid: int) -> None:
    os.chown(root, uid, gid, follow_symlinks=False)
    for path in root.rglob("*"):
        os.chown(path, uid, gid, follow_symlinks=False)


def sandbox_environment(
    temporary: Path, state_root: Path, uid: int, gid: int
) -> dict[str, str]:
    home = temporary / "home"
    python_packages = temporary / "python-packages"
    npm_prefix = temporary / "npm-prefix"
    temp_dir = temporary / "tmp"
    state_paths = {
        "XDG_CONFIG_HOME": state_root / "config",
        "XDG_DATA_HOME": state_root / "data",
        "XDG_STATE_HOME": state_root / "state",
        "XDG_CACHE_HOME": state_root / "cache",
    }
    for path in (
        home,
        python_packages,
        npm_prefix / "bin",
        temp_dir,
        *state_paths.values(),
    ):
        path.mkdir(parents=True, exist_ok=True)
    chown_tree(state_root, uid, gid)
    state_root.chmod(0o700)
    for path in (home, python_packages, npm_prefix, temp_dir):
        chown_tree(path, uid, gid)

    environment = {
        key: os.environ[key]
        for key in ("LANG", "LC_ALL", "TERM", "TZ", "SSL_CERT_FILE")
        if key in os.environ
    }
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{npm_prefix / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "PYTHONPATH": str(python_packages),
            "PIP_TARGET": str(python_packages),
            "PIP_CACHE_DIR": str(state_paths["XDG_CACHE_HOME"] / "pip"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONUSERBASE": str(temporary / "python-user"),
            "NPM_CONFIG_PREFIX": str(npm_prefix),
            "NPM_CONFIG_CACHE": str(state_paths["XDG_CACHE_HOME"] / "npm"),
            "UV_CACHE_DIR": str(state_paths["XDG_CACHE_HOME"] / "uv"),
            "CARGO_HOME": str(state_paths["XDG_CACHE_HOME"] / "cargo"),
            "TMPDIR": str(temp_dir),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "SZYN_LOCAL_API_KEY": "local-endpoint-placeholder",
            **{key: str(value) for key, value in state_paths.items()},
        }
    )
    return environment


def sandbox_command(command: list[str], uid: int, gid: int) -> list[str]:
    return [
        "setpriv",
        f"--reuid={uid}",
        f"--regid={gid}",
        "--clear-groups",
        "--",
        *command,
    ]


def write_opencode_config(case: Path, endpoint: str, model_name: str) -> None:
    atomic_json(
        case / "opencode.json",
        {
            "$schema": "https://opencode.ai/config.json",
            "snapshot": False,
            "model": f"vllm-local/{model_name}",
            "provider": {
                "vllm-local": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Local vLLM-HUST",
                    "options": {
                        "baseURL": endpoint,
                        "apiKey": "{env:SZYN_LOCAL_API_KEY}",
                    },
                    "models": {
                        model_name: {
                            "name": "Qwen3.5-35B-A3B BF16 TP2 native thinking=false",
                            "limit": {"context": 262144, "output": 32768},
                        }
                    },
                }
            },
            "permission": {"*": "allow"},
        },
    )


def session_id_from_events(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = event.get("sessionID")
        if isinstance(session_id, str) and session_id:
            return session_id
    return None


def create_patch(pristine: Path, case: Path, output: Path) -> int:
    remove_generated_files(case)
    with tempfile.TemporaryFile() as stream:
        completed = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--binary",
                "--no-renames",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                pristine.name,
                case.name,
            ],
            cwd=pristine.parent,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
        stream.seek(0)
        patch = stream.read()
    if completed.returncode not in (0, 1):
        raise subprocess.CalledProcessError(completed.returncode, completed.args)
    patch = patch.replace(f"a/{pristine.name}/".encode(), b"a/")
    patch = patch.replace(f"b/{case.name}/".encode(), b"b/")
    output.write_bytes(patch)
    return completed.returncode


def collect_one(
    task: dict[str, Any],
    *,
    contract: dict[str, Any],
    opencode: Path,
    mirror_root: Path,
    work_root: Path,
    output_root: Path,
    state_root: Path,
    attempt: int,
) -> dict[str, Any]:
    instance_id = task["instance_id"]
    result_dir = output_root / instance_id
    terminal_path = result_dir / "collection-terminal.json"
    if terminal_path.is_file():
        return load_json(terminal_path)

    attempt_dir = result_dir / f"attempt-{attempt}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(attempt_dir / "task-input.json", task)
    started_at = utc_now()
    started_ns = time.time_ns()
    terminal: dict[str, Any] = {
        "schema_version": "szyn-swebench-collection-terminal/v1",
        "execution_id": contract["execution_id"],
        "instance_id": instance_id,
        "attempt": attempt,
        "started_at": started_at,
    }
    temporary = Path(tempfile.mkdtemp(prefix=f"{instance_id}-", dir=work_root))
    temporary.chmod(0o755)
    pristine = temporary / "pristine"
    case = temporary / "case"
    try:
        mirror = mirror_path(mirror_root, task["repo"])
        extract_commit(mirror, task["base_commit"], pristine)
        extract_commit(mirror, task["base_commit"], case)
        write_opencode_config(
            case,
            contract["runtime"]["endpoint"],
            contract["runtime"]["served_model_name"],
        )
        write_opencode_config(
            pristine,
            contract["runtime"]["endpoint"],
            contract["runtime"]["served_model_name"],
        )
        sandbox_uid = int(contract["sandbox"]["process_uid_base"])
        sandbox_uid += int(state_root.name.removeprefix("worker-"))
        sandbox_gid = int(contract["sandbox"]["process_gid"])
        chown_tree(case, sandbox_uid, sandbox_gid)
        case.chmod(0o700)
        environment = sandbox_environment(
            temporary, state_root, sandbox_uid, sandbox_gid
        )
        events_path = attempt_dir / "opencode-events.jsonl"
        stderr_path = attempt_dir / "opencode-stderr.log"
        command = sandbox_command(
            [
                str(opencode),
                "run",
                "--format",
                "json",
                "--print-logs",
                "--log-level",
                "INFO",
                "--pure",
                "--dir",
                str(case),
                task["opencode_prompt"],
            ],
            sandbox_uid,
            sandbox_gid,
        )
        try:
            with events_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                completed = subprocess.run(
                    command,
                    cwd=case,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=contract["collector"]["agent_timeout_seconds"],
                    check=False,
                )
            terminal["collector_exit_code"] = completed.returncode
            terminal["collection_status"] = (
                "collected_ungraded" if completed.returncode == 0 else "agent_error"
            )
        except subprocess.TimeoutExpired:
            terminal["collector_exit_code"] = None
            terminal["collection_status"] = "agent_timeout"

        create_patch(pristine, case, attempt_dir / "agent.patch")
        session_id = session_id_from_events(events_path)
        terminal["session_id"] = session_id
        if session_id:
            export_path = attempt_dir / "opencode-session-export.sanitized.json"
            with (
                export_path.open("wb") as stdout,
                (attempt_dir / "export-stderr.log").open("wb") as stderr,
            ):
                exported = subprocess.run(
                    sandbox_command(
                        [str(opencode), "export", "--sanitize", session_id],
                        sandbox_uid,
                        sandbox_gid,
                    ),
                    cwd=case,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=120,
                    check=False,
                )
            terminal["export_exit_code"] = exported.returncode
        terminal["artifacts"] = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(attempt_dir.iterdir())
            if path.is_file()
        }
    except Exception as exc:  # noqa: BLE001 - one broken task must not stop the batch
        terminal["collection_status"] = "infrastructure_error"
        terminal["error_type"] = type(exc).__name__
        terminal["error"] = str(exc)
    finally:
        terminal["finished_at"] = utc_now()
        terminal["wall_time_seconds"] = (time.time_ns() - started_ns) / 1_000_000_000
        atomic_json(terminal_path, terminal)
        shutil.rmtree(temporary, ignore_errors=True)
    return terminal


def collect_partition(
    tasks: list[dict[str, Any]],
    *,
    worker_index: int,
    contract: dict[str, Any],
    opencode: Path,
    mirror_root: Path,
    work_root: Path,
    output_root: Path,
    state_root: Path,
    attempt: int,
) -> list[dict[str, Any]]:
    outcomes = []
    for task in tasks:
        outcome = collect_one(
            task,
            contract=contract,
            opencode=opencode,
            mirror_root=mirror_root,
            work_root=work_root,
            output_root=output_root,
            state_root=state_root / f"worker-{worker_index}",
            attempt=attempt,
        )
        outcomes.append(outcome)
        print(
            json.dumps(
                {
                    "instance_id": outcome["instance_id"],
                    "status": outcome.get("collection_status"),
                    "wall_time_seconds": outcome.get("wall_time_seconds"),
                    "worker": worker_index,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--task-pool", type=Path, required=True)
    parser.add_argument("--opencode", type=Path, required=True)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()

    contract = load_json(args.contract)
    verify_inputs(args.task_pool, contract, args.opencode)
    tasks = load_tasks(args.task_pool / "ordered-tasks.jsonl")
    selected = tasks[args.start_index :]
    if args.limit is not None:
        selected = selected[: args.limit]
    if args.workers < 1:
        raise ValueError("workers must be positive")
    args.work_root.mkdir(parents=True, exist_ok=True)
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.state_root.mkdir(parents=True, exist_ok=True)

    for repo in sorted({task["repo"] for task in selected}):
        ensure_mirror(args.mirror_root, repo)

    partitions = [selected[index :: args.workers] for index in range(args.workers)]
    outcomes: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                collect_partition,
                partition,
                worker_index=index,
                contract=contract,
                opencode=args.opencode,
                mirror_root=args.mirror_root,
                work_root=args.work_root,
                output_root=args.output_root,
                state_root=args.state_root,
                attempt=args.attempt,
            )
            for index, partition in enumerate(partitions)
            if partition
        ]
        for future in concurrent.futures.as_completed(futures):
            outcomes.extend(future.result())

    summary: dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome.get("collection_status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    atomic_json(
        args.output_root / "collection-summary.json",
        {
            "schema_version": "szyn-swebench-collection-summary/v1",
            "execution_id": contract["execution_id"],
            "generated_at": utc_now(),
            "selected_count": len(selected),
            "status_counts": dict(sorted(summary.items())),
        },
    )


if __name__ == "__main__":
    main()
