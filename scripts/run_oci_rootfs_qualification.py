#!/usr/bin/env python3
"""Qualify an extracted official OCI image without a nested Docker daemon.

PRoot is filesystem translation, NOT a security boundary. This path is for
trusted runtime recovery only and does not admit formal performance claims.
No host CANN/toolkit or host Python environment is mounted or inherited.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

MANIFEST = "6c183dfa86cf13ea5fa54ac8f0bcf7316c5b91e7f9774c26dc282dfd94da8ef9"
CONFIG = "cb25ae391cad9549f884b9ba57877e67b5a1da6f9200b870dde15b38df6696ba"
VENDOR = "/vllm-workspace/vllm-ascend/vllm_ascend/_cann_ops_custom/vendors/custom_transformer"


def add_image_custom_ops(env):
    # Source imports live in the project submodule, so __file__-relative
    # discovery there cannot find the image's precompiled operator package.
    # Expose the unchanged image artifacts before the process/loader starts.
    env["ASCEND_CUSTOM_OPP_PATH"] = VENDOR
    env["LD_LIBRARY_PATH"] = VENDOR + "/op_api/lib:" + env.get("LD_LIBRARY_PATH", "")
    return env


def verified_json(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"OCI object digest mismatch: {path}")
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--purpose", choices=["qualification", "matched-benchmark"], default="qualification")
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--devices", required=True)
    parser.add_argument("--proot", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.output.exists():
        parser.error("command required and output directory must be new")
    rootfs, repo = args.rootfs.resolve(), args.repo.resolve()
    manifest = verified_json(args.provenance / "arm64-manifest.json", MANIFEST)
    config = verified_json(args.provenance / "image-config.json", CONFIG)
    if manifest["config"]["digest"] != "sha256:" + CONFIG:
        raise ValueError("config is not the selected manifest's config")
    if not (args.provenance / "export-complete.json").is_file():
        raise ValueError("OCI export has not completed successfully")
    export = json.loads((args.provenance / "export-complete.json").read_text())
    if export.get("manifest") != "sha256:" + MANIFEST or export.get("returncode") != 0:
        raise ValueError("invalid export completion receipt")
    devices = args.devices.split(",")
    leased = os.environ.get("NPU_SHARE_LOGICAL_DEVICES", "").split(",")
    if not devices or any(d not in {"0", "1"} or d not in leased for d in devices):
        raise ValueError("requested devices must be part of a live timeshare lease")
    proot = str(args.proot.resolve()) if args.proot else shutil.which("proot")
    if not proot or not os.access(proot, os.X_OK):
        raise ValueError("proot unavailable")
    env = dict(item.split("=", 1) for item in config["config"]["Env"])
    add_image_custom_ops(env)
    env.update(ASCEND_RT_VISIBLE_DEVICES=args.devices,
               ASCEND_VISIBLE_DEVICES=args.devices,
               VLLM_KVDELTA_SKIP_VENDOR="1", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", PYTHONUNBUFFERED="1", HOME="/root")
    env["PYTHONPATH"] = "/workspace/kvdelta-plugin/src:/workspace/kvdelta-plugin/third_party/vllm-hust:/workspace/kvdelta-plugin/third_party/vllm-ascend-hust:" + env.get("PYTHONPATH", "")
    for name in ("VLLM_PLUGINS", "VLLM_HUST_API_KEY", "VLLM_WORKER_MULTIPROC_METHOD"):
        if name in os.environ:
            env[name] = os.environ[name]
    args.output.mkdir(parents=True)
    binds = [("/proc", "/proc"), ("/sys", "/sys"), ("/dev", "/dev"),
             ("/etc/resolv.conf", "/etc/resolv.conf"),
             ("/usr/local/Ascend/driver", "/usr/local/Ascend/driver"),
             ("/models", "/models"), (str(repo), "/workspace/kvdelta-plugin"),
             (str(args.output.resolve()), "/run/kvdelta")]
    argv = [proot, "-0", "-r", str(rootfs), "-w", "/workspace/kvdelta-plugin"]
    for source, destination in binds:
        argv.extend(["-b", f"{source}:{destination}"])
    argv.extend(["/usr/bin/env", "-i", *[f"{k}={v}" for k, v in env.items()], *command])
    receipt = dict(schema="kvdelta-oci-rootfs-qualification/v1",
                   paper_admissible=False, carrier="official-image-proot-qualification",
                   manifest="sha256:" + MANIFEST, config="sha256:" + CONFIG,
                   devices=devices, lease_id=os.environ.get("NPU_SHARE_LEASE_ID"),
                   proot_binary=proot,
                   proot_sha256=hashlib.sha256(Path(proot).read_bytes()).hexdigest(),
                   proot_seccomp_filter=True,
                   image_custom_op_vendor=VENDOR,
                   binds=binds, command=command,
                   claim_boundary="filesystem translation; not Docker isolation or formal timing")
    if args.purpose == "matched-benchmark":
        receipt.update(purpose=args.purpose, carrier="official-oci-rootfs-proot-matched/v1",
                       claim_boundary="fresh same-carrier online measurements; not native Docker timing; paper admission requires complete verified matched arms and oracle")
    def git_head(path):
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                text=True, capture_output=True, check=True)
        return result.stdout.strip()
    receipt["parent_commit"] = git_head(repo)
    receipt["runtime_commits"] = {
        name: git_head(repo / "third_party" / name) for name in
        ("vllm-hust", "vllm-ascend-hust", "vllm-hust-dev-hub",
         "ascend-runtime-manager", "triton-ascend-hust")}
    receipt["launcher_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt["source_command_files"] = {}
    for item in command:
        prefix = "/workspace/kvdelta-plugin/"
        if item.startswith(prefix):
            path = repo / item[len(prefix):]
            if path.is_file():
                receipt["source_command_files"][item] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / "launch.json").write_text(json.dumps(receipt, indent=2) + "\n")
    with (args.output / "runtime.log").open("w") as log:
        child = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True,
                                 env={"PATH": os.environ["PATH"]})
        def terminate(_signum, _frame):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
        old_handler = signal.signal(signal.SIGTERM, terminate)
        try:
            returncode = child.wait()
        finally:
            terminate(None, None)
            signal.signal(signal.SIGTERM, old_handler)
    receipt["returncode"] = returncode
    (args.output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"returncode": returncode, "output": str(args.output)}))
    return returncode


if __name__ == "__main__":
    sys.exit(main())
