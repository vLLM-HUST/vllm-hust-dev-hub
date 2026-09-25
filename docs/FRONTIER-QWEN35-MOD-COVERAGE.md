# Qwen3.5-35B-A3B MOD 曲线覆盖进度

**状态：进行中，尚未完成全部曲线。** 此说明不是性能结果表，也不是完成审计。

使用同一 SWE 多轮请求工作负载、900 秒测量窗口和匹配基线；保留 BF16、256K 上下文容量、MTP2、APC、async 和图执行。每点保留原始请求、窗口内 token、质量检查和服务释放回执。收尾时间不计入吞吐。部署环境只作为来源信息，不能单独命名为 MOD。

覆盖来源是网站目录的 46 个组件记录，其中 13 个为基础设施。下表的 33 个记录包括外部系统/连接器和工具/描述器配对，**不是 33 个独立优化算法**。缺少运行入口的记录不填零分、不连假曲线；适配中的项目也不视为完成。固定版本和清单哈希见 [完整覆盖账本](../scripts/frontier_curves/catalog-coverage.json)。

| 组件 | 当前证据与下一步 | 固定来源 |
| --- | --- | --- |
| Mooncake HUST | 容器已有 Mooncake 0.3.11.post1 和 master；AscendStore 支持 HMA/align。缺少 hccn.conf，通信配置与真实缓存读写仍待资格验证。 | [8b8c7ae7](https://github.com/vLLM-HUST/mooncake-hust/tree/8b8c7ae705bdaf918f5a8fbc7a06cb7eb1d5f3ca) |
| Mooncake vLLM Connectors | 找到 AscendStore HMA 路径；共同 NPU 运行时已有 Event 兼容处理。保持 APC/async/MTP/图模式的完整资格测试待执行。 | [d0f22d2b](https://github.com/vLLM-HUST/vllm-hust/tree/d0f22d2bda562156e4dbf433ce645e1769b4f804) |
| PegaFlow | 普通 PegaKVConnector 未声明 HMA 且只使用第 0 缓存组；独立 NIXL 路径需另行验证，不能一概声称不支持。 | [a3c574b8](https://github.com/vLLM-HUST/pegaflow-hust/tree/a3c574b8526969b70654715d86976474a4cc1b58) |
| PegaFlow vLLM Connectors | 普通 PegaKVConnector 未声明 HMA 且只使用第 0 缓存组；独立 NIXL 路径需另行验证，不能一概声称不支持。 | [a3c574b8](https://github.com/vLLM-HUST/pegaflow-hust/tree/a3c574b8526969b70654715d86976474a4cc1b58) |
| BidKV | 已有 C4/C16；准备在新共同运行时补齐五档并发。已有窗口未触发抢占，不能宣称抢占收益。 | [a0cba97d](https://github.com/vLLM-HUST/vllm-hust-bidkv/tree/a0cba97d9abdc99908e46616db622f0e0099127f) |
| DiffSpec | 当前载体要求 EAGLE3/TP4 且关闭 APC、async，不能直接替代本轮 MTP2/APC/async 配置。 | [42e5909f](https://github.com/vLLM-HUST/vllm-ascend-hust-diffspec/tree/42e5909fc6fe276ba0defe1901257a523653aefb) |
| vSpec | 发现针对 Qwen3.5-35B-A3B 的 EAGLE3 草稿模型；权重下载尚未成功，动态 ABI/硬件资格未通过。 | [d4c4f659](https://github.com/vLLM-HUST/vllm-hust-vSpec/tree/d4c4f659495826e64802eedb195de52019282b47) |
| LatchMoE | 当前启动器拒绝 APC；已执行对应拒绝路径测试。 | [9b2d4acd](https://github.com/vLLM-HUST/vllm-ascend-hust-LatchMoE/tree/9b2d4acdbfbe6463a22dd0bb8e6ca5bfda47e2c1) |
| Adaptive Quantized KV | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [ddd306fc](https://github.com/vLLM-HUST/vllm-ascend-adaptive-quantized-kv-hust/tree/ddd306fce8d885b9b9cfeb8c947ed576c5269e66) |
| Ascend Quant Toolkit | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [f161daab](https://github.com/vLLM-HUST/vllm-ascend-quant-hust/tree/f161daab91b2b558bc8ee65d2b1bc76cd78e00b6) |
| Ascend Quant Runtime Descriptor | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [f161daab](https://github.com/vLLM-HUST/vllm-ascend-quant-hust/tree/f161daab91b2b558bc8ee65d2b1bc76cd78e00b6) |
| Ascend KV Compression | 当前 provider 拒绝混合模型、MTP、APC、async 和多卡并行组合。 | [7c0d2114](https://github.com/vLLM-HUST/vllm-ascend-kvcompress-hust/tree/7c0d21144d99096736138812f727d6f59a93028a) |
| Prefix Router | 固定版本没有可运行发布；不能以安装或导入代替实测。 | [4e007c4f](https://github.com/vLLM-HUST/vllm-hust-prefix-router/tree/4e007c4fc1bd376a6dccfefbc1fd851019c8ceb6) |
| KV Tiering | 固定版本完整 Git 树仅含四个文档/维护文件，没有运行实现。 | [3a73c7e1](https://github.com/vLLM-HUST/vllm-hust-kv-tiering/tree/3a73c7e1628801ea5d4f585bcc9d06260161a78c) |
| KNorm | 固定版本完整 Git 树仅含四个文档/维护文件，没有运行实现。 | [e0e872ab](https://github.com/vLLM-HUST/vllm-hust-knorm/tree/e0e872abfc9fa88659b3e83c1c8b8b2b3de88fc0) |
| PyramidKV Ascend | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [77b0862c](https://github.com/vLLM-HUST/vllm-ascend-pyramidkv-hust/tree/77b0862c1e5be8c883fda934cdb383c57cf7ad0d) |
| SliceGPT | 固定版本完整 Git 树仅含四个文档/维护文件，没有运行实现。 | [6acf19d9](https://github.com/vLLM-HUST/vllm-hust-slicegpt/tree/6acf19d9cbb3ed6caa3f5e6341b1da41941f9f2e) |
| Quantized KV Cache | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [8dd24cdc](https://github.com/vLLM-HUST/vllm-ascend-quantized-kv-cache-hust/tree/8dd24cdce248519c173710993f6c633a96107c0d) |
| SimLLM | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [dcdc6edf](https://github.com/vLLM-HUST/vllm-ascend-simllm-hust/tree/dcdc6edf7bdcc68bdf35058888ebfd9752ae3566) |
| Unified Communication | 策略/注册表存在，但尚缺宿主 collective 接入。 | [f00d1ef4](https://github.com/vLLM-HUST/vllm-hust-unified-comm/tree/f00d1ef4c19a992d67ef8012952a9405d52dd447) |
| Split-Batch / Full-Graph Parallel | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [b46de46e](https://github.com/vLLM-HUST/vllm-ascend-split-batch-hust/tree/b46de46e90204a0a7636a1dbc952f73178859ada) |
| KV Transfer Observability | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [ec3446d9](https://github.com/vLLM-HUST/vllm-hust-kv-transfer-observability/tree/ec3446d936b6ac148e0be33b1dba831f9ecfc0c4) |
| Layered Prefill | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [a45e4170](https://github.com/vLLM-HUST/vllm-ascend-layered-prefill-hust/tree/a45e41709ccacc3d7c736910b93c1b5985d9ee94) |
| Activation Sparsity | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [0e4d0628](https://github.com/vLLM-HUST/vllm-hust-activation-sparsity/tree/0e4d0628c1972d5086a217b0007576c1fd8998a3) |
| Pipeline Microbatch | 已有 C4/C16；正在补 C1/C2/C8 的 Native 配对观测。 | [a15a2296](https://github.com/vLLM-HUST/vllm-hust-pipeline-microbatch/tree/a15a22961a0e4858da74a0ab806575c82cb254e6) |
| QoS Scheduler | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [13d376a7](https://github.com/vLLM-HUST/vllm-hust-qos-scheduler/tree/13d376a7d8990c4dcf5c0903cb6fbf2398ef0fb0) |
| StateHarbor | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | 内部来源，详见覆盖账本 |
| Scheduler Policy Lab | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | 内部来源，详见覆盖账本 |
| Request Lifecycle Causal Profiler | 插件依赖当前共同核心缺少的 kv_recovery_profile 观察接口；诊断功能不等于优化收益。 | [e32a0e91](https://github.com/vLLM-HUST/vllm-hust-request-lifecycle-profiler/tree/e32a0e91027ae7a2b96bf48d2dcb7db1b3c42c87) |
| KV Materialization Arrival Control | 需要特定请求元数据和分段复用宿主接口；无元数据的软件探针只选择重新计算，不能据此生成优化成绩。 | [10428b81](https://github.com/vLLM-HUST/vllm-hust-kv-materialization-arrival-control/tree/10428b81e2b383cdcb183d4548f38a98929fd0e4) |
| BetterScale | 网站已有实测；本轮不冒充新增结果。 | [仓库](https://github.com/vLLM-HUST/BetterScale)；完整来源待补 |
| DLA | 已准备已知输出预算准入与原始抢占选择器；容器内运行时验证和实测尚未完成。不是学习型长度预测结果。 | [dc20d0f8](https://github.com/vLLM-HUST/vllm-hust-dla/tree/dc20d0f8ea8d09106f77571e1947b9a2f8702545) |
| TraceLoom | 当前版本是离线 C++ 分析器，没有在线推理优化入口；不生成虚构的服务性能曲线。 | [37323af5](https://github.com/vLLM-HUST/vllm-hust-perf-analyzer/tree/37323af55aeb5851b9a70b97155f5eacf104eafc) |

已发布的新增对照点见网站 PR [#279](https://github.com/vLLM-HUST/vllm-hust-website/pull/279) 与 [#280](https://github.com/vLLM-HUST/vllm-hust-website/pull/280)。环境归组修正见 [#281](https://github.com/vLLM-HUST/vllm-hust-website/pull/281)。单次观测不能证明稳定加速；未触发的优化机制须明确标注。
