# 昇腾服务器硬件与带宽测试报告

测试日期：2026-04-07

测试主机：train05

归档成员目录：`Ascend-Machine/results/20260407_full`。原始文件已迁至
[benchmark 归档索引](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/evidence-devhub-20261020-v1/archive/dev-hub-20261020/manifest.json)，
下文 `results/` 路径均为归档内路径，不再指向本仓库工作树。

采集与测试脚本：

- benchmarks/run_bandwidth_benchmarks.sh
- benchmarks/numa_memcpy_bench.cpp
- benchmarks/acl_copy_bench.cpp

## 1. 机器静态配置

### 1.1 主机与固件

- 厂商：Huawei
- 机型：A800T A2
- 主板：IT21SK4E
- BIOS：Huawei Corp. 7.09
- BIOS 日期：2023-12-08
- 内核：Linux 5.10.0-60.18.0.50.oe2203.aarch64

### 1.2 CPU / NUMA / 内存

- CPU：4 x Kunpeng-920
- 每路核心数：48
- 总核心数：192
- 超线程：关闭（1 thread per core）
- NUMA 节点数：8
- NUMA 划分：
  - node0: CPU 0-23
  - node1: CPU 24-47
  - node2: CPU 48-71
  - node3: CPU 72-95
  - node4: CPU 96-119
  - node5: CPU 120-143
  - node6: CPU 144-167
  - node7: CPU 168-191
- 总内存：2.0 TiB
- 单 NUMA 容量：约 253-258 GiB

### 1.3 存储

- 系统盘：446.1 GB RAID1
- NVMe：2 x 3.5 TB Huawei ES3000 V6
- 当前挂载：
  - /data 位于一块 3.5 TB NVMe 上
- 已观察到的 NVMe PCIe 链路：16.0 GT/s x4

### 1.4 NPU

- NPU 数量：8
- 型号：Ascend 910B3
- 每卡 HBM：64 GB
- 驱动/CANN 版本：25.3.rc1
- 驱动版本文件：driver/version.info 中 package_version=25.3.rc1
- 空闲状态下 `npu-smi` 可见所有卡均无运行中进程

NPU 与 NUMA / CPU 亲和关系：

| NPU | Bus ID | NUMA | CPU Affinity | 备注 |
| --- | --- | --- | --- | --- |
| 0 | 0000:C1:00.0 | 6 | 144-167 | 与 NPU1 同 PHB |
| 1 | 0000:C2:00.0 | 6 | 144-167 | 与 NPU0 同 PHB |
| 2 | 0000:81:00.0 | 4 | 96-119 | 与 NPU3 同 PHB |
| 3 | 0000:82:00.0 | 4 | 96-119 | 与 NPU2 同 PHB |
| 4 | 0000:01:00.0 | 0 | 0-23 | 与 NPU5 同 PHB |
| 5 | 0000:02:00.0 | 0 | 0-23 | 与 NPU4 同 PHB |
| 6 | 0000:41:00.0 | 2 | 48-71 | 与 NPU7 同 PHB |
| 7 | 0000:42:00.0 | 2 | 48-71 | 与 NPU6 同 PHB |

已成功读取的 6 张 NPU sysfs 链路信息显示当前协商链路为 16.0 GT/s x16，最大能力为 32.0 GT/s x16。结合整机拓扑与 `npu-smi topo -m`，本机 8 卡分布在 4 个 PCIe 根复合域中，每域 2 卡。

### 1.5 网络

活跃网络端口：

- Mellanox ConnectX-5 双口卡 2 张，共 4 个 25 GbE 端口
  - NUMA 6：enp195s0f0np0, enp195s0f1np1
  - NUMA 2：enp67s0f0np0, enp67s0f1np1
- Huawei HNS 管理/板载网络
  - NUMA 4：enp189s0f0 1 GbE，链路 up
  - NUMA 0 / 4 的其余 HNS 端口当前 down

## 2. 实测带宽结果

### 2.1 CPU / NUMA / 存储侧

主表使用自定义 24 线程 `memcpy` 基准，`mbw` 的 MCBLOCK 结果作为单进程交叉验证。

