# Unified instance lifecycle

1. Freeze repository/host baseline and audit existing authority: complete.
2. Generic lifecycle API, durable concurrency/recovery: complete for injected qualified backends; shipped backend is explicit simulation only.
3. Fake integration and regressions: complete: 253 pytest tests and 56 subtests passed, including 20 new lifecycle tests and legacy-enrollment regression.
4. API/runbook/product examples and review: complete: documentation, examples, default-off template, independent CPU CI; local review and lint passed.
5. Commit, reconcile remote main, push and verify: complete. Implementation 35508ad and CI fix eff7787 pushed to main; lifecycle CI 34183534957 passed. Documentation-only completion record follows, with unchanged tested code.

Constraints: no production lifecycle changes, no automatic enrollment, preserve dirty work, exclude Sage Mate Responses and state-centric engine.

Boundary: no qualified production Docker/systemd adapter was present. Do not claim real inference rollout. OS writer exclusion and target-specific rollback must precede enrollment; all supplied gates remain closed.

Errors: initial sandbox denied bus/docker/socket and Git metadata/network access; retried with tool-required escalation. Extended tests exposed fixture schema initialization race, corrected. One test expected state_conflict where implementation consistently uses operation_conflict; corrected expectation. Ruff issues corrected.
