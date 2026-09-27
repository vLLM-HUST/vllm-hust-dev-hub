from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from instance_control import ControlError, DeploymentSpec, Store  # noqa: E402
from instance_control.controller import Controller  # noqa: E402
from instance_control.schema import digest  # noqa: E402
from instance_control.transport import CONFIG_SCHEMA, ControlTransport, load_configuration  # noqa: E402
import instance_control_entry  # noqa: E402


def specification(*, mod=False):
    artifact = {"source_sha": "a" * 40, "wheel_sha256": "b" * 64}
    manifest = {"schema_version": "0.2-experimental", "extension_id": "fixture-mod"}
    rendered = {"mod": mod}
    return {
        "schema": "vllm-hust.deployment-spec/v1",
        "image": {"id": "sha256:" + ("2" if mod else "1") * 64,
                  "digest": "sha256:" + ("4" if mod else "3") * 64,
                  "platform": "linux/arm64"},
        "core": artifact, "ascend": artifact, "manager": artifact,
        "witness": artifact if mod else None,
        "mods": [{"id": "fixture-mod", "artifact": artifact, "manifest": manifest}] if mod else [],
        "model": {"id": "Qwen/Qwen3.8-27B", "revision": "c" * 40,
                  "path": "/models/qwen", "files_sha256": "d" * 64},
        "resources": {"devices": [0, 1, 2, 3], "tp": 4, "pp": 1,
                      "graph": {"mode": "graph", "configuration": {"capture_sizes": [1, 2]}},
                      "ports": [], "mounts": []},
        "launch": {"interpreter": "/usr/bin/python3", "argv": ["/usr/bin/python3", "-m", "vllm"],
                   "environment": {"PATH": "/usr/bin:/bin"}, "working_directory": "/srv/vllm",
                   "plugin_allowlist": ["fixture-mod"] if mod else [],
                   "resolved_options": {"tensor_parallel_size": 4, "pipeline_parallel_size": 1,
                                        "model": "Qwen/Qwen3.8-27B", "enforce_eager": False,
                                        "compilation_config": {"capture_sizes": [1, 2]}}},
        "provider": {"id": "fixture", "source_sha": "e" * 40,
                     "configuration": {"mod": mod}, "rendered": rendered,
                     "rendered_sha256": digest(rendered),
                     "qualification": {"receipt_sha256": "f" * 64, "status": "qualified"}},
        "secrets": [{"id": "api-key", "version": "v1", "target": "VLLM_API_KEY"}],
    }


class Backend:
    def __init__(self, now, baseline):
        self.now = now
        self.spec = DeploymentSpec.freeze(baseline)
        self.generation = 1
        self.operation = None
        self.fail = False
        self.quiescent_value = True

    def qualify(self, registration, spec):
        return registration["backend_id"] == "fixture"

    def inspect(self, registration):
        mod_ids = [item["id"] for item in self.spec.value()["mods"]]
        return {"instance_id": registration["instance_id"], "spec_hash": self.spec.sha256,
                "identity": {"boot_id": "boot", "supervisor_generation": str(self.generation),
                             "resource_id": str(self.generation), "started_at": str(self.generation),
                             "processes": [{"pid": 101, "start_ticks": self.generation,
                                            "role": "worker", "rank": 0}]},
                "captured_at": self.now[0], "healthy": True,
                "components_executed": mod_ids, "inference_verified": True}

    def owns(self, registration, token, expected_identity, *, restore):
        return self.operation == token["id"] or (
            self.operation is None and self.inspect(registration)["identity"] == expected_identity
        )

    def deploy(self, registration, spec, token, deadline, *, restore):
        if self.fail and not restore:
            raise ControlError("fixture_failure")
        self.operation = token["id"]
        self.spec = spec
        self.generation += 1

    def verify(self, registration, spec_hash, token, deadline):
        observed = self.inspect(registration)
        if observed["spec_hash"] != spec_hash:
            raise ControlError("runtime_spec_drift")
        return observed

    def quiescent(self, registration, operation):
        return self.quiescent_value


