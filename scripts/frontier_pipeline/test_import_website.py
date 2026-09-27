import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location(
    "pipeline_import", Path(__file__).with_name("import_website.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def observation():
    return (
        dict(
            duration=900,
            chips=4,
            concurrency=4,
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
