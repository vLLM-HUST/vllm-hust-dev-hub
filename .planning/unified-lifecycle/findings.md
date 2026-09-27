# Findings
Existing instance_control already supplies private SQLite, deployment CAS, approvals, fencing and rollback; inspect reuse before adding lifecycle. manage.sh status may install a missing unit: do not use for read-only baseline. Initial worktree clean; no submodules.

Remote main is a9438f1 (initial worktree e8b0cf7 was stale). Updated isolated branch to main, retaining all remote fixes. No open PRs. Existing transport now handles Mod plans but has no start/stop, cross-product principals, durable client idempotency or allocation requests. New lifecycle namespace will share Store without pretending stopped instances are healthy Mod deployments.
Production baseline: sage-mate-vllm-engine and both statecentric units running; Sage container 1cf7fbf70dc1 and statecentric container 2d8450dda23e. Other running containers are pipeline-microbatch and monitoring. No mutations performed. Docker required sudo read-only; initial sandbox reads failed.
