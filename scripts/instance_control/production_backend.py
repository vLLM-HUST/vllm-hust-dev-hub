"""Production adapter: expiring one-use leases, durable daemon-effect journal.

The executor inherits the lifecycle flock. Parent/client death cannot authorize a
second writer while that executor survives. An interrupted *daemon command* is
not assumed quiescent: its durable intent quarantines recovery with no effects.
"""

import fcntl
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from .production_driver import make_driver
from .production_policy import artifact_sha
from .lifecycle_backend import EffectInProgress
from .schema import ControlError, digest, require


def same_runtime(left, right):
    return {k: v for k, v in left.items() if k != "healthy"} == {
        k: v for k, v in right.items() if k != "healthy"
    }


def owned(store, db, operation_id, fence):
    operation = store.get(db, "lifecycle_operation", operation_id)
    instance = store.get(db, "lifecycle_instance", operation["instance_id"])
    require(
        operation.get("fence") == fence
        and instance["fence"] == fence
        and instance["operation_id"] == operation_id
        and operation["phase"] in {"applying", "rolling_back"},
        "fence_lost",
    )
    return operation, instance


def validate_guard(store, fd):
    require(type(fd) is int and fd >= 0, "worker_guard_required")
    try:
        actual = os.fstat(fd)
        expected = (store.root / "lifecycle-worker.lock").stat()
    except OSError as exc:
        raise ControlError("worker_guard_required") from exc
    require(
        actual.st_ino == expected.st_ino and actual.st_dev == expected.st_dev,
        "worker_guard_required",
    )
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


class ProductionBackend:
    def __init__(
        self,
        store,
        policy,
        *,
        driver_factory=make_driver,
        clock=time.time,
        monotonic=time.monotonic,
        executor=None,
    ):
        require(
            str(store.root) == policy.state_directory, "authority_directory_mismatch"
        )
        self.store = store
        self.policy = policy
        self.driver_factory = driver_factory
        self.clock = clock
        self.monotonic = monotonic
        # Injectable only in trusted tests; no dynamic import or request hook.
        self.executor = executor or self._subprocess_executor

    @property
    def new_operations_enabled(self):
        return self.policy.enabled

    def preflight(self, instance_id):
        target = self.policy.target(instance_id)
        self.policy.verify_host(target)
        driver = self.driver_factory(target)
        observed = driver.inspect(self.monotonic() + target["timeout_seconds"])
        return {
            "target_kind": target["kind"],
            "target_binding": self.policy.binding(instance_id),
            "mutations_enabled": self.policy.enabled,
            "observation": observed,
        }

    def dry_run(self, instance_id, desired):
        require(desired in {"running", "stopped"}, "invalid_desired_state")
        return {
            **self.preflight(instance_id),
            "desired": desired,
            "effect_performed": False,
            "requires_approval": True,
        }

    def qualify(self, instance_id, profile):
        target = self.policy.target(instance_id)
        require(
            profile["backend_id"] == "production"
            and digest(profile) == target["profile_sha256"],
            "profile_not_allowlisted",
        )
        self.preflight(instance_id)
        return True

    def inspect(self, instance_id):
        return self.preflight(instance_id)["observation"]

    def _mint(self, instance_id, operation, restore):
        require(restore or self.policy.enabled, "production_backend_disabled")
        target = self.policy.target(instance_id)
        nonce = secrets.token_urlsafe(32)
        with self.store.transaction() as db:
            current, instance = owned(
                self.store, db, operation["id"], operation["fence"]
            )
            require(
                current["instance_id"] == instance_id
                and instance["profile_id"] == target["profile_id"]
                and instance["policy_hash"] == target["profile_sha256"],
                "target_binding_changed",
            )
            require(
                restore == (current["phase"] == "rolling_back"), "direction_conflict"
            )
            self.store.put(
                db,
                "production_lease",
                digest(nonce),
                {
                    "operation_id": operation["id"],
                    "instance_id": instance_id,
                    "fence": operation["fence"],
                    "restore": restore,
                    "binding": self.policy.binding(instance_id),
                    "consumed": False,
                    "expires_at": self.clock() + target["timeout_seconds"],
                },
                immutable=True,
            )
            self.store.event(
                db,
                "lifecycle:" + instance_id,
                "production_lease_issued",
                {
                    "operation_id": operation["id"],
                    "fence": operation["fence"],
                    "restore": restore,
                    "at": self.clock(),
                },
            )
        return nonce

    def _subprocess_executor(self, nonce, fd):
        helper = Path(__file__).resolve().parents[1] / "instance_production_executor.py"
        # Pinning the service's install and interpreter is an installation gate;
        # never run code that another Unix principal can modify.
        artifact_sha(str(helper))
        python = str(Path(sys.executable).resolve())
        artifact_sha(python)
        command = [
            python,
            str(helper),
            "--policy",
            self.policy.filename,
            "--state",
            str(self.store.root),
            "--guard-fd",
            str(fd),
        ]
        child = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=(fd,),
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            close_fds=True,
        )
        # Nonce is only sent through an anonymous pipe, never argv/env/audit.
        try:
            child.communicate(
                nonce.encode(),
                timeout=2
                * max(
                    (t["timeout_seconds"] for t in self.policy.targets.values()),
                    default=5,
                )
                + 5,
            )
        except subprocess.TimeoutExpired as exc:
            # Do not kill a helper which may own a queued daemon operation.
            # It retains flock, and another worker must fail busy until it exits.
            raise EffectInProgress("executor_still_active") from exc
        require(child.returncode == 0, "production_effect_failed")

    def _run(self, instance_id, operation, restore, worker_fd):
        validate_guard(self.store, worker_fd)
        nonce = self._mint(instance_id, operation, restore)
        self.executor(nonce, worker_fd)
        with self.store.transaction() as db:
            owned(self.store, db, operation["id"], operation["fence"])
            record = self.store.get(db, "production_effect", instance_id)
            require(
                record["operation_id"] == operation["id"]
                and record["phase"] == "verified"
                and record["restore"] == restore
                and record["fence"] == operation["fence"],
                "effect_not_verified",
            )
            return record["observation"]

    def apply(self, instance_id, operation, *, worker_fd=None):
        return self._run(instance_id, operation, False, worker_fd)

    def restore(self, instance_id, operation, *, worker_fd=None):
        return self._run(instance_id, operation, True, worker_fd)


