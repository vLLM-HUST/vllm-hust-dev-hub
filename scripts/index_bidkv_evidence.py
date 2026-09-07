#!/usr/bin/env python3
"""Add immutable provenance manifests to retained BidKV evidence suites.

The original online runs predate the manifest format.  This tool never rewrites
raw evidence: it records raw-file hashes and labels facts that were not captured
at run time as unknown instead of inferring them after the fact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


CORE_COMMIT = "a4d6aa022fb1885a25a802a6e29372c81eac6c9f"
ASCEND_COMMIT = "2c8c722107a54127999a64c4eb0ec86139df8c26"
BIDKV_MAIN_COMMIT = "ba700cb69ed5c84f012e5103eb115aa22cdbc1f5"
BIDKV_CANDIDATE_COMMIT = "199e0bdc6fc38fc9b14b626515efdcbf81de0b62"
MODEL_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
MODEL_PATH = "/data/shared_models/Qwen/Qwen3.8-27B"
BASELINE_IMAGE = "sage-mate/bidkv-main-requal:baseline-a4d6aa0-2c8c722-r2"
CANDIDATE_IMAGE = "sage-mate/bidkv-main-requal:candidate-a4d6aa0-2c8c722-199e0bd-r1"
IMAGE_IDS = {
    "baseline": "sha256:80f05c0d0c49c139f94922ae6057e3edb21251b8e8a332c1df35fb3d555d60d8",
    "candidate": "sha256:a4e042e304507b3fa03f51c319098edb8173d32ebd5d5a5704ff842ef0a1ed77",
}
MODEL_FILES = {
    "config.json": "191e0af232104ed8b65258cf3fb2b842e288008baca7633c11b82a1ac7203aab",
    "generation_config.json": "e70c136c1b78ddc1fb0905bac8e733a4dc448d4f852a5dd75143fffc70be550e",
    "model.safetensors.index.json": "77042094076611b69791a610065f28b7013b8c621795fa86ddccc8bac7d1b9df",
    "tokenizer.json": "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3",
    "tokenizer_config.json": "b11349aafa7cdc6a320767cf7ceb29ed82f7eda5d65e8e0819e76f0ce947bf27",
}
RUN_SOURCE_FILES = {
    "scripts/bidkv_matrix_workload.py": "7b5f9c24c0da476bd8e14b8b74e1190e8aa5a1feffdcba393cdd3e5a08f6e637",
    "scripts/run_bidkv_matrix.py": "9311b20e015c394d84c7c33688db225f0d2819f793dd09bf3998098231b0cdc4",
    "config/bidkv-tp4-graph-matrix.json": "c66cfb85b106e63937bcc63a1a6e8cd5fda334564c1d716fa06d634d92b1d6f4",
}
GENERATED = {"run-manifest.json", "evidence-index.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso_mtime(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def arm_directories(
    root: Path, cell_ids: list[str]
) -> list[tuple[int, int, Path, str, Path]]:
    repetitions = sorted(path for path in root.glob("repeat-*") if path.is_dir())
    run_roots = repetitions or [root]
    result = []
    for repetition, run_root in enumerate(run_roots, 1):
        cell_dirs = [run_root / cell_id for cell_id in cell_ids]
        for cell_index, cell_dir in enumerate(cell_dirs):
            order = (
                ("baseline", "candidate")
                if (cell_index + repetition - 1) % 2 == 0
                else ("candidate", "baseline")
            )
            for order_index, arm_name in enumerate(order, 1):
                if not (cell_dir / arm_name / "configuration.json").is_file():
                    continue
                result.append(
                    (repetition, order_index, cell_dir, arm_name, cell_dir / arm_name)
                )
    return result


def raw_files(directory: Path) -> list[dict[str, object]]:
    files = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.name in GENERATED:
            continue
        files.append(
            {
                "path": str(path.relative_to(directory)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return files


def write_index(root: Path, source_root: Path) -> dict[str, object]:
    matrix = json.loads((root / "matrix.json").read_text())
    cells = {cell["id"]: cell for cell in matrix["cells"]}
    started = (root / "started-at.txt").read_text().strip()
    finished = (root / "finished-at.txt").read_text().strip()
    snapshot_path = root / "source-snapshot.json"
    if snapshot_path.exists():
        source_snapshot = json.loads(snapshot_path.read_text())
    else:
        source_snapshot = {
            "status": "content-hash-recoverable; commit/dirty-state-not-captured-at-run-time",
            "files": dict(RUN_SOURCE_FILES),
            "commit": None,
            "dirty_state": "unknown-not-captured",
        }

    entries = []
    for repetition, order_index, cell_dir, arm_name, arm_dir in arm_directories(
        root, list(cells)
    ):
        files = raw_files(arm_dir)
        mtimes = [path.stat().st_mtime for path in arm_dir.iterdir() if path.is_file()]
        configuration = json.loads((arm_dir / "configuration.json").read_text())
        manifest = {
            "schema": "sage-mate.bidkv-run-manifest/v1",
            "evidence_class": "real-online-retained",
            "manifest_provenance": "derived-after-run-without-raw-file-rewrite",
            "suite_time_utc": {"started": started, "finished": finished},
            "arm_time_utc": {
                "status": "derived-from-retained-file-mtimes",
                "first": iso_mtime(min(mtimes)),
                "last": iso_mtime(max(mtimes)),
            },
            "execution_order": {
                "repetition": repetition,
                "cell": cell_dir.name,
                "arm_position_within_cell": order_index,
                "arm": arm_name,
            },
            "runtime": {
                "core_commit": CORE_COMMIT,
                "ascend_commit": ASCEND_COMMIT,
                "bidkv_commit": (
                    None if arm_name == "baseline" else BIDKV_CANDIDATE_COMMIT
                ),
                "bidkv_organization_main_commit": BIDKV_MAIN_COMMIT,
                "image": BASELINE_IMAGE if arm_name == "baseline" else CANDIDATE_IMAGE,
                "image_id": IMAGE_IDS[arm_name],
                "configuration": configuration,
            },
            "model": {
                "path": MODEL_PATH,
                "huggingface_snapshot_revision": MODEL_REVISION,
                "identity_file_sha256": MODEL_FILES,
            },
            "topology": {
                "accelerator": "Ascend NPU",
                "visible_devices": [0, 1, 2, 3],
                "reserved_untouched_devices": [4, 5, 6, 7],
                "tensor_parallel_size": 4,
                "tensor_parallel_ranks": [0, 1, 2, 3],
                "execution_mode": "FULL_DECODE_ONLY graph",
            },
            "cell_configuration": cells[cell_dir.name],
            "workload_source": {
                **source_snapshot,
            },
            "raw_files": files,
        }
        manifest_path = arm_dir / "run-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        entries.append(
            {
                "repetition": repetition,
                "cell": cell_dir.name,
                "arm": arm_name,
                "manifest": str(manifest_path.relative_to(root)),
                "manifest_sha256": sha256(manifest_path),
            }
        )
    index = {
        "schema": "sage-mate.bidkv-evidence-index/v1",
        "suite": str(root),
        "suite_time_utc": {"started": started, "finished": finished},
        "entries": entries,
        "limitations": [
            "manifests were derived after the run",
            "source dirty state and exact per-arm wall-clock timestamps were not captured",
            "legacy workload artifacts retain only output prefixes, not full output text",
        ],
    }
    index_path = root / "evidence-index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suites", nargs="+", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()
    for suite in args.suites:
        index = write_index(suite.resolve(), args.source_root.resolve())
        print(f"{suite}: indexed {len(index['entries'])} arms")


if __name__ == "__main__":
    main()
