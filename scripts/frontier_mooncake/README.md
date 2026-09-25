# Qwen3.5 Mooncake qualification prerequisites

Status: fixed-source build, imports, Ascend initialization and bounded real
transfers have passed. Cross-client multi-buffer Store operations also passed; Qwen3.5 serving
qualification remains pending; no performance observations exist.
The Native/BidKV/DLA campaign has completed and released its devices.
All probes below ran after that release. No Mooncake-backed vLLM service
has been started.

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


Post-release read-only device queries (`hccn_tool -i N -ip/-link/-net_health/-mtu -g`)
returned actual device 0 address `10.52.65.11` and device 1 address `10.52.65.10`,
both netmask `255.255.255.0`, link `UP`, MTU `8192`. Both health queries returned
`Receive timeout`; this does not by itself establish a failed transfer or identify
its cause. All query exit codes were zero. `/etc/hccn.conf` remains absent.
The archived `mooncake-readonly-network.json` records these exact outputs. No
network settings were written and no device transport was initialized. Known
addresses and link status alone do not substitute for the required configuration
or an actual end-to-end transfer qualification.


A bounded import-only check of the installed binary also fails independently of
transport setup. Both `import mooncake.engine` alone and importing `torch` /
`torch_npu` first print successful import, then abort at interpreter exit with
`corrupted size vs. prev_size` (SIGABRT, subprocess return code -6). No engine was
instantiated, no device selected and no transfer initialized. Device owners were
empty before and after. `mooncake-import-diagnostics.json` retains both exact
commands, outputs and hashes of 10 distribution binary/metadata files. This
establishes a software failure in the installed environment, not its cause;
initialization success must not be assumed or published as qualification.

The pinned source was subsequently built in the assigned container with an
isolated dependency prefix (39 downloaded Debian packages, no system package
installation or upgrade). Build attempt `build-r4` completed all 208 steps with
exit 0. `stage_build.py` copied the completed binaries into a private package;
no global CMake install hooks ran. Engine-only, Store-only and torch/NPU-first
imports all exited 0, with all resolved module paths verified inside that
private package and no missing dynamic libraries.

A bounded actual device-0 initialization of this staged Ascend Direct engine
then returned 0 and exited normally. ADXL initialization succeeded with
`HCCL_INTRA_ROCE_ENABLE=1`; device owners were empty before and after. This
succeeded while `/etc/hccn.conf` was still absent, so its absence alone is not a
verified initialization blocker. Actual memory transfer, hybrid cache save/load
and serving qualification are still pending. Neither import nor initialization
is a performance point. The old installed-binary crash remains a separate
observation; the fixed-source build does not use those installed binaries.


`transfer_probe.py` then passed actual two-process transfers on assigned devices
0 and 1 using the staged source-built engine. Each of host-to-host,
host-to-device, device-to-host and device-to-device performed a 2 MiB write,
independent receiver SHA256 verification, local overwrite, readback and SHA256
verification. All eight transfer calls returned zero; both workers exited zero,
and device owners were empty before and after. Protocol was Ascend Direct with
RoCE enabled. No host networking or hccn configuration was changed. These are
bounded transport correctness probes, not serving throughput, hybrid-cache
qualification, or an optimization benefit.


`store_probe.py` passed against an owned private master and two NPU clients,
using the same `batch_put_from_multi_buffers` / `batch_get_into_multi_buffers`
API family as the Ascend backend. One object held 2 MiB and 1 MiB NPU buffers.
After save, both clients overwrote their local buffers; the second client read
3145728 bytes and matched both original SHA256 values. Existence checks before
save, after save and after forced deletion passed. Both clients and the owned
master exited zero; device owners were empty. Each client contributed 1 GiB
with Ascend/P2PHANDSHAKE and no local copy buffer. This proves bounded Store
operations, not Qwen3.5 hybrid-cache correctness or serving performance.
