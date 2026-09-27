"""Production-adapter fault fixtures; never contacts a real daemon or accelerator."""

import json
import multiprocessing
import os
import socket
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from instance_control.lifecycle import Lifecycle, PROTOCOL
from instance_control.lifecycle_backend import EffectInProgress
from instance_control.production_backend import ProductionBackend, ProductionExecutor
from instance_control.production_driver import (
    DockerDriver,
    SystemdDriver,
    PROPERTIES,
    VOLATILE,
    CommandRunner,
)
from instance_control.production_policy import ProductionPolicy, artifact_sha
from instance_control.schema import ControlError, digest
from instance_control.store import Store


class FixturePolicy(ProductionPolicy):
    def verify_host(self, target):
        pass  # Fixture-only: no daemon socket or installed host artifacts.


class FakeDriver:
    def __init__(self, root, faults=()):
        self.store = Store(
            str(Path(root) / "resource"),
            initialize=not (Path(root) / "resource").exists(),
        )
        self.faults = faults

    def inspect(self, deadline):
        try:
            return self.store.read("resource", "target")
        except ControlError as exc:
            if str(exc) != "not_found":
                raise
            return {
                "state": "stopped",
                "identity": None,
                "resource": "fixed",
                "configuration": "c" * 64,
                "healthy": False,
                "evidence": "fake-driver",
            }

    def mutate(self, desired, deadline):
        if "before" in self.faults:
            raise ControlError("daemon_command_failed")
        if desired == "stopped" and "rollback" in self.faults:
            raise ControlError("command_outcome_unknown")
        with self.store.transaction() as db:
            current = {
                "state": desired,
                "identity": "identity-" + str(time.time_ns())
                if desired == "running"
                else None,
                "resource": "fixed",
                "configuration": "c" * 64,
                "healthy": desired == "running",
                "evidence": "fake-driver",
            }
            self.store.put(db, "resource", "target", current)
            self.store.event(db, "effects", desired, {})
        if "unknown" in self.faults:
            raise ControlError("command_outcome_unknown")

    def verify(self, desired, deadline):
        if desired == "running" and set(self.faults) & {"health", "partial"}:
            raise ControlError("health_failed")
        observed = self.inspect(deadline)
        if observed["state"] != desired:
            raise ControlError("health_failed")
        return observed

    def effects(self):
        with self.store.transaction() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT phase FROM events WHERE operation='effects'"
                )
            ]


def fixture(root, *, faults=(), checkpoint=lambda _: None, enabled=True):
    store = Store(
        str(Path(root) / "authority"),
        initialize=not (Path(root) / "authority").exists(),
    )
    profiles = {
        "fixed-profile": {
            "backend_id": "production",
            "requester_uids": [os.geteuid()],
            "operator_uids": [],
            "resources": ["fixture:fixed"],
        }
    }
    target = {
        "instance_id": "fixed",
        "profile_id": "fixed-profile",
        "profile_sha256": digest(profiles["fixed-profile"]),
        "kind": "docker",
        "name": "a" * 64,
        "runtime_directory": "/not-a-real-daemon",
        "configuration_sha256": "c" * 64,
        "artifacts": [],
        "timeout_seconds": 5,
        "stop_seconds": 1,
        "health_port": 0,
    }
    policy = FixturePolicy(
        "/no-real-policy", enabled, os.geteuid(), str(store.root), {"fixed": target}
    )
    driver = FakeDriver(root, faults)
    backend = ProductionBackend(store, policy, driver_factory=lambda _: driver)
    executor = ProductionExecutor(backend, checkpoint=checkpoint)
    backend.executor = executor.execute
    lifecycle = Lifecycle(
        store,
        profiles,
        {"production": backend},
        administrator_uids=[os.geteuid()],
        enabled=True,
    )
    return lifecycle, backend, driver


def crash(root, phase):
    def checkpoint(current):
        if current == phase:
            os._exit(93)

    fixture(root, checkpoint=checkpoint)[0].tick()


def race_helper(root, nonce, fd, barrier, results):
    backend = fixture(root)[1]
    barrier.wait(timeout=5)
    try:
        ProductionExecutor(backend).execute(nonce, fd)
        results.put("ok")
    except ControlError as exc:
        results.put(str(exc))


class ProductionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api, self.backend, self.driver = fixture(self.temp.name)
        self.sequence = 0
        self.call("request", profile_id="fixed-profile")
        self.call("approve", expected_generation=0)

    def call(self, action, **values):
        self.sequence += 1
        request = {"schema": PROTOCOL, "action": action, "instance_id": "fixed"}
        if action != "status":
            request["request_id"] = "req-" + str(self.sequence)
        return self.api.dispatch(os.geteuid(), {**request, **values})

    def status(self):
        return self.call("status")["instance"]

    def start(self):
        return self.call("start", expected_generation=self.status()["generation"])

    def test_roundtrip_and_exact_duplicate(self):
        initial = self.start()
        self.api.tick()
        self.assertEqual(self.status()["state"], "running")
        self.call("stop", expected_generation=self.status()["generation"])
        self.api.tick()
        self.assertEqual(self.status()["state"], "stopped")
        self.assertEqual(self.driver.effects(), ["running", "stopped"])
        self.assertTrue(initial["operation_id"].startswith("op-"))

    def test_default_off_preflight_dry_run_no_effects(self):
        self.api, self.backend, self.driver = fixture(self.temp.name, enabled=False)
        before = self.status()
        result = self.backend.dry_run("fixed", "running")
        self.assertFalse(result["mutations_enabled"])
        self.assertFalse(result["effect_performed"])
        self.assertEqual(before, self.status())
        with self.assertRaisesRegex(ControlError, "backend_operations_disabled"):
            self.start()
        self.api.tick()
        self.assertEqual(self.status()["state"], "stopped")
        self.assertEqual(self.driver.effects(), [])

    def test_confirmed_partial_failure_and_health_failure_rollback(self):
        for fault in ("partial", "health"):
            with self.subTest(fault=fault):
                self.api, self.backend, self.driver = fixture(
                    self.temp.name, faults=(fault,)
                )
                self.start()
                self.api.tick()
                self.assertEqual(self.status()["state"], "stopped")
                with self.api.store.transaction() as db:
                    self.assertEqual(
                        self.api.store.get(db, "production_effect", "fixed")["phase"],
                        "verified",
                    )

    def test_timeout_and_rollback_failure_quarantine(self):
        for faults in (("unknown",), ("partial", "rollback")):
            with tempfile.TemporaryDirectory() as root:
                api, backend, driver = fixture(root, faults=faults)
                for request in (
                    {
                        "action": "request",
                        "profile_id": "fixed-profile",
                        "request_id": "r",
                    },
                    {"action": "approve", "expected_generation": 0, "request_id": "a"},
                    {"action": "start", "expected_generation": 1, "request_id": "s"},
                ):
                    api.dispatch(
                        os.geteuid(),
                        {"schema": PROTOCOL, "instance_id": "fixed", **request},
                    )
                api.tick()
                self.assertEqual(
                    api.store.read("lifecycle_instance", "fixed")["state"],
                    "recovery_required",
                )
                self.assertEqual(driver.effects(), ["running"])
                generation = api.store.read("lifecycle_instance", "fixed")["generation"]
                api.dispatch(
                    os.geteuid(),
                    {
                        "schema": PROTOCOL,
                        "instance_id": "fixed",
                        "action": "recover",
                        "expected_generation": generation,
                        "request_id": "retry",
                    },
                )
                api.tick()
                self.assertEqual(driver.effects(), ["running"])

    def test_actual_process_crash_windows(self):
        for phase in (
            "lease_claimed",
            "intent",
            "daemon_returned",
            "settled",
            "verified",
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                api, _, driver = fixture(root)
                for request in (
                    {
                        "action": "request",
                        "profile_id": "fixed-profile",
                        "request_id": "r",
                    },
                    {"action": "approve", "expected_generation": 0, "request_id": "a"},
                    {"action": "start", "expected_generation": 1, "request_id": "s"},
                ):
                    api.dispatch(
                        os.geteuid(),
                        {"schema": PROTOCOL, "instance_id": "fixed", **request},
                    )
                child = multiprocessing.Process(target=crash, args=(root, phase))
                child.start()
                child.join(5)
                self.assertEqual(child.exitcode, 93)
                api = fixture(root)[0]
                api.tick()
                expected = (
                    "recovery_required"
                    if phase in {"intent", "daemon_returned"}
                    else "stopped"
                )
                self.assertEqual(
                    api.store.read("lifecycle_instance", "fixed")["state"], expected
                )
                if phase == "daemon_returned":
                    self.assertEqual(driver.effects(), ["running"])

    def test_stale_fence_replayed_and_expired_lease(self):
        nonces = []
        execute = self.backend.executor

        def capture(nonce, fd):
            nonces.append(nonce)
            return execute(nonce, fd)

        self.backend.executor = capture
        self.start()
        self.api.tick()
        with self.api.worker_guard() as fd:
            with self.assertRaisesRegex(ControlError, "fence_lost"):
                execute(nonces[0], fd)
        # The generic one-use predicate is also checked while operation owns fence.
        self.call("stop", expected_generation=self.status()["generation"])

        def expire(nonce, fd):
            with self.api.store.transaction() as db:
                lease = self.api.store.get(db, "production_lease", digest(nonce))
                lease["expires_at"] = 0
                self.api.store.put(db, "production_lease", digest(nonce), lease)
            return execute(nonce, fd)

        self.backend.executor = expire
        self.api.tick()
        self.assertEqual(self.status()["state"], "recovery_required")
        self.assertEqual(self.driver.effects(), ["running"])

    def test_foreign_identity_is_never_compensated(self):
        self.start()
        with self.driver.store.transaction() as db:
            self.driver.store.put(
                db,
                "resource",
                "target",
                {
                    "state": "running",
                    "identity": "foreign",
                    "configuration": "c" * 64,
                    "resource": "fixed",
                    "healthy": True,
                    "evidence": "fake-driver",
                },
            )
        self.api.tick()
        self.assertEqual(self.status()["state"], "recovery_required")
        self.assertEqual(self.driver.effects(), [])

    def test_surviving_executor_does_not_trigger_parallel_rollback(self):
        self.start()
        calls = []

        def pending(nonce, fd):
            calls.append(nonce)
            raise EffectInProgress("executor_still_active")

        self.backend.executor = pending
        self.api.tick()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.status()["state"], "recovery_required")
        self.assertEqual(self.driver.effects(), [])

    def test_guard_wrong_descriptor_and_no_dynamic_target(self):
        with open(__file__, "rb") as other:
            with self.assertRaisesRegex(ControlError, "worker_guard_required"):
                self.backend.restore("fixed", {}, worker_fd=other.fileno())
        with self.assertRaisesRegex(ControlError, "target_not_allowlisted"):
            self.backend.dry_run("sage", "stopped")

    def test_child_inherits_lock_after_parent_closes_descriptor(self):
        with self.api.worker_guard() as fd:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('ready', flush=True); sys.stdin.read()",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                pass_fds=(fd,),
            )
            self.assertEqual(child.stdout.readline(), b"ready\n")
        try:
            with self.assertRaisesRegex(ControlError, "worker_busy"):
                self.api.tick()
        finally:
            child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0)
        self.assertFalse(self.api.tick())

    def test_replay_while_fence_current_and_nonce_absent_from_audit(self):
        execute = self.backend.executor
        seen = []

        def duplicate(nonce, fd):
            seen.append(nonce)
            execute(nonce, fd)
            with self.assertRaisesRegex(ControlError, "lease_expired_or_replayed"):
                execute(nonce, fd)

        self.backend.executor = duplicate
        self.start()
        self.api.tick()
        self.assertEqual(self.driver.effects(), ["running"])
        with self.api.store.transaction() as db:
            audit = json.dumps([tuple(r) for r in db.execute("SELECT * FROM events")])
        self.assertTrue(all(nonce not in audit for nonce in seen))

    def test_nonzero_without_ack_is_quarantined_even_if_initially_unchanged(self):
        self.api, self.backend, self.driver = fixture(
            self.temp.name, faults=("before",)
        )
        self.start()
        self.api.tick()
        self.assertEqual(self.status()["state"], "recovery_required")
        self.assertEqual(self.driver.effects(), [])

    def test_gate_closed_allows_only_retained_completed_effect_rollback(self):
        child_phase = "verified"
        self.start()
        child = multiprocessing.Process(
            target=crash, args=(self.temp.name, child_phase)
        )
        child.start()
        child.join(5)
        self.assertEqual(child.exitcode, 93)
        self.api, self.backend, self.driver = fixture(self.temp.name, enabled=False)
        self.api.enabled = False
        self.api.tick()
        self.assertEqual(self.status()["state"], "stopped")
        self.assertEqual(self.driver.effects(), ["running", "stopped"])

    def test_policy_drift_between_lease_issue_and_claim_no_effect(self):
        execute = self.backend.executor

        def drift(nonce, fd):
            self.backend.policy.targets["fixed"]["configuration_sha256"] = "f" * 64
            return execute(nonce, fd)

        self.backend.executor = drift
        self.start()
        self.api.tick()
        self.assertEqual(self.driver.effects(), [])

    def test_qwen_transfer_rejected_through_each_helper_window(self):
        denied = []

        def checkpoint(phase):
            if phase in {"lease_claimed", "intent", "settled", "verified"}:
                with self.assertRaisesRegex(ControlError, "operation_conflict"):
                    self.call(
                        "transfer",
                        expected_generation=self.status()["generation"],
                        new_owner_uid=os.geteuid(),
                    )
                denied.append(phase)

        self.backend.executor = ProductionExecutor(
            self.backend, checkpoint=checkpoint
        ).execute
        self.start()
        with self.assertRaisesRegex(ControlError, "operation_conflict"):
            self.call(
                "transfer",
                expected_generation=self.status()["generation"],
                new_owner_uid=os.geteuid(),
            )
        self.api.tick()
        self.assertEqual(denied, ["lease_claimed", "intent", "settled", "verified"])
        self.assertEqual(self.status()["state"], "running")

    def test_qwen_two_helpers_one_nonce_exactly_one_effect(self):
        def racing(nonce, fd):
            barrier = multiprocessing.Barrier(3)
            results = multiprocessing.Queue()
            children = [
                multiprocessing.Process(
                    target=race_helper,
                    args=(self.temp.name, nonce, fd, barrier, results),
                )
                for _ in range(2)
            ]
            for child in children:
                child.start()
            barrier.wait(timeout=5)
            codes = [results.get(timeout=5) for _ in children]
            for child in children:
                child.join(5)
                self.assertEqual(child.exitcode, 0)
            self.assertEqual(codes.count("ok"), 1)
            self.assertTrue(
                set(codes)
                <= {"ok", "authority_busy_or_unavailable", "lease_expired_or_replayed"}
            )

        self.backend.executor = racing
        self.start()
        self.api.tick()
        self.assertEqual(self.driver.effects(), ["running"])
        self.assertEqual(self.status()["state"], "running")