@pytest.fixture
def authority(tmp_path):
    now = [1000.0]
    state = tmp_path / "state"
    store = Store(state, initialize=True)
    baseline = specification()
    candidate = specification(mod=True)
    backend = Backend(now, baseline)
    controller = Controller(store, {"fixture": backend}, admin_uids=[os.geteuid()],
                            enabled=True, clock=lambda: now[0])
    registration = {"instance_id": "fixture-instance", "owner_id": "fixture-owner",
                    "profile_id": "fixture-profile", "backend_id": "fixture",
                    "actions": ["apply", "disable", "rollback"],
                    "owner_uids": [os.geteuid()], "fencing_receipt_sha256": "9" * 64}
    controller.register(registration, baseline)
    candidate_hash = DeploymentSpec.freeze(candidate).sha256
    with store.transaction() as db:
        store.put(db, "spec", candidate_hash, candidate, immutable=True)
    config = tmp_path / "control.json"
    value = {"schema": CONFIG_SCHEMA, "enabled": True,
             "state_directory": str(state), "administrator_uids": [os.geteuid()],
             "backend_ids": ["fixture"], "candidates": {"fixture-mod": candidate_hash}}
    config.write_text(json.dumps(value))
    config.chmod(0o600)
    transport = ControlTransport.open(str(config), {"fixture": backend}, clock=lambda: now[0])
    return transport, backend, now, config, baseline, candidate


def request(action, **parameters):
    return {"schema": "vllm-hust.instance-control/v1", "action": action, **parameters}


def plan_approve(transport, deployment_action, candidate_id="fixture-mod"):
    planned = transport.dispatch(request("plan", instance_id="fixture-instance",
                                         candidate_id=candidate_id,
                                         deployment_action=deployment_action))["plan"]
    approval = transport.dispatch(request("approve", plan_id=planned["plan_id"]))["approval"]
    return planned, approval


def test_private_configuration_and_default_closed(tmp_path, authority):
    transport, _, now, config, _, _ = authority
    value = load_configuration(str(config))
    value["enabled"] = False
    closed = tmp_path / "closed.json"
    closed.write_text(json.dumps(value))
    closed.chmod(0o600)
    disabled = ControlTransport.open(
        str(closed), {"fixture": transport.backends["fixture"]}, clock=lambda: now[0]
    )
    assert disabled.dispatch(request("inspect", instance_id="fixture-instance"))["enabled"] is False
    with pytest.raises(ControlError, match="new_operations_disabled"):
        disabled.dispatch(request("plan", instance_id="fixture-instance",
                                  candidate_id="fixture-mod", deployment_action="apply"))
    closed.chmod(0o640)
    with pytest.raises(ControlError, match="untrusted_control_configuration"):
        load_configuration(str(closed))


def test_uninjected_backend_is_truthfully_unavailable(authority):
    _, _, now, config, _, _ = authority
    transport = ControlTransport.open(str(config), {}, clock=lambda: now[0])
    status = transport.dispatch(request("inspect", instance_id="fixture-instance"))
    assert status["instanceRegistered"] is True
    assert status["productionBackendQualified"] is False
    assert status["lifecycleAvailable"] is False
    assert status["reason"] == "host_backend_not_qualified"


def test_real_entrypoint_uses_private_config_but_never_invents_backend(authority):
    _, _, _, config, _, _ = authority
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts/instance_control_entry.py")],
        input=json.dumps(request("inspect", instance_id="fixture-instance")),
        text=True,
        capture_output=True,
        timeout=5,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
             "VLLM_HUST_INSTANCE_CONTROL_CONFIG": str(config)},
    )
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["authorityAvailable"] is True
    assert status["instanceRegistered"] is True
    assert status["productionBackendQualified"] is False
    assert status["lifecycleAvailable"] is False


def test_wire_redacts_unexpected_backend_error_and_preserves_authority(monkeypatch):
    class ExplodingAuthority:
        def dispatch(self, _request):
            raise RuntimeError("SECRET_CANARY backend command")

    monkeypatch.setattr(
        instance_control_entry.ControlTransport,
        "open",
        lambda _configuration: ExplodingAuthority(),
    )
    exit_code, response, is_error = instance_control_entry.dispatch_wire(
        request("inspect", instance_id="fixture-instance"), "/trusted/control.json"
    )
    assert exit_code == 2
    assert is_error is True
    assert response == {
        "protocol": "vllm-hust.instance-control/v1",
        "error": "transport_unavailable",
        "authorityAvailable": True,
    }
    assert "SECRET_CANARY" not in json.dumps(response)


