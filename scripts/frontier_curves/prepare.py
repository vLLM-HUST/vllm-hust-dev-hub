"""Materialize a fresh curve campaign without mutating the qualified capsule."""

import hashlib
import json
import socket
from pathlib import Path

BASE = Path("/home/coder/frontier-mods-qwen35-20260925")
OLD = BASE / "phase2"
ROOT = BASE / "phase3"
EXPECTED_HOST = "coder-admin-shuhao-evaluation-664b765847-wfh7z"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if socket.gethostname() != EXPECTED_HOST:
        raise RuntimeError("Preparation is restricted to the user-assigned container")
    old = json.loads((OLD / "manifest.json").read_text())
    for name, expected in old["sha256"].items():
        if digest(OLD / name) != expected:
            raise RuntimeError(f"Qualified source changed: {name}")
    for name, item in json.loads((BASE / "model-manifest.json").read_text()).items():
        path = BASE / "model" / name
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise RuntimeError(f"Model changed: {name}")
    if (
        digest(BASE / "prepared/qwen35.json")
        != "aa23f49e08a946d94eaab21307e9e015140cc8598adfbd5f7e244bdded7b17d0"
    ):
        raise RuntimeError("Prepared workload changed")
    (ROOT / "receipts").mkdir(exist_ok=False)
    for arm in ("nativepp", "pipelinepp"):
        launcher = (
            (OLD / f"launch-{arm}.sh").read_text().replace(f"cd {OLD}", f"cd {ROOT}")
        )
        (ROOT / f"launch-{arm}.sh").write_text(launcher)
        metadata = json.loads((OLD / f"metadata-{arm}.json").read_text())
        metadata.update(
            pod=EXPECTED_HOST,
            pod_uid="19a77c6d-a27a-4c6e-b955-e016beca3a82",
            container_allocated_npus=4,
            launch_script_sha256=digest(ROOT / f"launch-{arm}.sh"),
            campaign="qwen35-mod-curves-20260925",
            concurrency_sweep=[1, 2, 8],
            qualification_repeated_in_current_container=True,
        )
        metadata["runtime_source_files"] = {
            "../phase2/" + name: sha
            for name, sha in metadata["runtime_source_files"].items()
        }
        (ROOT / f"metadata-{arm}.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
    config = (OLD / "supervisord.conf").read_text().replace(str(OLD), str(ROOT))
    config = config.replace(
        "--gate pipelinepp-r4 --attempt paired-measurement-r2",
        "--gate ../../phase2/receipts/pipelinepp-r4 --attempt paired-curves-r1",
    )
    (ROOT / "supervisord.conf").write_text(config)
    manifest = dict(old)
    manifest["kind"] = "real-online-matched-PP2-curve-completion"
    manifest["sha256"] = {
        "../phase2/" + name: sha for name, sha in old["sha256"].items()
    }
    for path in ROOT.iterdir():
        if path.is_file() and path.name != "manifest.json":
            manifest["sha256"][path.name] = digest(path)
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        "Prepared: qualified runtime, model and workload hashes verified; no NPU run started",
        flush=True,
    )


if __name__ == "__main__":
    main()
