# Evaluation machine #112 live acceptance

The admission-gated Evaluation API completed a real three-repeat benchmark
job successfully on 2026-10-06.

- Job: `eval-20261006T212429Z-51ac8c7bedde`
- API terminal state: `succeeded`, exit code `0`
- Admission state: `VERIFIED`
- Assigned physical NPU: `2`
- Repeats: `3/3`, each `STATUS=OK`
- Bundle SHA256: `00c2e0997a76f1a88025cd7be54fbb95d61602dacf8695edf6268e8d7a1fcaa1`
- Request SHA256: `e60d08e878583418ea3b03b47d9b516f0984dba168966cc846a5791acd98f027`
- Schedule SHA256: `ca399e3aac03db4d0e4dee3780127369c3884d2e4d08cc01af9dd0af4a43cdf6`
- Benchmark evidence commit: `b8eef13110b29b927f96d89c0689e31f93785aa1`

The copied terminal record and external attestation are checksummed here.
The complete immutable bundle, raw token results, service logs, and resource
release snapshots are stored in
`reports/issue-136-evaluation-112-roundtrip-20261006/` in
vLLM-HUST/vllm-hust-benchmark PR #239.

Run `sha256sum -c SHA256SUMS` from this directory to verify this receipt.