class ProductionExecutor:
    """Runs under inherited guard; injectable drivers are fixture-only."""

    def __init__(self, backend, *, checkpoint=lambda phase: None):
        self.backend = backend
        self.store = backend.store
        self.checkpoint = checkpoint

    def execute(self, nonce, fd):
        validate_guard(self.store, fd)
        with self.store.transaction() as db:
            lease = self.store.get(db, "production_lease", digest(nonce))
            operation, instance = owned(
                self.store, db, lease["operation_id"], lease["fence"]
            )
            require(
                not lease["consumed"] and self.backend.clock() < lease["expires_at"],
                "lease_expired_or_replayed",
            )
            require(
                lease["binding"] == self.backend.policy.binding(lease["instance_id"])
                and instance["profile_id"]
                == self.backend.policy.target(instance["id"])["profile_id"]
                and instance["policy_hash"]
                == self.backend.policy.target(instance["id"])["profile_sha256"],
                "target_binding_changed",
            )
            require(
                lease["restore"] == (operation["phase"] == "rolling_back"),
                "direction_conflict",
            )
            require(
                lease["restore"] or self.backend.policy.enabled,
                "production_backend_disabled",
            )
            lease["consumed"] = True
            self.store.put(db, "production_lease", digest(nonce), lease)
        self.checkpoint("lease_claimed")
        instance_id, restore = lease["instance_id"], lease["restore"]
        target = self.backend.policy.target(instance_id)
        self.backend.policy.verify_host(target)
        deadline = self.backend.monotonic() + target["timeout_seconds"]
        driver = self.backend.driver_factory(target)
        before = driver.inspect(deadline)
        with self.store.transaction() as db:
            owned(self.store, db, operation["id"], lease["fence"])
            row = db.execute(
                "SELECT value FROM documents WHERE kind='production_effect' AND id=?",
                (instance_id,),
            ).fetchone()
            previous = self.store.get_value(row) if row else None
            if previous is not None:
                require(
                    previous["phase"] in {"settled", "verified"},
                    "daemon_outcome_unknown",
                )
                require(
                    previous["binding"] == lease["binding"]
                    and previous["fence"] <= lease["fence"],
                    "target_binding_changed",
                )
            if restore:
                # Exact baseline or this exact operation's recorded result only.
                require(
                    same_runtime(before, operation["baseline"])
                    or previous is not None
                    and previous["operation_id"] == operation["id"]
                    and same_runtime(before, previous["observation"]),
                    "external_ownership_lost",
                )
            else:
                require(
                    same_runtime(before, operation["baseline"]),
                    "external_ownership_lost",
                )
            require(
                self.backend.clock() < lease["expires_at"], "lease_expired_or_replayed"
            )
            desired = (
                operation["baseline"]["state"] if restore else operation["desired"]
            )
            record = {
                "operation_id": operation["id"],
                "fence": lease["fence"],
                "restore": restore,
                "binding": lease["binding"],
                "before": before,
                "desired": desired,
                "phase": "intent",
                "observation": None,
            }
            no_effect = before["state"] == desired
            if no_effect:
                record.update(phase="settled", observation=before)
            self.store.put(db, "production_effect", instance_id, record)
            self.store.event(
                db,
                "lifecycle:" + instance_id,
                "production_intent",
                {
                    "operation_id": operation["id"],
                    "fence": lease["fence"],
                    "restore": restore,
                    "at": self.backend.clock(),
                },
            )
        self.checkpoint("intent")
        if not no_effect:
            with self.store.transaction() as db:
                owned(self.store, db, operation["id"], lease["fence"])
                require(
                    self.backend.clock() < lease["expires_at"],
                    "lease_expired_or_replayed",
                )
            try:
                driver.mutate(desired, deadline)
            except Exception as exc:
                # Even a CLI nonzero exit can mean connection loss after the
                # daemon accepted the request. No success ACK => no compensation.
                raise ControlError("daemon_outcome_unknown") from exc
            self.checkpoint("daemon_returned")
            observed = driver.inspect(deadline)
            with self.store.transaction() as db:
                owned(self.store, db, operation["id"], lease["fence"])
                record.update(phase="settled", observation=observed)
                self.store.put(db, "production_effect", instance_id, record)
            self.checkpoint("settled")
        observed = driver.verify(desired, deadline)
        require(
            same_runtime(observed, record["observation"]), "verification_identity_drift"
        )
        with self.store.transaction() as db:
            owned(self.store, db, operation["id"], lease["fence"])
            record.update(phase="verified", observation=observed)
            self.store.put(db, "production_effect", instance_id, record)
            self.store.event(
                db,
                "lifecycle:" + instance_id,
                "production_verified",
                {
                    "operation_id": operation["id"],
                    "fence": lease["fence"],
                    "restore": restore,
                    "at": self.backend.clock(),
                },
            )
        self.checkpoint("verified")