class DriverFixtures(unittest.TestCase):
    def docker(self, change=None):
        value = {
            "Id": "a" * 64,
            "Created": "created",
            "Image": "sha256:" + "b" * 64,
            "Config": {
                "Healthcheck": {"Test": ["CMD", "health"]},
                "Env": ["PRIVATE=must-not-leak"],
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "no"},
                "AutoRemove": False,
                "ReadonlyRootfs": True,
            },
            "Mounts": [],
            "State": {"Running": False, "Status": "exited", "Pid": 0},
            "RestartCount": 0,
        }
        target = {
            "name": value["Id"],
            "runtime_directory": "/private/runtime",
            "stop_seconds": 2,
            "configuration_sha256": digest(
                {
                    k: value[k]
                    for k in (
                        "Id",
                        "Created",
                        "Image",
                        "Config",
                        "HostConfig",
                        "Mounts",
                    )
                }
            ),
        }
        calls = []
        if change:
            change(value)

        def runner(argv, env, timeout):
            calls.append((argv, env, timeout))
            return json.dumps([value]).encode()

        return DockerDriver(target, runner=runner), calls

    def test_docker_exact_id_private_endpoint_and_redacted_snapshot(self):
        driver, calls = self.docker()
        observation = driver.inspect(time.monotonic() + 5)
        self.assertNotIn("must-not-leak", json.dumps(observation))
        self.assertEqual(
            calls[0][0],
            [
                "/usr/bin/docker",
                "--host",
                "unix:///private/runtime/docker.sock",
                "inspect",
                "a" * 64,
            ],
        )
        self.assertEqual(driver.mutation_args("running"), ["start", "a" * 64])
        self.assertEqual(
            driver.mutation_args("stopped"), ["stop", "--time", "2", "a" * 64]
        )

    def test_docker_config_restart_and_foreign_id_fail_closed(self):
        for mutate in (
            lambda v: v.update(Id="f" * 64),
            lambda v: v["HostConfig"].update(AutoRemove=True),
            lambda v: v["Config"].update(Image="changed"),
        ):
            driver, _ = self.docker(mutate)
            with self.assertRaises(ControlError):
                driver.inspect(time.monotonic() + 5)

    def test_systemd_unit_hooks_and_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            fragment = Path(root) / "unit.service"
            fragment.write_text("[Service]\nType=notify\n")
            fragment.chmod(0o600)
            value = dict.fromkeys(PROPERTIES, "")
            value.update(
                Id="devhub-managed-test.service",
                LoadState="loaded",
                ActiveState="inactive",
                SubState="dead",
                MainPID="0",
                FragmentPath=str(fragment),
                Type="notify",
                Restart="no",
                KillMode="control-group",
                NeedDaemonReload="no",
                DynamicUser="no",
                RemainAfterExit="no",
                WatchdogUSec="0",
                NotifyAccess="main",
                Delegate="no",
                ProtectControlGroups="yes",
                NoNewPrivileges="yes",
            )
            target = {
                "name": value["Id"],
                "runtime_directory": "/private/user",
                "health_port": 9999,
                "artifacts": [{"path": str(fragment)}],
                "configuration_sha256": digest(
                    {
                        "properties": {
                            k: v for k, v in value.items() if k not in VOLATILE
                        },
                        "fragment_sha256": artifact_sha(str(fragment)),
                    }
                ),
            }
            calls = []

            def runner(argv, env, timeout):
                calls.append(argv)
                return "\n".join(k + "=" + v for k, v in value.items()).encode()

            driver = SystemdDriver(target, runner=runner)
            self.assertEqual(driver.inspect(time.monotonic() + 5)["state"], "stopped")
            self.assertEqual(
                driver.mutation_args("running"),
                ["start", "devhub-managed-test.service"],
            )
            value["ExecStopPost"] = "legacy-kill"
            with self.assertRaisesRegex(ControlError, "unfenced_unit_hook_or_input"):
                driver.inspect(time.monotonic() + 5)
            self.assertTrue(
                all(argv[:2] == ["/usr/bin/systemctl", "--user"] for argv in calls)
            )

    def test_command_timeout_and_error_do_not_leak_output(self):
        import subprocess

        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                ["secret"], 1, output=b"PASSWORD=private"
            ),
        ):
            with self.assertRaisesRegex(ControlError, "^command_outcome_unknown$"):
                CommandRunner()(["/fake"], {}, 1)
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, b"private", b"private"),
        ):
            with self.assertRaisesRegex(ControlError, "^daemon_command_failed$"):
                CommandRunner()(["/fake"], {}, 1)

    def test_systemd_execution_metadata_does_not_change_configuration_pin(self):
        from instance_control.production_driver import unit_snapshot

        values = dict.fromkeys(PROPERTIES, "")
        values["ExecStart"] = (
            "{ path=/opt/worker ; argv[]=/opt/worker ; ignore_errors=no ; start_time=[n/a] ; pid=0 ; status=0/0 }"
        )
        baseline = unit_snapshot(values, "a" * 64)
        values["ExecStart"] = (
            values["ExecStart"]
            .replace("[n/a]", "[timestamp]")
            .replace("pid=0", "pid=123")
        )
        self.assertEqual(unit_snapshot(values, "a" * 64), baseline)
        values["ExecStart"] = values["ExecStart"].replace("/opt/worker", "/opt/foreign")
        self.assertNotEqual(unit_snapshot(values, "a" * 64), baseline)

    def test_proc_fixture_rejects_foreign_listener_and_populated_cgroup(self):
        from instance_control.production_driver import listener_owned, cgroup_empty

        with tempfile.TemporaryDirectory() as root:
            proc = Path(root) / "proc"
            (proc / "net").mkdir(parents=True)
            (proc / "123" / "fd").mkdir(parents=True)
            (proc / "123" / "cgroup").write_text("0::/unit\n")
            (proc / "123" / "fd" / "3").symlink_to("socket:[42]")
            header = "header\n"
            row = "0: 00000000:270F 00000000:0000 0A 0 0 0 0 0 42\n"
            (proc / "net" / "tcp").write_text(header + row)
            (proc / "net" / "tcp6").write_text(header)
            self.assertTrue(listener_owned(9999, "/unit", proc_root=proc))
            (proc / "net" / "tcp").write_text(header + row + row.replace(" 42", " 43"))
            self.assertFalse(listener_owned(9999, "/unit", proc_root=proc))
            cgroups = Path(root) / "cgroup"
            (cgroups / "unit").mkdir(parents=True)
            events = cgroups / "unit" / "cgroup.events"
            events.write_text("populated 1\n")
            self.assertFalse(cgroup_empty("/unit", cgroup_root=cgroups))
            events.write_text("populated 0\n")
            self.assertTrue(cgroup_empty("/unit", cgroup_root=cgroups))

    def test_health_probe_rejects_slow_or_replaced_process(self):
        clock = [0.0]
        identity = {"pid": 123, "start_ticks": 4, "boot_id": "boot", "cgroup": "/unit"}
        driver = SystemdDriver(
            {"runtime_directory": "/fake", "health_port": 9999},
            monotonic=lambda: clock[0],
            identity=lambda _: {"pid": 123, "start_ticks": 4, "boot_id": "boot"},
        )
        with (
            mock.patch(
                "instance_control.production_driver.listener_owned", return_value=True
            ),
            mock.patch(
                "instance_control.production_driver.http.client.HTTPConnection"
            ) as connection,
        ):
            connection.return_value.getresponse.return_value.status = 200
            self.assertTrue(driver._health(identity, 5))
            driver.identity = lambda _: {
                "pid": 123,
                "start_ticks": 999,
                "boot_id": "boot",
            }
            self.assertFalse(driver._health(identity, 5))
            driver.identity = lambda _: {
                "pid": 123,
                "start_ticks": 4,
                "boot_id": "boot",
            }

            def late():
                clock[0] = 6
                return mock.Mock(status=200)

            connection.return_value.getresponse.side_effect = late
            self.assertFalse(driver._health(identity, 5))

    def test_capture_is_read_only_and_not_qualification(self):
        driver, calls = self.docker()
        driver.target["configuration_sha256"] = "0" * 64
        with self.assertRaisesRegex(ControlError, "configuration_drift"):
            driver.inspect(time.monotonic() + 5)
        driver.capture = True
        candidate = driver.inspect(time.monotonic() + 5)
        self.assertNotEqual(candidate["configuration"], "0" * 64)
        self.assertTrue(all(c[0][-2] == "inspect" for c in calls))


