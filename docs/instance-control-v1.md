# Instance control v1: default-off producer milestone

Status: isolated transaction implementation; **not production lifecycle ready**.
No production backend, instance enrollment, service restart, NPU operation or
external-writer permission change is included. Do not open either product's gate
because these files are present. The owner CLI deliberately rejects all effects.

## Accepted consumer and ownership

Accept Sage Mate `d310686`'s exact `vllm-hust.instance-owner-entry/v1` JSON/stdin
protocol and `config/instance-owner-contract.json`. No schema change is requested.
`serve/start/stop/restart/reconcile/cleanup/monitor` are recognized; without a
qualified backend all return exit 2, `lifecycleAvailable=false`, no fallback.
Caller `owner_id`, `consumer`, `invocation_id`, inherited env and enable preference
are never authorization. Only the process's independently authenticated OS
identity may be mapped to host policy. A Web admin session must NOT be translated
into an arbitrary `administrator_uid` field.

Workstation is the single writer for this dev-hub controller implementation.
Workstation owns library preparation, compatibility/worker evidence, approval UI
and a pinned thin client. Sage Mate owns its consumer and lifecycle entrypoints;
it must not copy this state machine. Both consume a committed dev-hub gitlink.
Runtime-manager backend changes need separate explicit file ownership agreement.

Extension Manager owns Manifest `0.2-experimental`, discovery, compatibility,
configuration, intent, conflict detection and Provider rendering. This service
protocol is not another plugin API. It must not call plugin `register()` directly
or independently generate Manager-owned native manifests. See the documentation
baseline `vllm-hust-docs@e70e423` BidKV packaging guide and Workstation's
`docs/mod-plugin-guide-alignment.md`.

## Implemented library

`scripts/instance_control/` uses stdlib only. `DeploymentSpec.freeze(dict)` stores
canonical immutable JSON bytes and a SHA256, including:

- immutable image **ID and digest** and platform;
- Core/Ascend/Manager source SHA and wheel hashes; optional witness and Mod pins;
- original Mod manifest (Manager, not this controller, validates its domain);
- model ID/revision/path and model file-tree hash;
- physical device IDs, TP/PP, graph configuration, ports and mount snapshots;
- serving interpreter, complete argv, non-secret env, working directory, explicit
  plugin allowlist, fully resolved engine options;
- Provider source/config/rendered bytes/hash and qualification receipt reference;
- versioned secret references, never secret values.

No mutable `.env` lookup occurs during execution. JSON validation checks a
declared snapshot, not real capture completeness. `backend.qualify` must resolve
and prove the image, artifacts, model, mounts, secrets, Provider result and all
implicit launch defaults. A hash or client-written `qualified` label cannot
substitute for that check. Model, all resources, TP/PP and graph are invariant
across Mod transitions. Only one Mod per instance is currently admitted.

Host-private mode-0700 storage / mode-0600 SQLite provides `BEGIN IMMEDIATE`,
`synchronous=FULL`, immutable spec/plan storage, generation/CAS, one-time hashed
approval nonces and an append-only operation event sequence. No deployment state
is created merely by parsing an owner request.

`Controller` operations:

1. Host-admin `register`: fixed backend, action allowlist, owner identity mapping,
   independently qualified fencing receipt, captured healthy baseline.
2. `plan`: backend qualification + fresh actual identity, complete candidate and
   baseline snapshots, invariant check, restart impact, verification and recovery
   budgets, expiry, expected generation/fence and exact rollback scope.
3. `approve`: actual authorized OS identity issues a one-time secret nonce for
   the exact plan/action/generation/expiry. The private store holds only its hash.
   `cancel_plan` durably cancels only a plan which has not reserved an operation;
   it prevents both later approval and consumption of an already issued approval.
   Reserved or executing work returns `cancellation_not_safe` and remains under
   its rollback/recovery state machine.
4. `begin`: atomically revalidate identity/CAS, consume approval, increment fence,
   store operation/executor identity and retain the complete baseline snapshot.
5. `execute`: persisted applying -> synchronous fenced deployment -> verifying ->
   exact process/component execution and inference evidence -> committed.
6. Failure: only the original baseline, while this operation still owns the
   resource. Untouched healthy baseline ends failed without a restart. Foreign
   identity or failed restoration leaves recovery-required/rollback_failed.
7. `recover_approve`: an explicit admin issues a separate one-time nonce bound to
   the exact operation, instance, current generation/fence and original bounded
   recovery deadline. `recover` atomically consumes it only after backend proof of
   old effects' quiescence, then persists a higher fence and new executor identity.
   Old executors are rejected even if they revive. Expiry/PID absence alone never
   authorizes recovery; an expired original recovery scope cannot be extended by
   minting another nonce.

