# Ascend 910B2 单卡 HBM 带宽测试报告

测试日期：2026-07-19

本报告补充 [`../HARDWARE_REPORT_20260407.md`](../HARDWARE_REPORT_20260407.md)
未覆盖的单卡 HBM 流式带宽。这里测量的是当前 910B2 + 26.0.rc1 软件栈，不能与
旧报告中的 910B3 + 25.3.rc1 身份混用。

## 1. 测试环境

- NPU：Ascend 910B2，物理 NPU 7，64 GiB HBM
- PCIe Bus ID：`0000:42:00.0`
- NUMA：node2，CPU affinity `48-71`
- Driver / `npu-smi`：26.0.rc1
- 容器镜像：`quay.io/ascend/vllm-ascend:v0.21.0rc1-openeuler`
- PyTorch：2.10.0
- torch-npu：2.10.0
- 测试前后 NPU 7 均无其他设备进程

测试脚本和原始结果：

- [`benchmarks/single_npu_hbm.py`](benchmarks/single_npu_hbm.py)
- [`results/20260719_single_npu_hbm_npu7/single_npu_hbm.json`（benchmark 归档索引）](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/evidence-devhub-20261020-v1/archive/dev-hub-20261020/manifest.json)

## 2. 测试方法

使用 BF16 tensor 测量两类连续访存：

1. Device-to-Device copy：每个元素一次读、一次写，估算 HBM 流量为
   `2 * tensor_bytes / time`；同时报告不乘流量系数的单向 payload 带宽。
2. BF16 vector add：`output = a + b`，每个元素两次读、一次写，估算 HBM
   流量为 `3 * tensor_bytes / time`。

每个尺寸先 warmup 10 次，再采集 7 个样本。每个样本包含多次迭代，使估算总
流量接近 64 GiB。主计时使用 NPU event；host wall clock 与 event 结果接近。
所有 GB/s 使用十进制字节。

这里的“HBM 流量”是根据算子读写量建立的模型，不是硬件 PMU counter。

## 3. 测试结果

下表使用 7 次采样的中位数：

| 单 tensor 大小 | D2D copy payload | D2D copy HBM 流量（1R+1W） | BF16 add HBM 流量（2R+1W） |
| ---: | ---: | ---: | ---: |
| 64 MiB | 2532.41 GB/s | 5064.83 GB/s | 2726.98 GB/s |
| 256 MiB | 633.76 GB/s | 1267.51 GB/s | 1128.45 GB/s |
| 1024 MiB | 638.47 GB/s | 1276.93 GB/s | 1142.93 GB/s |
| 2048 MiB | 637.46 GB/s | 1274.92 GB/s | 1133.78 GB/s |
| 4096 MiB | 637.26 GB/s | 1274.52 GB/s | 1146.86 GB/s |

## 4. 结论与使用方式

- 64 MiB 的数值明显来自片上 cache，不能称为 HBM 带宽。
- 从 256 MiB 到 4 GiB，D2D copy 稳定在约 **1.275 TB/s** 的估算读写总流量。
- BF16 vector add 稳定在约 **1.13-1.15 TB/s**，可取 **1.14 TB/s** 作为
  Vector 算子的实用 HBM roofline。
- 对权重流量主导的小 M GEMM 或 projection，若用 `weight_bytes / latency`
  计算有效权重带宽，`0.9 TB/s` 约等于实用 HBM roofline 的 79%，`1.0 TB/s`
  约等于 88%。

建议在算子优化报告中同时列出：

1. 端到端 latency；
2. 按实际 tensor 读写量计算的总流量 GB/s；
3. 相对 1.14 TB/s 的利用率；
4. 若是权重主导算子，额外列出 `weight_bytes / latency`，但不要把它与包含
   output/activation 流量的总 HBM 流量混为一谈。

## 5. 复现

在仅映射一张空闲 NPU 的 Ascend PyTorch 容器内执行：

```bash
python3 Ascend-Machine/910B2/benchmarks/single_npu_hbm.py \
  --output Ascend-Machine/910B2/results/my_run/single_npu_hbm.json
```

默认测试 `64,256,1024,2048,4096` MiB。容器内选中的物理设备会被重新编号为
逻辑 `npu:0`。
