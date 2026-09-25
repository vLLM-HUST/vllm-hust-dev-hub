# Qwen3.5 Mooncake qualification prerequisites

Status: preparation only; no Mooncake service or NPU transfer has been run.
The serial Native/BidKV/DLA campaign owns the measurement interval. Do not
initialize TransferEngine, start a master, or run device probes during it.

Use the assigned SSH31769 container after the previous campaign releases devices.
Keep the compiled SWE workload, BF16, 262144 context, APC, Mamba align, actual MTP2,
async scheduling and FULL_AND_PIECEWISE graphs. The frozen AscendStoreConnector
supports HMA; use non-layerwise transfer and kv_load_failure_policy=fail.
The recompute fallback is not qualified for this hybrid model.

Before a serving run:

1. Verify actual owners are absent and preserve the completed campaign receipts.
2. Resolve binary provenance: installed mooncake-transfer-engine-npu is0.3.11.post1
   without direct_url metadata. Catalog source8b8c7ae7 declares0.3.12.post1.
   Do not label that installed binary as the catalog commit. Retain distribution
   RECORD/file hashes and establish a source mapping, or build an isolated pinned
   package. Do not replace the active phase4 environment.
3. Verify assigned-device network configuration. Both the frozen Ascend guide and
   Mooncake source require /etc/hccn.conf, which is absent in this container.
   Use an actual configuration from this host/container allocation; do not invent
   NIC IP addresses or modify host networking. If the required configuration is
   unavailable, retain this as a concrete prerequisite failure.
4. The Mooncake Ascend Direct guide requires setting the selected NPU before
   TransferEngine.initialize. For A2 direct RoCE, the frozen Ascend guide specifies
   HCCL_INTRA_ROCE_ENABLE=1. This is not proof that the device network works.
5. Start only an owned local master with a dedicated port. Configure P2PHANDSHAKE,
   protocol ascend, non-layerwise KV, and a documented memory contribution. Record
   master/worker ownership, source identity and resource overhead for both arms.
6. Qualify real save/load and exact retrieval across hybrid cache groups, then the
   same26 retrieval probes and60s protocol gate. A successful import or empty
   store connection does not prove reuse. Distinguish stores, external-hit tokens,
   completed loads and transfer failures in receipts.
7. Only after qualification, run fresh matched Native/Mooncake C1/2/4/8/16
   900-second windows serially. Preserve the client cache-salt/history semantics;
   do not change the workload to manufacture external hits. Zero actual loads
   must remain explicitly unexercised, and negative performance stays visible.

Source witnesses:

- Mooncake8b8c7ae705bdaf918f5a8fbc7a06cb7eb1d5f3ca,
  docs/source/design/transfer-engine/ascend_direct_transport.md, lines74–80:
  selected-device initialization and host hccn.conf prerequisites.
- Same tree pyproject.toml line15:0.3.12.post1. Relative to upstream
  6cc1a100404ea40a13940b49616a9127c5662b1d, only HUST_FORK.md and the upstream
  sync workflow differ; there is no evidenced HUST runtime optimization in that diff.
- Qualified Ascend docs/source/user_guide/feature_guide/kv_pool.md:
  hybrid failure policy, A2 RoCE and configuration requirements.
- Qualified Ascend mooncake_backend.py uses the actual shared TransferEngine
  and raises on failed setup; it does not validate end-to-end serving correctness.
