"""Host-only immutable production allowlist. Empty and disabled by default."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from .schema import decode, digest, fields, hash_value, identifier, path, require
from .transport import _private_file


def trusted_parents(p):
    for parent in p.parents:
        info = parent.stat()
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid in {0, os.geteuid()}
            and (info.st_mode & 0o022 == 0 or sticky_root),
            "unsafe_parent_directory",
        )


def artifact_sha(filename):
    p = Path(filename)
    require(p.is_absolute() and p.resolve() == p, "unsafe_artifact")
    trusted_parents(p)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid in {0, os.geteuid()}
            and info.st_mode & 0o022 == 0,
            "unsafe_artifact",
        )
        value = hashlib.sha256()
        while chunk := os.read(fd, 65536):
            value.update(chunk)
        return value.hexdigest()
    finally:
        os.close(fd)


@dataclass(frozen=True)
class ProductionPolicy:
    filename: str
    enabled: bool
    executor_uid: int
    state_directory: str
    targets: dict

    @classmethod
    def load(cls, filename):
        p = Path(filename)
        require(p.is_absolute() and p.resolve() == p, "unsafe_policy")
        trusted_parents(p)
        value = decode(_private_file(p))
        fields(value, "schema enabled executor_uid state_directory targets")
        path(value["state_directory"])
        require(
            value["schema"] == "vllm-hust.production-backend/v1"
            and type(value["enabled"]) is bool
            and type(value["executor_uid"]) is int
            and value["executor_uid"] == os.geteuid()
            and isinstance(value["targets"], list),
            "invalid_production_policy",
        )
        targets = {}
        resources = set()
        for item in value["targets"]:
            fields(
                item,
                "instance_id profile_id profile_sha256 kind name runtime_directory configuration_sha256 artifacts timeout_seconds stop_seconds health_port",
            )
            identifier(item["instance_id"])
            identifier(item["profile_id"])
            hash_value(item["profile_sha256"])
            hash_value(item["configuration_sha256"])
            path(item["runtime_directory"])
            require(
                item["kind"] in {"docker", "systemd"} and isinstance(item["name"], str),
                "invalid_target",
            )
            if item["kind"] == "docker":
                hash_value(
                    item["name"]
                )  # Exact immutable container ID, never a name/tag.
                require(item["health_port"] == 0, "docker_native_health_required")
            else:
                require(
                    re.fullmatch(
                        r"devhub-managed-[a-z0-9][a-z0-9.-]{0,80}\.service",
                        item["name"],
                    ),
                    "unit_not_allowlisted",
                )
                require(
                    type(item["health_port"]) is int
                    and 1024 <= item["health_port"] <= 65535,
                    "invalid_health_port",
                )
            require(
                type(item["timeout_seconds"]) is int
                and 5 <= item["timeout_seconds"] <= 600
                and type(item["stop_seconds"]) is int
                and 1 <= item["stop_seconds"] < item["timeout_seconds"],
                "invalid_deadline",
            )
            require(
                isinstance(item["artifacts"], list) and item["artifacts"],
                "artifacts_required",
            )
            for artifact in item["artifacts"]:
                fields(artifact, "path sha256")
                path(artifact["path"])
                hash_value(artifact["sha256"])
            key = (item["kind"], item["runtime_directory"], item["name"])
            require(
                key not in resources and item["instance_id"] not in targets,
                "duplicate_target",
            )
            resources.add(key)
            targets[item["instance_id"]] = item
        return cls(
            str(p),
            value["enabled"],
            value["executor_uid"],
            value["state_directory"],
            targets,
        )

    def target(self, instance_id):
        require(instance_id in self.targets, "target_not_allowlisted")
        return self.targets[instance_id]

    def binding(self, instance_id):
        return digest({"uid": self.executor_uid, "target": self.target(instance_id)})

    def verify_host(self, target):
        require(os.geteuid() == self.executor_uid, "executor_identity_changed")
        root = Path(target["runtime_directory"])
        require(root.resolve() == root, "private_manager_required")
        trusted_parents(root)
        info = root.stat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == self.executor_uid
            and stat.S_IMODE(info.st_mode) == 0o700,
            "private_manager_required",
        )
        endpoint = root / ("bus" if target["kind"] == "systemd" else "docker.sock")
        info = endpoint.lstat()
        require(
            stat.S_ISSOCK(info.st_mode) and info.st_uid == self.executor_uid,
            "private_manager_required",
        )
        executable = (
            "/usr/bin/docker" if target["kind"] == "docker" else "/usr/bin/systemctl"
        )
        require(
            str(Path(executable).resolve()) in {a["path"] for a in target["artifacts"]},
            "daemon_client_not_pinned",
        )
        for artifact in target["artifacts"]:
            require(
                artifact_sha(artifact["path"]) == artifact["sha256"], "artifact_drift"
            )
