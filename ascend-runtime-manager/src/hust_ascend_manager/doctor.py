import json
import os
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip().strip('"')
    return data


def _find_toolkit_root() -> str | None:
    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix:
        candidates = [
            Path(conda_prefix) / "Ascend/cann",
            Path(conda_prefix) / "Ascend/ascend-toolkit/latest",
        ]
        for c in candidates:
            if (c / "runtime/lib64").is_dir():
                return str(c)

    candidates = [
        Path("/usr/local/Ascend/ascend-toolkit/latest"),
        Path("/usr/local/Ascend/ascend-toolkit.bak.8.1/latest"),
    ]
    for c in candidates:
        if (c / "runtime/lib64").is_dir():
            return str(c)

    ascend_root = Path("/usr/local/Ascend")
    if not ascend_root.is_dir():
        return None
    all_latest = sorted(ascend_root.glob("**/latest"))
    for c in reversed(all_latest):
        if (c / "runtime/lib64").is_dir():
            return str(c)
    return None


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in paths:
        if not item:
            continue
        normalized = str(Path(item)) if os.path.isabs(item) else item
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _find_hccl(root: str | None) -> str | None:
    if not root:
        return None
    root_path = Path(root)
    parent = root_path.parent
    checks = [
        root_path / "lib64/libhccl.so",
        parent / "hccl/lib64/libhccl.so",
        root_path / "hccl/lib64/libhccl.so",
        root_path / "compiler/lib64/libhccl.so",
    ]
    for p in checks:
        if p.exists():
            return str(p)
    for p in parent.glob("*/hccl/lib64/libhccl.so"):
        if p.exists():
            return str(p)
    return None


def _collect_runtime_lib_dirs(root: str, hccl_lib: str | None) -> list[str]:
    root_path = Path(root)
    candidates = [
        root_path / "lib64",
        root_path / "runtime/lib64",
        root_path / "compiler/lib64",
        root_path / "aarch64-linux/lib64",
        root_path / "opp/built-in/op_impl/ai_core/tbe/op_tiling",
    ]

    parent = root_path.parent
    candidates.extend(
        [
            parent / "hccl/lib64",
            parent / "compiler/lib64",
            parent / "aarch64-linux/lib64",
        ]
    )

    if hccl_lib:
        candidates.append(Path(hccl_lib).parent)
        candidates.append(Path(hccl_lib).resolve().parent)

    existing = [str(path) for path in candidates if path.is_dir()]
    return _dedupe_paths(existing)


def _ascend_has_stream_attr(root: str | None) -> bool:
    if not root:
        return False
    root_path = Path(root)
    libs = list(root_path.glob("**/lib64/libascendcl.so"))
    for lib in libs:
        rc, out, _ = _run(["strings", str(lib)])
        if rc == 0 and "aclrtSetStreamAttribute" in out:
            return True
    return False


def _pip_version(pkg: str) -> str | None:
    rc, out, _ = _run(["python", "-m", "pip", "show", pkg])
    if rc != 0:
        return None
    m = re.search(r"^Version:\s*(.+)$", out, flags=re.MULTILINE)
    return m.group(1).strip() if m else None


def _find_atb_lib_dir(root: str | None = None) -> str | None:
    candidates: list[Path] = []

    if root:
        root_path = Path(root)
        root_parent = root_path.parent
        candidates.extend(
            [
                root_path / "nnal/atb/latest/atb/cxx_abi_1/lib",
                root_path / "nnal/atb/atb/cxx_abi_1/lib",
                root_parent / "nnal/atb/latest/atb/cxx_abi_1/lib",
                root_parent / "nnal/atb/atb/cxx_abi_1/lib",
                root_parent / "nnal/atb/8.5.0/atb/cxx_abi_1/lib",
            ]
        )

    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix:
        candidates.extend(
            [
                Path(conda_prefix) / "Ascend/cann/nnal/atb/latest/atb/cxx_abi_1/lib",
                Path(conda_prefix) / "Ascend/cann/nnal/atb/atb/cxx_abi_1/lib",
            ]
        )

    candidates = [
        *candidates,
        Path("/usr/local/Ascend/nnal/atb/latest/atb/cxx_abi_1/lib"),
    ]
    if Path("/usr/local/Ascend/nnal/atb").exists():
        candidates.extend(Path("/usr/local/Ascend/nnal/atb").glob("*/atb/cxx_abi_1/lib"))
    for c in candidates:
        if (c / "libatb.so").exists():
            return str(c)
    return None


