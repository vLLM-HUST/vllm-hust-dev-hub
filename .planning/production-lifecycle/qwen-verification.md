# Primary verification of the successful Qwen3.8 review

Actual contribution: 8 bounded threat/test pairs and 2 atomicity caveats. No code
or tests were executed by Qwen in the successful retry. Attempt 1 timed out after
tool-read activity; attempt 2 (tool-free context, same profile) exited 0.
Model/profile: Qwen/Qwen3.8-27B, sage_qwen38, Responses, context window 32768;
codex-cli 0.153.4. Raw auth/config contents and command-backed credentials were
not included in the prompt or checked-in evidence.

| Qwen item | Primary conclusion | Verification |
|---|---|---|
| 1. Transfer during helper window | Valid; check+CAS already share a transaction and operation remains attached until terminal. | `test_qwen_transfer_rejected_through_each_helper_window`, generic resource-transfer tests |
| 2. Idempotency generation/direction | Already correct: exact body hash is bound to actor+key; changed generation/direction rejects rather than suppressing legitimate work. | Existing exact-replay, generation conflict and same-key process tests |
| 3. Nonce redelivery/race | Consume-once is valid. Refine claim: an *unconsumed* nonce within the same valid fence is not inherently invalid; a consumed or superseded nonce is. | `test_qwen_two_helpers_one_nonce_exactly_one_effect`, current-fence replay and expiry tests |
| 4. ACK before settled crash | Valid and a hard boundary. Intent-only remains quarantined even if the resource looks stopped/running. | Actual-process crash at `intent` and `daemon_returned` |
| 5. Parent timeout and duplicate rollback | Valid. Implementation quarantines and invalidates later helper commits rather than promising a surviving helper must commit. No second compensator is launched. | `test_surviving_executor_does_not_trigger_parallel_rollback`, inherited-lock subprocess test |
| 6. Lock/PID absence is not daemon quiescence | Valid. Unknown journal persists; even explicit admin recover cannot clear it. | Unknown timeout plus repeated recover, actual-process crash windows |
| 7. Foreign fixed identity/config | Refine scenario: ordinary Docker clients cannot generally choose an arbitrary container ID. Same-ID configuration drift and unit-name reuse are still valid threats. | Docker fingerprint/ID tests, policy drift and foreign identity tests |
| 8. Stale baseline/owner restore | Valid. Profile/config binding, operation ID, fence and exact incarnation are rechecked. | Foreign identity, changed policy, current/stale fence and rollback failure tests |

Additional primary findings addressed: any nonzero CLI exit may follow accepted
work and therefore is not a safe failure ACK; `ExecStart` debug metadata is
volatile and must not poison immutable configuration fingerprints; stop must
prove cgroup emptiness, and a local /health response must be attributed to the
unit rather than a foreign listener; preflight/dry-run must not open mutation
gates; policy files and executable/artifact parent directories must be trusted.

No claim is made that a daemon consumes native fencing tokens, that root can be
fenced, that all daemon endpoints can be inferred from one socket, or that a
simulation proves production qualification. Independent custody/real-target
qualification remains a deployment gate.
