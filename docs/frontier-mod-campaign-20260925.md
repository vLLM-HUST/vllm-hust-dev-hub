# Qwen3.5-35B-A3B：K8s Frontier MOD 实测

本轮已完成并释放实验资源，证据类型为 **real-online**。全部推理和测量位于用户指定
NodePort 30033 对应的 Kubernetes 容器，未在裸机运行实验。MacBook 公钥已在容器授权；
实际执行使用已有 Kubernetes 管理连接，没有修改 SSH 密钥。

## 结果和解释

| Arm | C | 输出 tokens/s/芯片 | Decode P90 tokens/s | 请求失败 | 策略调用 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Native | 4 | 121.040 | 88.998 | 0 | 0 |
| BidKV | 4 | 119.515 | 89.202 | 0 | 0 |
| Native | 16 | 184.020 | 35.545 | 0 | 0 |
| BidKV | 16 | 184.852 | 35.400 | 0 | 0 |

每点均为完整900秒窗口，吞吐只计算窗口内收到的输出 token，排除 drain。
两臂各通过26项冷/热长上下文和16并发检索检查，以及独立C2/60秒协议与缓存检查。
这是有限检索正确性验收，不是通用回答质量或SWE解题能力认证。

BidKV 已启用，但两个窗口均未调用策略，无预占、失败或非法选择。因此标为
**not-exercised**，不能把小幅波动解释成优化收益。原计划重复配对在首轮机制检查后停止；
重复一个未触发的策略无法证明优化收益。后续压力实验需另行声明配置并补跑匹配控制。

## 复现合同

基准模型为 Qwen3.5-35B-A3B，BF16、TP2、PP1、256K容量、16服务槽位、4096调度预算、
APC、Mamba align、异步调度、自然MTP2、FULL_AND_PIECEWISE图，KV为26038239232字节/芯片。
部署使用容器NPU0、1，按全部参与的两张芯片归一化；pod的8卡配额另行披露。

所有22个模型文件的SHA256和大小均匹配ModelScope历史版本712cf743。Prepared artifact
保留实际aa23f49e SHA；仅替换tokenizer路径及Transformers版本metadata即可精确重建历史
8044561f SHA，固定输入token增量、输出预算和session顺序不变。实际生成token作为历史续接。

见[配置和实际窗口记录](../config/frontier-mod-campaign-20260925.json)及
[运行脚本与共同源码覆盖](../scripts/frontier_runtime/README.md)。核心752a3a50、后端9bf964cb，
两臂共用preemption API移植、Mamba V1/SD ABI桥接和独立的accepted-token反馈缓冲区。
这些共同修正不属于BidKV处理变量。容器CANN9.1.0和torch-npu2.10不同于历史主机，故使用新原生对照。
失败资格检查保留FAILED标记及原始日志，不纳入性能点。

## 其他 MOD 的具体限制

- DiffSpec 的42e5909实现要求TP4、dense Qwen、关闭APC与异步调度；虽有35B Eagle3 draft，仍不兼容当前TP2/MoE/APC/async单元。
- LatchMoE 当前拒绝APC，需要先实现并验证兼容性。
- Pipeline Microbatch 需要PP拓扑匹配的独立控制，当前PP1不适用。
- DLA 需要明确的预测输入和额外调度接口；不能拿真实输出预算充当预测。

## 证据和发布

完整原始证据：容器及本地制品目录`frontier-mods-qwen35-20260925/runs/{native-r1,bidkv-r1}`。
本地根目录为`/data/codex-build-artifacts/frontier-mods-qwen35-20260925`。
每组status均passed，supervisor退出0、所选设备FD所有者为空。公共数据保留原始请求文件哈希。

[网站实验报告](https://github.com/vLLM-HUST/vllm-hust-website/blob/main/docs/FRONTIER-QWEN35-MODS-K8S.md)
提供同配置结果、源代码覆盖和可下载配置；本地导入器拒绝未完成、资格失败或未释放资源的点。