def test_wire_domain_rejection_does_not_report_authority_outage(monkeypatch):
    class RejectingAuthority:
        def dispatch(self, _request):
            raise ControlError("plan_cancelled")

    monkeypatch.setattr(
        instance_control_entry.ControlTransport,
        "open",
        lambda _configuration: RejectingAuthority(),
    )
    exit_code, response, is_error = instance_control_entry.dispatch_wire(
        request("approve", plan_id="a" * 64), "/trusted/control.json"
    )
    assert exit_code == 2
    assert is_error is True
    assert response["error"] == "plan_cancelled"
    assert response["authorityAvailable"] is True
    assert "operationsAccepting" not in response


def test_apply_status_disable_and_retained_rollback(authority):
    transport, backend, _, _, baseline, candidate = authority
    plan, approval = plan_approve(transport, "apply")
    applied = transport.dispatch(request("apply", plan_id=plan["plan_id"], approval=approval))
    assert applied["operation"]["phase"] == "committed"
    assert backend.spec.sha256 == DeploymentSpec.freeze(candidate).sha256
    status = transport.dispatch(request("operation_status", operation_id=applied["operation"]["id"]))
    assert status["terminal"] is True
    assert [event["phase"] for event in status["events"]][-1] == "committed"

    backend.operation = None
    transport.configuration["candidates"]["baseline"] = DeploymentSpec.freeze(baseline).sha256
    plan, approval = plan_approve(transport, "disable", "baseline")
    disabled = transport.dispatch(request("disable", plan_id=plan["plan_id"], approval=approval))
    assert disabled["operation"]["phase"] == "committed"
    assert backend.spec.sha256 == DeploymentSpec.freeze(baseline).sha256

    backend.operation = None
    plan, approval = plan_approve(transport, "rollback")
    rolled = transport.dispatch(request("rollback", plan_id=plan["plan_id"], approval=approval))
    assert rolled["operation"]["phase"] == "committed"
    assert backend.spec.sha256 == DeploymentSpec.freeze(candidate).sha256


def test_approval_expiry_replay_and_action_substitution(authority):
    transport, _, now, _, _, _ = authority
    plan, approval = plan_approve(transport, "apply")
    with pytest.raises(ControlError, match="deployment_action_mismatch"):
        transport.dispatch(request("disable", plan_id=plan["plan_id"], approval=approval))
    transport.dispatch(request("apply", plan_id=plan["plan_id"], approval=approval))
    with pytest.raises(ControlError, match="approval_expired_or_replayed|generation_conflict"):
        transport.dispatch(request("apply", plan_id=plan["plan_id"], approval=approval))

    transport.configuration["candidates"]["baseline"] = transport.store.read(
        "instance", "fixture-instance"
    )["spec"]
    plan, approval = plan_approve(transport, "apply", "baseline")
    now[0] = plan["expires_at"] + 1
    with pytest.raises(ControlError, match="approval_expired_or_replayed"):
        transport.dispatch(request("apply", plan_id=plan["plan_id"], approval=approval))


@pytest.mark.parametrize("_iteration", range(32))
def test_concurrent_approval_consumption_has_one_winner(authority, _iteration):
    transport, _, _, _, _, _ = authority
    plan, approval = plan_approve(transport, "apply")

    def attempt():
        try:
            result = transport.dispatch(
                request("apply", plan_id=plan["plan_id"], approval=approval)
            )
            return result["operation"]["phase"]
        except ControlError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert outcomes.count("committed") == 1
    assert any(
        outcome in {"authority_busy_or_unavailable", "approval_expired_or_replayed",
                    "generation_conflict"}
        for outcome in outcomes
    )


def test_status_distinguishes_closed_busy_and_recovery(authority):
    transport, _, _, _, _, _ = authority
    closed = ControlTransport(
        {**transport.configuration, "enabled": False},
        {"fixture": transport.backends["fixture"]},
        clock=transport.clock,
    )
    status = closed.dispatch(request("inspect", instance_id="fixture-instance"))
    assert status["lifecycleAvailable"] is False
    assert status["operationsAccepting"] is False
    assert status["reason"] == "new_operations_disabled"

    plan, approval = plan_approve(transport, "apply")
    transport.controller.begin(plan["plan_id"], approval)
    status = transport.dispatch(request("inspect", instance_id="fixture-instance"))
    assert status["lifecycleAvailable"] is True
    assert status["operationsAccepting"] is False
    assert status["reason"] == "operation_in_progress"

    with transport.store.transaction() as db:
        instance = transport.store.get(db, "instance", "fixture-instance")
        instance["status"] = "recovery_required"
        transport.store.put(db, "instance", "fixture-instance", instance)
    status = transport.dispatch(request("inspect", instance_id="fixture-instance"))
    assert status["operationsAccepting"] is False
    assert status["reason"] == "recovery_required"


