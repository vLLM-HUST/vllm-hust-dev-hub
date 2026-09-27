import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "extension-catalog-v1.json"


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_extension_catalog_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "catalog.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_extension_catalog.py"),
            "--output",
            str(output),
        ],
        check=True,
    )
    assert output.read_bytes() == CATALOG.read_bytes()


def test_extension_catalog_has_reviewed_19_entry_policy() -> None:
    catalog = load_catalog()
    entries = catalog["extensions"]
    assert catalog["schema"] == "vllm-hust.extension-catalog/v1"
    assert len(entries) == 19
    assert [entry["id"] for entry in entries] == sorted(
        entry["id"] for entry in entries
    )
    assert len({entry["id"] for entry in entries}) == 19

    qualified = [entry for entry in entries if entry["maturity"] == "qualified"]
    assert {entry["id"] for entry in qualified} == {
        "bidkv",
        "diffspec",
        "latchmoe",
        "pipeline-microbatch",
    }
    for entry in qualified:
        assert entry["availability"] == "available"
        assert entry["enablement"] == {"allowed": True, "blocker": None}
        assert entry["installation"] is not None
        assert entry["functional_qualification"]["status"] == "passed"
        assert entry["functional_qualification"]["recovery"] == "passed"

    for entry in entries:
        if entry["availability"] == "preview":
            assert entry["installation"] is None
            assert entry["enablement"]["allowed"] is False
            assert entry["functional_qualification"]["status"] == "unverified"


def test_pipeline_availability_uses_merged_remote_commits() -> None:
    entries = {entry["id"]: entry for entry in load_catalog()["extensions"]}
    pipeline = entries["pipeline-microbatch"]
    assert pipeline["source"]["commit"] == (
        "a15a22961a0e4858da74a0ab806575c82cb254e6"
    )
    assert pipeline["installation"]["commit"] == pipeline["source"]["commit"]
    assert pipeline["availability"] == "available"
    assert pipeline["recommendation"]["level"] == (
        "not-recommended-for-tested-cell"
    )
    assert "PP2 x TP2" in pipeline["runtime_requirements"]["topologies"][0]


def test_latchmoe_keeps_dense_qwen_not_applicable() -> None:
    entries = {entry["id"]: entry for entry in load_catalog()["extensions"]}
    latchmoe = entries["latchmoe"]
    assert "Qwen3-30B-A3B" in latchmoe["runtime_requirements"]["models"]
    assert any(
        "Qwen3.8-27B" in model and "not applicable" in model
        for model in latchmoe["runtime_requirements"]["models"]
    )


def test_diffspec_pins_exact_draft_hash() -> None:
    entries = {entry["id"]: entry for entry in load_catalog()["extensions"]}
    draft = entries["diffspec"]["runtime_requirements"]["additional_models"]
    assert draft == [
        {
            "model": "VirVen/Qwen3.5-27B-EAGLE3-v2",
            "sha256": (
                "sha256:a57cefc45874197a24dd2a092cfd0d0f7d6a2f2cca156d09f2d2f4a56dc4e5be"
            ),
            "required": True,
        }
    ]
