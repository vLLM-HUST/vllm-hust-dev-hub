"""Stage a completed pinned Mooncake build without invoking global install hooks."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(root, attempt):
    state = json.loads((root / f"{attempt}-status.json").read_text())
    if not state.get("completed") or state.get("exit") != 0:
        raise ValueError("Refuse to stage an incomplete or failed build")
    preparation = json.loads((root / "preparation.json").read_text())
    source = Path(preparation["root"])
    build = root / "build"
    output = root / f"stage-{attempt}"
    if output.exists():
        raise FileExistsError(output)
    shared = sorted(
        p
        for p in build.rglob("*.so*")
        if p.is_file() and re.search(r"\.so(?:\.\d+)*$", p.name)
    )
    for module in ("engine", "store"):
        if not any(
            p.name == f"{module}.so" or p.name.startswith(f"{module}.") for p in shared
        ):
            raise ValueError(f"Missing compiled Python module: {module}")
    master = build / "mooncake-store/src/mooncake_master"
    if not master.is_file():
        raise ValueError("Missing compiled master")
    package = output / "python/mooncake"
    package.mkdir(parents=True)
    records = []

    def copy(origin, destination):
        digest = sha(origin)
        if destination.exists() and sha(destination) != digest:
            raise ValueError(f"Conflicting staged basename: {destination.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
        records.append(
            {
                "source": str(origin),
                "staged": str(destination.relative_to(output)),
                "sha256": digest,
            }
        )

    copy(build / "mooncake-integration/mooncake/__init__.py", package / "__init__.py")
    for path in shared:
        copy(path, package / path.name)
    for relative in (
        "allocator_ascend_npu.py",
        "fabric_allocator_utils.py",
        "shared_segment.py",
        "store/async_store.py",
    ):
        path = source / "mooncake-integration" / relative
        if path.is_file():
            copy(path, package / path.name)
    copy(master, output / "bin/mooncake_master")
    receipt = {
        "kind": "staged-source-build-not-performance",
        "preparation": preparation,
        "build_status": state,
        "files": records,
        "global_install_invoked": False,
        "qualification_passed": False,
        "scope": "Private source-built package; installed distribution metadata does not identify these binaries",
    }
    (output / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"build-r[1-9][0-9]*", args.attempt):
        parser.error("attempt must identify a recorded build-rN")
    print(stage(args.root, args.attempt))
