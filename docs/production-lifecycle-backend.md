# Default-off Docker/systemd lifecycle adapter

This extends `vllm-hust.lifecycle/v1` with a pluggable `production` backend for
**pre-existing, explicitly allowlisted, stopped** resources. It does not discover,
create, recreate, install, deploy or adopt a running service. No Sage Mate or
Workstation profile is supplied, and neither product owns an executor. Their
existing thin-client protocol remains unchanged.

The repository policy is `enabled:false`, with `targets:[]`; the service does not
load production code unless a trusted operator supplies `--production-config`.
The lifecycle admission gate and the separate production mutation gate must both
be open for a new effect. Closing the production gate rejects new start/stop at
admission (`backend_operations_disabled`). Recovery of a retained, confirmed
operation remains possible under its original pinned configuration. Importing
code, preflight, digest capture and dry-run never open either gate.

## Supported targets and custody boundary

The host policy is a private, mode-0600 JSON file owned by root or the dedicated
executor UID, with non-writable parent directories. It binds the exact authority
state directory, executor UID, instance, profile ID and complete profile digest.
Targets cannot be selected, extended or parameterized by an API request.

| Backend | Required scope | Rejected examples |
|---|---|---|
| Docker | Exact 64-hex container ID and immutable inspected configuration digest, explicit private Unix daemon socket, native HEALTHCHECK, no restart policy or auto-remove, read-only root and persistent mounts | Container name/tag discovery, shared Docker socket, privileged/host-PID containers, lifecycle-capable capabilities, mutable root/persistent mounts, broad control-directory/socket mounts |
| systemd | Exact `devhub-managed-*.service` in a dedicated user manager, pinned fragment with no drop-ins, `Type=notify`, `NotifyAccess=main`, `Restart=no`, `KillMode=control-group`, no delegated cgroups, protected cgroups and no new privileges | Shared system units, existing Sage unit names, timers/hooks/recursive shell management, mutable EnvironmentFiles, uncontrolled dependencies |

The manager runtime directory must resolve canonically, be owned by the executor
UID and have mode 0700; its `docker.sock` or `bus` must also belong to that UID.
The configured binary and artifacts are hashed from trusted regular files;
symlinks, unsafe ownership and group/world-writable artifacts are rejected.
The Docker ID, image ID, creation identity, Config, HostConfig and mount metadata
form its configuration fingerprint. Runtime environment values may be read in
private process memory for hashing, but are never returned, logged or persisted.
For systemd, the immutable fragment and stable manager properties are pinned;
volatile `ExecStart` execution-result metadata is excluded. Versioned
`LoadCredential` sources must also appear in the artifact pins.

**These checks require an operational custody prerequisite:** this executor UID
and root are trusted, all products run under different UIDs, the daemon has no
other writable sockets/TCP listeners exposed to other actors, and all watchdogs,
legacy launchers, release jobs and unit writers have been excluded. Private socket
permissions alone do not prove the absence of another daemon endpoint. The code
cannot fence a hostile root administrator or a process given the same executor
credentials. Do not set `enabled:true` until those exclusions are independently
reviewed. Existing shared Docker access and legacy launchers are not qualified.
Mounted model/artifact sources must remain immutable for the retained baseline;
pin the relevant inputs, not merely the CLI executable. Rollback restores runtime
intent/configuration, not application memory, request progress or mutable data.

## Executor, lease and recovery protocol

1. Existing API approval atomically claims resources with generation CAS. A
   start/stop request atomically stores the exact idempotent admission response
   and retained baseline; no command is accepted from the caller.
2. The worker takes the authority's nonblocking `flock`, increments the fencing
   epoch and commits `applying`. A one-use, expiring nonce is bound to operation,
   instance, direction, profile/config binding and fence. Only its digest is
   stored; the raw value is sent through an anonymous pipe.
3. The trusted helper inherits the **same open lock description** using
   `pass_fds`. It consumes the nonce atomically and revalidates the durable owner,
   epoch and configuration before recording an external effect intent.
4. `intent` is durable before the fixed daemon command. After a successful
   synchronous reply and fresh stable identity inspection, `settled` records the
   exact resulting resource. Health and identity validation produce `verified`.
5. The controller commits only a verified result. A normal settled health failure
   can restore the original running/stopped baseline, provided the current
   resource still matches that exact operation's observed incarnation.
6. Parent/client death does not release a surviving helper's lock. A parent wait
   timeout raises `EffectInProgress`, leaves recovery-required, and **does not
   spawn a concurrent rollback helper**. A helper invalidated by this transition
   cannot commit a later stale result.
7. Helper/host death with only `intent`, command timeout, lost connection, even a
   nonzero CLI exit without a success acknowledgment: the daemon outcome is
   unknown. Recovery refuses all effects. A released lock, missing PID, expiry,
   apparently stopped resource or a fresh fence is not proof that a queued daemon
   request cannot run later. The unknown journal cannot be overridden by the
   admin `recover` API.
8. A crash after `settled`/`verified` can restore the retained baseline after
   fresh configuration and exact identity checks under a new fence. Foreign
   incarnation/configuration, unresolved prior intent or failed restoration keeps
   `recovery_required` and retains resource claims.

Atomicity means admission, claim, owner transfer, nonce consumption, epoch and
journal transitions are atomic in the authority. It does **not** mean a Docker or
systemd effect can atomically commit with SQLite. Neither daemon consumes our
fence natively; the lock, trusted executor, journal and conservative quarantine
close the dangerous reuse windows. There is deliberately no “force recover” or
lease-timeout takeover shortcut.

