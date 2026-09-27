import copy
import json
from pathlib import Path

import pytest
from contract import normalize, validate_plans


def commands():
    baseline = ["python", "-m", "vllm.entrypoints.cli.main", "serve", "model"]
    settings = {
        "--tensor-parallel-size": "2",
        "--pipeline-parallel-size": "1",
        "--dtype": "bfloat16",
        "--kv-cache-dtype": "auto",
        "--max-model-len": "262144",
        "--max-num-seqs": "16",
        "--max-num-batched-tokens": "4096",
        "--kv-cache-memory-bytes": "26038239232",
        "--seed": "17",
        "--compilation-config": json.dumps(
            {
                "cudagraph_mode": "FULL_AND_PIECEWISE",
                "cudagraph_capture_sizes": [3, 6, 12, 24, 48],
                "max_cudagraph_capture_size": 48,
            }
        ),
        "--speculative-config": json.dumps(
            {"method": "mtp", "num_speculative_tokens": 2}
        ),
    }
    for key, value in settings.items():
        baseline.extend([key, value])
    baseline.extend(["--enable-prefix-caching", "--async-scheduling"])
    return {
        "native": baseline,
        "mooncake": baseline
        + [
            "--kv-transfer-config",
            json.dumps(
                {
                    "kv_connector": "AscendStoreConnector",
                    "kv_connector_extra_config": {"backend": "mooncake"},
                }
            ),
        ],
        "tiering": baseline
        + [
            "--kv-transfer-config",
            json.dumps({"kv_connector": "HustAscendTieringConnector"}),
        ],
    }


def test_only_plugin_treatment_can_differ():
    plans = commands()
    validate_plans(plans)
    for arm in plans:
        assert normalize(plans[arm], arm) == plans["native"]


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--max-num-seqs", "8"),
        ("--tensor-parallel-size", "4"),
        ("--pipeline-parallel-size", "2"),
        ("--seed", "18"),
        ("--kv-cache-memory-bytes", "20000000000"),
    ],
)
def test_candidate_cannot_change_common_configuration(flag, value):
    plans = copy.deepcopy(commands())
    plans["tiering"][plans["tiering"].index(flag) + 1] = value
    with pytest.raises(ValueError):
        validate_plans(plans)


def test_even_all_arms_cannot_downgrade_frontier():
    plans = commands()
    for p in plans.values():
        p.remove("--async-scheduling")
    with pytest.raises(ValueError):
        validate_plans(plans)


def test_unknown_connector_cannot_be_normalized_away():
    with pytest.raises(ValueError):
        normalize(["--kv-transfer-config", '{"kv_connector":"other"}'], "tiering")


def test_generated_harness_compiles_when_supplied():
    root = Path("/home/coder/frontier-mods-qwen35-20260925/phase9-unified-r3")
    if not root.exists():
        pytest.skip("generated container capsule not present")
    for name in (
        "qualify.py",
        "run_campaign.py",
        "contract.py",
        "measurement_support.py",
        "managed_custody.py",
    ):
        compile((root / name).read_text(), name, "exec")
    validate_plans(json.loads((root / "manager-plans.json").read_text()))


def test_manager_logs_do_not_replace_the_structured_plan():
    from contract import manager_json

    assert manager_json('INFO plugin selected\n{\n"command": ["python"]\n}\n') == {
        "command": ["python"]
    }
    with pytest.raises(ValueError):
        manager_json("INFO no plan produced")
