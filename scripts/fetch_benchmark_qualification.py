"""Materialize pinned benchmark qualification evidence into a disposable cache."""

import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

COMMIT = "4b0d2a97e3e4707d2f88659a7b00d2f0168af4e6"
BASE = "https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark"
PREFIX = "results/szyn-opencode-qwen35-20261002/django__django-15104/"


def download(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def materialize(destination: Path) -> Path:
    manifest = json.loads(
        download(f"{BASE}/{COMMIT}/archive/dev-hub-20261020/manifest.json")
    )
    packed = download(manifest["asset"]["url"])
    if (
        hashlib.sha256(packed).hexdigest() != manifest["asset"]["sha256"]
        or len(packed) != manifest["asset"]["bytes"]
    ):
        raise ValueError("Benchmark archive integrity mismatch")
    rows = [row for row in manifest["files"] if row["path"].startswith(PREFIX)]
    if not rows:
        raise ValueError("Qualification missing from pinned manifest")
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as archive:
        for row in rows:
            name = row["path"][len(PREFIX) :]
            if not name or Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("Unsafe qualification member path")
            source = row["destination"]
            if source["kind"] == "git":
                raw = download(f"{BASE}/{source['commit']}/{source['path']}")
            else:
                member = archive.getmember(source["member"])
                if not member.isfile():
                    raise ValueError("Qualification member is not a regular file")
                raw = archive.extractfile(member).read()
            if (
                hashlib.sha256(raw).hexdigest() != row["sha256"]
                or len(raw) != row["bytes"]
            ):
                raise ValueError("Qualification file integrity mismatch")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
    return destination


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(materialize(parser.parse_args().destination))
