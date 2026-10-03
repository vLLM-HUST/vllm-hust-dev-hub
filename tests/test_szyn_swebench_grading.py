from __future__ import annotations

import fcntl
import importlib.util
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluation_machine" / "run_szyn_swebench_grading.py"


def load_module():
    spec = importlib.util.spec_from_file_location("szyn_grading", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_image_name_uses_official_swebench_encoding() -> None:
    module = load_module()
    assert module.image_name("django__django-15104", "arm64") == (
        "docker.io/swebench/sweb.eval.arm64.django_1776_django-15104:latest"
    )


def test_skopeo_platform_args_override_x86_on_arm_hosts() -> None:
    module = load_module()
    assert module.skopeo_platform_args("x86_64") == ["--override-arch", "amd64"]
    assert module.skopeo_platform_args("arm64") == []


def test_run_logged_terminates_process_group_when_interrupted(tmp_path: Path) -> None:
    module = load_module()
    process = mock.Mock()
    process.pid = 12345
    process.wait.side_effect = [KeyboardInterrupt, 0]
    process.poll.return_value = None
    with (
        mock.patch.object(module.subprocess, "Popen", return_value=process),
        mock.patch.object(module.os, "killpg") as killpg,
        pytest.raises(KeyboardInterrupt),
    ):
        module.run_logged(["command"], log=tmp_path / "command.log", timeout=30)
    killpg.assert_called_once_with(12345, module.signal.SIGTERM)


def test_inspect_digest_retries_transient_registry_failure() -> None:
    module = load_module()
    transient = subprocess.CompletedProcess([], 1, "", "unexpected EOF")
    success = subprocess.CompletedProcess([], 0, "sha256:abc\n", "")
    sleeps: list[int] = []
    with mock.patch.object(module.subprocess, "run", side_effect=[transient, success]):
        digest = module.inspect_digest(
            "example.invalid/image:tag",
            "arm64",
            attempts=2,
            sleep=sleeps.append,
        )
    assert digest == "sha256:abc"
    assert sleeps == [5]


def test_inspect_digest_does_not_retry_missing_manifest() -> None:
    module = load_module()
    missing = subprocess.CompletedProcess([], 1, "", "manifest unknown")
    with mock.patch.object(module.subprocess, "run", return_value=missing) as run:
        try:
            module.inspect_digest(
                "example.invalid/image:tag",
                "arm64",
                attempts=8,
                sleep=lambda _: None,
            )
        except module.ImageUnavailableError:
            pass
        else:
            raise AssertionError("missing manifest was not classified as unavailable")
    assert run.call_count == 1


def test_inspect_digest_treats_docker_hub_denial_as_unavailable() -> None:
    module = load_module()
    denied = subprocess.CompletedProcess(
        [],
        1,
        "",
        "denied: requested access to the resource is denied\n"
        "unauthorized: authentication required",
    )
    with mock.patch.object(module.subprocess, "run", return_value=denied) as run:
        try:
            module.inspect_digest(
                "docker.io/swebench/missing-arm-image:latest",
                "arm64",
                attempts=8,
                sleep=lambda _: None,
            )
        except module.ImageUnavailableError:
            pass
        else:
            raise AssertionError("Docker Hub denial was not classified as unavailable")
    assert run.call_count == 1


def test_select_image_falls_back_from_unavailable_arm_to_x86() -> None:
    module = load_module()
    policy = {
        "digest_inspect_attempts": 8,
        "backoff_seconds": [5],
    }
    with mock.patch.object(
        module,
        "inspect_digest",
        side_effect=[module.ImageUnavailableError("missing"), "sha256:x86"],
    ) as inspect:
        result = module.select_image("django__django-10914", "arm64", policy)
    assert result == (
        "x86_64",
        module.image_name("django__django-10914", "x86_64"),
        "sha256:x86",
    )
    assert inspect.call_count == 2


def test_select_image_consumes_contract_retry_policy() -> None:
    module = load_module()
    policy = {
        "digest_inspect_attempts": 7,
        "backoff_seconds": [3, 9],
    }
    with mock.patch.object(
        module, "inspect_digest", return_value="sha256:abc"
    ) as inspect:
        result = module.select_image("django__django-15104", "arm64", policy)
    assert result[0] == "arm64"
    inspect.assert_called_once_with(
        module.image_name("django__django-15104", "arm64"),
        "arm64",
        attempts=7,
        backoff_seconds=[3, 9],
    )


def test_task_lock_excludes_second_grader(tmp_path: Path) -> None:
    module = load_module()
    with (
        module.task_lock(tmp_path),
        (tmp_path / ".grader.lock").open("a+b") as contender,
    ):
        try:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("a second grader acquired the task lock")


def test_select_tasks_assigns_disjoint_deterministic_shards() -> None:
    module = load_module()
    tasks = [{"instance_id": str(index)} for index in range(10)]
    shards = [
        module.select_tasks(
            tasks,
            start_index=1,
            limit=None,
            instance_id=None,
            shard_count=3,
            shard_index=index,
        )
        for index in range(3)
    ]
    assert [[task["instance_id"] for task in shard] for shard in shards] == [
        ["1", "4", "7"],
        ["2", "5", "8"],
        ["3", "6", "9"],
    ]
    assert {task["instance_id"] for shard in shards for task in shard} == {
        str(index) for index in range(1, 10)
    }


def test_select_tasks_rejects_invalid_shard_options() -> None:
    module = load_module()
    tasks = [{"instance_id": "one"}]
    with pytest.raises(ValueError, match="shard count must be positive"):
        module.select_tasks(
            tasks,
            start_index=0,
            limit=None,
            instance_id=None,
            shard_count=0,
            shard_index=0,
        )
    with pytest.raises(ValueError, match="cannot be combined with sharding"):
        module.select_tasks(
            tasks,
            start_index=0,
            limit=None,
            instance_id="one",
            shard_count=2,
            shard_index=0,
        )


def test_fex_guest_uses_single_thread_math_libraries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"OPENBLAS_NUM_THREADS": "1"' in source
    assert '"OMP_NUM_THREADS": "1"' in source
    assert 'terminal["interrupted"] = True' in source


def test_guest_runner_handles_nonempty_and_empty_patches() -> None:
    module = load_module()
    nonempty = module.guest_runner("abc123", False)
    empty = module.guest_runner("abc123", True)
    assert "git apply -v /grader/agent.patch" in nonempty
    assert "if true; then" in empty
    assert ">>>>> Applied Patch (pred)" in nonempty
    assert "git reset" not in nonempty
    assert "git clean" not in nonempty
    assert "actual_image_head=$(git rev-parse HEAD)" in nonempty
    assert '!= "$expected_image_head"' in nonempty


def test_inspect_image_repository_accepts_swebench_setup_commit(
    tmp_path: Path,
) -> None:
    module = load_module()
    repository = tmp_path / "rootfs" / "testbed"
    repository.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"],
        check=True,
    )
    (repository / "module.py").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repository / "tox.ini").write_text("pytest -rA\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "SWE-bench"],
        check=True,
    )

    state = module.inspect_image_repository(tmp_path / "rootfs", base)
    assert state["relation"] == "swebench-setup-commit"
    assert state["head_parent"] == base
    assert state["worktree_clean"] is True


