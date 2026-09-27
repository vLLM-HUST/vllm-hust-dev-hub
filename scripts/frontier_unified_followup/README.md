# Shared-Native follow-up

This queue adds BidKV and declared-budget DLA to the already running phase9 contract. It does not
measure another Native. Both candidates reuse phase9's exact Qwen3.5-35B model, runtime, workload,
TP2/PP1 topology, graph/APC/MTP2/async settings and C1/2/4/8/16 windows. The manager adds only the
declared preemption policy; DLA additionally enables its exact-budget reservation flag and adapter
configuration.

The queue is supervised before phase9 finishes, but its waiter starts measurements only after all
phase9 arms pass and release the participating devices. BetterScale is not added: its Qwen3.5 path
requires `TASK_QUEUE_ENABLE=0`, while the frozen contract requires `1`. Pipeline Microbatch changes
PP1 to PP2. vSpec and DiffSpec replace MTP2 with another speculative method/model pair. LatchMoE and
KVCompression require different models/topology or disable fixed Frontier features. Those are
configuration incompatibilities, not missing numeric values to be filled with another baseline.

`collect_when_complete.py` waits for this follow-up and the phase9 collection, copies the raw
candidate capsule, and audits BidKV/DLA against phase9's five Native run IDs. The derived artifact
must contain ten unique candidate run IDs and exactly five reused Native run IDs before publication.
