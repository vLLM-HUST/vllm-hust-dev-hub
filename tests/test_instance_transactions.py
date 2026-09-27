"""CPU-only control logic fixtures. No service, container or accelerator calls."""

import copy
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from instance_control import ControlError, DeploymentSpec, Store
from instance_control.controller import Controller
from instance_control.schema import digest


def specification(mod=False):
    artifact = {"source_sha": "a" * 40, "wheel_sha256": "b" * 64}
    value = {"schema": "vllm-hust.deployment-spec/v1",
             "image": {"id": "sha256:" + "c" * 64, "digest": "sha256:" + "d" * 64, "platform": "linux/arm64"},
             "core": artifact, "ascend": artifact, "manager": artifact,
             "witness": artifact if mod else None,
             "mods": [{"id": "org.fixture.policy", "artifact": artifact,
                       "manifest": {"schema_version": "0.2-experimental", "extension_id": "org.fixture.policy"}}] if mod else [],
             "model": {"id": "fixture/model", "revision": "a" * 40, "path": "/fixture/model", "files_sha256": "b" * 64},
             "resources": {"devices": [0, 1, 2, 3], "tp": 4, "pp": 1,
                           "graph": {"mode": "graph", "configuration": {"capture_sizes": [1, 2, 4]}},
                           "ports": [{"address": "127.0.0.1", "host": 18001, "container": 8000, "protocol": "tcp"}],
                           "mounts": [{"source": "/fixture/model", "target": "/model", "read_only": True, "content_sha256": "b" * 64}]},
             "launch": {"interpreter": "/runtime/bin/python", "argv": ["vllm", "serve", "fixture/model"],
                        "environment": {}, "working_directory": "/runtime", "plugin_allowlist": ["fixture"],
                        "resolved_options": {"tensor_parallel_size": 4, "pipeline_parallel_size": 1,
                                             "model": "fixture/model", "enforce_eager": False,
                                             "compilation_config": {"capture_sizes": [1, 2, 4]}}},
             "provider": {"id": "vllm", "source_sha": "a" * 40, "configuration": {},
                          "rendered": {"fixture": True}, "rendered_sha256": digest({"fixture": True}),
                          "qualification": {"receipt_sha256": "b" * 64, "status": "qualified"}},
             "secrets": [{"id": "api-key", "version": "v7", "target": "VLLM_API_KEY"}]}
    return copy.deepcopy(value)


class FakeBackend:
    """No host commands; models fencing-compliant synchronous resource changes."""
    def __init__(self, clock, baseline):
        self.clock = clock
        self.spec = DeploymentSpec.freeze(baseline)
        self.generation = 1
        self.operation = None
        self.effects = []
        self.fail_deploy = False
        self.fail_verify = False
        self.fail_restore = False
        self.foreign = False
        self.quiet = True
        self.qualified = True
        self.during_effect = None

    def qualify(self, registration, spec):
        return self.qualified

    def inspect(self, registration):
        return {"instance_id": registration["instance_id"], "spec_hash": self.spec.sha256,
                "identity": {"boot_id": "fixture-boot", "supervisor_generation": str(self.generation),
                             "resource_id": str(self.generation), "started_at": str(self.generation),
                             "processes": [{"pid": 123, "start_ticks": self.generation, "role": "scheduler", "rank": None}]},
                "captured_at": self.clock(), "healthy": True,
                "components_executed": [mod["id"] for mod in self.spec.value()["mods"]], "inference_verified": True}

    def owns(self, registration, token, expected_identity, *, restore):
        if self.foreign:
            return False
        # A recovery executor may restore only this operation's resource or the
        # untouched baseline. In production this needs real supervisor identity.
        return self.operation == token["id"] or (
            self.operation is None and self.inspect(registration)["identity"] == expected_identity)

    def deploy(self, registration, spec, token, deadline, *, restore):
        if restore and self.fail_restore:
            raise RuntimeError("SECRET_CANARY restore failed")
        self.effects.append(("restore" if restore else "apply", spec.sha256))
        self.operation = token["id"]
        self.spec = spec
        self.generation += 1
        if self.during_effect:
            self.during_effect()
        if not restore and self.fail_deploy:
            raise RuntimeError("SECRET_CANARY apply failed")

    def verify(self, registration, spec_hash, token, deadline):
        result = self.inspect(registration)
        if self.fail_verify and self.spec.value()["mods"]:
            result["components_executed"] = []
        return result

    def quiescent(self, registration, operation):
        return self.quiet and not self.foreign