def test_normalize_patch_excludes_only_matching_diff_sections() -> None:
    module = load_module()
    patch = """diff --git a/pkg/core.py b/pkg/core.py
--- a/pkg/core.py
+++ b/pkg/core.py
@@ -1 +1 @@
-old
+new
diff --git a/case/pkg.egg-info/PKG-INFO b/pkg.egg-info/PKG-INFO
new file mode 100644
--- /dev/null
+++ b/pkg.egg-info/PKG-INFO
@@ -0,0 +1 @@
+generated
diff --git a/case/pkg/native.cpython-312-aarch64-linux-gnu.so b/pkg/native.cpython-312-aarch64-linux-gnu.so
new file mode 100755
--- /dev/null
+++ b/pkg/native.cpython-312-aarch64-linux-gnu.so
@@ -0,0 +1 @@
+generated
"""
    normalized, excluded = module.normalize_patch(patch, ["*.egg-info/*", "*.so"])
    assert excluded == [
        "pkg.egg-info/PKG-INFO",
        "pkg/native.cpython-312-aarch64-linux-gnu.so",
    ]
    assert "pkg/core.py" in normalized
    assert "egg-info" not in normalized
    assert ".so" not in normalized


def test_normalize_patch_accepts_unquoted_paths_with_spaces() -> None:
    module = load_module()
    patch = """diff --git a/case/templates/ssi include.html b/templates/ssi include.html
new file mode 100644
--- /dev/null
+++ b/templates/ssi include.html
@@ -0,0 +1 @@
+content
"""
    normalized, excluded = module.normalize_patch(patch, ["*.egg-info/*"])
    assert normalized == patch
    assert excluded == []


def test_grader_hash_is_frozen_when_module_loads(tmp_path: Path) -> None:
    module = load_module()
    original = module.GRADER_HARNESS_SHA256
    with mock.patch.object(module, "sha256", return_value="changed-on-disk"):
        assert module.GRADER_HARNESS_SHA256 == original


def test_artifact_manifest_hashes_only_existing_files(tmp_path: Path) -> None:
    module = load_module()
    (tmp_path / "present.txt").write_text("evidence\n", encoding="utf-8")
    manifest = module.artifact_manifest(tmp_path, ["present.txt", "missing.txt"])
    assert list(manifest) == ["present.txt"]
    assert manifest["present.txt"]["bytes"] == 9


def test_wait_for_collection_returns_existing_terminal(tmp_path: Path) -> None:
    module = load_module()
    terminal = {"collection_status": "collected_ungraded"}
    (tmp_path / "collection-terminal.json").write_text(json.dumps(terminal))
    assert module.wait_for_collection(tmp_path, 0) == terminal
