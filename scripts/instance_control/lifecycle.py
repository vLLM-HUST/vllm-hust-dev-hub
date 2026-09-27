"""Product-neutral lifecycle authority. No host targets are discovered or adopted.

A trusted backend must perform bounded synchronous effects, reject foreign
identities, and fence every external writer. The worker lock serializes effects
and recovery across processes; SQLite serializes admission across API clients.
"""

from contextlib import contextmanager
import fcntl
import os
import time
import uuid

from .schema import ControlError, canonical, decode, digest, fields, identifier, require
from .lifecycle_backend import EffectInProgress

PROTOCOL = "vllm-hust.lifecycle/v1"
PARAMETERS = {
    "request": "instance_id profile_id request_id",
    "approve": "instance_id expected_generation request_id",
    "reject": "instance_id expected_generation request_id",
    "start": "instance_id expected_generation request_id",
    "stop": "instance_id expected_generation request_id",
    "transfer": "instance_id expected_generation request_id new_owner_uid",
    "recover": "instance_id expected_generation request_id",
    "status": "instance_id",
    "operation": "operation_id",
    "audit": "instance_id after_sequence",
    "list": "",
}
TERMINAL = {"committed", "rolled_back", "recovery_required"}


def validate(value):
    require(
        isinstance(value, dict)
        and isinstance(value.get("action"), str)
        and value["action"] in PARAMETERS,
        "invalid_action",
    )
    fields(value, "schema action " + PARAMETERS[value["action"]])
    require(value["schema"] == PROTOCOL, "unsupported_protocol")
    for key in ("instance_id", "profile_id", "request_id", "operation_id"):
        if key in value:
            identifier(value[key])
    for key in ("expected_generation", "new_owner_uid", "after_sequence"):
        if key in value:
            require(type(value[key]) is int and value[key] >= 0, "invalid_integer")
    return value


