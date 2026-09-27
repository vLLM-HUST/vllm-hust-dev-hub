Dev Hub's lifecycle API previously had only a simulation backend. Add restricted production Docker/systemd adapters for explicitly approved, pre-existing stopped targets while leaving all production policy gates disabled and the allowlist empty. Sage Mate/Workstation keep using the same thin API; no product runtime, online service, deployment or accelerator was operated by this change.

The backend validates immutable target/profile/configuration/artifact pins, private manager custody, one-use expiring leases and the durable instance fence. A trusted executor inherits the worker lock, records intent before daemon commands, and commits only observed, identity-checked health evidence. Confirmed effects can restore their retained baseline; unknown daemon outcomes and surviving-helper timeouts quarantine instead of launching unsafe concurrent rollback. Add read-only preflight/dry-run and diagnostic configuration capture, with no activation or registration side effects.

The adapter deliberately rejects shared Docker/system units, mutable containers, autonomous restart/hooks, foreign identities and unknown-intent force recovery. External writer exclusion, sealed inputs and real isolated target qualification remain explicit production rollout gates; none is declared completed here.

Validation:
- Full local suite: 287 passed, 63 subtests passed.
- Ruff and diff checks passed.
- New fault fixtures cover daemon command shapes, process/ACK crash windows, partial health failure, timeout/rollback failure, nonce races/replay/expiry, transfer conflicts, inherited lock custody, private endpoint checks, unit cgroup/listener attribution and PID/health drift.
- Qwen3.8 bounded threat/test review completed on a same-profile tool-free retry after the initial file-tool attempt stalled. The primary independently checked all eight items, corrected two overbroad premises and implemented/ran the tests. Raw credentials and CLI logs are excluded; review and verification are in `.planning/production-lifecycle/`.
- Hosted CI must pass before merge. No production backend activation or live Docker/systemd lifecycle validation is included.
