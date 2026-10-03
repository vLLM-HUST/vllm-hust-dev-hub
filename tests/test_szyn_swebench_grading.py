from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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


def test_fex_guest_uses_single_thread_math_libraries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"OPENBLAS_NUM_THREADS": "1"' in source
    assert '"OMP_NUM_THREADS": "1"' in source


def test_guest_runner_handles_nonempty_and_empty_patches() -> None:
    module = load_module()
    nonempty = module.guest_runner("abc123", False)
    empty = module.guest_runner("abc123", True)
    assert "git apply -v /grader/agent.patch" in nonempty
    assert "if true; then" in empty
    assert ">>>>> Applied Patch (pred)" in nonempty


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
