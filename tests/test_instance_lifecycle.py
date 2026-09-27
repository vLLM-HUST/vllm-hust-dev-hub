"""Control-logic evidence only: no Docker, systemd, models or NPU operations."""

import multiprocessing
import os
from pathlib import Path
import socket
import subprocess
import time
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from instance_control.lifecycle import Lifecycle, PROTOCOL
from instance_control.lifecycle_backend import SimulationBackend
from instance_control.lifecycle_client import call
from instance_control.lifecycle_server import LifecycleServer
from instance_control.schema import ControlError, canonical
from instance_control.store import Store


def authority(root, **kwargs):
    root = Path(root)
    store = Store(str(root / "control"), initialize=not (root / "control").exists())
    backend = SimulationBackend(
        Store(str(root / "resource"), initialize=not (root / "resource").exists())
    )
    profiles = {
        "cpu": {
            "backend_id": "simulation",
            "requester_uids": [os.geteuid(), 111, 222],
            "operator_uids": [333],
            "resources": ["simulation:cpu-slot"],
        }
    }
    return Lifecycle(
        store,
        profiles,
        {"simulation": backend},
        administrator_uids=[os.geteuid()],
        enabled=True,
        **kwargs,
    )


def crash_worker(root, phase):
    def crash(current):
        if current == phase:
            os._exit(91)

    service = authority(root, checkpoint=crash)
    if phase in {"rolling_back", "restore_effect"}:

        def fail(current):
            if current == "apply":
                raise RuntimeError("simulated partial effect")

        service.backends["simulation"].fault = fail
    service.tick()


