import json
from pathlib import Path

import publish_website as publication


def test_point_uses_public_mod_id_and_unified_series(tmp_path: Path):
    request = tmp_path / "c1/requests.jsonl"
    request.parent.mkdir()
    request.write_text(json.dumps({"success": True}) + "\n")
    template = {
        "id": "template",
        "cohort_id": "old",
        "label": "old",
        "configuration": {
            "engine_version": "old",
            "mods": [],
            "hardware": {"accelerator_count": 2},
            "parameters": {},
        },
        "load": {},
        "metrics": {},
        "evidence": {},
    }
    summary = {
        "output_tokens_per_second": 123.5,
        "decode_tokens_per_second_p90": 80.0,
        "ttft_seconds_p95": 0.5,
        "requests_completed_in_window": 10,
        "max_prompt_tokens_observed": 2000,
        "mean_client_inflight": 0.99,
        "full_concurrency_fraction": 0.98,
    }
    checked = {
        "windows": {
            "c1": (
                {
                    "run_id": "real-run",
                    "started_at_unix": 1_790_000_000,
                    "workload_sha256": "workload",
                    "tokenizer": {"fingerprint": "tokenizer"},
                },
                summary,
            )
        },
        "metadata": {
            "ascend_provenance": {"tracker_fix": {"revision": "ascend"}},
            "core_commit": "core",
            "model_manifest_sha256": "model",
            "benchmark_revision": "benchmark",
            "worker": "worker.Worker",
            "serving_devices": [0, 1],
            "serving_chips": 2,
            "container_allocated_npus": 4,
        },
        "custody": {"command": "vllm-hust-ext run -- vllm serve"},
        "run": tmp_path,
    }
    point, evidence = publication.build_point(
        template,
        "tiering",
        checked,
        1,
        "https://example.test/evidence",
        "contract",
    )
    assert point["configuration"]["mods"] == ["kv-tiering-migration"]
    assert point["load"]["concurrency_series"] == (
        "swe-unified-kv-tiering-migration-20260927"
    )
    assert point["configuration"]["parameters"]["host_kv_budget_gib"] == 8
    assert point["metrics"]["output_tps"] == 123.5
    assert point["evidence"]["run_ids"] == ["real-run"]
    assert evidence["validation"]["shared_native_contract_sha256"] == "contract"


def test_all_candidates_share_exactly_one_declared_native_series():
    assert publication.SERIES["native"] == "swe-unified-native-20260927"
    assert set(publication.PUBLIC_IDS) == {"mooncake", "tiering", "bidkv", "dla"}
    assert len(set(publication.SERIES.values())) == 5
