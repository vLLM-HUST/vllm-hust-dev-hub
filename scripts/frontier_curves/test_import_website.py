import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location(
    "curves_import", Path(__file__).with_name("import_website.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def observation():
    return (
        dict(
            duration=900,
            chips=4,
            concurrency=1,
            workload_sha256=module.WORKLOAD,
            server_metadata=dict(serving_chips=4, serving_devices=[0, 1, 2, 3]),
        ),
        dict(
            valid=True,
            aborted=False,
            failed_requests=0,
            measurement_seconds=900,
            planned_measurement_seconds=900,
            decode_tokens_per_second_p90=30,
        ),
    )


@pytest.mark.parametrize(
    "field,value", [("duration", 60), ("chips", 2), ("workload_sha256", "wrong")]
)
def test_rejects_calibration_or_wrong_denominator(field, value):
    config, summary = observation()
    module.validate_window(config, summary)
    invalid = copy.deepcopy(config)
    invalid[field] = value
    with pytest.raises(ValueError):
        module.validate_window(invalid, summary)


def test_failed_requests_or_unreleased_devices_cannot_publish():
    config, summary = observation()
    summary["failed_requests"] = 1
    with pytest.raises(ValueError):
        module.validate_window(config, summary)
    with pytest.raises(ValueError):
        module.released(dict(passed=True, release=dict(exit=0, owners=[123])))


def test_actual_deployment_topology_must_agree_with_client():
    config, summary = observation()
    config["server_metadata"]["serving_devices"] = [0, 1]
    with pytest.raises(ValueError, match="topology"):
        module.validate_window(config, summary)


def test_summary_cannot_hide_a_truncated_raw_request(tmp_path):
    path = tmp_path / "requests.jsonl"
    row = dict(success=True, error=None, token_ids=[1, 2], expected_output_tokens=3)
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="output budgets"):
        module.validate_requests(path)
    row["token_ids"].append(3)
    path.write_text(json.dumps(row) + "\n")
    module.validate_requests(path)


def curve_point():
    keys = (
        "tensor_parallel_size",
        "pipeline_parallel_size",
        "max_num_seqs",
        "max_num_batched_tokens",
        "mtp_draft_tokens",
        "async_scheduling",
        "prefix_caching",
        "kv_cache_memory_bytes",
        "graph_mode",
        "graph_capture_sizes",
        "checkpoint_revision",
    )
    params = {key: key for key in keys}
    params["runtime_receipt"] = dict(
        runtime_source_files={"core/model.py": "sha"},
        packages={"engine": "1"},
        prepared_workload_sha256="workload",
        model_manifest_sha256="model",
    )
    return dict(
        cohort_id="cohort",
        configuration=dict(
            mods=[],
            hardware={"chips": 4},
            context_capacity_tokens=262144,
            parameters=params,
        ),
    )


def test_curve_accepts_same_sources_after_directory_move():
    a = curve_point()
    b = copy.deepcopy(a)
    b["configuration"]["parameters"]["runtime_receipt"]["runtime_source_files"] = {
        "../phase2/core/model.py": "sha"
    }
    module.compatible_curve(a, b)


def test_curve_rejects_different_runtime_even_if_mod_name_matches():
    a = curve_point()
    b = copy.deepcopy(a)
    b["configuration"]["parameters"]["runtime_receipt"]["runtime_source_files"][
        "core/model.py"
    ] = "changed"
    with pytest.raises(ValueError, match="identity"):
        module.compatible_curve(a, b)
    b = copy.deepcopy(a)
    b["configuration"]["parameters"]["kv_cache_memory_bytes"] = "changed"
    with pytest.raises(ValueError, match="runtime changed"):
        module.compatible_curve(a, b)


def test_drain_tokens_cannot_be_counted_as_window_throughput(tmp_path):
    path = tmp_path / "requests.jsonl"
    row = dict(
        success=True,
        error=None,
        token_ids=[1, 2, 3],
        expected_output_tokens=3,
        usage=dict(completion_tokens=3),
        start=899,
        end=901,
        chunks=[[899.5, 1], [901, 2]],
    )
    path.write_text(json.dumps(row) + "\n")
    summary = dict(
        measurement_seconds=900,
        requests_started=1,
        requests_completed_in_window=0,
        requests_drained=1,
        observed_output_tokens_in_window=1,
        output_tokens_per_second=1 / 900,
        output_tokens_per_second_per_chip=1 / 3600,
    )
    module.validate_requests(path, summary)
    summary.update(
        observed_output_tokens_in_window=3,
        output_tokens_per_second=3 / 900,
        output_tokens_per_second_per_chip=3 / 3600,
    )
    with pytest.raises(ValueError, match="raw streams"):
        module.validate_requests(path, summary)


@pytest.mark.parametrize("token", [-1, True, 1.5])
def test_output_budget_length_does_not_validate_invalid_token_ids(tmp_path, token):
    path = tmp_path / "requests.jsonl"
    path.write_text(
        json.dumps(
            dict(success=True, error=None, token_ids=[token], expected_output_tokens=1)
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="output budgets"):
        module.validate_requests(path)
