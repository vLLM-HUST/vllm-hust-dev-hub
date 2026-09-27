"""Lifecycle backend contract and explicit durable simulation implementation."""

from typing import Protocol

from .schema import ControlError, decode, require


class EffectInProgress(ControlError):
    """Executor still owns the lock; compensation must not run concurrently."""


class LifecycleBackend(Protocol):
    """Host-installed objects only; never selected/imported from a wire request.

    qualify must prove exclusive resource ownership, immutable launch capture and
    bounded recovery, not trust a receipt supplied by a client. inspect returns a
    stable identity+state snapshot (no timestamps). apply compares the complete
    baseline immediately before effects. restore may touch only that baseline or
    this operation's resource; foreign occupants must fail closed. Both return
    verified observations and honor the monotonic operation fence. All lifecycle
    writers must participate in worker_guard; queued systemctl/Docker operations
    and detached child writers are not qualified by a SQLite lock.
    """

    def qualify(self, instance_id, profile) -> bool: ...
    def inspect(self, instance_id) -> dict: ...
    def apply(self, instance_id, operation, *, worker_fd=None) -> dict: ...
    def restore(self, instance_id, operation, *, worker_fd=None) -> dict: ...


class SimulationBackend:
    """Separate durable resource DB emulates an external supervisor, no processes.

    Explicitly opt-in and reports evidence=simulation. Not inference evidence.
    """

    def __init__(self, store, *, fault=lambda phase: None):
        self.store = store
        self.fault = fault

    def qualify(self, instance_id, profile):
        return profile["backend_id"] == "simulation" and all(
            resource.startswith("simulation:") for resource in profile["resources"]
        )

    @staticmethod
    def _initial():
        return {"state": "stopped", "identity": None, "evidence": "simulation"}

    def inspect(self, instance_id):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT value FROM documents WHERE kind='sim_resource' AND id=?",
                (instance_id,),
            ).fetchone()
            return decode(row[0])["observation"] if row else self._initial()

    def _change(self, instance_id, operation, restore):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT value FROM documents WHERE kind='sim_resource' AND id=?",
                (instance_id,),
            ).fetchone()
            resource = (
                decode(row[0])
                if row
                else {"observation": self._initial(), "operation": None, "fence": 0}
            )
            require(resource["fence"] <= operation["fence"], "fence_lost")
            observed = resource["observation"]
            require(
                observed == operation["baseline"]
                or (restore and resource["operation"] == operation["id"]),
                "foreign_resource",
            )
            desired = (
                operation["baseline"]["state"] if restore else operation["desired"]
            )
            observation = {
                "state": desired,
                "identity": operation["id"] + ("-restore" if restore else "")
                if desired == "running"
                else None,
                "evidence": "simulation",
            }
            if restore and observed == operation["baseline"]:
                observation = observed
            self.store.put(
                db,
                "sim_resource",
                instance_id,
                {
                    "observation": observation,
                    "operation": operation["id"],
                    "fence": operation["fence"],
                },
            )
        self.fault("restore" if restore else "apply")
        return observation

    def apply(self, instance_id, operation, *, worker_fd=None):
        return self._change(instance_id, operation, False)

    def restore(self, instance_id, operation, *, worker_fd=None):
        return self._change(instance_id, operation, True)
