"""The continuation cannot allocate devices after a failed control arm."""

import json
from unittest.mock import patch

import pytest
import run_next_arm as continuation


@pytest.mark.parametrize("released", [False, True])
def test_failed_native_prevents_candidate_start(tmp_path, released):
    (tmp_path / "receipts").mkdir()
    native = tmp_path / "runs/native-r1"
    native.mkdir(parents=True)
    (native / "status.json").write_text(
        json.dumps({"passed": False, "release": {"released": released}})
    )
    with (
        patch.object(continuation, "ROOT", tmp_path),
        patch.object(continuation.os, "chdir"),
        patch.object(continuation.signal, "signal"),
        patch.object(continuation.subprocess, "run") as process,
    ):
        with pytest.raises(RuntimeError, match="Native arm failed"):
            continuation.main()
        process.assert_not_called()
    receipt = json.loads((tmp_path / "receipts/bidkv-continuation.json").read_text())
    assert receipt["stage"] == "failed"
