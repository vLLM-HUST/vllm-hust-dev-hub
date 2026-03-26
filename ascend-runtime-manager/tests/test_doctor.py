from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hust_ascend_manager import doctor


def test_collect_runtime_lib_dirs_includes_nonstandard_layout(tmp_path: Path):
    root = tmp_path / "ascend-toolkit.bak.8.1" / "latest"
    (root / "runtime/lib64").mkdir(parents=True)
    (root / "compiler/lib64").mkdir(parents=True)
    (root / "aarch64-linux/lib64").mkdir(parents=True)
    (root / "opp/built-in/op_impl/ai_core/tbe/op_tiling").mkdir(parents=True)
    hccl_lib = root / "aarch64-linux/lib64/libhccl.so"
    hccl_lib.write_text("")

    with (
        patch("hust_ascend_manager.doctor._find_hccl", return_value=str(hccl_lib)),
        patch("hust_ascend_manager.doctor._ascend_has_stream_attr", return_value=True),
        patch("hust_ascend_manager.doctor._find_atb_lib_dir", return_value=None),
    ):
        env = doctor.build_env_dict(ascend_root=str(root))

    lib_dirs = env["LD_LIBRARY_PATH"].split(":")

    assert str(root / "runtime/lib64") in lib_dirs
    assert str(root / "compiler/lib64") in lib_dirs
    assert str(root / "aarch64-linux/lib64") in lib_dirs
    assert str(root / "opp/built-in/op_impl/ai_core/tbe/op_tiling") in lib_dirs
    assert len(lib_dirs) == len(set(lib_dirs))


def test_collect_report_includes_manager_import_probe(tmp_path: Path):
    toolkit = tmp_path / "ascend" / "latest"
    (toolkit / "runtime").mkdir(parents=True)
    (toolkit / "runtime/version.info").write_text("version=8.5.0\n")

    fake_env = {
        "ASCEND_HOME_PATH": str(toolkit),
        "ASCEND_OPP_PATH": f"{toolkit}/opp",
        "ASCEND_AICPU_PATH": str(toolkit),
        "LD_LIBRARY_PATH": f"{toolkit}/runtime/lib64",
        "TORCH_DEVICE_BACKEND_AUTOLOAD": "0",
        "HUST_ASCEND_RUNTIME_VERSION": "8.5.0",
        "HUST_ASCEND_HAS_STREAM_ATTR": "1",
    }
    with (
        patch("hust_ascend_manager.doctor._find_toolkit_root", return_value=str(toolkit)),
        patch("hust_ascend_manager.doctor._find_hccl", return_value=f"{toolkit}/lib64/libhccl.so"),
        patch("hust_ascend_manager.doctor._run", return_value=(0, "", "")),
        patch("hust_ascend_manager.doctor._ascend_has_stream_attr", return_value=True),
        patch("hust_ascend_manager.doctor._find_atb_set_env", return_value=None),
        patch("hust_ascend_manager.doctor._pip_version", side_effect=["2.9.0", "2.9.0"]),
        patch("hust_ascend_manager.doctor._read_os_release", return_value={}),
        patch("hust_ascend_manager.doctor.build_env_dict", return_value=fake_env),
        patch("hust_ascend_manager.doctor._probe_torch_npu_import", return_value=(True, None)),
    ):
        report = doctor.collect_report()

    assert report["ascend"]["manager_env_torch_npu_import_ok"] is True
    assert report["ascend"]["manager_env_torch_npu_import_error"] is None
    assert report["ascend"]["manager_env_ld_library_path"] == fake_env["LD_LIBRARY_PATH"]


def test_collect_report_tolerates_incomplete_runtime_env(tmp_path: Path):
    toolkit = tmp_path / "ascend" / "latest"
    (toolkit / "runtime/lib64").mkdir(parents=True)
    (toolkit / "runtime/version.info").write_text("version=8.5.0\n")

    with (
        patch("hust_ascend_manager.doctor._find_toolkit_root", return_value=str(toolkit)),
        patch("hust_ascend_manager.doctor._find_hccl", return_value=None),
        patch("hust_ascend_manager.doctor._run", return_value=(0, "", "")),
        patch("hust_ascend_manager.doctor._ascend_has_stream_attr", return_value=False),
        patch("hust_ascend_manager.doctor._find_atb_set_env", return_value=None),
        patch("hust_ascend_manager.doctor._pip_version", side_effect=[None, None]),
        patch("hust_ascend_manager.doctor._read_os_release", return_value={}),
    ):
        report = doctor.collect_report()

    assert report["ascend"]["manager_env_torch_npu_import_ok"] is False
    assert "libhccl.so" in report["ascend"]["manager_env_torch_npu_import_error"]
    assert report["ascend"]["manager_env_ld_library_path"] is None