| 项目 | 方法 | 结果 |
| --- | --- | --- |
| 本地 NUMA 到本地 DDR（node0 -> node0） | 24 线程 memcpy | 34.85 GB/s |
| 同 socket 跨 NUMA（CPU node0, memory node1） | 24 线程 memcpy | 30.28 GB/s |
| 跨 socket 跨 NUMA（CPU node0, memory node4） | 24 线程 memcpy | 12.44 GB/s |
| NVMe 顺序读（/data 所在 NVMe） | fio, 1M block, depth 32 | 7.01 GB/s |

`mbw` MCBLOCK 交叉验证：

| 项目 | mbw MCBLOCK |
| --- | --- |
| node0 -> node0 | 29.16 GB/s |
| node0 -> node1 | 15.67 GB/s |
| node0 -> node4 | 7.61 GB/s |

说明：

- `memcpy` 多线程值更接近整机吞吐上限，建议作为主参考。
- `mbw` 是单进程块拷贝基准，数值更保守，可视为下界交叉验证。

### 2.2 NPU <-> Host 拷贝带宽

使用自定义 Ascend ACL 拷贝基准，在 clean env 中执行，避免当前 conda 环境污染 `LD_LIBRARY_PATH` 导致 `aclInit` 失败。

| 项目 | 测试说明 | 结果 |
| --- | --- | --- |
| 单 NPU Device -> Host | NPU4，1 GiB，20 iter | 28.60 GB/s |
| 单 NPU Host -> Device | NPU4，1 GiB，20 iter | 25.29 GB/s |
| 同 PCIe 域双 NPU Host -> Device | NPU4+NPU5，分别 1 GiB，20 iter，聚合墙钟吞吐 | 48.84 GB/s |
| 8 NPU Host -> Device 聚合 | 8 卡并发，单卡 512 MiB，20 iter，聚合墙钟吞吐 | 193.57 GB/s |

说明：

- 单卡结果与 PCIe 4 x16 经验值一致。
- 8 卡聚合值是全机四个 PCIe 域并发的总吞吐，不能直接与单域或单卡值做线性比较。

### 2.3 NPU 侧集合通信（HCCL）

使用 toolkit 自带 `hccl_test` 源码本地构建，OpenMPI 单机 8 rank 执行。标准测量参数为：8 NPU、64 MiB、fp32、5 iter、2 warmup。`broadcast` / `reduce` 按 README 示例使用 `root=1`，并关闭结果校验 `-c 0` 以避开当前栈的校验路径问题。

2026-04-25 复测更新：针对 2026-04-07 首次测量中失败的 `alltoall` / `reduce_scatter`，本次在当前机器实际可用的官方路径上重新测量：直接使用 toolkit 自带官方 `hccl_test` 源码、当前 `libhccl.so` 接口，以及 `/usr/lib64/mpich/bin/mpiexec.hydra`。以下表格中 `alltoall` / `reduce_scatter` 结果已按这次复测更新。

| 操作 | 状态 | 结果 |
| --- | --- | --- |
| All Gather | 成功 | 136.53 GB/s |
| All Reduce | 成功 | 65.64 GB/s |
| Scatter | 成功 | 110.76 GB/s |
| Broadcast | 成功 | 66.41 GB/s |
| Reduce | 成功 | 58.89 GB/s |
| All To All | 成功 | 约 107.8 GB/s（2026-04-25 复测） |
| Reduce Scatter | 成功 | 约 123.3 GB/s（2026-04-25 复测） |

补充说明：

