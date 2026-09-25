"""Preparation must preserve topology/flags and pin every imported source."""

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace


def test_prepare_keeps_all_arms_matched_and_records_imported_sources(
    tmp_path, monkeypatch
):
    path = Path(__file__).with_name("prepare.py")
    spec = importlib.util.spec_from_file_location("dla_prepare", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base, old, root = tmp_path, tmp_path / "phase2", tmp_path / "phase4"
    old.mkdir()
    root.mkdir()
    for key, value in (("BASE", base), ("OLD", old), ("ROOT", root)):
        monkeypatch.setattr(module, key, value)
    monkeypatch.setattr(module.socket, "gethostname", lambda: module.POD)
    monkeypatch.setitem(sys.modules, "qualify", SimpleNamespace(owners=lambda: []))
    (base / "model-manifest.json").write_text("{}")
    (base / "prepared").mkdir()
    workload = base / "prepared/qwen35.json"
    workload.write_text("fixture workload")
    digest = module.digest
    monkeypatch.setattr(
        module,
        "digest",
        lambda p: (
            "aa23f49e08a946d94eaab21307e9e015140cc8598adfbd5f7e244bdded7b17d0"
            if p == workload
            else digest(p)
        ),
    )
    (old / "pipeline_worker.py").write_text("# fixture shared worker\n")
    (old / "manifest.json").write_text(
        json.dumps(
            {"sha256": {"pipeline_worker.py": digest(old / "pipeline_worker.py")}}
        )
    )
    (old / "metadata-nativepp.json").write_text(
        json.dumps(
            {
                "environment": {},
                "source_commits_are_bases": True,
                "source_patches_sha256": {"core-qualified.patch.gz": "old"},
                "runtime_common_changes": "shared runtime",
            }
        )
    )
    (old / "supervisord.conf").write_text(
        f"[supervisord]\npidfile={old}/supervisord.pid\n[program:old]\n"
    )
    (old / "launch-nativepp.sh").write_text(f"""cd {old}
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3
export PYTHONPATH={old}/core:{old}/ascend-wheel:{old}/plugin/src
vllm serve MODEL --port 33782 --served-model-name frontier-qwen35-pp2 --tensor-parallel-size 2 --pipeline-parallel-size 2 --enable-prefix-caching --async-scheduling --speculative-config '{{"method":"mtp","num_speculative_tokens":2}}' --additional-config '{{"enable_cpu_binding":false}}'
""")
    pth = (
        base
        / ".venv/lib/python3.12/site-packages/__editable__.vllm_hust_bidkv-0.2.1.pth"
    )
    pth.parent.mkdir(parents=True)
    pth.write_text(str(base / "bidkv/src") + "\n")
    bidkv = base / "bidkv/src/bidkv/__init__.py"
    bidkv.parent.mkdir(parents=True)
    bidkv.write_text("# fixture BidKV\n")
    lock = {}
    for name, revision, filename in (
        ("core", module.CORE, "vllm/__init__.py"),
        ("plugin", module.DLA, "src/dla/__init__.py"),
    ):
        archive_path = root / f"{name}-source.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            data = b"# fixture source\n"
            info = tarfile.TarInfo(filename)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        lock[name] = dict(
            revision=revision, archive=archive_path.name, sha256=digest(archive_path)
        )
    (root / "source-lock.json").write_text(json.dumps(lock))
    (root / "core-output-budget.patch.gz").write_bytes(b"fixture patch")
    module.main()
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["software_tests_passed"] is False
    for arm in ("native", "bidkv", "dla"):
        launch = (root / f"launch-{arm}.sh").read_text()
        assert "--pipeline-parallel-size 1" in launch
        assert "--enable-prefix-caching --async-scheduling" in launch
        assert '"num_speculative_tokens":2' in launch
        assert ("--scheduler-reserve-output-budget" in launch) == (arm == "dla")
        assert ('"dla_exact_output_budgets":true' in launch) == (arm == "dla")
        metadata = json.loads((root / f"metadata-{arm}.json").read_text())
        assert metadata["serving_chips"] == 2
        assert "source_commits_are_bases" not in metadata
        assert "core-qualified.patch.gz" not in metadata["source_patches_sha256"]
        assert (
            metadata["runtime_source_files"]["../bidkv/src/bidkv/__init__.py"]
            == hashlib.sha256(bidkv.read_bytes()).hexdigest()
        )
        assert (
            metadata["runtime_source_files"]["../phase2/pipeline_worker.py"]
            == manifest["sha256"]["../phase2/pipeline_worker.py"]
        )
    assert "[program:campaign]" in (root / "supervisord.conf").read_text()
