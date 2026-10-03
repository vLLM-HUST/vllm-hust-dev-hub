from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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


def image_name(instance_id: str, arch: str) -> str:
    escaped_id = instance_id.replace("__", "_1776_")
    return f"docker.io/swebench/sweb.eval.{arch}.{escaped_id}:latest"


def image_tag(instance_id: str) -> str:
    return hashlib.sha256(instance_id.encode()).hexdigest()[:20]


def artifact_manifest(directory: Path, names: list[str]) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for name in names:
        path = directory / name
        if path.is_file():
            artifacts[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    return artifacts


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if len(tasks) != 500:
        raise ValueError(f"expected 500 frozen tasks, found {len(tasks)}")
    return tasks


def verify_inputs(
    *,
    contract_path: Path,
    contract: dict[str, Any],
    task_pool: Path,
    dataset: Path,
    swebench_source: Path,
    proot: Path,
    fex: Path,
    fex_server: Path,
) -> None:
    expected_pool = contract["task_pool"]
    for field, name in (
        ("ordered_tasks_sha256", "ordered-tasks.jsonl"),
        ("hidden_oracle_hashes_sha256", "hidden-oracle-hashes.json"),
        ("task_pool_manifest_sha256", "manifest.json"),
    ):
        actual = sha256(task_pool / name)
        if actual != expected_pool[field]:
            raise ValueError(f"{field} mismatch: {actual}")

    grader = contract["grader"]
    checks = {
        "dataset_parquet_sha256": sha256(dataset),
        "proot_binary_sha256": sha256(proot),
        "fex_binary_sha256": sha256(fex),
        "fex_server_binary_sha256": sha256(fex_server),
        "harness_script_sha256": sha256(Path(__file__)),
    }
    for field, actual in checks.items():
        if actual != grader[field]:
            raise ValueError(f"{field} mismatch: {actual}")

    revision = subprocess.run(
        ["git", "-C", str(swebench_source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != grader["swebench_commit"]:
        raise ValueError(f"SWE-bench commit mismatch: {revision}")
    if contract_path.resolve() == dataset.resolve():
        raise ValueError("contract and dataset paths must be distinct")


def load_instances(dataset: Path) -> dict[str, dict[str, Any]]:
    from pyarrow import parquet

    rows = parquet.read_table(dataset).to_pylist()
    return {str(row["instance_id"]): row for row in rows}


def make_spec(instance: dict[str, Any], swebench_source: Path) -> Any:
    import sys

    sys.path.insert(0, str(swebench_source))
    try:
        from swebench.harness.test_spec import make_test_spec

        return make_test_spec(instance)
    finally:
        sys.path.pop(0)


def grade_report(
    *,
    test_spec: Any,
    instance_id: str,
    patch: str,
    test_output: Path,
    swebench_source: Path,
) -> dict[str, Any]:
    import sys

    sys.path.insert(0, str(swebench_source))
    try:
        from swebench.harness.grading import get_eval_report

        return get_eval_report(
            test_spec=test_spec,
            prediction={
                "instance_id": instance_id,
                "model_name_or_path": "Qwen3.5-35B-A3B",
                "model_patch": patch,
            },
            log_path=str(test_output),
            include_tests_status=True,
        )
    finally:
        sys.path.pop(0)


def run_logged(
    command: list[str],
    *,
    log: Path,
    timeout: int,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int | None, bool, float]:
    started = time.monotonic()
    with log.open("wb") as output:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=timeout)
            return returncode, False, time.monotonic() - started
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            return None, True, time.monotonic() - started


def skopeo_platform_args(arch: str) -> list[str]:
    return ["--override-arch", "amd64"] if arch == "x86_64" else []


def inspect_digest(image: str, arch: str) -> str:
    return subprocess.run(
        [
            "skopeo",
            "inspect",
            *skopeo_platform_args(arch),
            "--format",
            "{{.Digest}}",
            f"docker://{image}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def select_image(instance_id: str, preferred_arch: str) -> tuple[str, str, str]:
    candidates = [preferred_arch]
    if preferred_arch != "x86_64":
        candidates.append("x86_64")
    errors = []
    for arch in candidates:
        image = image_name(instance_id, arch)
        try:
            return arch, image, inspect_digest(image, arch)
        except subprocess.CalledProcessError as exc:
            errors.append(f"{arch}: exit {exc.returncode}")
    raise RuntimeError("no official SWE-bench image available; " + "; ".join(errors))


def prepare_image(
    *,
    instance_id: str,
    arch: str,
    image: str,
    digest: str,
    oci_layout: Path,
    bundle: Path,
    result_dir: Path,
) -> None:
    tag = image_tag(instance_id)
    oci_layout.parent.mkdir(parents=True, exist_ok=True)
    copy_code, copy_timeout, _ = run_logged(
        [
            "skopeo",
            "copy",
            "--retry-times",
            "3",
            *skopeo_platform_args(arch),
            f"docker://{image}",
            f"oci:{oci_layout}:{tag}",
        ],
        log=result_dir / "image-copy.log",
        timeout=3600,
    )
    if copy_timeout or copy_code != 0:
        raise RuntimeError(
            f"image copy failed: timeout={copy_timeout}, exit={copy_code}"
        )
    if bundle.exists():
        shutil.rmtree(bundle)
    unpack_code, unpack_timeout, _ = run_logged(
        ["umoci", "unpack", "--image", f"{oci_layout}:{tag}", str(bundle)],
        log=result_dir / "image-unpack.log",
        timeout=1800,
    )
    if unpack_timeout or unpack_code != 0:
        raise RuntimeError(
            f"image unpack failed: timeout={unpack_timeout}, exit={unpack_code}"
        )
    atomic_json(
        result_dir / "image-source.json",
        {
            "architecture": arch,
            "digest": digest,
            "image": image,
            "oci_tag": tag,
        },
    )


def normalize_patch(patch: str, exclude_patterns: list[str]) -> tuple[str, list[str]]:
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_path: str | None = None
    current_lines: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_path is not None:
                sections.append((current_path, current_lines))
            fields = shlex.split(line)
            if len(fields) != 4 or not fields[3].startswith("b/"):
                raise ValueError(f"cannot parse patch header: {line.rstrip()}")
            current_path = fields[3][2:]
            current_lines = [line]
        elif current_path is None:
            preamble.append(line)
        else:
            current_lines.append(line)
    if current_path is not None:
        sections.append((current_path, current_lines))

    excluded = [
        path
        for path, _ in sections
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in exclude_patterns)
    ]
    excluded_set = set(excluded)
    normalized = preamble + [
        line for path, lines in sections if path not in excluded_set for line in lines
    ]
    return "".join(normalized), excluded


def guest_runner(base_commit: str, patch_is_empty: bool) -> str:
    quoted_commit = shlex.quote(base_commit)
    apply = "true" if patch_is_empty else "git apply -v /grader/agent.patch"
    return f"""#!/bin/bash
set -o pipefail
cd /testbed
git reset --hard {quoted_commit}
git clean -fd
if {apply}; then
  echo ">>>>> Applied Patch (pred)"
elif patch --batch --fuzz=5 -p1 -i /grader/agent.patch; then
  echo ">>>>> Applied Patch (pred)"
else
  echo ">>>>> Patch Apply Failed (pred)"
  exit 40
fi
/bin/bash /grader/eval.sh
"""


def execute_guest(
    *,
    rootfs: Path,
    arch: str,
    proot: Path,
    fex: Path,
    fex_server: Path,
    test_output: Path,
    server_output: Path,
    timeout: int,
) -> tuple[int | None, bool, float]:
    if arch == "x86_64" and platform.machine() not in {"x86_64", "amd64"}:
        return execute_fex_guest(
            rootfs=rootfs,
            fex=fex,
            fex_server=fex_server,
            test_output=test_output,
            server_output=server_output,
            timeout=timeout,
        )
    command = [str(proot), "-R", str(rootfs)]
    command.extend(["-w", "/testbed", "/bin/bash", "/grader/run.sh"])
    environment = {
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "TERM": "dumb",
        "TZ": "Etc/UTC",
    }
    return run_logged(
        command,
        log=test_output,
        timeout=timeout,
        env=environment,
    )


def execute_fex_guest(
    *,
    rootfs: Path,
    fex: Path,
    fex_server: Path,
    test_output: Path,
    server_output: Path,
    timeout: int,
) -> tuple[int | None, bool, float]:
    mappings = {
        Path("/testbed"): rootfs / "testbed",
        Path("/grader"): rootfs / "grader",
        Path("/opt/miniconda3"): rootfs / "opt" / "miniconda3",
    }
    guest_path = ":".join(
        str(rootfs / path)
        for path in (
            "usr/local/sbin",
            "usr/local/bin",
            "usr/sbin",
            "usr/bin",
            "sbin",
            "bin",
        )
    )
    socket = rootfs / "grader" / "fex-server.socket"
    environment = {
        "FEX_ROOTFS": str(rootfs),
        "FEX_SERVERSOCKETPATH": str(socket),
        "HOME": str(rootfs / "root"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MKL_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PATH": f"{fex.parent}:{guest_path}",
        "TERM": "dumb",
        "TZ": "Etc/UTC",
    }
    lock_path = Path("/tmp/szyn-swebench-fex.lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        created_links: list[Path] = []
        server: subprocess.Popen[bytes] | None = None
        try:
            for link, target in mappings.items():
                if link.exists() or link.is_symlink():
                    raise RuntimeError(f"FEX mapping path already exists: {link}")
                link.symlink_to(target, target_is_directory=True)
                created_links.append(link)
            with server_output.open("wb") as output:
                server = subprocess.Popen(
                    [str(fex_server), "--foreground", "-p"],
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                deadline = time.monotonic() + 15
                while not socket.exists():
                    if server.poll() is not None:
                        raise RuntimeError(
                            f"FEXServer exited before readiness: {server.returncode}"
                        )
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "FEXServer socket was not ready in 15 seconds"
                        )
                    time.sleep(0.1)
                return run_logged(
                    [str(fex), "/bin/bash", "/grader/run.sh"],
                    log=test_output,
                    timeout=timeout,
                    env=environment,
                )
        finally:
            if server is not None and server.poll() is None:
                os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()
            for link in reversed(created_links):
                if link.is_symlink():
                    link.unlink()


def collection_patch(result_dir: Path, terminal: dict[str, Any]) -> Path:
    attempt = int(terminal["attempt"])
    return result_dir / f"attempt-{attempt}" / "agent.patch"


def wait_for_collection(result_dir: Path, wait_seconds: int) -> dict[str, Any] | None:
    terminal = result_dir / "collection-terminal.json"
    deadline = time.monotonic() + wait_seconds
    while not terminal.is_file():
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(10, max(0.1, deadline - time.monotonic())))
    return load_json(terminal)


def grade_one(
    task: dict[str, Any],
    *,
    instance: dict[str, Any],
    contract: dict[str, Any],
    results_root: Path,
    work_root: Path,
    oci_layout: Path,
    swebench_source: Path,
    proot: Path,
    fex: Path,
    fex_server: Path,
    wait_seconds: int,
) -> dict[str, Any] | None:
    instance_id = str(task["instance_id"])
    result_dir = results_root / instance_id
    grader_terminal_path = result_dir / "grader-terminal.json"
    if grader_terminal_path.is_file():
        return load_json(grader_terminal_path)

    collection = wait_for_collection(result_dir, wait_seconds)
    if collection is None:
        return None

    started_at = utc_now()
    started_ns = time.time_ns()
    terminal: dict[str, Any] = {
        "schema_version": "szyn-swebench-grader-terminal/v1",
        "execution_id": contract["execution_id"],
        "instance_id": instance_id,
        "started_at": started_at,
        "collection_status": collection.get("collection_status"),
    }
    bundle = work_root / f"{image_tag(instance_id)}-bundle"
    try:
        collection_status = collection.get("collection_status")
        if collection_status != "collected_ungraded":
            terminal["status"] = (
                collection_status
                if collection_status in {"agent_timeout", "agent_error"}
                else "grader_error"
            )
            terminal["error"] = "collection did not produce a gradable response"
            return terminal

        patch_path = collection_patch(result_dir, collection)
        expected_patch = collection["artifacts"]["agent.patch"]["sha256"]
        if sha256(patch_path) != expected_patch:
            raise ValueError("agent patch hash does not match collection terminal")

        test_spec = make_spec(instance, swebench_source)
        preferred_arch = str(test_spec.arch)
        arch, image, digest = select_image(instance_id, preferred_arch)
        prepare_image(
            instance_id=instance_id,
            arch=arch,
            image=image,
            digest=digest,
            oci_layout=oci_layout,
            bundle=bundle,
            result_dir=result_dir,
        )
        rootfs = bundle / "rootfs"

        grader_dir = rootfs / "grader"
        grader_dir.mkdir()
        raw_patch = patch_path.read_text(encoding="utf-8", errors="replace")
        normalization = contract["grader"]["patch_normalization"]
        patch, excluded_paths = normalize_patch(
            raw_patch, list(normalization["exclude_patterns"])
        )
        evaluated_patch = result_dir / "evaluated-agent.patch"
        evaluated_patch.write_text(patch, encoding="utf-8")
        terminal["patch_normalization"] = {
            "mode": normalization["mode"],
            "exclude_patterns": normalization["exclude_patterns"],
            "excluded_paths": excluded_paths,
            "raw_patch_sha256": sha256(patch_path),
            "evaluated_patch_sha256": sha256(evaluated_patch),
        }
        eval_script = str(test_spec.eval_script)
        (result_dir / "eval.sh").write_text(eval_script, encoding="utf-8")
        (grader_dir / "agent.patch").write_text(patch, encoding="utf-8")
        (grader_dir / "eval.sh").write_text(eval_script, encoding="utf-8")
        runner = guest_runner(str(instance["base_commit"]), not patch.strip())
        (grader_dir / "run.sh").write_text(runner, encoding="utf-8")

        test_output = result_dir / "test-output.txt"
        returncode, timed_out, runtime = execute_guest(
            rootfs=rootfs,
            arch=arch,
            proot=proot,
            fex=fex,
            fex_server=fex_server,
            test_output=test_output,
            server_output=result_dir / "fex-server.log",
            timeout=int(contract["scoring"]["grader_timeout_seconds"]),
        )
        terminal["grader_exit_code"] = returncode
        terminal["grader_runtime_seconds"] = runtime
        if timed_out:
            terminal["status"] = "grader_timeout"
        elif returncode == 40:
            terminal["status"] = "invalid_patch"
        else:
            report = grade_report(
                test_spec=test_spec,
                instance_id=instance_id,
                patch=patch,
                test_output=test_output,
                swebench_source=swebench_source,
            )
            atomic_json(result_dir / "report.json", report)
            terminal["status"] = (
                "resolved" if report[instance_id]["resolved"] else "unresolved"
            )
        terminal["image"] = {
            "preferred_architecture": preferred_arch,
            "executed_architecture": arch,
            "digest": digest,
            "name": image,
        }
        terminal["execution_backend"] = (
            "fex-2609.1"
            if arch == "x86_64" and platform.machine() not in {"x86_64", "amd64"}
            else "native-proot"
        )
    except Exception as exc:  # noqa: BLE001 - preserve a terminal record per task
        terminal["status"] = "grader_error"
        terminal["error_type"] = type(exc).__name__
        terminal["error"] = str(exc)
    finally:
        if bundle.exists():
            shutil.rmtree(bundle, ignore_errors=True)
        terminal["finished_at"] = utc_now()
        terminal["wall_time_seconds"] = (time.time_ns() - started_ns) / 1_000_000_000
        terminal["artifacts"] = artifact_manifest(
            result_dir,
            [
                "collection-terminal.json",
                "evaluated-agent.patch",
                "eval.sh",
                "fex-server.log",
                "image-copy.log",
                "image-source.json",
                "image-unpack.log",
                "report.json",
                "test-output.txt",
            ],
        )
        atomic_json(grader_terminal_path, terminal)
    return terminal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--task-pool", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--oci-layout", type=Path, required=True)
    parser.add_argument("--swebench-source", type=Path, required=True)
    parser.add_argument("--proot", type=Path, required=True)
    parser.add_argument("--fex", type=Path, required=True)
    parser.add_argument("--fex-server", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--instance-id")
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()

    contract = load_json(args.contract)
    verify_inputs(
        contract_path=args.contract,
        contract=contract,
        task_pool=args.task_pool,
        dataset=args.dataset,
        swebench_source=args.swebench_source,
        proot=args.proot,
        fex=args.fex,
        fex_server=args.fex_server,
    )
    tasks = load_tasks(args.task_pool / "ordered-tasks.jsonl")
    if args.instance_id:
        selected = [task for task in tasks if task["instance_id"] == args.instance_id]
        if not selected:
            raise ValueError(f"unknown instance ID: {args.instance_id}")
    else:
        selected = tasks[args.start_index :]
        if args.limit is not None:
            selected = selected[: args.limit]
    instances = load_instances(args.dataset)
    args.results_root.mkdir(parents=True, exist_ok=True)
    args.work_root.mkdir(parents=True, exist_ok=True)

    outcomes: list[dict[str, Any]] = []
    for task in selected:
        instance_id = str(task["instance_id"])
        outcome = grade_one(
            task,
            instance=instances[instance_id],
            contract=contract,
            results_root=args.results_root,
            work_root=args.work_root,
            oci_layout=args.oci_layout,
            swebench_source=args.swebench_source,
            proot=args.proot,
            fex=args.fex,
            fex_server=args.fex_server,
            wait_seconds=args.wait_seconds,
        )
        if outcome is None:
            print(json.dumps({"instance_id": instance_id, "status": "not_collected"}))
            continue
        outcomes.append(outcome)
        print(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "status": outcome["status"],
                    "wall_time_seconds": outcome["wall_time_seconds"],
                },
                sort_keys=True,
            ),
            flush=True,
        )

    counts: dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome["status"])
        counts[status] = counts.get(status, 0) + 1
    atomic_json(
        args.results_root / "grading-summary.json",
        {
            "schema_version": "szyn-swebench-grading-summary/v1",
            "execution_id": contract["execution_id"],
            "generated_at": utc_now(),
            "graded_count": len(outcomes),
            "status_counts": dict(sorted(counts.items())),
        },
    )


if __name__ == "__main__":
    main()
