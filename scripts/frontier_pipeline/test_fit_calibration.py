"""Calibration rejects missing provenance and evaluates unseen rows."""

import json
from pathlib import Path
import importlib.util

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "fit_calibration", Path(__file__).with_name("fit_calibration.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def profile(path, change_holdout=False):
    lines = []
    for i in range(100):
        n = 1 + i % 16
        ctx = n * (1024 + 128 * (i % 11))
        cost = 2 * n + ctx * 0.0001 + 3
        if change_holdout and i >= 70:
            cost *= 10
        for kind in ("execute", "sample"):
            lines.append(
                json.dumps(
                    dict(
                        step=i,
                        kind=kind,
                        pp_rank=0,
                        tp_rank=0,
                        request_num=n,
                        aggregated_ctx_length=ctx,
                        decode_only=True,
                        elapsed_ms=cost / 2,
                    )
                )
            )
    path.write_text("\n".join(lines) + "\n")


def test_known_positive_model_predicts_unseen_rows(tmp_path):
    p = tmp_path / "rank-0.jsonl"
    profile(p)
    _, coefficients, report = module.fit_rank(p)
    assert report["passed"]
    np.testing.assert_allclose(coefficients, [2, 0.0001, 3], rtol=1e-8)


def test_holdout_shift_is_rejected(tmp_path):
    p = tmp_path / "rank-0.jsonl"
    profile(p, True)
    assert not module.fit_rank(p)[2]["passed"]


def test_missing_sample_cannot_be_fitted(tmp_path):
    p = tmp_path / "rank-0.jsonl"
    profile(p)
    p.write_text("\n".join(p.read_text().splitlines()[:-1]) + "\n")
    with pytest.raises(ValueError, match="Incomplete"):
        module.fit_rank(p)
