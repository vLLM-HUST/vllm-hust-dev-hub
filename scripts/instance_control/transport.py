"""Host-private transport for the instance transaction controller.

This module authenticates a local operator by the ownership and mode of a fixed
host configuration plus the process' real euid.  It deliberately has no dynamic
backend imports: product backends are installed by trusted server code through
``backend_registry`` and are never named into existence by a wire request.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import time

from .controller import ACTIONS, TERMINAL, Controller
from .schema import ControlError, DeploymentSpec, decode, fields, hash_value, identifier, require
from .store import Store

PROTOCOL = "vllm-hust.instance-control/v1"
CONFIG_SCHEMA = "vllm-hust.instance-control-host/v1"
PARAMETERS = {
    "inspect": "instance_id",
    "plan": "instance_id candidate_id deployment_action",
    "approve": "plan_id",
    "cancel_plan": "plan_id",
    "apply": "plan_id approval",
    "disable": "plan_id approval",
    "rollback": "plan_id approval",
    "operation_status": "operation_id",
    "recover_approve": "operation_id",
    "recover": "operation_id approval",
}


def validate_request(value: dict) -> dict:
    require(
        isinstance(value, dict)
        and isinstance(value.get("action"), str)
        and value["action"] in PARAMETERS,
        "invalid_action",
    )
    action = value["action"]
    fields(value, "schema action " + PARAMETERS[action])
    require(value["schema"] == PROTOCOL, "unsupported_protocol")
    for key in ("instance_id", "candidate_id"):
        if key in value:
            identifier(value[key])
    if "plan_id" in value:
        hash_value(value["plan_id"])
    if "operation_id" in value:
        hash_value(value["operation_id"], 32)
    if "deployment_action" in value:
        require(
            isinstance(value["deployment_action"], str)
            and value["deployment_action"] in ACTIONS,
            "invalid_deployment_action",
        )
    if "approval" in value:
        require(
            isinstance(value["approval"], str) and 32 <= len(value["approval"]) <= 128,
            "invalid_approval",
        )
    return value


def _private_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid in {0, os.geteuid()}
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_size <= 65536,
            "untrusted_control_configuration",
        )
        data = os.read(descriptor, 65537)
    finally:
        os.close(descriptor)
    require(len(data) <= 65536, "untrusted_control_configuration")
    return data


def load_configuration(path_text: str) -> dict:
    path = Path(path_text)
    require(
        path_text
        and path.is_absolute()
        and path.resolve() == path
        and path != Path("/"),
        "control_configuration_required",
    )
    try:
        value = decode(_private_file(path).decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ControlError("control_configuration_unavailable") from exc
    fields(value, "schema enabled state_directory administrator_uids backend_ids candidates")
    require(
        value["schema"] == CONFIG_SCHEMA and type(value["enabled"]) is bool,
        "invalid_control_configuration",
    )
    state = Path(value["state_directory"])
    require(
        state.is_absolute() and state.resolve() == state and state != Path("/"),
        "invalid_control_configuration",
    )
    require(
        isinstance(value["administrator_uids"], list)
        and value["administrator_uids"]
        and all(type(uid) is int and uid >= 0 for uid in value["administrator_uids"])
        and len(set(value["administrator_uids"])) == len(value["administrator_uids"]),
        "invalid_control_configuration",
    )
    require(
        isinstance(value["backend_ids"], list)
        and all(isinstance(item, str) for item in value["backend_ids"]),
        "invalid_control_configuration",
    )
    for item in value["backend_ids"]:
        identifier(item)
    require(len(set(value["backend_ids"])) == len(value["backend_ids"]),
            "invalid_control_configuration")
    require(isinstance(value["candidates"], dict), "invalid_control_configuration")
    for candidate_id, spec_hash in value["candidates"].items():
        identifier(candidate_id)
        hash_value(spec_hash)
    return value


class ControlTransport:
    """Strict request dispatcher around one durable Controller authority."""

    def __init__(self, configuration: dict, backend_registry: dict | None = None,
                 *, clock=time.time):
        self.configuration = configuration
        self.clock = clock
        self.enabled = configuration["enabled"] is True
        self.admin_uids = frozenset(configuration["administrator_uids"])
        require(os.geteuid() in self.admin_uids, "administrator_os_identity_required")
        available = dict(backend_registry or {})
        # Configuration is an allowlist, not an import or factory mechanism.
        self.backends = {
            backend_id: available[backend_id]
            for backend_id in configuration["backend_ids"]
            if backend_id in available
        }
        self.store = Store(configuration["state_directory"])
        self.controller = Controller(
            self.store,
            self.backends,
            admin_uids=self.admin_uids,
            enabled=self.enabled,
            clock=clock,
        )

    @classmethod
    def open(cls, path_text: str, backend_registry: dict | None = None,
             *, clock=time.time):
        return cls(load_configuration(path_text), backend_registry, clock=clock)

    def _registration(self, instance_id: str):
        try:
            registration = self.store.read("registration", instance_id)
            instance = self.store.read("instance", instance_id)
        except ControlError as exc:
            if str(exc) == "not_found":
                return None, None
            raise
        return registration, instance

    def _status(self, instance_id: str, *, refresh: bool) -> dict:
        registration, instance = self._registration(instance_id)
        if registration is None:
            return {
                "protocol": PROTOCOL,
                "authorityAvailable": True,
                "enabled": self.enabled,
                "instanceId": instance_id,
                "instanceRegistered": False,
                "productionBackendQualified": False,
                "lifecycleAvailable": False,
                "operationsAccepting": False,
                "reason": "instance_not_registered",
            }
        backend = self.backends.get(registration["backend_id"])
        qualified = False
        if backend is not None:
            try:
                spec = DeploymentSpec.freeze(self.store.read("spec", instance["spec"]))
                qualified = backend.qualify(registration, spec) is True
            except (ControlError, OSError, ValueError):
                qualified = False
        operations_accepting = (
            self.enabled
            and qualified
            and instance["status"] == "ready"
            and instance["operation"] is None
        )
        base = {
            "protocol": PROTOCOL,
            "authorityAvailable": True,
            "enabled": self.enabled,
            "instanceId": instance_id,
            "instanceRegistered": True,
            "generation": instance["generation"],
            "fence": instance["fence"],
            "specHash": instance["spec"],
            "controllerStatus": instance["status"],
            "operationId": instance["operation"],
            "productionBackendQualified": qualified,
            "lifecycleAvailable": self.enabled and qualified,
            "operationsAccepting": operations_accepting,
        }
        if not qualified:
            return {**base, "reason": "host_backend_not_qualified"}
        if instance["status"] == "recovery_required":
            return {**base, "observation": instance["observation"],
                    "reason": "recovery_required"}
        if instance["operation"] is not None:
            return {**base, "observation": instance["observation"],
                    "reason": "operation_in_progress"}
        if not self.enabled:
            return {**base, "observation": instance["observation"],
                    "reason": "new_operations_disabled"}
        if refresh:
            observed = backend.inspect(registration)
            self.controller._observation(observed, instance_id, instance["spec"])
            return {**base, "observation": observed, "reason": "ready"}
        return {**base, "observation": instance["observation"], "reason": "ready"}

    def _operation(self, operation_id: str) -> dict:
        operation = self.store.read("operation", operation_id)
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT seq,phase,value FROM events WHERE operation=? ORDER BY seq",
                (operation_id,),
            ).fetchall()
        return {
            "protocol": PROTOCOL,
            "authorityAvailable": True,
            "operation": operation,
            "terminal": operation["phase"] in TERMINAL,
            "events": [
                {"sequence": row["seq"], "phase": row["phase"], "value": decode(row["value"])}
                for row in rows
            ],
        }

    def dispatch(self, request: dict) -> dict:
        request = validate_request(request)
        action = request["action"]
        if action == "inspect":
            return self._status(request["instance_id"], refresh=True)
        if action == "operation_status":
            return self._operation(request["operation_id"])
        if action == "cancel_plan":
            cancellation = self.controller.cancel_plan(request["plan_id"])
            return {"protocol": PROTOCOL, "authorityAvailable": True,
                    "cancellation": cancellation}
        if action == "recover_approve":
            approval = self.controller.approve_recovery(request["operation_id"])
            return {"protocol": PROTOCOL, "authorityAvailable": True,
                    "operationId": request["operation_id"], "approval": approval}
        if action == "recover":
            result = self.controller.recover(request["operation_id"], request["approval"])
            return {"protocol": PROTOCOL, "authorityAvailable": True,
                    "operation": result,
                    "status": self._status(result["instance_id"], refresh=False)}
        require(self.enabled, "new_operations_disabled")
        if action == "plan":
            candidate_id = request["candidate_id"]
            require(candidate_id in self.configuration["candidates"], "candidate_not_registered")
            candidate_hash = self.configuration["candidates"][candidate_id]
            candidate = self.store.read("spec", candidate_hash)
            plan = self.controller.plan(
                request["instance_id"], request["deployment_action"], candidate
            )
            return {"protocol": PROTOCOL, "authorityAvailable": True, "plan": plan}
        if action == "approve":
            approval = self.controller.approve(request["plan_id"])
            return {"protocol": PROTOCOL, "authorityAvailable": True,
                    "planId": request["plan_id"], "approval": approval}
        if action in ACTIONS:
            operation = self.controller.begin(
                request["plan_id"], request["approval"], expected_action=action
            )
            result = self.controller.execute(operation)
            return {"protocol": PROTOCOL, "authorityAvailable": True,
                    "operation": result,
                    "status": self._status(result["instance_id"], refresh=False)}
        raise ControlError("unsupported_action")
