"""Fixed-argv Docker/systemd primitives. Raw daemon output never leaves memory."""

import http.client
import os
from pathlib import Path
import subprocess
import time

from .host_authority import _process_start_ticks
from .production_policy import artifact_sha
from .schema import ControlError, decode, digest, require


class CommandRunner:
    def __call__(self, argv, environment, timeout):
        require(timeout > 0, "deadline_exceeded")
        try:
            result = subprocess.run(
                argv,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ControlError("command_outcome_unknown") from exc
        except OSError as exc:
            raise ControlError("command_unavailable") from exc
        require(result.returncode == 0, "daemon_command_failed")
        require(len(result.stdout) <= 4 * 1024 * 1024, "daemon_reply_too_large")
        return result.stdout


def process_identity(pid):
    require(type(pid) is int and pid > 0, "process_identity_missing")
    return {
        "pid": pid,
        "start_ticks": _process_start_ticks(pid),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }


class Driver:
    def __init__(
        self,
        target,
        *,
        runner=None,
        monotonic=time.monotonic,
        identity=process_identity,
        capture=False,
    ):
        self.target = target
        self.runner = runner or CommandRunner()
        self.monotonic = monotonic
        self.identity = identity
        self.capture = capture
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C"}

    def command(self, args, deadline):
        return self.runner(
            self.prefix + args, self.environment, max(0, deadline - self.monotonic())
        )

    def mutate(self, desired, deadline):
        self.command(self.mutation_args(desired), deadline)

    def verify(self, desired, deadline):
        while self.monotonic() < deadline:
            observation = self.inspect(deadline)
            if observation["state"] == desired and (
                desired == "stopped" or observation["healthy"]
            ):
                return observation
            time.sleep(min(0.05, max(0, deadline - self.monotonic())))
        raise ControlError("health_deadline")


class DockerDriver(Driver):
    def __init__(self, target, **kwargs):
        super().__init__(target, **kwargs)
        self.prefix = [
            "/usr/bin/docker",
            "--host",
            "unix://" + target["runtime_directory"] + "/docker.sock",
        ]

    def mutation_args(self, desired):
        return (
            ["start", self.target["name"]]
            if desired == "running"
            else [
                "stop",
                "--time",
                str(self.target["stop_seconds"]),
                self.target["name"],
            ]
        )

    def inspect(self, deadline):
        values = decode(self.command(["inspect", self.target["name"]], deadline))
        require(isinstance(values, list) and len(values) == 1, "target_missing")
        value = values[0]
        require(value["Id"] == self.target["name"], "target_identity_changed")
        config, host = value["Config"], value["HostConfig"]
        require(
            host.get("ReadonlyRootfs") is True
            and all(
                mount.get("RW") is False
                or mount.get("Type") == "tmpfs"
                and mount.get("Destination") in {"/tmp", "/run"}
                for mount in value["Mounts"]
            ),
            "mutable_container_filesystem",
        )
        for mount in value["Mounts"]:
            if mount.get("Type") == "tmpfs":
                continue
            source = mount.get("Source", "").rstrip("/")
            require(
                source
                and source != self.target["runtime_directory"]
                and source not in {"/run", "/var/run", "/proc", "/sys", "/dev"}
                and not self.target["runtime_directory"].startswith(source + "/"),
                "container_custody_unsafe",
            )
        require(
            not host.get("Privileged")
            and host.get("PidMode") != "host"
            and not (
                {"ALL", "SYS_ADMIN", "SYS_PTRACE"} & set(host.get("CapAdd") or [])
            ),
            "container_custody_unsafe",
        )
        require(
            all(
                not mount.get("Source", "").endswith(".sock")
                for mount in value["Mounts"]
            ),
            "container_custody_unsafe",
        )
        require(
            host["RestartPolicy"]["Name"] in {"no", ""}
            and host.get("AutoRemove") is False,
            "autonomous_lifecycle_writer",
        )
        require(
            config.get("Healthcheck", {}).get("Test", ["NONE"])[0] not in {"NONE", ""},
            "healthcheck_required",
        )
        snapshot = digest(
            {
                "Id": value["Id"],
                "Created": value["Created"],
                "Image": value["Image"],
                "Config": config,
                "HostConfig": host,
                "Mounts": value["Mounts"],
            }
        )
        require(
            self.capture or snapshot == self.target["configuration_sha256"],
            "configuration_drift",
        )
        state = value["State"]
        require(
            not state.get("Restarting")
            and not state.get("Paused")
            and not state.get("Dead"),
            "runtime_unstable",
        )
        running = state["Running"] is True
        require(
            running or state["Status"] in {"created", "exited"} and state["Pid"] == 0,
            "runtime_unstable",
        )
        identity = (
            {
                **self.identity(state["Pid"]),
                "started_at": state["StartedAt"],
                "restarts": value["RestartCount"],
            }
            if running
            else None
        )
        return {
            "state": "running" if running else "stopped",
            "identity": identity,
            "resource": value["Id"],
            "configuration": snapshot,
            "healthy": running and state.get("Health", {}).get("Status") == "healthy",
            "evidence": "docker-observation",
        }


PROPERTIES = (
    "Id LoadState ActiveState SubState MainPID InvocationID ControlGroup Job "
    "FragmentPath DropInPaths Type Restart KillMode NeedDaemonReload "
    "ExecStart ExecStop ExecStartPre ExecStartPost ExecStopPost ExecCondition "
    "Environment EnvironmentFiles LoadCredential TriggeredBy Triggers "
    "OnFailure OnSuccess PartOf BindsTo Conflicts Requires Wants "
    "RootDirectory RootImage DynamicUser RemainAfterExit WatchdogUSec NotifyAccess Delegate ProtectControlGroups NoNewPrivileges"
).split()
VOLATILE = {
    "ActiveState",
    "SubState",
    "MainPID",
    "InvocationID",
    "ControlGroup",
    "Job",
    "NeedDaemonReload",
}


def unit_snapshot(values, fragment_sha):
    properties = {k: v for k, v in values.items() if k not in VOLATILE}
    # systemctl appends volatile execution result metadata to ExecStart; the
    # command prefix and complete immutable fragment are the configuration.
    properties["ExecStart"] = (
        properties["ExecStart"].split(" ; start_time=", 1)[0].rstrip()
    )
    return digest({"properties": properties, "fragment_sha256": fragment_sha})


def cgroup_empty(group, *, cgroup_root=Path("/sys/fs/cgroup")):
    if not group:
        return True
    require(group.startswith("/") and ".." not in group.split("/"), "invalid_cgroup")
    directory = cgroup_root / group.lstrip("/")
    if not directory.exists():
        return True  # Kernel cannot remove a populated cgroup.
    fields = dict(
        line.split() for line in (directory / "cgroup.events").read_text().splitlines()
    )
    return fields.get("populated") == "0"


def listener_owned(port, group, *, proc_root=Path("/proc")):
    """All listeners on this local port must belong to the pinned unit cgroup."""
    require(group.startswith("/") and ".." not in group.split("/"), "invalid_cgroup")
    inodes = set()
    for network in ("tcp", "tcp6"):
        for line in (proc_root / "net" / network).read_text().splitlines()[1:]:
            columns = line.split()
            if columns[3] == "0A" and int(columns[1].split(":")[1], 16) == port:
                inodes.add(columns[9])
    if not inodes:
        return False
    owned_inodes = set()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            groups = [
                line.split(":", 2)[2]
                for line in (entry / "cgroup").read_text().splitlines()
            ]
            if not any(
                value == group or value.startswith(group + "/") for value in groups
            ):
                continue
            for fd in (entry / "fd").iterdir():
                try:
                    value = os.readlink(fd)
                except OSError:
                    continue
                if value.startswith("socket:["):
                    owned_inodes.add(value[8:-1])
        except (OSError, ValueError):
            continue
    return inodes <= owned_inodes


class SystemdDriver(Driver):
    def __init__(self, target, **kwargs):
        super().__init__(target, **kwargs)
        self.prefix = ["/usr/bin/systemctl", "--user"]
        self.last_cgroup = ""
        self.environment.update(
            XDG_RUNTIME_DIR=target["runtime_directory"],
            DBUS_SESSION_BUS_ADDRESS="unix:path="
            + target["runtime_directory"]
            + "/bus",
        )

    def mutation_args(self, desired):
        return ["start" if desired == "running" else "stop", self.target["name"]]

    def inspect(self, deadline):
        raw = self.command(
            [
                "show",
                self.target["name"],
                "--no-pager",
                "--property=" + ",".join(PROPERTIES),
            ],
            deadline,
        )
        values = {}
        for line in raw.decode().splitlines():
            key, sep, value = line.partition("=")
            require(sep and key not in values, "invalid_unit_reply")
            values[key] = value
        require(set(values) == set(PROPERTIES), "incomplete_unit_reply")
        require(
            values["Id"] == self.target["name"]
            and values["LoadState"] == "loaded"
            and values["NeedDaemonReload"] == "no"
            and values["Job"] in {"", "0"},
            "unit_not_quiescent",
        )
        require(
            values["Type"] == "notify"
            and values["Restart"] == "no"
            and values["KillMode"] == "control-group"
            and values["DynamicUser"] == "no"
            and values["RemainAfterExit"] == "no"
            and values["WatchdogUSec"] == "0"
            and values["NotifyAccess"] == "main"
            and values["Delegate"] == "no"
            and values["ProtectControlGroups"] == "yes"
            and values["NoNewPrivileges"] == "yes",
            "unsupported_unit_supervision",
        )
        for name in (
            "DropInPaths",
            "ExecStop",
            "ExecStartPre",
            "ExecStartPost",
            "ExecStopPost",
            "ExecCondition",
            "EnvironmentFiles",
            "TriggeredBy",
            "Triggers",
            "OnFailure",
            "OnSuccess",
            "PartOf",
            "BindsTo",
            "Conflicts",
            "RootDirectory",
            "RootImage",
        ):
            require(values[name] == "", "unfenced_unit_hook_or_input")
        require(
            set(values["Requires"].split()) <= {"basic.target"}
            and set(values["Wants"].split()) <= {"basic.target"},
            "unfenced_unit_dependency",
        )
        for credential in values["LoadCredential"].split():
            _, separator, source = credential.partition(":")
            require(
                separator and source in {a["path"] for a in self.target["artifacts"]},
                "credential_input_not_pinned",
            )
        fragment = values["FragmentPath"]
        require(
            fragment in {a["path"] for a in self.target["artifacts"]},
            "unit_artifact_not_pinned",
        )
        snapshot = unit_snapshot(values, artifact_sha(fragment))
        require(
            self.capture or snapshot == self.target["configuration_sha256"],
            "configuration_drift",
        )
        running = values["ActiveState"] == "active" and values["SubState"] == "running"
        stopped = (
            values["ActiveState"] in {"inactive", "failed"} and values["MainPID"] == "0"
        )
        require(running or stopped, "runtime_unstable")
        self.last_cgroup = values["ControlGroup"] or self.last_cgroup
        if stopped:
            require(cgroup_empty(self.last_cgroup), "unit_processes_remain")
        identity = (
            {
                **self.identity(int(values["MainPID"])),
                "invocation_id": values["InvocationID"],
                "cgroup": values["ControlGroup"],
            }
            if running
            else None
        )
        if running:
            require(
                values["InvocationID"] and values["ControlGroup"],
                "process_identity_missing",
            )
        observation = {
            "state": "running" if running else "stopped",
            "identity": identity,
            "resource": self.target["name"],
            "configuration": snapshot,
            "healthy": False,
            "evidence": "systemd-local-health-observation",
        }
        if running:
            observation["healthy"] = self._health(identity, deadline)
        return observation

    def _health(self, identity, deadline):
        if self.monotonic() >= deadline or not listener_owned(
            self.target["health_port"], identity["cgroup"]
        ):
            return False
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.target["health_port"],
            timeout=max(0.001, deadline - self.monotonic()),
        )
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            same_process = self.identity(identity["pid"])
            return (
                response.status == 200
                and self.monotonic() < deadline
                and all(identity[k] == v for k, v in same_process.items())
            )
        except (OSError, http.client.HTTPException, ControlError):
            return False
        finally:
            connection.close()

    def verify(self, desired, deadline):
        observation = super().verify(desired, deadline)
        require(self.inspect(deadline) == observation, "health_identity_drift")
        return observation


def make_driver(target, *, capture=False):
    return {"docker": DockerDriver, "systemd": SystemdDriver}[target["kind"]](
        target, capture=capture
    )
