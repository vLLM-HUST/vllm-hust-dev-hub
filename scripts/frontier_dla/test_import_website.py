"""Reject wrong chip normalization and mismatched candidate/control runtimes."""

import copy
import importlib.util
import json
import shlex
import sys
from pathlib import Path

import pytest


@pytest.fixture
def importer(monkeypatch):
    root = Path(__file__).parent
    for name, filename in (
        ("policy_receipt", "policy_receipt.py"),
        ("dla_importer", "import_website.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, root / filename)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return module


def point(arm):
    extra = {"enable_cpu_binding": False}
    args = [
        "vllm",
        "serve",
        "MODEL",
        "--tensor-parallel-size",
        "2",
        "--pipeline-parallel-size",
        "1",
        "--enable-prefix-caching",
        "--async-scheduling",
    ]
    if arm == "dla":
        extra["dla_exact_output_budgets"] = True
        args += [
            "--preemption-policy",
            "dla.preemption.DeclaredBudgetPreemptionPolicy",
            "--scheduler-reserve-output-budget",
        ]
    elif arm == "bidkv":
        args += [
            "--preemption-policy",
            "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy",
        ]
    args += ["--additional-config", json.dumps(extra)]
    meta = dict(
        runtime_source_files={"core/model.py": "sha"},
        packages={"vllm": "test"},
        prepared_workload_sha256="workload",
        model_manifest_sha256="model",
        core_commit="core",
        source_archives={"core": "archive"},
    )
    return dict(
        configuration=dict(
            mods=[] if arm == "native" else [arm],
            parameters=dict(server_command=shlex.join(args), runtime_receipt=meta),
        )
    )


def test_control_comparison_allows_only_declared_mod_options(importer):
    points = [point(arm) for arm in ("native", "bidkv", "dla")]
    importer.compatible_controls(points)
    changed = copy.deepcopy(points)
    changed[2]["configuration"]["parameters"]["server_command"] += (
        " --no-async-scheduling"
    )
    with pytest.raises(ValueError, match="startup parameters"):
        importer.compatible_controls(changed)
    changed = copy.deepcopy(points)
    changed[1]["configuration"]["parameters"]["runtime_receipt"]["core_commit"] = (
        "different"
    )
    with pytest.raises(ValueError, match="source differs"):
        importer.compatible_controls(changed)


def test_admission_flag_cannot_leak_into_bidkv(importer):
    candidate = point("bidkv")
    candidate["configuration"]["parameters"]["server_command"] += (
        " --scheduler-reserve-output-budget"
    )
    with pytest.raises(ValueError, match="policy launch"):
        importer.common_command(candidate)


def test_raw_streams_use_two_participating_chips(importer, tmp_path):
    path = tmp_path / "requests.jsonl"
    path.write_text(
        json.dumps(
            dict(
                success=True,
                error=None,
                token_ids=[1, 2, 3],
                expected_output_tokens=3,
                usage=dict(completion_tokens=3),
                start=0,
                end=2,
                chunks=[[1, 1], [2, 2]],
            )
        )
        + "\n"
    )
    summary = dict(
        measurement_seconds=900,
        requests_started=1,
        requests_completed_in_window=1,
        requests_drained=0,
        observed_output_tokens_in_window=3,
        output_tokens_per_second=3 / 900,
        output_tokens_per_second_per_chip=3 / 1800,
    )
    importer.validate_requests(path, summary)
    summary["output_tokens_per_second_per_chip"] = 3 / 3600
    with pytest.raises(ValueError, match="raw streams"):
        importer.validate_requests(path, summary)


def test_window_rejects_container_quota_as_participating_chip_count(importer):
    config = dict(
        duration=900, chips=4, concurrency=1, workload_sha256=importer.WORKLOAD
    )
    with pytest.raises(ValueError, match="two-chip"):
        importer.validate_window(config, {})