def _find_atb_set_env(root: str | None = None) -> str | None:
    candidates: list[Path] = []

    if root:
        root_path = Path(root)
        root_parent = root_path.parent
        candidates.extend(
            [
                root_path / "nnal/atb/set_env.sh",
                root_path / "nnal/atb/latest/set_env.sh",
                root_parent / "nnal/atb/set_env.sh",
                root_parent / "nnal/atb/latest/set_env.sh",
            ]
        )

    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix:
        candidates.extend(
            [
                Path(conda_prefix) / "Ascend/cann/nnal/atb/set_env.sh",
                Path(conda_prefix) / "Ascend/cann/nnal/atb/latest/set_env.sh",
            ]
        )

    candidates.extend(
        [
            Path("/usr/local/Ascend/nnal/atb/set_env.sh"),
            Path("/usr/local/Ascend/nnal/atb/latest/set_env.sh"),
        ]
    )

    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _sanitize_ld_path(old_ld: str) -> str:
    kept: list[str] = []
    for item in old_ld.split(":"):
        if not item:
            continue
        if "/Ascend/" in item:
            continue
        kept.append(item)
    return ":".join(kept)


def _probe_torch_npu_import(env: dict[str, str]) -> tuple[bool, str | None]:
    probe_env = os.environ.copy()
    probe_env.update(env)
    proc = subprocess.run(
        [sys.executable, "-c", "import torch_npu"],
        capture_output=True,
        text=True,
        env=probe_env,
    )
    if proc.returncode == 0:
        return True, None
    stderr = proc.stderr.strip()
    stdout = proc.stdout.strip()
    return False, stderr or stdout or f"exit code {proc.returncode}"


def build_env_dict(ascend_root: str | None = None) -> dict[str, str]:
    root = ascend_root or _find_toolkit_root()
    if not root:
        raise RuntimeError("Could not discover Ascend runtime root")

    root_path = Path(root)
    if not (root_path / "runtime/lib64").is_dir():
        raise RuntimeError(f"Invalid Ascend root, missing runtime/lib64: {root}")

    hccl_lib = _find_hccl(root)
    if not hccl_lib:
        raise RuntimeError(f"Cannot locate libhccl.so under or near: {root}")

    atb_lib = _find_atb_lib_dir(root=root)

    runtime_version = None
    version_file = root_path / "runtime/version.info"
    if version_file.exists():
        raw = version_file.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"([0-9]+(?:\.[0-9A-Za-z]+)+)", raw)
        runtime_version = m.group(1) if m else None

    has_stream_attr = _ascend_has_stream_attr(root)
    clean_ld = _sanitize_ld_path(os.getenv("LD_LIBRARY_PATH", ""))

    new_ld_parts = _collect_runtime_lib_dirs(root, hccl_lib)
    if atb_lib:
        new_ld_parts.append(atb_lib)
    if clean_ld:
        new_ld_parts.extend([item for item in clean_ld.split(":") if item])
    new_ld_parts = _dedupe_paths(new_ld_parts)

    exports: dict[str, str] = {
        "ASCEND_HOME_PATH": root,
        "ASCEND_OPP_PATH": f"{root}/opp",
        "ASCEND_AICPU_PATH": root,
        "LD_LIBRARY_PATH": ":".join(new_ld_parts),
        "TORCH_DEVICE_BACKEND_AUTOLOAD": os.getenv("TORCH_DEVICE_BACKEND_AUTOLOAD", "1"),
        "HUST_ASCEND_RUNTIME_VERSION": runtime_version or "",
        "HUST_ASCEND_HAS_STREAM_ATTR": "1" if has_stream_attr else "0",
    }

    atb_set_env = _find_atb_set_env(root=root)
    if atb_set_env:
        exports["HUST_ATB_SET_ENV"] = atb_set_env

    return exports


