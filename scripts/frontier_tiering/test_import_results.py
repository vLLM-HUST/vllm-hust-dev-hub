import json
from types import SimpleNamespace

import pytest

from import_results import main, normalized_launch


def arguments():
    flags = {
        "--tensor-parallel-size": "2",
        "--pipeline-parallel-size": "1",
        "--dtype": "bfloat16",
        "--kv-cache-dtype": "auto",
        "--max-model-len": "262144",
        "--max-num-seqs": "16",
        "--max-num-batched-tokens": "4096",
        "--kv-cache-memory-bytes": "26038239232",
        "--mamba-cache-mode": "align",
        "--speculative-config": json.dumps(
            {"method": "mtp", "num_speculative_tokens": 2}
        ),
        "--compilation-config": json.dumps(
            {
                "cudagraph_mode": "FULL_AND_PIECEWISE",
                "cudagraph_capture_sizes": [3, 6, 12, 24, 48],
                "max_cudagraph_capture_size": 48,
            }
        ),
    }
    return [
        "python",
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        "MODEL",
        "--enable-prefix-caching",
        "--async-scheduling",
    ] + [v for pair in flags.items() for v in pair]


def test_reject_downgraded_config_and_wrong_treatment():
    args = arguments()
    custody = {"serving_child": {"argv": args}}
    assert normalized_launch(custody, "native")[0] == args
    args.remove("--async-scheduling")
    with pytest.raises(ValueError, match="execution features"):
        normalized_launch(custody, "native")
    args = arguments() + ["--kv-transfer-config", "{}"]
    with pytest.raises(ValueError, match="Unexpected connector"):
        normalized_launch({"serving_child": {"argv": args}}, "native")


def test_incomplete_pair_cannot_touch_site(tmp_path):
    status = tmp_path / "receipts/matched-curves-r1/status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"passed": False, "arms": []}))
    with pytest.raises(ValueError, match="incomplete"):
        main(SimpleNamespace(artifacts=tmp_path, site=tmp_path / "must-not-exist"))
    assert not (tmp_path / "must-not-exist").exists()