Docker starts use the stopped container's exact ID without attach/interactive
options, preserving its immutable configuration; readiness is verified separately.
See the [Docker start command contract](https://docs.docker.com/reference/cli/docker/container/start/).
Systemd starts/stops use synchronous job completion, not recursive owner scripts
or `--no-block`. After stop, a populated cgroup is rejected. Running identity
includes boot ID, PID/start ticks, unit invocation and cgroup. `/health` is probed
only after listener inodes are attributed to the unit's cgroup; slow probes,
foreign listeners and PID reuse cannot pass verification. Each probe consumes the
remaining monotonic budget. No API response contains a raw daemon reply or nonce.

## Policy and read-only operator tools

Start from `config/instance-production-host.example.json`. The configured
`state_directory` must exactly match the existing private authority, and
`executor_uid` must be the dedicated service account's UID. Each target has exactly
these fields:

```json
{
  "instance_id": "isolated-example",
  "profile_id": "isolated-profile",
  "profile_sha256": "<SHA256 of the complete canonical lifecycle profile>",
  "kind": "docker",
  "name": "<exact 64-hex pre-created container ID>",
  "runtime_directory": "/run/devhub-private-manager",
  "configuration_sha256": "<reviewed configuration fingerprint>",
  "artifacts": [{"path": "/usr/bin/docker", "sha256": "<binary SHA256>"}],
  "timeout_seconds": 120,
  "stop_seconds": 20,
  "health_port": 0
}
```

This is a field guide, not an enabled or complete production profile. Real artifact
pins must include the immutable launch inputs; for systemd, include the unit
fragment, program, dependencies and any versioned credential files. Its health
port must be 1024–65535; Docker uses `health_port:0` and its native healthcheck.
Timeouts are bounded to 5–600 seconds, stop timeout is positive and smaller than
the total. A systemd unit's own start/stop timeouts must fit this budget. Temporary
container scratch space can be placed in tmpfs at `/tmp` or `/run`; persistent
writable launch inputs are rejected.

The following commands are **read-only operator tooling** and were not run against
any live target during this change:

```bash
python3 scripts/instance_production_preflight.py \
  --policy /etc/vllm-hust/production.json --instance-id isolated-example
python3 scripts/instance_production_preflight.py \
  --policy /etc/vllm-hust/production.json --instance-id isolated-example --desired running
```

For a not-yet-pinned configuration, `--capture-configuration` emits a candidate
fingerprint while keeping all other structural/custody checks. It is diagnostic,
not qualification, approval or enrollment. Review the fingerprint and sealed
inputs offline, then store it in the disabled host policy; rerun ordinary preflight
and dry-run before enabling a future isolated qualification.

Future service wiring is `instance_lifecycle.py --config <lifecycle policy>
--production-config <production policy>`. The checked-in systemd service does not
add this flag. Its sandbox must expose the exact private manager endpoint (the
default ProtectHome setting may hide `/run/user`), and its shutdown timeout must
cover the selected helper budget. Review any override separately. Do not install
or restart a service merely because this code is merged.

Sage Mate and Workstation use the existing `request/approve/start/stop/status/
operation/audit` API and generation/idempotency rules. They receive no nonce,
backend configuration, Docker group membership or unit control permission. UI
buttons must treat conflict, drift, disabled and recovery-required as distinct
states; neither product should duplicate the executor or retry via a shell.

## Failure operations and remaining production gates

A failed health check after a confirmed effect is automatically compensated within
the original baseline scope. For recovery-required with an unknown daemon intent,
keep admission closed. A host operator must preserve evidence and establish
quiescence of the **dedicated** manager and every old writer in a separate incident
procedure. Do not edit SQLite, delete locks, restore an old DB alone, reissue a
nonce or blindly invoke `recover`. No automatic unknown-intent clearance or shared
production incident procedure is included. Root-level custody changes and recovery
of a dead/wedged daemon require separate authorization and qualification.

Before any real target can be enabled: prove external-writer exclusion and sealed
inputs; prepare a compatible isolated unit/container; validate real startup,
health timeout, stop/cgroup cleanup, helper and host death, manager restart,
rollback and recovery failure; audit permission and backup/restore boundaries;
then approve the specific target and rollout. This round runs **fake daemon and
filesystem fixtures plus CPU-only process tests**, not real-online inference or
real Docker/systemd lifecycle commands. No NPU, Sage/Workstation deployment or
state-centric native engine is touched.

## Validation and bounded Qwen contribution

`tests/test_production_lifecycle.py` exercises both daemon command shapes and
fingerprint parsing, real helper-process lock inheritance, one-use nonce races,
expiry/replay/stale ownership, gate closure, confirmed partial/health failures,
unknown timeout, rollback failure, crash at each journal boundary, restart,
foreign identity, unit hooks, private endpoints, listener/cgroup ownership and
slow/replaced health probes. Existing lifecycle tests retain concurrent request,
idempotency, atomic resource claim and owner-transfer coverage.

Qwen3.8 was invoked with `codex --profile qwen38 exec --sandbox workspace-write`.
The first file-reading attempt stalled without a final report and was terminated;
profile checks confirmed Qwen3.8, 32768 context and Responses, without an explicit
protocol or context-overflow error. A smaller, tool-free retry on the same profile
completed successfully. Its eight threat/test pairs and the primary's independent
verification are retained under `.planning/production-lifecycle/`; no fallback
model or Qwen test execution is claimed. The primary added and ran the tests and
owns all implementation and merge decisions.