Disable is a new approved no-Mod/no-witness deployment. Manual rollback requires
another plan/approval and a retained revision. Reference protection is conservative:
all stored specs remain retained, so v1 does not garbage-collect their artifacts.

## Backend contract and fencing boundary

Backends are trusted host code injected by the controller, not names/import paths
from a browser. Required methods: `qualify`, `inspect`, `owns`, synchronous
`deploy`, bounded `verify`, `quiescent` (see controller and CPU fixture).

All mutation methods, including monitor recovery and cleanup, must execute under
the same authoritative fence. Every backend effect validates current operation,
executor and monotonic fencing epoch inside the authority transaction. The lock
is retained across a **synchronous bounded effect**. No async child writer may
outlive it. If this cannot be guaranteed, reject backend qualification. SQLite
alone cannot fence an external daemon's already queued work.

Nested authority entry fails immediately with busy; it never waits while holding
another lifecycle lock or returns to an unfenced legacy writer. A blocking
`systemctl start` that waits for ExecStart to re-enter this owner CLI is therefore
not a valid backend. A production adapter must supply direct non-recursive
primitives and an approved foreground supervisor protocol; it cannot reuse the
old shell entrypoint recursively.

External root/Docker/systemctl writers are outside SQLite's security boundary.
Before enabling: restrict daemon socket/unit/config write access to the owner
broker; audit watchdog, ExecStopPost, boot recovery and release installers that
modify `.env`/checkout before quickstart; prove in-flight daemon commands are
fenced; test foreground signal propagation and startup/cleanup re-entry. These
checks are **not** satisfied by a receipt string or a caller's ID. No host OS
policy or production adapter is installed by this milestone.

## Tests and next gates

Run `python3 -m unittest discover -s tests -p 'test_instance_transactions.py'`.
Tests use temp directories and a synchronous fake resource backend, with real
multi-process approval/CAS contention. Fault injection covers reservation, apply,
effect completion, verification, commit, every rollback checkpoint and recovery
executor replacement. Tests cover replay/expiry/tampering, closed gate, external
identity drift, foreign occupancy, failed rollback, immutable snapshot drift,
model/TP/graph preservation, redacted errors and nested writer rejection.

These are control-logic evidence, NOT real Mod inference or production fencing.
Next gates: production backend/OS writer exclusion, authenticated local transport,
foreground supervision, Manager-rendered launch consumption, thin-client/UI wiring
and separate target-specific TP4/graph qualification. Keep all live gates closed.

The separate `instance-control/v1` local transport is described in
`config/instance-control-contract.json` and `scripts/instance_control_entry.py`.
It accepts only registered candidate/instance/plan/operation IDs and opaque approval
nonces, not deployment specs, commands or owner authorization claims. Without
`VLLM_HUST_INSTANCE_CONTROL_CONFIG`, `inspect` truthfully reports unavailable and
every mutation fails closed. A configured authority additionally requires an
absolute, non-symlink, mode-0600 host file owned by root or the process euid; that
file fixes the mode-0700 state directory, administrator euid allowlist, backend ID
allowlist and candidate-ID-to-spec-hash map. See
`config/instance-control-host.example.json`.

Trusted host code may embed `ControlTransport` and inject already constructed
backend objects. Neither host configuration nor wire JSON can import a backend.
The standalone CLI deliberately injects none, so a registered shared instance is
reported with `productionBackendQualified=false` and `lifecycleAvailable=false`.
`operationsAccepting` is a stricter current-state gate: it is true only when the
authority is enabled, the backend is qualified, the instance is ready and no
operation owns it. Closed, in-progress and recovery-required states use distinct
reason codes. A rejected plan or consumed approval does not falsely change
`authorityAvailable` to false. Unexpected backend exceptions are redacted to
`transport_unavailable`; their text and Python traceback never cross the CLI wire.
This provides real plan/approve/cancel/apply/disable/rollback/status and separately
approved recovery dispatch for qualified embedded fixtures without converting
repository checkout, Web login, a caller-provided owner ID or a configuration
string into production authority. Cancellation is intentionally limited to an
unreserved plan; this transport has no unsafe mid-deployment interrupt primitive.
Closing the new-operation gate rejects plan/approve/apply/disable/rollback, while
read-only status, safe unreserved-plan cancellation and separately authorized
recovery remain available so shutdown of the control feature cannot strand an
already reserved deployment.

Initial focused validation covers instance transactions, transport, existing
deployment receipts, optimization profiles and foreground ownership, plus Ruff
and diff checks. Test counts are reported by the validating commit rather than
hard-coded here as the fault matrix grows.

## Generic lifecycle integration

Allocation and start/stop now have a separate [product-neutral lifecycle API](instance-lifecycle-v1.md).
It reuses the private Store while keeping stopped/allocation state distinct from
verified Mod deployment state. Same-store dual registration is rejected; no
production backend or live-instance migration is enabled by this addition.