class Lifecycle:
    def __init__(
        self,
        store,
        profiles,
        backends,
        *,
        administrator_uids=(),
        enabled=False,
        clock=time.time,
        checkpoint=lambda phase: None,
    ):
        self.store = store
        # Copy host policy; requests cannot supply commands or change policy.
        self.profiles = decode(canonical(profiles))
        self.backends = dict(backends)
        self.admins = frozenset(administrator_uids)
        self.enabled = enabled is True
        self.clock = clock
        self.checkpoint = checkpoint
        for name, profile in self.profiles.items():
            identifier(name)
            fields(profile, "backend_id requester_uids operator_uids resources")
            identifier(profile["backend_id"])
            for key in ("requester_uids", "operator_uids"):
                require(
                    isinstance(profile[key], list)
                    and all(type(uid) is int and uid >= 0 for uid in profile[key]),
                    "invalid_profile",
                )
            require(
                isinstance(profile["resources"], list)
                and profile["resources"]
                and all(
                    isinstance(r, str) and 0 < len(r) <= 128
                    for r in profile["resources"]
                )
                and len(set(profile["resources"])) == len(profile["resources"]),
                "invalid_profile",
            )

    def _event(self, db, instance, phase, uid, **detail):
        self.store.event(
            db,
            "lifecycle:" + instance,
            phase,
            {"uid": uid, "at": self.clock(), **detail},
        )

    def _get(self, db, instance):
        return self.store.get(db, "lifecycle_instance", instance)

    def _profile(self, instance):
        profile = self.profiles.get(instance["profile_id"])
        require(
            profile is not None and digest(profile) == instance["policy_hash"],
            "policy_changed",
        )
        return profile

    def _access(self, uid, instance):
        require(
            uid in self.admins
            or uid == instance["owner_uid"]
            or uid in self._profile(instance)["operator_uids"],
            "forbidden",
        )

    def _backend(self, instance):
        profile = self._profile(instance)
        backend = self.backends.get(profile["backend_id"])
        try:
            qualified = (
                backend is not None and backend.qualify(instance["id"], profile) is True
            )
        except Exception:
            qualified = False
        require(qualified, "backend_not_qualified")
        return backend

    def _inspect(self, backend, instance_id):
        try:
            observed = backend.inspect(instance_id)
            require(
                isinstance(observed, dict)
                and observed.get("state") in {"running", "stopped"}
                and "identity" in observed
                and "evidence" in observed,
                "invalid_observation",
            )
            return observed
        except Exception as exc:
            raise ControlError("observation_unavailable") from exc

    def _public(self, instance):
        return {
            k: v for k, v in instance.items() if k not in {"baseline", "policy_hash"}
        }

    def dispatch(self, uid, value):
        """Trusted service only: uid MUST come from SO_PEERCRED, never JSON."""
        require(type(uid) is int and uid >= 0, "forbidden")
        value = validate(value)
        try:
            return self._dispatch(uid, value)
        except ControlError as exc:
            # No raw body, backend exception, token, path or launch config in audit.
            if str(exc) != "authority_busy_or_unavailable":
                with self.store.transaction() as db:
                    self._event(
                        db,
                        value.get("instance_id", "unknown"),
                        "rejected",
                        uid,
                        action=value["action"],
                        code=str(exc),
                    )
            raise

    def _dispatch(self, uid, request):
        action = request["action"]
        with self.store.transaction() as db:
            if action == "list":
                rows = db.execute(
                    "SELECT value FROM documents WHERE kind='lifecycle_instance' ORDER BY id"
                )
                result = []
                for row in rows:
                    instance = decode(row[0])
                    try:
                        self._access(uid, instance)
                    except ControlError:
                        continue
                    result.append(self._public(instance))
                return {"instances": result, "enabled": self.enabled}
            if action == "operation":
                operation = self.store.get(
                    db, "lifecycle_operation", request["operation_id"]
                )
                self._access(uid, self._get(db, operation["instance_id"]))
                return {"operation": operation}
            instance_id = request["instance_id"]
            if action in {"status", "audit"}:
                instance = self._get(db, instance_id)
                self._access(uid, instance)
                if action == "status":
                    result = {
                        "instance": self._public(instance),
                        "enabled": self.enabled,
                        "backend_available": False,
                        "observed": None,
                    }
                    if instance["state"] not in {"requested", "rejected"}:
                        try:
                            result["observed"] = self._inspect(
                                self._backend(instance), instance_id
                            )
                            result["backend_available"] = True
                            result["observed_at"] = self.clock()
                            result["drift"] = (
                                result["observed"] != instance["observation"]
                            )
                        except ControlError:
                            pass
                    return result
                rows = db.execute(
                    "SELECT seq,phase,value FROM events WHERE operation=? AND seq>? ORDER BY seq LIMIT 100",
                    ("lifecycle:" + instance_id, request["after_sequence"]),
                ).fetchall()
                return {
                    "events": [
                        {"sequence": r[0], "phase": r[1], **decode(r[2])} for r in rows
                    ]
                }

            # Durable key binds actor + exact request; checked before gate/CAS.
            key = digest({"uid": uid, "key": request["request_id"]})
            previous = db.execute(
                "SELECT value FROM documents WHERE kind='lifecycle_request' AND id=?",
                (key,),
            ).fetchone()
            if previous:
                saved = decode(previous[0])
                require(saved["hash"] == digest(request), "idempotency_conflict")
                self._access(uid, self._get(db, instance_id))
                return saved["response"]
            require(self.enabled or action == "recover", "new_operations_disabled")
            if action == "request":
                profile = self.profiles.get(request["profile_id"])
                require(profile is not None, "profile_not_registered")
                require(
                    uid in self.admins or uid in profile["requester_uids"], "forbidden"
                )
                require(
                    db.execute(
                        "SELECT 1 FROM documents WHERE kind='lifecycle_instance' AND id=?",
                        (instance_id,),
                    ).fetchone()
                    is None,
                    "instance_exists",
                )
                instance = {
                    "id": instance_id,
                    "profile_id": request["profile_id"],
                    "policy_hash": digest(profile),
                    "owner_uid": uid,
                    "generation": 0,
                    "fence": 0,
                    "state": "requested",
                    "operation_id": None,
                    "observation": None,
                }
                response = {"instance": self._public(instance)}
            else:
                instance = self._get(db, instance_id)
                self._access(uid, instance)
                require(
                    instance["generation"] == request["expected_generation"],
                    "generation_conflict",
                )
                if action in {"approve", "reject", "transfer", "recover"}:
                    require(uid in self.admins, "administrator_required")
                if action == "approve":
                    require(instance["state"] == "requested", "state_conflict")
                    profile = self._profile(instance)
                    backend = self._backend(instance)
                    observation = self._inspect(backend, instance_id)
                    require(
                        observation["state"] == "stopped",
                        "external_instance_not_stopped",
                    )
                    # Claims and registration commit atomically; retained until a
                    # future qualified decommission API, even while stopped.
                    for resource in profile["resources"]:
                        require(
                            db.execute(
                                "SELECT 1 FROM documents WHERE kind='lifecycle_resource' AND id=?",
                                (resource,),
                            ).fetchone()
                            is None,
                            "resource_conflict",
                        )
                        self.store.put(
                            db,
                            "lifecycle_resource",
                            resource,
                            {"instance_id": instance_id},
                            immutable=True,
                        )
                    require(
                        db.execute(
                            "SELECT 1 FROM documents WHERE kind='registration' AND id=?",
                            (instance_id,),
                        ).fetchone()
                        is None,
                        "legacy_authority_conflict",
                    )
                    instance.update(
                        state="stopped",
                        observation=observation,
                        observed_at=self.clock(),
                    )
                elif action == "reject":
                    require(instance["state"] == "requested", "state_conflict")
                    instance["state"] = "rejected"
                elif action == "transfer":
                    require(
                        instance["state"] in {"stopped", "running"}
                        and instance["operation_id"] is None,
                        "operation_conflict",
                    )
                    require(
                        request["new_owner_uid"]
                        in self._profile(instance)["requester_uids"],
                        "owner_not_allowed",
                    )
                    instance["owner_uid"] = request["new_owner_uid"]
                    instance["fence"] += 1
                elif action == "recover":
                    require(instance["state"] == "recovery_required", "state_conflict")
                    operation = self.store.get(
                        db, "lifecycle_operation", instance["operation_id"]
                    )
                    operation.update(phase="rolling_back", error=None)
                    self.store.put(
                        db, "lifecycle_operation", operation["id"], operation
                    )
                    instance["state"] = "recovering"
                else:
                    require(
                        instance["state"] in {"stopped", "running"}
                        and instance["operation_id"] is None,
                        "operation_conflict",
                    )
                    backend = self._backend(instance)
                    require(
                        getattr(backend, "new_operations_enabled", True) is True,
                        "backend_operations_disabled",
                    )
                    observation = self._inspect(backend, instance_id)
                    require(
                        observation == instance["observation"], "runtime_identity_drift"
                    )
                    desired = "running" if action == "start" else "stopped"
                    operation = {
                        "id": "op-" + uuid.uuid4().hex,
                        "instance_id": instance_id,
                        "action": action,
                        "uid": uid,
                        "baseline": observation,
                        "desired": desired,
                        "phase": "queued",
                        "error": None,
                        "created_at": self.clock(),
                        "policy_hash": instance["policy_hash"],
                    }
                    if observation["state"] == desired:
                        operation["phase"] = "committed"
                    else:
                        instance.update(
                            state="starting" if action == "start" else "stopping",
                            operation_id=operation["id"],
                        )
                    self.store.put(
                        db, "lifecycle_operation", operation["id"], operation
                    )
                instance["generation"] += 1
                response = {"instance": self._public(instance)}
                if action in {"start", "stop", "recover"}:
                    response["operation_id"] = operation["id"]
            self.store.put(db, "lifecycle_instance", instance_id, instance)
            self.store.put(
                db,
                "lifecycle_request",
                key,
                {"hash": digest(request), "response": response},
                immutable=True,
            )
            self._event(
                db,
                instance_id,
                action,
                uid,
                generation=instance["generation"],
                request_id=request["request_id"],
                operation_id=instance["operation_id"],
            )
            return response

    @contextmanager
    def worker_guard(self):
        """No TTL takeover. OS releases lock only when every executor is gone.

        Backends cannot spawn detached *writers* or issue queued daemon commands.
        Serving workers may outlive the executor but cannot perform lifecycle writes.
        """
        fd = os.open(
            self.store.root / "lifecycle-worker.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ControlError("worker_busy") from exc
            yield fd
        finally:
            os.close(fd)

    def tick(self):
        """Run one durable operation. On restart, uncertain effects roll back."""
        with self.worker_guard() as worker_fd:
            with self.store.transaction() as db:
                rows = db.execute(
                    "SELECT value FROM documents WHERE kind='lifecycle_operation' ORDER BY id"
                ).fetchall()
                operation = next(
                    (
                        decode(r[0])
                        for r in rows
                        if decode(r[0])["phase"] not in TERMINAL
                    ),
                    None,
                )
                if operation is None:
                    return False
                instance = self._get(db, operation["instance_id"])
                require(
                    instance["operation_id"] == operation["id"], "operation_conflict"
                )
                restore = operation["phase"] != "queued" or not self.enabled
                instance["fence"] += 1
                operation.update(
                    fence=instance["fence"],
                    phase="rolling_back" if restore else "applying",
                )
                self.store.put(db, "lifecycle_instance", instance["id"], instance)
                self.store.put(db, "lifecycle_operation", operation["id"], operation)
                self._event(
                    db,
                    instance["id"],
                    operation["phase"],
                    operation["uid"],
                    operation_id=operation["id"],
                    fence=operation["fence"],
                )
            self.checkpoint("reserved")
            try:
                backend = self._backend(instance)
                require(
                    operation["policy_hash"] == instance["policy_hash"],
                    "policy_changed",
                )
                if restore:
                    observed = backend.restore(
                        instance["id"], operation, worker_fd=worker_fd
                    )
                else:
                    observed = backend.apply(
                        instance["id"], operation, worker_fd=worker_fd
                    )
                self.checkpoint("effect")
                require(
                    observed == backend.inspect(instance["id"]), "verification_failed"
                )
                require(
                    observed["state"]
                    == (
                        operation["baseline"]["state"]
                        if restore
                        else operation["desired"]
                    ),
                    "verification_failed",
                )
                self._finish(
                    instance,
                    operation,
                    observed,
                    "rolled_back" if restore else "committed",
                )
            except EffectInProgress:
                self._finish(instance, operation, None, "recovery_required")
            except Exception:
                # Persist compensation intent before invoking the backend.
                with self.store.transaction() as db:
                    operation.update(
                        phase="rolling_back", error="effect_or_verification_failed"
                    )
                    self.store.put(
                        db, "lifecycle_operation", operation["id"], operation
                    )
                    self._event(
                        db,
                        instance["id"],
                        "rolling_back",
                        operation["uid"],
                        operation_id=operation["id"],
                    )
                self.checkpoint("rolling_back")
                try:
                    backend = self._backend(instance)
                    observed = backend.restore(
                        instance["id"], operation, worker_fd=worker_fd
                    )
                    self.checkpoint("restore_effect")
                    require(
                        observed == backend.inspect(instance["id"])
                        and observed["state"] == operation["baseline"]["state"],
                        "verification_failed",
                    )
                    self._finish(instance, operation, observed, "rolled_back")
                except Exception:
                    self._finish(instance, operation, None, "recovery_required")
            return True

    def _finish(self, instance, operation, observation, phase):
        with self.store.transaction() as db:
            current = self._get(db, instance["id"])
            require(
                current["operation_id"] == operation["id"]
                and current["fence"] == operation["fence"],
                "fence_lost",
            )
            operation["phase"] = phase
            operation["finished_at"] = self.clock()
            if phase == "recovery_required":
                current["state"] = phase
            else:
                current.update(
                    state=observation["state"],
                    observation=observation,
                    observed_at=self.clock(),
                    operation_id=None,
                )
            current["generation"] += 1
            self.store.put(db, "lifecycle_instance", instance["id"], current)
            self.store.put(db, "lifecycle_operation", operation["id"], operation)
            self._event(
                db,
                instance["id"],
                phase,
                operation["uid"],
                operation_id=operation["id"],
                generation=current["generation"],
            )
        self.checkpoint("finished")
