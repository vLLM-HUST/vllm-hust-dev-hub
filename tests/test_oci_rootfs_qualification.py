import hashlib
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("rootfs_qualification", Path(__file__).resolve().parents[1] / "scripts/run_oci_rootfs_qualification.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_content_digest_required(tmp_path):
    raw = b'{"config": {}}'
    path = tmp_path / "object.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert MODULE.verified_json(path, digest) == {"config": {}}
    path.write_bytes(b'{"config": {"changed": true}}')
    with pytest.raises(ValueError, match="digest mismatch"):
        MODULE.verified_json(path, digest)


def test_command_and_new_evidence_directory_required(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["qualify", "--rootfs", str(tmp_path),
                        "--provenance", str(tmp_path), "--repo", str(tmp_path),
                        "--output", str(tmp_path), "--devices", "0", "--", "true"])
    with pytest.raises(SystemExit):
        MODULE.main()


def test_custom_operator_artifacts_come_from_image():
    env = MODULE.add_image_custom_ops({"LD_LIBRARY_PATH": "/image/framework/libs"})
    assert env["ASCEND_CUSTOM_OPP_PATH"] == MODULE.VENDOR
    assert env["LD_LIBRARY_PATH"] == MODULE.VENDOR + "/op_api/lib:/image/framework/libs"