def request_worker(root, barrier, queue, action, key, generation):
    service = authority(root)
    barrier.wait(timeout=5)
    try:
        queue.put(
            service.dispatch(
                111,
                {
                    "schema": PROTOCOL,
                    "action": action,
                    "instance_id": "test",
                    "request_id": key,
                    "expected_generation": generation,
                },
            )
        )
    except ControlError as exc:
        queue.put(str(exc))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = authority(self.tmp.name)
        self.admin = os.geteuid()
        self.index = 0

    def request(self, action, uid=111, **kwargs):
        value = {"schema": PROTOCOL, "action": action}
        if action != "list" and action != "operation":
            value["instance_id"] = "test"
        if action in {
            "request",
            "approve",
            "reject",
            "start",
            "stop",
            "transfer",
            "recover",
        }:
            self.index += 1
            value["request_id"] = "r-" + str(self.index)
        value.update(kwargs)
        return self.service.dispatch(uid, value)

    def enroll(self):
        self.request("request", profile_id="cpu")
        self.request("approve", uid=self.admin, expected_generation=0)

    def status(self):
        return self.request("status")["instance"]

    def change(self, action):
        return self.request(action, expected_generation=self.status()["generation"])

    def test_approval_permissions_and_default_off(self):
        self.request("request", profile_id="cpu")
        with self.assertRaisesRegex(ControlError, "administrator_required"):
            self.request("approve", expected_generation=0)
        self.service.enabled = False
        with self.assertRaisesRegex(ControlError, "new_operations_disabled"):
            self.request("approve", uid=self.admin, expected_generation=0)
        self.assertEqual(self.status()["state"], "requested")
        self.assertFalse(self.service.tick())

    def test_start_stop_and_noop(self):
        self.enroll()
        for action, state in [
            ("start", "running"),
            ("start", "running"),
            ("stop", "stopped"),
            ("stop", "stopped"),
        ]:
            result = self.change(action)
            self.service.tick()
            self.assertEqual(self.status()["state"], state)
            operation = self.request("operation", operation_id=result["operation_id"])[
                "operation"
            ]
            self.assertEqual(operation["phase"], "committed")
        self.assertEqual(self.status()["observation"]["evidence"], "simulation")

    def test_exact_replay_after_completion_and_gate_closure(self):
        self.enroll()
        first = self.request("start", expected_generation=1, request_id="same")
        self.service.tick()
        self.service.enabled = False
        self.assertEqual(
            first, self.request("start", expected_generation=1, request_id="same")
        )
        with self.assertRaisesRegex(ControlError, "idempotency_conflict"):
            self.request("stop", expected_generation=1, request_id="same")
        self.assertEqual(self.status()["generation"], 3)

    def test_generation_and_inflight_conflicts(self):
        self.enroll()
        self.change("start")
        with self.assertRaisesRegex(ControlError, "generation_conflict"):
            self.request("stop", uid=333, expected_generation=1)
        with self.assertRaisesRegex(ControlError, "operation_conflict"):
            self.request("stop", uid=333, expected_generation=2)

    def test_apply_failure_after_effect_rolls_back_and_retry_new_key(self):
        self.enroll()
        backend = self.service.backends["simulation"]

        def fail(phase):
            if phase == "apply":
                raise RuntimeError("private API token must never escape")

        backend.fault = fail
        result = self.change("start")
        self.service.tick()
        self.assertEqual(self.status()["state"], "stopped")
        op = self.request("operation", operation_id=result["operation_id"])["operation"]
        self.assertEqual(op["phase"], "rolled_back")
        self.assertNotIn("private API", canonical(op))
        backend.fault = lambda _: None
        self.change("start")
        self.service.tick()
        self.assertEqual(self.status()["state"], "running")

    def test_rollback_failure_requires_admin_recovery_even_with_gate_closed(self):
        self.enroll()
        backend = self.service.backends["simulation"]
        backend.fault = lambda _: (_ for _ in ()).throw(RuntimeError("secret"))
        self.change("start")
        self.service.tick()
        self.assertEqual(self.status()["state"], "recovery_required")
        with self.assertRaisesRegex(ControlError, "administrator_required"):
            self.change("recover")
        backend.fault = lambda _: None
        self.service.enabled = False
        self.request(
            "recover", uid=self.admin, expected_generation=self.status()["generation"]
        )
        self.service.tick()
        self.assertEqual(self.status()["state"], "stopped")

    def test_crash_recovery_at_each_durable_boundary(self):
        self.enroll()
        for phase in [
            "reserved",
            "effect",
            "rolling_back",
            "restore_effect",
            "finished",
        ]:
            with self.subTest(phase=phase):
                if self.status()["state"] == "running":
                    self.change("stop")
                    self.service.tick()
                result = self.change("start")
                child = multiprocessing.Process(
                    target=crash_worker, args=(self.tmp.name, phase)
                )
                child.start()
                child.join(5)
                self.assertEqual(child.exitcode, 91)
                self.service = authority(self.tmp.name)
                self.service.tick()
                expected = "running" if phase == "finished" else "stopped"
                self.assertEqual(self.status()["state"], expected)
                op = self.request("operation", operation_id=result["operation_id"])[
                    "operation"
                ]
                self.assertEqual(
                    op["phase"], "committed" if phase == "finished" else "rolled_back"
                )

    def test_stop_crash_restores_running_baseline(self):
        self.enroll()
        self.change("start")
        self.service.tick()
        self.change("stop")
        child = multiprocessing.Process(
            target=crash_worker, args=(self.tmp.name, "effect")
        )
        child.start()
        child.join(5)
        self.assertEqual(child.exitcode, 91)
        self.service = authority(self.tmp.name)
        self.service.tick()
        self.assertEqual(self.status()["state"], "running")

    def test_multiprocess_start_stop_only_one_admitted(self):
        self.enroll()
        barrier = multiprocessing.Barrier(3)
        queue = multiprocessing.Queue()
        children = [
            multiprocessing.Process(
                target=request_worker,
                args=(self.tmp.name, barrier, queue, action, action + "-key", 1),
            )
            for action in ("start", "stop")
        ]
        for child in children:
            child.start()
        barrier.wait(timeout=5)
        results = [queue.get(timeout=5) for _ in children]
        for child in children:
            child.join(5)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertTrue(
            any(
                r in {"generation_conflict", "authority_busy_or_unavailable"}
                for r in results
                if isinstance(r, str)
            )
        )

    def test_resource_claim_and_atomic_transfer(self):
        self.enroll()
        self.request("request", instance_id="second", profile_id="cpu")
        with self.assertRaisesRegex(ControlError, "resource_conflict"):
            self.request(
                "approve", instance_id="second", uid=self.admin, expected_generation=0
            )
        self.request(
            "transfer", uid=self.admin, expected_generation=1, new_owner_uid=222
        )
        with self.assertRaisesRegex(ControlError, "forbidden"):
            self.request("status")
        self.assertEqual(self.request("status", uid=222)["instance"]["owner_uid"], 222)
        with self.assertRaisesRegex(ControlError, "generation_conflict"):
            self.request(
                "transfer", uid=self.admin, expected_generation=1, new_owner_uid=111
            )

    def test_foreign_identity_never_stopped_or_restored(self):
        self.enroll()
        self.change("start")
        store = self.service.backends["simulation"].store
        foreign = {
            "observation": {
                "state": "running",
                "identity": "foreign",
                "evidence": "simulation",
            },
            "operation": "foreign",
            "fence": 0,
        }
        with store.transaction() as db:
            store.put(db, "sim_resource", "test", foreign)
        self.service.tick()
        self.assertEqual(self.status()["state"], "recovery_required")
        self.assertEqual(store.read("sim_resource", "test"), foreign)

    def test_worker_fencing_and_disabled_queue_rollback(self):
        self.enroll()
        self.change("start")
        with self.service.worker_guard():
            with self.assertRaisesRegex(ControlError, "worker_busy"):
                authority(self.tmp.name).tick()
        self.service.enabled = False
        self.service.tick()
        self.assertEqual(self.status()["state"], "stopped")

    def test_audit_redaction_pagination_and_access(self):
        self.enroll()
        with self.assertRaisesRegex(ControlError, "forbidden"):
            self.request("status", uid=999)
        events = self.request("audit", after_sequence=0)["events"]
        self.assertTrue(
            any(e["phase"] == "rejected" and e["uid"] == 999 for e in events)
        )
        self.assertEqual(
            self.request("audit", after_sequence=events[-1]["sequence"])["events"], []
        )
        self.assertEqual(self.request("list", uid=999)["instances"], [])

    def test_wire_auth_schema_and_disconnected_retry(self):
        path = str(Path(self.tmp.name) / "api.sock")
        server = LifecycleServer(path, self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = {
            "schema": PROTOCOL,
            "action": "request",
            "instance_id": "wire",
            "profile_id": "cpu",
            "request_id": "wire-key",
        }
        result = call(path, request)
        self.assertEqual(result["instance"]["owner_uid"], os.geteuid())
        self.assertEqual(call(path, request), result)
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(path)
            client.sendall(canonical({**request, "uid": 0}).encode())
            client.shutdown(socket.SHUT_WR)
            self.assertIn(b"invalid_fields", client.recv(4096))

    def test_policy_drift_blocks_execution_and_no_automatic_enrollment(self):
        self.assertEqual(self.request("list")["instances"], [])
        self.enroll()
        self.change("start")
        self.service.profiles["cpu"]["resources"] = ["simulation:other"]
        self.service.tick()
        self.assertEqual(self.status()["state"], "recovery_required")

    def test_request_rejection_and_unqualified_backend(self):
        self.request("request", profile_id="cpu")
        self.request("reject", uid=self.admin, expected_generation=0)
        self.assertEqual(self.status()["state"], "rejected")
        with self.assertRaisesRegex(ControlError, "operation_conflict"):
            self.change("start")
        self.request("request", instance_id="other", profile_id="cpu")
        self.service.backends.clear()
        with self.assertRaisesRegex(ControlError, "backend_not_qualified"):
            self.request(
                "approve", uid=self.admin, instance_id="other", expected_generation=0
            )

    def test_legacy_authority_conflict_is_atomic(self):
        self.request("request", profile_id="cpu")
        with self.service.store.transaction() as db:
            self.service.store.put(db, "registration", "test", {"legacy": True})
        with self.assertRaisesRegex(ControlError, "legacy_authority_conflict"):
            self.request("approve", uid=self.admin, expected_generation=0)
        with self.service.store.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM documents WHERE kind='lifecycle_resource'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_same_key_race_and_retry(self):
        self.enroll()
        barrier = multiprocessing.Barrier(3)
        queue = multiprocessing.Queue()
        children = [
            multiprocessing.Process(
                target=request_worker,
                args=(self.tmp.name, barrier, queue, "start", "shared-key", 1),
            )
            for _ in range(2)
        ]
        for child in children:
            child.start()
        barrier.wait(timeout=5)
        results = [queue.get(timeout=5) for _ in children]
        for child in children:
            child.join(5)
            self.assertEqual(child.exitcode, 0)
        accepted = [r for r in results if isinstance(r, dict)]
        self.assertTrue(accepted)
        replay = self.request("start", expected_generation=1, request_id="shared-key")
        self.assertTrue(all(r == replay for r in accepted))
        self.service.tick()
        self.assertEqual(self.status()["generation"], 3)

    def test_backend_exception_redacted_at_wire_boundary(self):
        self.enroll()
        backend = self.service.backends["simulation"]
        backend.inspect = lambda _: (_ for _ in ()).throw(ControlError("TOP-SECRET"))
        with self.assertRaisesRegex(ControlError, "^observation_unavailable$"):
            self.change("start")
        self.assertNotIn(
            "TOP-SECRET", canonical(self.request("audit", after_sequence=0))
        )

    def test_service_subprocess_restart_and_stale_socket(self):
        root = Path(self.tmp.name)
        config = root / "host.json"
        socket_path = str(root / "service.sock")
        config.write_text(
            canonical(
                {
                    "schema": "vllm-hust.lifecycle-host/v1",
                    "enabled": True,
                    "state_directory": str(root / "service-state"),
                    "socket_path": socket_path,
                    "socket_gid": None,
                    "administrator_uids": [self.admin],
                    "profiles": self.service.profiles,
                }
            )
        )
        config.chmod(0o600)
        script = Path(__file__).resolve().parents[1] / "scripts/instance_lifecycle.py"
        children = []

        def cleanup():
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)

        self.addCleanup(cleanup)

        def boot():
            child = subprocess.Popen(
                [sys.executable, str(script), "--config", str(config), "--simulation"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            children.append(child)
            return child

        def rpc(action, **values):
            request = {"schema": PROTOCOL, "action": action, **values}
            deadline = time.monotonic() + 5
            while True:
                try:
                    return call(socket_path, request)
                except (OSError, ControlError) as exc:
                    if (
                        time.monotonic() > deadline
                        or isinstance(exc, ControlError)
                        and str(exc) != "authority_busy_or_unavailable"
                    ):
                        raise
                    time.sleep(0.02)

        first = boot()
        rpc("request", instance_id="api", profile_id="cpu", request_id="apply-1")
        rpc("approve", instance_id="api", expected_generation=0, request_id="approve-1")
        admitted = rpc(
            "start", instance_id="api", expected_generation=1, request_id="start-1"
        )
        deadline = time.monotonic() + 5
        while rpc("status", instance_id="api")["instance"]["state"] != "running":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        first.kill()
        first.wait(timeout=5)
        first.stderr.close()
        # Preserve the stale socket to exercise guarded startup recovery.
        second = boot()
        self.assertEqual(
            rpc(
                "start", instance_id="api", expected_generation=1, request_id="start-1"
            ),
            admitted,
        )
        self.assertEqual(
            rpc("status", instance_id="api")["instance"]["state"], "running"
        )
        second.terminate()
        self.assertEqual(second.wait(timeout=5), 0)
        second.stderr.close()


if __name__ == "__main__":
    unittest.main()
