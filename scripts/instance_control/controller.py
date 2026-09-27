"""One authority for approved deployment changes and recovery.

Backends are trusted, host-installed objects, never imported from request fields.
Every backend mutation runs inside the same authority transaction after fence
validation. It MUST be synchronous, bounded, and leave no untracked child writer.
No Docker/systemd backend is enrolled by this module. An adapter unable to satisfy
those conditions must refuse qualification, not weaken the fence.
"""

import os
import secrets
import time
import uuid

from .schema import DeploymentSpec, digest, fields, identifier, require

TERMINAL = {"committed", "rolled_back", "failed", "ownership_lost"}
ACTIONS = {"apply", "disable", "rollback"}


class Controller:
    def __init__(self, store, backends, *, admin_uids=(), enabled=False,
                 clock=time.time, checkpoint=lambda phase: None):
        self.store = store
        self.backends = dict(backends)
        self.admin_uids = frozenset(admin_uids)
        self.enabled = enabled
        self.clock = clock
        self.checkpoint = checkpoint  # Fault injection; never supplied by a client.

    def _admin(self):
        require(os.geteuid() in self.admin_uids, "administrator_os_identity_required")

    def _gate(self):
        require(self.enabled is True, "new_operations_disabled")

    def _backend(self, registration):
        require(registration["backend_id"] in self.backends, "backend_not_qualified")
        return self.backends[registration["backend_id"]]

    def register(self, registration, baseline):
        """Explicit host-admin enrollment; never inferred from discovered services."""
        self._gate()
        self._admin()
        fields(registration, "instance_id owner_id profile_id backend_id actions owner_uids fencing_receipt_sha256")
        for name in ("instance_id", "owner_id", "profile_id", "backend_id"):
            identifier(registration[name])
        require(isinstance(registration["actions"], list)
                and all(isinstance(action, str) for action in registration["actions"])
                and set(registration["actions"]) <= ACTIONS, "invalid_action_allowlist")
        require(isinstance(registration["owner_uids"], list)
                and all(type(uid) is int and uid >= 0 for uid in registration["owner_uids"]), "invalid_owner_uids")
        from .schema import hash_value
        hash_value(registration["fencing_receipt_sha256"])
        spec = DeploymentSpec.freeze(baseline)
        backend = self._backend(registration)
        # Host receipt alone is not evidence: backend verifies external-writer
        # exclusion and capture completeness, and must fail closed if absent.
        require(backend.qualify(registration, spec) is True, "backend_not_qualified")
        observation = backend.inspect(registration)
        self._observation(observation, registration["instance_id"], spec.sha256)
        require(set(observation["components_executed"]) == {mod["id"] for mod in spec.value()["mods"]},
                "baseline_component_execution_unverified")
        with self.store.transaction() as db:
            rows = db.execute("SELECT 1 FROM documents WHERE kind='instance' AND id=?",
                              (registration["instance_id"],)).fetchone()
            require(rows is None, "instance_already_registered")
            lifecycle = db.execute("SELECT value FROM documents WHERE kind='lifecycle_instance' AND id=?",
                                   (registration["instance_id"],)).fetchone()
            require(lifecycle is None, "lifecycle_authority_conflict")
            self.store.put(db, "spec", spec.sha256, spec.value(), immutable=True)
            self.store.put(db, "registration", registration["instance_id"], registration, immutable=True)
            self.store.put(db, "instance", registration["instance_id"], {
                "generation": 0, "fence": 0, "spec": spec.sha256,
                "observation": observation, "operation": None, "status": "ready"})
            self.store.event(db, registration["instance_id"], "registered", {"spec": spec.sha256})

    def _observation(self, value, instance, spec_hash, *, execution=False):
        fields(value, "instance_id spec_hash identity captured_at healthy components_executed inference_verified")
        require(value["instance_id"] == instance and value["spec_hash"] == spec_hash, "runtime_spec_drift")
        identity = value["identity"]
        fields(identity, "boot_id supervisor_generation resource_id started_at processes")
        require(all(isinstance(identity[key], str) and identity[key] for key in
                    ("boot_id", "supervisor_generation", "resource_id", "started_at")), "incomplete_runtime_identity")
        require(isinstance(identity["processes"], list) and identity["processes"], "process_identity_required")
        for process in identity["processes"]:
            fields(process, "pid start_ticks role rank")
            require(type(process["pid"]) is int and process["pid"] > 0
                    and type(process["start_ticks"]) is int and process["start_ticks"] > 0
                    and isinstance(process["role"], str) and process["role"], "invalid_process_identity")
            require(process["rank"] is None or type(process["rank"]) is int, "invalid_rank")
        require(type(value["captured_at"]) in (float, int)
                and 0 <= self.clock() - value["captured_at"] <= 30, "stale_observation")
        require(value["healthy"] is True and value["inference_verified"] is True, "runtime_verification_failed")
        require(isinstance(value["components_executed"], list)
                and all(isinstance(item, str) for item in value["components_executed"]), "component_evidence_required")
        if execution:
            spec = DeploymentSpec.freeze(self.store.read("spec", spec_hash))
            require(set(value["components_executed"]) == {mod["id"] for mod in spec.value()["mods"]},
                    "component_execution_unverified")

    def plan(self, instance_id, action, candidate, *, ttl=300, verify_seconds=120, recovery_seconds=900):
        self._gate()
        self._admin()
        require(action in ACTIONS and type(ttl) is int and 1 <= ttl <= 600, "invalid_plan")
        require(type(verify_seconds) is int and 1 <= verify_seconds <= 600
                and type(recovery_seconds) is int and verify_seconds <= recovery_seconds <= 3600, "invalid_budget")
        spec = DeploymentSpec.freeze(candidate)
        registration = self.store.read("registration", instance_id)
        require(action in registration["actions"], "action_not_allowed")
        backend = self._backend(registration)
        require(backend.qualify(registration, spec) is True, "candidate_not_qualified")
        observed = backend.inspect(registration)
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", instance_id)
            require(current["status"] == "ready" and current["operation"] is None, "recovery_required")
            baseline = DeploymentSpec.freeze(self.store.get(db, "spec", current["spec"]))
            self._observation(observed, instance_id, baseline.sha256)
            require(observed["identity"] == current["observation"]["identity"], "runtime_identity_drift")
            require(spec.invariant() == baseline.invariant(), "model_topology_graph_or_resources_changed")
            if action == "disable":
                require(not spec.value()["mods"] and spec.value()["witness"] is None, "disable_requires_no_mod")
            if action == "rollback":
                retained = db.execute("SELECT 1 FROM documents WHERE kind='retained' AND id=?",
                                      (instance_id + ":" + spec.sha256,)).fetchone()
                require(retained is not None, "rollback_revision_not_retained")
            plan = {"instance_id": instance_id, "action": action,
                    "generation": current["generation"], "fence": current["fence"],
                    "expected_identity": observed["identity"], "baseline": baseline.sha256,
                    "candidate": spec.sha256, "created_at": self.clock(),
                    "expires_at": self.clock() + ttl, "verify_seconds": verify_seconds,
                    "recovery_seconds": recovery_seconds,
                    "rollback_scope": {"instance_id": instance_id, "spec": baseline.sha256},
                    "impact": {"restart": True, "resources": spec.value()["resources"]}}
            plan_id = digest(plan)
            self.store.put(db, "spec", spec.sha256, spec.value(), immutable=True)
            self.store.put(db, "plan", plan_id, plan, immutable=True)
            self.store.event(db, plan_id, "planned", {"action": action, "candidate": spec.sha256})
        return {"plan_id": plan_id, **plan}

    def approve(self, plan_id):
        self._gate()
        self._admin()
        nonce = secrets.token_urlsafe(32)
        with self.store.transaction() as db:
            plan = self.store.get(db, "plan", plan_id)
            require(digest(plan) == plan_id and self.clock() < plan["expires_at"], "plan_expired_or_changed")
            cancelled = db.execute(
                "SELECT 1 FROM documents WHERE kind='plan_cancellation' AND id=?", (plan_id,)
            ).fetchone()
            require(cancelled is None, "plan_cancelled")
            current = self.store.get(db, "instance", plan["instance_id"])
            require(current["generation"] == plan["generation"] and current["fence"] == plan["fence"]
                    and current["operation"] is None, "generation_conflict")
            self.store.put(db, "approval", digest(nonce), {"plan_id": plan_id,
                "action": plan["action"], "generation": plan["generation"],
                "expires_at": plan["expires_at"], "administrator_uid": os.geteuid(), "consumed": False}, immutable=True)
            self.store.event(db, plan_id, "approved", {"administrator_uid": os.geteuid()})
        return nonce  # Only returned once, never in public logs or operation status.

    def cancel_plan(self, plan_id):
        """Cancel only a plan which has never reserved an operation.

        Cancellation is allowed while the new-operation gate is closed, but it
        cannot interrupt or relabel an already reserved/executing deployment.
        """
        self._admin()
        with self.store.transaction() as db:
            plan = self.store.get(db, "plan", plan_id)
            require(digest(plan) == plan_id, "plan_changed")
            existing = db.execute(
                "SELECT 1 FROM documents WHERE kind='plan_cancellation' AND id=?", (plan_id,)
            ).fetchone()
            if existing is not None:
                return self.store.get(db, "plan_cancellation", plan_id)
            operations = db.execute(
                "SELECT value FROM documents WHERE kind='operation'"
            ).fetchall()
            require(
                not any(self.store.get_value(row)["plan_id"] == plan_id for row in operations),
                "cancellation_not_safe",
            )
            cancellation = {"plan_id": plan_id, "cancelled_at": self.clock(),
                            "administrator_uid": os.geteuid()}
            self.store.put(db, "plan_cancellation", plan_id, cancellation, immutable=True)
            self.store.event(db, plan_id, "plan_cancelled", {})
        return cancellation

    def begin(self, plan_id, approval, *, expected_action=None):
        """Atomic CAS + approval consume + durable recovery spec + fence grant."""
        self._gate()
        self._admin()
        # Keep the bounded identity inspection in the reservation transaction.
        # This leaves one fail-fast lock acquisition before the CAS, so racing
        # callers cannot alternate across pre-read transactions and both lose.
        with self.store.transaction() as db:
            plan = self.store.get(db, "plan", plan_id)
            registration = self.store.get(db, "registration", plan["instance_id"])
            backend = self._backend(registration)
            observed = backend.inspect(registration)
            require(expected_action is None or plan["action"] == expected_action,
                    "deployment_action_mismatch")
            cancelled = db.execute(
                "SELECT 1 FROM documents WHERE kind='plan_cancellation' AND id=?", (plan_id,)
            ).fetchone()
            require(cancelled is None, "plan_cancelled")
            ticket = self.store.get(db, "approval", digest(approval))
            current = self.store.get(db, "instance", plan["instance_id"])
            require(digest(plan) == plan_id and ticket["plan_id"] == plan_id
                    and ticket["action"] == plan["action"] and ticket["generation"] == plan["generation"], "approval_mismatch")
            require(not ticket["consumed"] and self.clock() < ticket["expires_at"], "approval_expired_or_replayed")
            require(plan["action"] in registration["actions"], "action_not_allowed")
            require(current["status"] == "ready" and current["operation"] is None
                    and current["generation"] == plan["generation"] and current["fence"] == plan["fence"]
                    and current["spec"] == plan["baseline"], "generation_conflict")
            self._observation(observed, plan["instance_id"], plan["baseline"])
            require(observed["identity"] == plan["expected_identity"], "runtime_identity_drift")
            operation_id = uuid.uuid4().hex
            current.update(fence=current["fence"] + 1, operation=operation_id, status="changing")
            operation = {"id": operation_id, "plan_id": plan_id, "instance_id": plan["instance_id"],
                         "fence": current["fence"], "phase": "reserved", "administrator_uid": ticket["administrator_uid"],
                         "baseline": plan["baseline"], "candidate": plan["candidate"],
                         "deadline": self.clock() + plan["verify_seconds"],
                         "recovery_deadline": self.clock() + plan["recovery_seconds"],
                         "executor": uuid.uuid4().hex}
            ticket["consumed"] = True
            self.store.put(db, "approval", digest(approval), ticket)
            self.store.put(db, "instance", plan["instance_id"], current)
            self.store.put(db, "operation", operation_id, operation)
            self.store.put(db, "retained", plan["instance_id"] + ":" + plan["baseline"],
                           {"spec": plan["baseline"]}, immutable=True)
            self.store.event(db, operation_id, "reserved", {"fence": operation["fence"], "plan_id": plan_id})
        self.checkpoint("reserved")
        return operation

    def _owned(self, db, token):
        operation = self.store.get(db, "operation", token["id"])
        current = self.store.get(db, "instance", operation["instance_id"])
        require(operation["fence"] == token["fence"] and operation["executor"] == token["executor"]
                and current["fence"] == token["fence"] and current["operation"] == token["id"], "fence_lost")
        require(operation["phase"] not in TERMINAL, "operation_terminal")
        return operation, current

    def _phase(self, token, phase):
        with self.store.transaction() as db:
            operation, _ = self._owned(db, token)
            allowed = {"applying": {"reserved"}, "verifying": {"applying"},
                       "rolling_back": {"reserved", "applying", "verifying", "recovering"}}
            require(operation["phase"] in allowed[phase], "phase_conflict")
            operation["phase"] = phase
            self.store.put(db, "operation", token["id"], operation)
            self.store.event(db, token["id"], phase, {"fence": token["fence"]})
        self.checkpoint(phase)

    def _effect(self, token, *, restore):
        # The authoritative transaction stays held through a synchronous mutation.
        # A nested consumer fails immediately with busy; no wait or legacy fallback.
        # Backends must use direct non-recursive primitives, NOT blocking systemctl
        # start -> ExecStart -> this controller recursion.
        with self.store.transaction() as db:
            operation, _ = self._owned(db, token)
            registration = self.store.get(db, "registration", operation["instance_id"])
            backend = self._backend(registration)
            deadline = operation["recovery_deadline"] if restore else operation["deadline"]
            require(self.clock() < deadline, "operation_deadline")
            if not restore:
                self._gate()
            plan = self.store.get(db, "plan", operation["plan_id"])
            spec_hash = operation["baseline"] if restore else operation["candidate"]
            spec = DeploymentSpec.freeze(self.store.get(db, "spec", spec_hash))
            require(backend.qualify(registration, spec) is True, "backend_not_qualified")
            # Bracket external identity immediately before mutation, not only at
            # plan/begin. restore must identify this exact operation, not its owner.
            require(backend.owns(registration, token, plan["expected_identity"], restore=restore) is True,
                    "external_ownership_lost")
            if not restore:
                observed = backend.inspect(registration)
                self._observation(observed, operation["instance_id"], plan["baseline"])
                require(observed["identity"] == plan["expected_identity"], "runtime_identity_drift")
            backend.deploy(registration, spec, token, deadline, restore=restore)
        self.checkpoint("restore_effect" if restore else "deploy_effect")

    def _verify(self, token, *, restore):
        operation = self.store.read("operation", token["id"])
        registration = self.store.read("registration", operation["instance_id"])
        spec_hash = operation["baseline"] if restore else operation["candidate"]
        backend = self._backend(registration)
        deadline = operation["recovery_deadline"] if restore else operation["deadline"]
        require(self.clock() < deadline, "operation_deadline")
        observed = backend.verify(registration, spec_hash, token, deadline)
        self._observation(observed, operation["instance_id"], spec_hash, execution=True)
        require(self.clock() < deadline, "operation_deadline")
        plan = self.store.read("plan", operation["plan_id"])
        require(observed["identity"] != plan["expected_identity"], "process_not_replaced")
        require(backend.owns(registration, token, plan["expected_identity"], restore=True) is True,
                "external_ownership_lost")
        with self.store.transaction() as db:
            self._owned(db, token)
            self.store.put(db, "evidence", token["id"], observed)
        self.checkpoint("restore_verified" if restore else "verified")
        return observed

    def _commit(self, token, observed, *, restore):
        with self.store.transaction() as db:
            operation, current = self._owned(db, token)
            registration = self.store.get(db, "registration", operation["instance_id"])
            backend = self._backend(registration)
            latest = backend.inspect(registration)
            self._observation(latest, operation["instance_id"], observed["spec_hash"])
            require(latest["identity"] == observed["identity"], "runtime_identity_drift")
            plan = self.store.get(db, "plan", operation["plan_id"])
            require(backend.owns(registration, token, plan["expected_identity"], restore=True) is True,
                    "external_ownership_lost")
            current.update(generation=current["generation"] + 1, operation=None, status="ready",
                           spec=operation["baseline"] if restore else operation["candidate"], observation=observed)
            operation["phase"] = "rolled_back" if restore else "committed"
            self.store.put(db, "instance", operation["instance_id"], current)
            self.store.put(db, "operation", token["id"], operation)
            self.store.event(db, token["id"], operation["phase"], {"generation": current["generation"]})
        self.checkpoint(operation["phase"])
        return operation

    def execute(self, token):
        self._admin()
        self._phase(token, "applying")
        try:
            self._effect(token, restore=False)
            self._phase(token, "verifying")
            observation = self._verify(token, restore=False)
            return self._commit(token, observation, restore=False)
        except Exception:
            # Raw adapter exceptions may contain credentials. Persist only phase.
            return self._rollback(token)

    def execute_external(self, token, effect, restore_effect):
        """Commit an effect performed by a trusted, fenced execution plane.

        ``effect`` and ``restore_effect`` are installed callables, never selected
        or populated by a wire request.  This path exists for brokers whose
        one-use grant must be claimed under a distinct OS owner identity before
        the Controller can verify and commit the resulting runtime observation.
        """
        self._admin()
        require(callable(effect) and callable(restore_effect), "trusted_effect_required")
        self._phase(token, "applying")
        try:
            effect()
            self.checkpoint("deploy_effect")
            self._phase(token, "verifying")
            observation = self._verify(token, restore=False)
            return self._commit(token, observation, restore=False)
        except Exception:
            # Execution-plane errors may include credentials or host details.
            return self._rollback_external(token, restore_effect)

    def _rollback_external(self, token, restore_effect):
        try:
            with self.store.transaction() as db:
                operation, current = self._owned(db, token)
                registration = self.store.get(db, "registration", operation["instance_id"])
                plan = self.store.get(db, "plan", operation["plan_id"])
                backend = self._backend(registration)
                observed = backend.inspect(registration)
                if (observed["spec_hash"] == operation["baseline"]
                        and observed["identity"] == plan["expected_identity"]
                        and backend.owns(registration, token, plan["expected_identity"], restore=True) is True):
                    self._observation(observed, operation["instance_id"], operation["baseline"])
                    operation["phase"] = "failed"
                    current.update(operation=None, status="ready", observation=observed)
                    self.store.put(db, "instance", operation["instance_id"], current)
                    self.store.put(db, "operation", token["id"], operation)
                    self.store.event(db, token["id"], "failed", {"reason": "baseline_unchanged"})
                    return operation
            self._phase(token, "rolling_back")
            restore_effect()
            self.checkpoint("restore_effect")
            observation = self._verify(token, restore=True)
            return self._commit(token, observation, restore=True)
        except Exception:
            with self.store.transaction() as db:
                operation, current = self._owned(db, token)
                operation["phase"] = "rollback_failed"
                current["status"] = "recovery_required"
                self.store.put(db, "instance", operation["instance_id"], current)
                self.store.put(db, "operation", token["id"], operation)
                self.store.event(db, token["id"], "rollback_failed",
                                 {"reason": "verification_or_ownership_failed"})
            return operation

    def _rollback(self, token):
        try:
            # No mutation occurred: closing the new-operation gate or failing
            # before apply must not restart an unchanged healthy shared service.
            with self.store.transaction() as db:
                operation, current = self._owned(db, token)
                registration = self.store.get(db, "registration", operation["instance_id"])
                plan = self.store.get(db, "plan", operation["plan_id"])
                backend = self._backend(registration)
                observed = backend.inspect(registration)
                if (observed["spec_hash"] == operation["baseline"]
                        and observed["identity"] == plan["expected_identity"]
                        and backend.owns(registration, token, plan["expected_identity"], restore=True) is True):
                    self._observation(observed, operation["instance_id"], operation["baseline"])
                    operation["phase"] = "failed"
                    current.update(operation=None, status="ready", observation=observed)
                    self.store.put(db, "instance", operation["instance_id"], current)
                    self.store.put(db, "operation", token["id"], operation)
                    self.store.event(db, token["id"], "failed", {"reason": "baseline_unchanged"})
                    return operation
            self._phase(token, "rolling_back")
            self._effect(token, restore=True)
            observation = self._verify(token, restore=True)
            return self._commit(token, observation, restore=True)
        except Exception:
            with self.store.transaction() as db:
                operation, current = self._owned(db, token)
                operation["phase"] = "rollback_failed"
                current["status"] = "recovery_required"
                self.store.put(db, "instance", operation["instance_id"], current)
                self.store.put(db, "operation", token["id"], operation)
                self.store.event(db, token["id"], "rollback_failed", {"reason": "verification_or_ownership_failed"})
            return operation

    def approve_recovery(self, operation_id, *, ttl=300):
        """Issue one bounded recovery approval for the exact current fence."""
        self._admin()
        require(type(ttl) is int and 1 <= ttl <= 600, "invalid_recovery_approval")
        nonce = secrets.token_urlsafe(32)
        with self.store.transaction() as db:
            operation = self.store.get(db, "operation", operation_id)
            require(operation["phase"] not in TERMINAL, "operation_terminal")
            current = self.store.get(db, "instance", operation["instance_id"])
            require(current["operation"] == operation_id
                    and current["fence"] == operation["fence"], "fence_lost")
            require(self.clock() < operation["recovery_deadline"],
                    "recovery_scope_expired")
            expires_at = min(self.clock() + ttl, operation["recovery_deadline"])
            ticket = {"operation_id": operation_id, "instance_id": operation["instance_id"],
                      "fence": operation["fence"], "generation": current["generation"],
                      "expires_at": expires_at, "administrator_uid": os.geteuid(),
                      "consumed": False}
            self.store.put(db, "recovery_approval", digest(nonce), ticket, immutable=True)
            self.store.event(db, operation_id, "recovery_approved",
                             {"fence": operation["fence"], "expires_at": expires_at})
        return nonce

    def recover(self, operation_id, approval):
        """Only explicit admin recovery within original approved baseline scope.

        No lease timeout/PID absence takeover. Backend must establish that all old
        effects are quiescent under this authority before a replacement executor
        can receive a higher fence. A revived old token fails every later step.
        """
        self._admin()
        with self.store.transaction() as db:
            operation = self.store.get(db, "operation", operation_id)
            require(operation["phase"] not in TERMINAL, "operation_terminal")
            current = self.store.get(db, "instance", operation["instance_id"])
            require(current["operation"] == operation_id and current["fence"] == operation["fence"], "fence_lost")
            ticket = self.store.get(db, "recovery_approval", digest(approval))
            require(ticket["operation_id"] == operation_id
                    and ticket["instance_id"] == operation["instance_id"]
                    and ticket["fence"] == operation["fence"]
                    and ticket["generation"] == current["generation"],
                    "recovery_approval_mismatch")
            require(not ticket["consumed"] and self.clock() < ticket["expires_at"]
                    and self.clock() < operation["recovery_deadline"],
                    "recovery_approval_expired_or_replayed")
            registration = self.store.get(db, "registration", operation["instance_id"])
            require(self._backend(registration).quiescent(registration, operation) is True, "old_executor_not_fenced")
            ticket["consumed"] = True
            current["fence"] += 1
            operation.update(fence=current["fence"], executor=uuid.uuid4().hex, phase="recovering")
            self.store.put(db, "recovery_approval", digest(approval), ticket)
            self.store.put(db, "instance", operation["instance_id"], current)
            self.store.put(db, "operation", operation_id, operation)
            self.store.event(db, operation_id, "recovering", {"fence": operation["fence"]})
        self.checkpoint("recovering")
        return self._rollback(operation)

    def referenced(self, spec_hash):
        """Conservative retention: specs and their artifacts are never GC'd in v1."""
        with self.store.transaction() as db:
            row = db.execute("SELECT 1 FROM documents WHERE kind='spec' AND id=?", (spec_hash,)).fetchone()
            return row is not None