def build_shell_env_exports(ascend_root: str | None = None) -> str:
    exports = build_env_dict(ascend_root=ascend_root)

    lines: list[str] = []
    for key, val in exports.items():
        lines.append(f"export {key}={shlex.quote(val)}")
    return "\n".join(lines)


def collect_report() -> dict[str, Any]:
    os_release = _read_os_release()
    toolkit = _find_toolkit_root()
    hccl = _find_hccl(toolkit)
    rc, npu_smi_out, _ = _run(["npu-smi", "info"])

    runtime_version = None
    if toolkit:
        version_file = Path(toolkit) / "runtime/version.info"
        if version_file.exists():
            raw = version_file.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"([0-9]+(?:\.[0-9A-Za-z]+)+)", raw)
            runtime_version = m.group(1) if m else None

    atb_set_env = _find_atb_set_env(root=toolkit)
    env_exports = None
    torch_npu_import_ok = False
    torch_npu_import_error = None
    if toolkit:
        try:
            env_exports = build_env_dict(toolkit)
        except RuntimeError as exc:
            torch_npu_import_error = str(exc)
        else:
            torch_npu_import_ok, torch_npu_import_error = _probe_torch_npu_import(env_exports)
    else:
        torch_npu_import_error = "toolkit not found"

    return {
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "os": os_release,
        },
        "ascend": {
            "npu_smi_available": rc == 0,
            "npu_smi_summary": npu_smi_out.splitlines()[:8] if npu_smi_out else [],
            "toolkit_root": toolkit,
            "toolkit_root_exists": bool(toolkit and Path(toolkit).exists()),
            "hccl_lib": hccl,
            "runtime_version": runtime_version,
            "has_aclrt_set_stream_attribute": _ascend_has_stream_attr(toolkit),
            "atb_set_env_exists": atb_set_env is not None,
            "atb_set_env_path": atb_set_env,
            "manager_env_torch_npu_import_ok": torch_npu_import_ok,
            "manager_env_torch_npu_import_error": torch_npu_import_error,
            "manager_env_ld_library_path": env_exports["LD_LIBRARY_PATH"] if env_exports else None,
        },
        "python_stack": {
            "torch": _pip_version("torch"),
            "torch_npu": _pip_version("torch-npu"),
        },
        "recommendations": {
            "target_torch": "2.9.0",
            "target_torch_npu": "2.9.0",
            "target_cann": "8.5.0",
            "npugraph_ready": _ascend_has_stream_attr(toolkit),
        },
    }


def print_human(report: dict[str, Any]) -> None:
    ascend = report["ascend"]
    py = report["python_stack"]
    rec = report["recommendations"]

    print("[doctor] Ascend runtime report")
    print(f"  toolkit_root: {ascend['toolkit_root']}")
    print(f"  runtime_version: {ascend['runtime_version']}")
    print(f"  has_aclrtSetStreamAttribute: {ascend['has_aclrt_set_stream_attribute']}")
    print(f"  npu_smi_available: {ascend['npu_smi_available']}")
    print(f"  manager_env_torch_npu_import_ok: {ascend['manager_env_torch_npu_import_ok']}")
    if ascend["manager_env_torch_npu_import_error"]:
        print(f"  manager_env_torch_npu_import_error: {ascend['manager_env_torch_npu_import_error']}")
    print(f"  torch: {py['torch']}")
    print(f"  torch-npu: {py['torch_npu']}")
    print(f"  target torch/torch-npu/cann: {rec['target_torch']}/{rec['target_torch_npu']}/{rec['target_cann']}")


def print_json(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=True, indent=2))
