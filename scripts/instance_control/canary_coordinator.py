"""Controller-backed lifecycle closure for the fixed inert CPU canary only."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import time

from .controller import Controller
from .host_authority import _process_start_ticks, peer_from_unix_socket
from .schema import ControlError, DeploymentSpec, digest, require

CANARY_ID = "inert-canary"
CANARY_COMPONENT = "dev-hub.inert-canary"


def _artifact(target):
    source = target.policy_sha256[:40]
    return {"source_sha": source, "wheel_sha256": target.policy_sha256}


def canary_spec(target, *, running: bool) -> DeploymentSpec:
    artifact = _artifact(target)
    rendered = {
        "instance_id": CANARY_ID,
        "policy_sha256": target.policy_sha256,
        "running": running,
    }
    value = {
        "schema": "vllm-hust.deployment-spec/v1",
        "image": {
            "id": "sha256:" + target.policy_sha256,
            "digest": "sha256:" + target.policy_sha256,
            "platform": "linux/arm64",
        },
        "core": artifact,
        "ascend": artifact,
        "manager": artifact,
        "witness": artifact if running else None,
        "mods": (
            [
                {
                    "id": CANARY_COMPONENT,
                    "artifact": artifact,
                    "manifest": {
                        "schema_version": "0.2-experimental",
                        "extension_id": CANARY_COMPONENT,
                    },
                }
            ]
            if running
            else []
        ),
        "model": {
            "id": "dev-hub/inert-cpu-canary",
            "revision": target.policy_sha256[:40],
            "path": target.cwd,
            "files_sha256": target.policy_sha256,
        },
        # The schema requires an explicit topology. This is a logical CPU-only
        # fixture slot and is never passed to a device runtime or launch command.
        "resources": {
            "devices": [0],
            "tp": 1,
            "pp": 1,
            "graph": {"mode": "graph", "configuration": {"capture_sizes": [1]}},
            "ports": [],
            "mounts": [],
        },
        "launch": {
            "interpreter": target.argv[0],
            "argv": list(target.argv),
            "environment": dict(target.environment),
            "working_directory": target.cwd,
            "plugin_allowlist": [CANARY_COMPONENT] if running else [],
            "resolved_options": {
                "tensor_parallel_size": 1,
                "pipeline_parallel_size": 1,
                "model": "dev-hub/inert-cpu-canary",
                "enforce_eager": False,
                "compilation_config": {"capture_sizes": [1]},
            },
        },
        "provider": {
            "id": "inert-canary",
            "source_sha": target.policy_sha256[:40],
            "configuration": {"cpu_only": True},
            "rendered": rendered,
            "rendered_sha256": digest(rendered),
            "qualification": {
                "receipt_sha256": target.policy_sha256,
                "status": "qualified",
            },
        },
        "secrets": [],
    }
    return DeploymentSpec.freeze(value)


class CanaryBackend:
    """Observation backend; the granted broker callback owns every mutation."""

    def __init__(self, adapter, target, store, *, clock=time.time):
        self.adapter = adapter
        self.target = target
        self.store = store
        self.clock = clock
        self.stopped = canary_spec(target, running=False)
        self.running = canary_spec(target, running=True)
        self._described = None
        self._resource_value = None
        self.refresh()

    def qualify(self, registration, spec):
        return registration == {
            "instance_id": CANARY_ID,
            "owner_id": "host-broker",
            "profile_id": "inert-cpu-self-test",
            "backend_id": "inert-canary",
            "actions": ["apply", "disable", "rollback"],
            "owner_uids": [os.geteuid()],
            "fencing_receipt_sha256": self.target.policy_sha256,
        } and spec.sha256 in {self.stopped.sha256, self.running.sha256}

    def _read_resource(self):
        try:
            return self.store.read("host_resource", CANARY_ID)
        except ControlError as exc:
            if str(exc) == "not_found":
                return None
            raise

    def refresh(self):
        """Refresh outside Controller transactions; commit reads this sealed view."""
        self._described = self.adapter.inspect(self.target)
        self._resource_value = self._read_resource()
        return self._described

    def inspect(self, registration):
        described = self._described
        require(described is not None, "canary_observation_unavailable")
        running = described["state"] == "running" and described["healthy"] is True
        resource = self._resource_value
        if running:
            identity = {
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "supervisor_generation": str(resource["fence"]),
                "resource_id": f"pid:{resource['pid']}:{resource['start_ticks']}",
                "started_at": str(resource["started_at"]),
                "processes": [
                    {
                        "pid": resource["pid"],
                        "start_ticks": resource["start_ticks"],
                        "role": "inert-canary",
                        "rank": None,
                    }
                ],
            }
            spec = self.running
            components = [CANARY_COMPONENT]
        else:
            ticks = _process_start_ticks(1)
            suffix = (
                "initial"
                if resource is None
                else str(resource.get("stop_operation_id", "stopped"))
            )
            identity = {
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "supervisor_generation": self.target.policy_sha256,
                "resource_id": "stopped:" + suffix,
                "started_at": str(resource.get("stopped_at", 0) if resource else 0),
                "processes": [
                    {
                        "pid": 1,
                        "start_ticks": ticks,
                        "role": "host-boot-witness",
                        "rank": None,
                    }
                ],
            }
            spec = self.stopped
            components = []
        return {
            "instance_id": CANARY_ID,
            "spec_hash": spec.sha256,
            "identity": identity,
            "captured_at": self.clock(),
            "healthy": True,
            "components_executed": components,
            "inference_verified": True,
        }

    def owns(self, registration, token, expected_identity, *, restore):
        resource = self._resource_value
        observed = self.inspect(registration)
        if observed["spec_hash"] == self.stopped.sha256:
            return resource is None or resource.get("stop_operation_id") == token["id"]
        return resource is not None and resource.get("operation_id") == token["id"]

    def deploy(self, *_args, **_kwargs):
        raise ControlError("canary_requires_granted_external_effect")

    def verify(self, registration, spec_hash, token, deadline):
        require(self.clock() < deadline, "operation_deadline")
        self.refresh()
        observed = self.inspect(registration)
        require(observed["spec_hash"] == spec_hash, "runtime_spec_drift")
        return observed

    def quiescent(self, registration, operation):
        described = self.refresh()
        return described["state"] in {"running", "stopped"}


class CanaryCoordinator:
    """Keep approvals and raw grants entirely inside the broker process."""

    def __init__(self, store, target, adapter, authority, *, clock=time.time):
        require(target.instance_id == CANARY_ID, "canary_only_target_required")
        self.store = store
        self.target = target
        self.adapter = adapter
        self.authority = authority
        self.clock = clock
        self.backend = CanaryBackend(adapter, target, store, clock=clock)
        self.controller = Controller(
            store,
            {"inert-canary": self.backend},
            admin_uids=[os.geteuid()],
            enabled=True,
            clock=clock,
        )
        self._ensure_registered()

    def _registration(self):
        return {
            "instance_id": CANARY_ID,
            "owner_id": "host-broker",
            "profile_id": "inert-cpu-self-test",
            "backend_id": "inert-canary",
            "actions": ["apply", "disable", "rollback"],
            "owner_uids": [os.geteuid()],
            "fencing_receipt_sha256": self.target.policy_sha256,
        }

    def _ensure_registered(self):
        try:
            registration = self.store.read("registration", CANARY_ID)
            require(registration == self._registration(), "canary_registration_drift")
        except ControlError as exc:
            if str(exc) != "not_found":
                raise
            require(
                self.adapter.inspect(self.target)["state"] == "stopped",
                "canary_initial_state_not_stopped",
            )
            self.controller.register(self._registration(), self.backend.stopped.value())

    @staticmethod
    def _owner_peer():
        left, right = socket.socketpair(socket.AF_UNIX)
        try:
            return peer_from_unix_socket(left)
        finally:
            left.close()
            right.close()

    def status(self):
        described = self.adapter.inspect(self.target)
        instance = self.store.read("instance", CANARY_ID)
        return {
            **described,
            "generation": instance["generation"],
            "controllerStatus": instance["status"],
            "operationId": instance["operation"],
            "effective": False,
        }

    def run(self, action: str):
        require(
            action in {"start", "stop", "restart", "rollback"},
            "lifecycle_action_not_allowed",
        )
        host_action = "stop" if action == "rollback" else action
        require(host_action in self.target.actions, "lifecycle_action_not_allowed")
        before = self.backend.refresh()
        require(
            (action == "start" and before["state"] == "stopped")
            or (
                action in {"stop", "restart", "rollback"}
                and before["state"] == "running"
            ),
            "canary_state_conflict",
        )
        candidate = (
            self.backend.running
            if action in {"start", "restart"}
            else self.backend.stopped
        )
        deployment_action = (
            {
                "start": "apply",
                "restart": "apply",
                "stop": "disable",
                "rollback": "rollback",
            }
        )[action]
        plan = self.controller.plan(
            CANARY_ID,
            deployment_action,
            candidate.value(),
            ttl=60,
            verify_seconds=30,
            recovery_seconds=120,
        )
        approval = self.controller.approve(plan["plan_id"])
        operation = self.controller.begin(plan["plan_id"], approval)
        inverse = "stop" if host_action == "start" else "start"
        forward_grant = self.authority.mint(
            operation, self.target.command_sha256(host_action), os.geteuid(), ttl=30
        )
        peer = self._owner_peer()

        def execute(grant, lifecycle_action):
            lease = self.authority.claim(
                grant, peer, self.target.command_sha256(lifecycle_action)
            )
            try:
                if lifecycle_action == "start":
                    self.adapter.start(
                        self.target, operation, lease, peer, self.authority
                    )
                elif lifecycle_action == "stop":
                    self.adapter.stop(
                        self.target, operation, lease, peer, self.authority
                    )
                else:
                    self.adapter.stop(
                        self.target, operation, lease, peer, self.authority
                    )
                    self.adapter.start(
                        self.target, operation, lease, peer, self.authority
                    )
                self.backend.refresh()
            finally:
                self.authority.retire(lease, peer)

        def restore():
            restore_action = inverse
            if host_action == "restart":
                restore_action = (
                    "restart"
                    if self.adapter.inspect(self.target)["state"] == "running"
                    else "start"
                )
            restore_grant = self.authority.mint(
                operation,
                self.target.command_sha256(restore_action),
                os.geteuid(),
                ttl=60,
            )
            execute(restore_grant, restore_action)

        result = self.controller.execute_external(
            operation,
            lambda: execute(forward_grant, host_action),
            restore,
        )
        require(result["phase"] == "committed", "canary_operation_not_committed")
        try:
            self.authority.claim(
                forward_grant, peer, self.target.command_sha256(host_action)
            )
            replay_rejected = False
        except ControlError as exc:
            replay_rejected = str(exc) == "launch_grant_expired_or_replayed"
        require(replay_rejected, "canary_grant_replay_not_rejected")
        return {
            **self.status(),
            "operationId": result["id"],
            "phase": result["phase"],
            "replayRejected": True,
        }