def test_failure_rolls_back_and_projects_durable_result(authority):
    transport, backend, _, _, baseline, _ = authority
    backend.fail = True
    plan, approval = plan_approve(transport, "apply")
    result = transport.dispatch(request("apply", plan_id=plan["plan_id"], approval=approval))
    assert result["operation"]["phase"] == "failed"
    assert backend.spec.sha256 == DeploymentSpec.freeze(baseline).sha256
    reopened = ControlTransport(
        transport.configuration, {"fixture": backend}, clock=transport.clock
    )
    persisted = reopened.dispatch(request("operation_status",
                                          operation_id=result["operation"]["id"]))
    assert persisted["operation"]["phase"] == "failed"


def test_recover_requires_quiescence_and_advances_fence(authority):
    transport, backend, _, _, _, _ = authority
    plan, approval = plan_approve(transport, "apply")
    token = transport.controller.begin(plan["plan_id"], approval)
    closed_config = {**transport.configuration, "enabled": False}
    recovery_transport = ControlTransport(
        closed_config, {"fixture": backend}, clock=transport.clock
    )
    recovery = recovery_transport.dispatch(
        request("recover_approve", operation_id=token["id"])
    )["approval"]
    backend.quiescent_value = False
    with pytest.raises(ControlError, match="old_executor_not_fenced"):
        recovery_transport.dispatch(
            request("recover", operation_id=token["id"], approval=recovery)
        )
    backend.quiescent_value = True
    recovered = recovery_transport.dispatch(
        request("recover", operation_id=token["id"], approval=recovery)
    )
    assert recovered["operation"]["phase"] in {"failed", "rolled_back"}
    assert transport.store.read("instance", "fixture-instance")["fence"] == token["fence"] + 1


def test_recovery_approval_expiry_replay_and_external_occupancy(authority):
    transport, backend, now, _, _, _ = authority
    plan, approval = plan_approve(transport, "apply")
    token = transport.controller.begin(plan["plan_id"], approval)
    expired = transport.dispatch(
        request("recover_approve", operation_id=token["id"])
    )["approval"]
    now[0] += 301
    with pytest.raises(ControlError, match="recovery_approval_expired_or_replayed"):
        transport.dispatch(request("recover", operation_id=token["id"], approval=expired))

    fresh = transport.dispatch(
        request("recover_approve", operation_id=token["id"])
    )["approval"]
    backend.quiescent_value = False
    with pytest.raises(ControlError, match="old_executor_not_fenced"):
        transport.dispatch(request("recover", operation_id=token["id"], approval=fresh))
    assert transport.store.read("recovery_approval", digest(fresh))["consumed"] is False
    backend.quiescent_value = True
    transport.dispatch(request("recover", operation_id=token["id"], approval=fresh))
    with pytest.raises(ControlError, match="operation_terminal|expired_or_replayed"):
        transport.dispatch(request("recover", operation_id=token["id"], approval=fresh))


def test_cancel_plan_before_reservation_and_refuse_active_cancel(authority):
    transport, _, now, _, _, _ = authority
    now[0] += 1
    plan, approval = plan_approve(transport, "apply")
    transport.enabled = transport.controller.enabled = False
    cancelled = transport.dispatch(request("cancel_plan", plan_id=plan["plan_id"]))
    assert cancelled["cancellation"]["plan_id"] == plan["plan_id"]
    transport.enabled = transport.controller.enabled = True
    with pytest.raises(ControlError, match="plan_cancelled"):
        transport.dispatch(request("approve", plan_id=plan["plan_id"]))
    with pytest.raises(ControlError, match="plan_cancelled"):
        transport.dispatch(request("apply", plan_id=plan["plan_id"], approval=approval))

    now[0] += 1
    plan, approval = plan_approve(transport, "apply")
    transport.controller.begin(plan["plan_id"], approval)
    with pytest.raises(ControlError, match="cancellation_not_safe"):
        transport.dispatch(request("cancel_plan", plan_id=plan["plan_id"]))