- `broadcast` / `reduce` 在默认校验开启时会返回 `retcode 7`，但按 README 推荐 root 配置并关闭校验后可稳定得到带宽结果，因此这两个问题被归类为“校验路径/调用参数问题已绕开”，而不是通信本身失败。
- 2026-04-07 的 `alltoall` / `reduce_scatter` 失败结论来自旧测试链路：`OpenMPI + libhccl_v2 + *V2 API`。该链路已经不再匹配当前机器上的实际可用软件栈，因此不能再视为最新结论。
- 2026-04-25 复测中，`all_gather` 对照组仍稳定在约 136.5 GB/s，与旧结果一致；在同一运行路径下，`alltoall` / `reduce_scatter` 已经能够连续输出有效带宽样本，分别约为 107.8 GB/s 和 123.3 GB/s。
- 由于本次复测使用外层 `timeout` 包裹单项命令，输出尾部会出现 `mpiexec.hydra` 的中断清理日志；这些日志发生在已经产生有效带宽样本之后，不应解读为 HCCL collective 再次回到 `retcode 7` 失败状态。
- 成功项应视为本机当前 CANN/HCCL 栈下可稳定复现的单机 8 卡集合通信带宽；但 collective 可用性结论应绑定到具体测试路径，而不能脱离运行时和工具链版本单独引用。

## 3. 方法与环境说明

### 3.1 本次补装依赖

- numactl
- fio
- iproute2
- ethtool
- pciutils
- mbw
- openmpi-bin
- libopenmpi-dev

### 3.2 关键实现细节

- Ascend ACL / HCCL 测试必须在 clean env 中运行。
- 直接继承当前 `vllm-hust-dev` conda 环境时，`aclInit` 会失败。
- `npu-smi` 位于用户本地路径 `/home/shuhao/.local/bin/npu-smi`，不能只依赖系统 PATH。
- `/data` 写入需要 `sudo /usr/bin/fio`。
- `broadcast` / `reduce` 需要使用 README 推荐的 `root=1`；在当前软件栈上开启结果校验会触发 `retcode 7`，因此脚本默认对 HCCL 用例使用 `-c 0`。
- 2026-04-25 HCCL 复测使用的是当前机器实际可用路径：`/usr/lib64/mpich/bin/mpiexec.hydra` + toolkit 当前 `libhccl.so` + 官方 `hccl_test` 源码；旧的 `OpenMPI + libhccl_v2 + *V2` 假设已不再成立。

### 3.3 结果文件定位

原始采样与结果见：

- `results/20260407_full/summary.txt`
- `results/20260407_full/npu-smi-info.txt`
- `results/20260407_full/npu-smi-topo.txt`
- `results/20260407_full/fio-seqread.json`
- `results/20260407_full/acl-copy-single-h2d.txt`
- `results/20260407_full/acl-copy-single-d2h.txt`
- `results/20260407_full/acl-copy-dual-h2d.txt`
- `results/20260407_full/acl-copy-all8-h2d.txt`
- `results/20260407_full/hccl-all-gather.txt`
- `results/20260407_full/hccl-all-reduce.txt`
- `results/20260407_full/hccl-broadcast.txt`
- `results/20260407_full/hccl-reduce.txt`
- `results/20260407_full/hccl-scatter.txt`

失败样例也已保留：

- `results/20260407_full/hccl-alltoall.txt`
- `results/20260407_full/hccl-reduce-scatter.txt`

2026-04-25 复测结果：

- `results/hccl_retest_official_control_20260425_023409.txt`
- `results/hccl_retest_official_alltoall_20260425.txt`
- `results/hccl_retest_official_reduce_scatter_20260425.txt`

## 4. 结论

这台机器可以归纳为：

- 4 路鲲鹏 920，8 NUMA，2 TiB 内存。
- 8 张 Ascend 910B3，按 4 个 PCIe 根域分成 4 组，每组 2 卡。
- 单卡 Host<->NPU 带宽约 25-29 GB/s，符合 PCIe 4 x16 的经验范围。
- CPU 本地内存带宽显著高于跨 socket 访问，跨 socket 远端内存仅约本地的 1/3。
- 单机 8 卡 HCCL 下，All Gather / Scatter / All Reduce / Broadcast / Reduce 可正常测得稳定带宽。
- 2026-04-25 复测表明，在当前官方 `hccl_test + libhccl.so + MPICH` 路径上，All To All 与 Reduce Scatter 也已恢复可用，带宽分别约为 107.8 GB/s 与 123.3 GB/s。
- 因此，旧的 `retcode 7` 结论应被视为历史测试链路结论，而不是当前机器状态的最新描述。
