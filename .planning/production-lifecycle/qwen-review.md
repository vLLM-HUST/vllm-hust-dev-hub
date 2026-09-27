

Static threat model — no tests run by me, no systems touched; each item pairs a threat with a concrete failure-injection test to be designed and run against fake fixtures only.

1. **Transfer vs. in-flight race.** Transfer is gated on "no in-flight operation," but if the check and the ownership mutation are not one SQLite FULL transaction, or "in-flight" does not cover the helper window (INTENT→SETTLED→VERIFIED), an admin transfer can move a resource ID mid-apply, so rollback/baseline restore lands on the wrong owner.
*Test:* fake daemon sleeps between INTENT and SETTLED; fire transfer in each phase (queued, applying, helper alive). Assert rejection in all three, or explicit deferral to commit/quiescence; assert no double-claim, no orphaned baseline, ownership CAS still passes post-commit.

2. **Idempotency key scope.** If keyed only on (actor, request_id), a replayed request_id across a generation CAS bump or across directions (start→stop) can suppress a legitimate new operation, or double-enqueue on product retry if the key is over-specified.
*Test:* fixture resubmits the same request_id at old and new generations and in opposite directions; assert replay returns the original result or a clean reject and never a second enqueue; a legitimate post-failure retry enqueues exactly once under the correct fence.

3. **Nonce re-delivery.** Nonces are one-time and fence-bound, but a helper crash after issuance and before INTENT — or the parent-timeout bug spawning two helpers — can present the same live nonce to a second helper; validation must consume-once from durable state, not just check expiry.
*Test:* kill the helper after issuance, before INTENT; a replacement presents the same nonce → assert rejection (consumed/fence mismatch). Also feed the same nonce to two concurrent helpers via a fake pipe; assert exactly one proceeds, the other quarantines, and exactly one INTENT row remains.

4. **INTENT-only crash after daemon ACK.** "Helper/host death with only INTENT" can still mean the daemon *completed*: a crash between dockerd/systemd ACK and the SETTLED write leaves the container actually running. Blind baseline restore in this window is a silent kill or no-op against unknown state.
*Test:* fake daemon ACKs `start`, then SIGKILLs the helper before SETTLED. On recovery assert: instance → quarantined (no auto-restore, no auto-kill), no compensation runs, lock resolves via flock semantics only, no second helper spawns; recovery requires explicit daemon-side identity verification.

5. **Duplicate rollback helper on parent timeout.** If the timeout handler cannot reliably observe helper liveness (zombie, closed pipe, reaped PID), it may launch a second rollback helper while the first is mid-SETTLE, producing competing durable writes.
*Test:* inject a long daemon delay; fire the parent timeout while the helper is alive. Assert the second launch is rejected or a no-op (fixture process registry shows exactly one helper), the first helper's SETTLE/VERIFIED is the only durable write, and its inherited flock FD is not bypassed by a second lock path.

6. **Quiescence inferred from lock/PID absence.** Any recovery path treating a missing PID or released lock as "daemon idle" can resurrect a stale generation: with a fixed immutable container ID (or `devhub-managed-*.service`), a slow dockerd from the previous epoch can satisfy the new generation's `start`, reviving the old artifact pin and defeating the config digest.
*Test:* fake dockerd with delayed ACK; kill worker and helper mid-apply; apply a new generation. Assert the adapter queries the daemon for live identity/digest before starting, detects the stale incarnation, and quarantines rather than starting; same check against the systemd unit state.

7. **Foreign pre-created identity.** A local process can pre-create a container with the expected fixed ID (or colliding unit name) but a different image/config; if SETTLED/VERIFIED matches ID/name only, without re-reading the config digest from daemon state, the foreign container is adopted.
*Test:* fixture pre-creates a container with the correct ID but tampered digest; run the helper flow. Assert VERIFIED fails on digest re-verification from daemon state, the instance quarantines, and the foreign container is left untouched and recorded as evidence.

8. **Cross-owner/stale baseline restore.** Rollback may touch only the same operation's exact resource and retained pinned baseline, but the baseline is captured at operation start; a mid-flight ownership change (pair 1 bug) or external mutation can make restore re-apply a stale digest to a resource the operator no longer owns.
*Test:* during a start in applying, force (via a fixture bug path) an ownership change, or swap the live digest externally. Assert rollback re-validates ownership CAS and digest before restoring, refuses cross-owner or digest-mismatched restores, and quarantines instead.

**Caveats — impossible guarantees**

1. **INTENT-only ⇒ no effect is impossible.** A crash/kill-power window always exists between daemon execution and SETTLED persistence. The achievable invariant is "no unverified automatic compensation; unknown state quarantines," not "INTENT-only implies the daemon did nothing." Any claim of crash-window-free atomic adoption is false.

2. **Quiescence from local state alone is impossible.** The daemon is an out-of-band actor; flock release, PID absence, and socket unavailability are all weak signals. "No running instance" requires a daemon-side identity query, which is itself result-unknown if the daemon is wedged — so post-crash clean state is a best-effort assertion, not an invariant. The real invariant: every automatic action is fenced, digest-pinned, single-nonce, and every unknown state is quarantined, never guessed.