# One shared Native series

The campaign runs **Native once**, at C1/2/4/8/16, then candidates on the same frozen runtime and
same two Ascend cards. No candidate gets a separate Native comparator. The initial admitted queue
is Native → Mooncake → KV Tiering. Other MODs need compatible activation and qualification before
joining this single-baseline comparison; old results are not re-denominated.

Preparation is read-only with respect to prior runtime capsules. It creates a new experiment
capsule and a shared wheel overlay, records one common command/source contract, and verifies that
candidate plans differ only by the declared connector. A Mooncake offline Provider plan is not a
health proof: before launch the controller starts its owned master, requires the manager's live
health/dry-run gate, and compares the resulting command to the frozen plan.

Every arm passes 26 retrieval checks and the existing prefix-reuse gate before its 900-second
measurement windows. A dedicated supervisor owns all processes and the outer cleanup checks both
process groups and actual HBM release. Qualification and failed preparation are never performance
points. The first preparation directory records an offline health-gate failure without launching
serving or benchmarks; `phase9-unified-r3` is the prepared successor.

The same Qwen3.5-35B-A3B BF16 model, TP2/PP1, APC, MTP2, asynchronous scheduling,
FULL_AND_PIECEWISE captures3/6/12/24/48, context262144, maxseq16, batch4096 and KV26038239232
bytes/chip apply to all arms. The common contract records the workload hash and original runtime
source hashes. Each metadata file references the exact common-contract digest and shared Native ID.

Run `python -m pytest scripts/frontier_unified/test_contract.py` for CPU validation. Container
preparation must be followed by tests of the actual generated harness before setting the manifest's
software qualification flag or starting its supervisor. Never repeat `prepare.py` into an existing
directory or overwrite the prior capsule.
