"""Record actual capsule integration tests before allowing measurements."""

import hashlib
import json
import shlex
import socket
import subprocess
import time

from prepare import BASE, POD, ROOT
from qualify import owners, write


def verify_sources(manifest):
    for name, expected in manifest["sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Source identity changed: {name}")


def main():
    if socket.gethostname() != POD or owners():
        raise RuntimeError("Requires the assigned container with released devices")
    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    verify_sources(manifest)
    if manifest["software_tests_passed"]:
        raise RuntimeError(
            "Existing successful software receipt; do not rerun silently"
        )
    launch = (ROOT / "launch-native.sh").read_text()
    prefix, delimiter, _ = launch.partition("\nexec ")
    if not delimiter:
        raise RuntimeError("Cannot identify launcher environment")
    command = [
        str(BASE / ".venv/bin/python"),
        "-m",
        "pytest",
        "--import-mode=importlib",
        str(ROOT / "test_runtime_integration.py"),
        "-q",
    ]
    out = ROOT / "receipts/software-integration"
    out.mkdir(exist_ok=False)
    receipt = dict(
        passed=False,
        kind="actual-runtime-software-test-not-performance",
        command=command,
        started=time.time(),
    )
    write(out / "status.json", receipt)
    try:
        with (out / "pytest.log").open("w") as log:
            result = subprocess.run(
                ["/bin/bash", "-c", prefix + "\nexec " + shlex.join(command)],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
            )
        receipt["exit_code"] = result.returncode
        verify_sources(manifest)
        if result.returncode:
            raise RuntimeError(
                "Actual runtime integration tests failed; inspect pytest.log"
            )
        remaining = owners()
        receipt["remaining_device_owners"] = remaining
        if remaining:
            raise RuntimeError(
                "Software test left device owners; cannot enable campaign"
            )
        receipt["passed"] = True
        receipt["test_source_sha256"] = hashlib.sha256(
            (ROOT / "test_runtime_integration.py").read_bytes()
        ).hexdigest()
        manifest["software_tests_passed"] = True
        manifest["software_test_receipt"] = "receipts/software-integration/status.json"
        write(manifest_path, manifest)
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["finished"] = time.time()
        write(out / "status.json", receipt)


if __name__ == "__main__":
    main()
