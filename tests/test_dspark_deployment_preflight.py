from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "dspark_deployment_preflight.py"
SPEC = importlib.util.spec_from_file_location(
    "dspark_deployment_preflight", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


DSPARK_CONFIG = {
    "architectures": ["DeepSeekV4ForCausalLM"],
    "dspark_block_size": 5,
    "dspark_target_layer_ids": [1, 2, 3],
    "dspark_markov_rank": 8,
}


def test_dspark_profile_generates_explicit_config() -> None:
    args = preflight.normalize_profile(
        model_config=DSPARK_CONFIG,
        extra_args_raw="[]",
        mode="dspark",
        dspark_tokens=5,
    )

    assert args[0] == "--speculative-config"
    assert json.loads(args[1]) == {
        "method": "dspark",
        "num_speculative_tokens": 5,
    }


@pytest.mark.parametrize("mode", ["auto", "dspark"])
def test_dspark_checkpoint_rejects_legacy_mtp(mode: str) -> None:
    extra = json.dumps(
        [
            "--speculative-config",
            json.dumps({"method": "mtp", "num_speculative_tokens": 2}),
        ]
    )
    with pytest.raises(preflight.PreflightError, match="legacy method=mtp"):
        preflight.normalize_profile(
            model_config=DSPARK_CONFIG,
            extra_args_raw=extra,
            mode=mode,
            dspark_tokens=5,
        )


def test_disabled_profile_rejects_accidental_speculation() -> None:
    extra = json.dumps(
        [
            "--speculative-config",
            json.dumps({"method": "dspark", "num_speculative_tokens": 5}),
        ]
    )
    with pytest.raises(preflight.PreflightError, match="forbids"):
        preflight.normalize_profile(
            model_config=DSPARK_CONFIG,
            extra_args_raw=extra,
            mode="disabled",
            dspark_tokens=None,
        )


def test_dspark_profile_requires_local_metadata_and_positive_width() -> None:
    with pytest.raises(preflight.PreflightError, match="local checkpoint"):
        preflight.normalize_profile(
            model_config=None,
            extra_args_raw="[]",
            mode="dspark",
            dspark_tokens=5,
        )
    with pytest.raises(preflight.PreflightError, match="positive integer"):
        preflight.normalize_profile(
            model_config=DSPARK_CONFIG,
            extra_args_raw="[]",
            mode="dspark",
            dspark_tokens=None,
        )


def _runtime_tree(tmp_path: Path, *, proposer: bool = True) -> Path:
    root = tmp_path / "vllm_ascend"
    (root / "models").mkdir(parents=True)
    (root / "spec_decode").mkdir()
    (root / "models" / "__init__.py").write_text(
        "def register_model():\n"
        "    ModelRegistry.register_model(\n"
        "        'DSparkDraftModel',\n"
        "        'vllm_ascend.models.deepseek_v4.dspark:DSparkDeepseekV4ForCausalLM',\n"
        "    )\n",
        encoding="utf-8",
    )
    (root / "spec_decode" / "dspark_proposer.py").write_text(
        (
            "class AscendDSparkProposer:\n    pass\n"
            if proposer
            else "class Other:\n    pass\n"
        ),
        encoding="utf-8",
    )
    return root


def test_runtime_probe_is_structured_and_source_bound(tmp_path: Path) -> None:
    capability = preflight.probe_runtime(_runtime_tree(tmp_path))

    assert capability["schema_version"] == "vllm-hust.dspark-capability/v1"
    assert capability["supported"] is True
    assert capability["draft_architecture"] == "DSparkDraftModel"
    assert len(capability["sources"]["registry"]["sha256"]) == 64
    assert len(capability["sources"]["proposer"]["sha256"]) == 64


def test_runtime_probe_rejects_missing_proposer(tmp_path: Path) -> None:
    capability = preflight.probe_runtime(_runtime_tree(tmp_path, proposer=False))

    assert capability["supported"] is False


def test_cli_writes_owner_only_capability_receipt(tmp_path: Path) -> None:
    root = _runtime_tree(tmp_path)
    output = tmp_path / "receipt.json"
    extra = json.dumps(
        [
            "--speculative-config",
            json.dumps({"method": "dspark", "num_speculative_tokens": 5}),
        ]
    )

    assert (
        preflight.main(
            [
                "probe-runtime",
                "--ascend-root",
                str(root),
                "--extra-args-json",
                extra,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())["verdict"] == "admitted"
