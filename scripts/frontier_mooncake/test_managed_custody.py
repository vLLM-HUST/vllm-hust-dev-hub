import json

import pytest

from managed_custody import launched_arguments


def test_captures_only_the_actual_planned_serving_child(tmp_path):
    root = tmp_path / "capsule"
    root.mkdir()
    expected = [
        "/env/bin/python",
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        "model",
        "--async-scheduling",
    ]
    (root / "manager-plans.json").write_text(json.dumps({"mooncake": expected}))
    proc = tmp_path / "proc"
    parent = proc / "12/task/12"
    parent.mkdir(parents=True)
    (parent / "children").write_text("13 14")
    child = proc / "14"
    child.mkdir()
    (child / "cmdline").write_bytes(
        b"\0".join(value.encode() for value in expected) + b"\0"
    )
    assert launched_arguments(12, "mooncake", root, proc) == {
        "pid": 14,
        "argv": expected,
    }
    (child / "cmdline").write_bytes(
        b"\0".join(value.encode() for value in expected[:-1])
    )
    with pytest.raises(RuntimeError, match="differs"):
        launched_arguments(12, "mooncake", root, proc)


def test_missing_serving_child_has_a_bounded_deadline(tmp_path):
    (tmp_path / "manager-plans.json").write_text(json.dumps({"native": []}))
    with pytest.raises(TimeoutError, match="capture"):
        launched_arguments(12, "native", tmp_path, tmp_path, timeout=0)