class PolicyTests(unittest.TestCase):
    def test_empty_disabled_config_and_authority_binding(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "vllm-hust.production-backend/v1",
                        "enabled": False,
                        "executor_uid": os.geteuid(),
                        "state_directory": str(Path(root) / "state"),
                        "targets": [],
                    }
                )
            )
            path.chmod(0o600)
            policy = ProductionPolicy.load(str(path))
            self.assertFalse(policy.enabled)
            self.assertEqual(policy.targets, {})
            other = Store(str(Path(root) / "other"), initialize=True)
            with self.assertRaisesRegex(ControlError, "authority_directory_mismatch"):
                ProductionBackend(other, policy)

    def test_private_manager_and_strict_unit_allowlist(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "runtime"
            directory.mkdir(mode=0o700)
            endpoint = socket.socket(socket.AF_UNIX)
            self.addCleanup(endpoint.close)
            endpoint.bind(str(directory / "bus"))
            binary = str(Path("/usr/bin/systemctl").resolve())
            target = {
                "instance_id": "fixed",
                "profile_id": "fixed-profile",
                "profile_sha256": "a" * 64,
                "kind": "systemd",
                "name": "devhub-managed-fixture.service",
                "runtime_directory": str(directory),
                "configuration_sha256": "b" * 64,
                "artifacts": [{"path": binary, "sha256": artifact_sha(binary)}],
                "timeout_seconds": 5,
                "stop_seconds": 1,
                "health_port": 19999,
            }
            data = {
                "schema": "vllm-hust.production-backend/v1",
                "enabled": False,
                "executor_uid": os.geteuid(),
                "state_directory": str(Path(root) / "state"),
                "targets": [target],
            }
            path = Path(root) / "policy.json"
            path.write_text(json.dumps(data))
            path.chmod(0o600)
            policy = ProductionPolicy.load(str(path))
            policy.verify_host(target)
            directory.chmod(0o755)
            with self.assertRaisesRegex(ControlError, "private_manager_required"):
                policy.verify_host(target)
            target["name"] = "sage-mate-vllm-engine.service"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ControlError, "unit_not_allowlisted"):
                ProductionPolicy.load(str(path))
            target["kind"] = "docker"
            target["name"] = "my-container-name"
            path.write_text(json.dumps(data))
            with self.assertRaises(ControlError):
                ProductionPolicy.load(str(path))


if __name__ == "__main__":
    unittest.main()