class Crash(BaseException):
    pass


def competing_reservation(root, baseline, plan_id, approval, barrier, results):
    store = Store(root)
    backend = FakeBackend(lambda: 1000.0, baseline)
    controller = Controller(store, {"fixture": backend}, enabled=True,
                            admin_uids=[os.geteuid()], clock=lambda: 1000.0)
    barrier.wait(timeout=5)
    try:
        token = controller.begin(plan_id, approval)
        results.put(("reserved", token["id"]))
    except ControlError as exc:
        results.put(("rejected", str(exc)))


class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="instance-transaction-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "authority"
        self.store = Store(self.root, initialize=True)
        self.time = 1000.0
        self.baseline = specification()
        self.candidate = specification(True)
        self.backend = FakeBackend(lambda: self.time, self.baseline)
        self.controller = Controller(self.store, {"fixture": self.backend}, enabled=True,
                                     admin_uids=[os.geteuid()], clock=lambda: self.time)
        self.registration = {"instance_id": "fixture", "owner_id": "owner", "profile_id": "profile",
                             "backend_id": "fixture", "actions": ["apply", "disable", "rollback"],
                             "owner_uids": [os.geteuid()], "fencing_receipt_sha256": "a" * 64}
        self.controller.register(self.registration, self.baseline)

    def begin(self, action="apply", candidate=None):
        plan = self.controller.plan("fixture", action, candidate or self.candidate)
        approval = self.controller.approve(plan["plan_id"])
        return self.controller.begin(plan["plan_id"], approval)

    @staticmethod
    def recover(controller, operation_id):
        approval = controller.approve_recovery(operation_id)
        return controller.recover(operation_id, approval)

    def test_registration_cannot_bypass_lifecycle_authority(self):
        registration = {**self.registration, "instance_id": "lifecycle-owned"}
        with self.store.transaction() as db:
            self.store.put(db, "lifecycle_instance", "lifecycle-owned", {"state": "stopped"})
        with self.assertRaisesRegex(ControlError, "lifecycle_authority_conflict"):
            self.controller.register(registration, self.baseline)

    def test_immutable_complete_spec_and_roundtrip(self):
        frozen = DeploymentSpec.freeze(self.candidate)
        self.candidate["launch"]["environment"]["DRIFT"] = "changed"
        self.assertNotEqual(frozen.sha256, DeploymentSpec.freeze(self.candidate).sha256)
        restored = DeploymentSpec(frozen.encoded)
        self.assertEqual(frozen, restored)
        for key in frozen.value():
            with self.subTest(key=key):
                value = frozen.value()
                del value[key]
                with self.assertRaises(ControlError):
                    DeploymentSpec.freeze(value)

    def test_apply_disable_and_retained_rollback(self):
        result = self.controller.execute(self.begin())
        self.assertEqual(result["phase"], "committed")
        # Previous effect has ended; fake backend models a newly stable owner.
        self.backend.operation = None
        disabled = self.controller.execute(self.begin("disable", self.baseline))
        self.assertEqual(disabled["phase"], "committed")
        self.assertFalse(self.backend.spec.value()["mods"])
        self.backend.operation = None
        rollback = self.controller.execute(self.begin("rollback", self.candidate))
        self.assertEqual(rollback["phase"], "committed")
        self.assertTrue(self.controller.referenced(DeploymentSpec.freeze(self.baseline).sha256))
        self.assertEqual(self.store.read("instance", "fixture")["generation"], 3)

    def test_default_off_and_owner_id_is_not_authority(self):
        self.controller.enabled = False
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ControlError, "disabled"):
            self.controller.plan("fixture", "apply", self.candidate)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.controller.enabled = True
        self.controller.admin_uids = frozenset()
        with self.assertRaisesRegex(ControlError, "os_identity"):
            self.controller.plan("fixture", "apply", self.candidate)
        self.assertEqual(self.backend.effects, [])

    def test_approval_expiry_replay_and_tamper(self):
        plan = self.controller.plan("fixture", "apply", self.candidate)
        approval = self.controller.approve(plan["plan_id"])
        with self.assertRaises(ControlError):
            self.controller.begin(plan["plan_id"], approval + "altered")
        self.time += 301
        with self.assertRaisesRegex(ControlError, "expired"):
            self.controller.begin(plan["plan_id"], approval)
        self.time -= 301
        token = self.controller.begin(plan["plan_id"], approval)
        with self.assertRaisesRegex(ControlError, "replayed"):
            self.controller.begin(plan["plan_id"], approval)
        self.controller.execute(token)
        effects = list(self.backend.effects)
        with self.assertRaises(ControlError):
            self.controller.execute(token)
        self.assertEqual(effects, self.backend.effects)

    def test_competing_plans_only_one_reserves(self):
        plan = self.controller.plan("fixture", "apply", self.candidate)
        first, second = (self.controller.approve(plan["plan_id"]) for _ in range(2))
        self.controller.begin(plan["plan_id"], first)
        with self.assertRaisesRegex(ControlError, "generation_conflict"):
            self.controller.begin(plan["plan_id"], second)

    def test_real_processes_race_one_atomic_reservation(self):
        plan = self.controller.plan("fixture", "apply", self.candidate)
        approvals = [self.controller.approve(plan["plan_id"]) for _ in range(2)]
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(2)
        results = ctx.Queue()
        children = [ctx.Process(target=competing_reservation,
                    args=(str(self.root), self.baseline, plan["plan_id"], approval, barrier, results))
                    for approval in approvals]
        for child in children:
            child.start()
        try:
            outcomes = [results.get(timeout=10) for _ in children]
            self.assertEqual(sorted(item[0] for item in outcomes), ["rejected", "reserved"])
            for child in children:
                child.join(timeout=5)
                self.assertEqual(child.exitcode, 0)
            consumed = sum(self.store.read("approval", digest(value))["consumed"] for value in approvals)
            self.assertEqual(consumed, 1)
            self.assertEqual(self.store.read("instance", "fixture")["fence"], 1)
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=5)

    def test_each_persisted_forward_phase_crash_is_recoverable(self):
        for phase in ("reserved", "applying", "deploy_effect", "verifying", "verified", "committed"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(prefix="crash-forward-") as tmp:
                store = Store(Path(tmp) / "state", initialize=True)
                backend = FakeBackend(lambda: self.time, self.baseline)
                controller = Controller(store, {"fixture": backend}, enabled=True,
                                        admin_uids=[os.geteuid()], clock=lambda: self.time)
                controller.register(self.registration, self.baseline)
                plan = controller.plan("fixture", "apply", self.candidate)
                approval = controller.approve(plan["plan_id"])
                def checkpoint(actual):
                    if actual == phase:
                        raise Crash()
                controller.checkpoint = checkpoint
                with self.assertRaises(Crash):
                    controller.execute(controller.begin(plan["plan_id"], approval))
                replacement = Controller(Store(Path(tmp) / "state"), {"fixture": backend}, enabled=False,
                                         admin_uids=[os.geteuid()], clock=lambda: self.time)
                current = store.read("instance", "fixture")
                if phase == "committed":
                    self.assertIsNone(current["operation"])
                    self.assertEqual(current["spec"], DeploymentSpec.freeze(self.candidate).sha256)
                else:
                    recovered = self.recover(replacement, current["operation"])
                    self.assertEqual(recovered["phase"], "failed" if phase in {"reserved", "applying"} else "rolled_back")
                    self.assertEqual(backend.spec.sha256, DeploymentSpec.freeze(self.baseline).sha256)

    def test_each_rollback_phase_crash_keeps_original_scope(self):
        for phase in ("rolling_back", "restore_effect", "restore_verified", "rolled_back"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(prefix="crash-rollback-") as tmp:
                store = Store(Path(tmp) / "state", initialize=True)
                backend = FakeBackend(lambda: self.time, self.baseline)
                controller = Controller(store, {"fixture": backend}, enabled=True,
                                        admin_uids=[os.geteuid()], clock=lambda: self.time)
                controller.register(self.registration, self.baseline)
                plan = controller.plan("fixture", "apply", self.candidate)
                token = controller.begin(plan["plan_id"], controller.approve(plan["plan_id"]))
                backend.fail_verify = True
                def checkpoint(actual):
                    if actual == phase:
                        raise Crash()
                controller.checkpoint = checkpoint
                with self.assertRaises(Crash):
                    controller.execute(token)
                current = store.read("instance", "fixture")
                if current["operation"]:
                    replacement = Controller(Store(Path(tmp) / "state"), {"fixture": backend}, enabled=False,
                                             admin_uids=[os.geteuid()], clock=lambda: self.time)
                    self.assertEqual(self.recover(replacement, token["id"])["phase"], "rolled_back")
                self.assertEqual(backend.spec.sha256, DeploymentSpec.freeze(self.baseline).sha256)

    def test_recovery_crash_fences_both_preceding_executors(self):
        token = self.begin()
        self.controller.checkpoint = lambda phase: (_ for _ in ()).throw(Crash()) if phase == "deploy_effect" else None
        with self.assertRaises(Crash):
            self.controller.execute(token)
        self.controller.checkpoint = lambda phase: (_ for _ in ()).throw(Crash()) if phase == "recovering" else None
        with self.assertRaises(Crash):
            self.recover(self.controller, token["id"])
        second = self.store.read("operation", token["id"])
        self.controller.checkpoint = lambda _: None
        self.recover(self.controller, token["id"])
        for stale in (token, second):
            with self.assertRaisesRegex(ControlError, "fence_lost"):
                self.controller.execute(stale)

    def test_recovery_approval_replay_after_fence_commit_cannot_resume(self):
        token = self.begin()
        approval = self.controller.approve_recovery(token["id"])
        self.controller.checkpoint = lambda phase: (
            (_ for _ in ()).throw(Crash()) if phase == "recovering" else None
        )
        with self.assertRaises(Crash):
            self.controller.recover(token["id"], approval)
        operation = self.store.read("operation", token["id"])
        self.assertEqual(operation["phase"], "recovering")
        self.assertTrue(self.store.read("recovery_approval", digest(approval))["consumed"])
        effects = list(self.backend.effects)
        with self.assertRaisesRegex(ControlError, "recovery_approval_mismatch|expired_or_replayed"):
            self.controller.recover(token["id"], approval)
        self.assertEqual(effects, self.backend.effects)

    def test_action_allowlist_and_tampered_plan_are_rejected(self):
        with self.store.transaction() as db:
            registration = self.store.get(db, "registration", "fixture")
            registration["actions"] = []
            self.store.put(db, "registration", "fixture", registration)
        with self.assertRaisesRegex(ControlError, "not_allowed"):
            self.controller.plan("fixture", "apply", self.candidate)
        with self.store.transaction() as db:
            self.store.put(db, "registration", "fixture", self.registration)
        plan = self.controller.plan("fixture", "apply", self.candidate)
        approval = self.controller.approve(plan["plan_id"])
        with self.store.transaction() as db:
            stored = self.store.get(db, "plan", plan["plan_id"])
            stored["action"] = "disable"
            self.store.put(db, "plan", plan["plan_id"], stored)
        with self.assertRaisesRegex(ControlError, "mismatch"):
            self.controller.begin(plan["plan_id"], approval)
        self.assertEqual(self.backend.effects, [])

    def test_drift_after_approval_does_not_consume_or_deploy(self):
        plan = self.controller.plan("fixture", "apply", self.candidate)
        approval = self.controller.approve(plan["plan_id"])
        self.backend.generation += 1
        with self.assertRaisesRegex(ControlError, "identity_drift"):
            self.controller.begin(plan["plan_id"], approval)
        self.assertFalse(self.store.read("approval", digest(approval))["consumed"])
        self.assertEqual(self.backend.effects, [])

    def test_drift_between_reservation_and_effect_never_touches_foreign(self):
        token = self.begin()
        self.backend.foreign = True
        self.backend.generation += 1
        result = self.controller.execute(token)
        self.assertEqual(result["phase"], "rollback_failed")
        self.assertEqual(self.backend.effects, [])
        with self.assertRaisesRegex(ControlError, "recovery_required"):
            self.controller.plan("fixture", "apply", self.candidate)

    def test_verification_failure_restores_only_original_baseline(self):
        self.backend.fail_verify = True
        result = self.controller.execute(self.begin())
        self.assertEqual(result["phase"], "rolled_back")
        self.assertEqual(self.backend.spec.sha256, DeploymentSpec.freeze(self.baseline).sha256)

    def test_failed_rollback_is_durable_and_redacted(self):
        self.backend.fail_deploy = self.backend.fail_restore = True
        result = self.controller.execute(self.begin())
        self.assertEqual(result["phase"], "rollback_failed")
        replacement = Store(self.root)
        self.assertEqual(replacement.read("operation", result["id"])["phase"], "rollback_failed")
        self.assertNotIn(b"SECRET_CANARY", self.store.path.read_bytes())

    def test_crash_recovery_revokes_old_executor_even_when_gate_closed(self):
        token = self.begin()
        self.controller.checkpoint = lambda phase: (_ for _ in ()).throw(Crash()) if phase == "deploy_effect" else None
        with self.assertRaises(Crash):
            self.controller.execute(token)
        self.controller.checkpoint = lambda _: None
        self.controller.enabled = False
        recovered = self.recover(self.controller, token["id"])
        self.assertEqual(recovered["phase"], "rolled_back")
        effects = list(self.backend.effects)
        with self.assertRaisesRegex(ControlError, "fence_lost"):
            self.controller.execute(token)
        self.assertEqual(effects, self.backend.effects)

    def test_external_effect_uses_controller_commit_and_redacts_failure(self):
        token = self.begin()
        calls = []
        self.backend.spec = DeploymentSpec.freeze(self.candidate)
        self.backend.generation += 1
        self.backend.operation = token["id"]
        result = self.controller.execute_external(
            token, lambda: calls.append("apply"), lambda: calls.append("restore"))
        self.assertEqual(result["phase"], "committed")
        self.assertEqual(calls, ["apply"])
        self.assertEqual(self.store.read("instance", "fixture")["generation"], 1)

    def test_external_effect_failure_without_mutation_closes_operation(self):
        token = self.begin()
        result = self.controller.execute_external(
            token,
            lambda: (_ for _ in ()).throw(RuntimeError("SECRET_EXTERNAL")),
            lambda: self.fail("unchanged baseline must not be restored"),
        )
        self.assertEqual(result["phase"], "failed")
        self.assertNotIn(b"SECRET_EXTERNAL", self.store.path.read_bytes())

    def test_recovery_requires_quiescence_not_time_or_pid_absence(self):
        token = self.begin()
        self.backend.quiet = False
        approval = self.controller.approve_recovery(token["id"])
        with self.assertRaisesRegex(ControlError, "not_fenced"):
            self.controller.recover(token["id"], approval)
        self.time += 1000
        with self.assertRaisesRegex(ControlError, "recovery_scope_expired"):
            self.controller.approve_recovery(token["id"])
        self.assertEqual(self.backend.effects, [])

    def test_nested_writer_fails_fast_instead_of_deadlocking(self):
        outcomes = []
        def nested():
            try:
                with self.store.transaction():
                    outcomes.append("unsafe")
            except ControlError:
                outcomes.append("busy")
        self.backend.during_effect = nested
        self.controller.execute(self.begin())
        self.assertEqual(outcomes, ["busy"])

    def test_gate_closure_after_approval_does_not_restart_unchanged_service(self):
        token = self.begin()
        self.controller.enabled = False
        result = self.controller.execute(token)
        self.assertEqual(result["phase"], "failed")
        self.assertEqual(self.backend.effects, [])
        self.assertEqual(self.backend.generation, 1)

    def test_resolved_launch_cannot_hide_eager_or_lower_tp(self):
        for key, value in (("enforce_eager", True), ("tensor_parallel_size", 1),
                           ("pipeline_parallel_size", 2), ("compilation_config", {})):
            candidate = copy.deepcopy(self.candidate)
            candidate["launch"]["resolved_options"][key] = value
            with self.assertRaisesRegex(ControlError, "resolved_launch_mismatch"):
                self.controller.plan("fixture", "apply", candidate)

    def test_model_tp_graph_resources_and_secrets_cannot_drift(self):
        variants = []
        for key in ("tp", "devices", "graph"):
            candidate = copy.deepcopy(self.candidate)
            candidate["resources"][key] = {"tp": 1, "devices": [0], "graph": {"mode": "eager", "configuration": {}}}[key]
            variants.append(candidate)
        candidate = copy.deepcopy(self.candidate)
        candidate["model"]["id"] = "another/model"
        variants.append(candidate)
        candidate = copy.deepcopy(self.candidate)
        candidate["launch"]["environment"]["API_KEY"] = "SECRET_CANARY"
        variants.append(candidate)
        candidate = copy.deepcopy(self.candidate)
        candidate["provider"]["rendered"]["drift"] = True
        variants.append(candidate)
        for candidate in variants:
            with self.assertRaises(ControlError):
                self.controller.plan("fixture", "apply", candidate)


class EntryTransport(unittest.TestCase):
    def test_all_owner_actions_default_off_without_side_effects(self):
        script = Path(__file__).resolve().parents[1] / "scripts/instance_owner_entry.py"
        with tempfile.TemporaryDirectory(prefix="owner-entry-") as tmp:
            for action in ("serve", "start", "stop", "restart", "reconcile", "cleanup", "monitor"):
                request = {"schema": "vllm-hust.instance-owner-entry/v1", "consumer": "sage-mate",
                           "instance_id": "fixture", "owner_id": "owner", "profile_id": "profile",
                           "action": action, "new_operations_enabled": True, "invocation_id": None}
                result = subprocess.run([sys.executable, "-I", str(script)], cwd=tmp,
                    input=json.dumps(request), text=True, capture_output=True, timeout=5,
                    env={"PATH": "/nonexistent", "HOME": tmp, "PYTHONPATH": "/untrusted"})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(json.loads(result.stderr)["lifecycleAvailable"])
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_control_transport_never_accepts_owner_as_administrator(self):
        script = Path(__file__).resolve().parents[1] / "scripts/instance_control_entry.py"
        requests = [
            {"action": "inspect", "instance_id": "fixture"},
            {"action": "approve", "plan_id": "a" * 64},
            {"action": "apply", "plan_id": "a" * 64, "approval": "SECRET_CANARY" * 3},
            {"action": "approve", "plan_id": "a" * 64, "owner_id": "root"},
            {"action": "plan", "instance_id": "fixture", "candidate_id": "candidate", "deployment_action": "apply", "argv": ["sh"]},
        ]
        with tempfile.TemporaryDirectory(prefix="control-entry-") as tmp:
            for item in requests:
                item["schema"] = "vllm-hust.instance-control/v1"
                result = subprocess.run([sys.executable, "-I", str(script)], cwd=tmp,
                    input=json.dumps(item), text=True, capture_output=True, timeout=5,
                    env={"PATH": "/nonexistent", "HOME": tmp})
                self.assertEqual(result.returncode, 0 if item["action"] == "inspect" else 2)
                self.assertFalse(json.loads(result.stdout or result.stderr)["authorityAvailable"])
                self.assertNotIn("SECRET_CANARY", result.stdout + result.stderr)
                self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
