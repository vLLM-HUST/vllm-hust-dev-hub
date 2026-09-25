# Qwen3.5-35B-A3B MOD 曲线覆盖进度

**状态：进行中，尚未完成全部曲线。** 此说明不是性能结果表，也不是完成审计。

使用同一编译后的 SWE 多轮工作负载、900 秒测量窗口和匹配基线；保留 BF16、256K 上下文容量、MTP2、APC、async 和图执行。每点保留原始请求、窗口内 token、质量检查和服务释放回执。收尾时间不计入吞吐。部署环境只作为来源信息，不能单独命名为 MOD。

该协议是闭环生成：实际输出 token 会拼入下一轮输入，固定的是编译后的输入长度和输出预算，不保证各轮 token 内容跨运行完全相同。每组服务启动后先做资格检查，再串行测各档并发，档位之间不重置缓存。共同请求的逐 token 比较只是补充核验，不能推广为一般质量结论。

覆盖来源是网站目录的 46 个组件记录，其中 13 个为基础设施。下表的 33 个记录包括外部系统/连接器和工具/描述器配对，**不是 33 个独立优化算法**。缺少运行入口的记录不填零分、不连假曲线；适配中的项目也不视为完成。固定版本和清单哈希见 [完整覆盖账本](../scripts/frontier_curves/catalog-coverage.json)。

| 组件 | 当前证据与下一步 | 固定来源 |
| --- | --- | --- |
| Mooncake HUST | 已从固定源码构建，四类真实传输与跨进程 NPU Store 读写通过；Qwen3.5 检索资格两次失败：1 GiB/rank 在 warm-131072 失败；16 GiB/rank 在 warm-262080 失败，尚无性能曲线。 | [8b8c7ae7](https://github.com/vLLM-HUST/mooncake-hust/tree/8b8c7ae705bdaf918f5a8fbc7a06cb7eb1d5f3ca) |
| Mooncake vLLM Connectors | 实际 AscendStore HMA/align 服务已加载模型并捕获图；相同环境 Native 26 项全通过；扩大容量后候选第 10 项 warm-262080 仍失败，且无容量错误日志。需修复混合缓存正确性与退出问题。 | [d0f22d2b](https://github.com/vLLM-HUST/vllm-hust/tree/d0f22d2bda562156e4dbf433ce645e1769b4f804) |
| PegaFlow | 普通连接器未声明 HMA 且只使用第 0 缓存组；NIXL 路径虽支持 HMA，但固定版本设备表无 NPU，共同 Ascend 平台未扩展该表，会被设备检查拒绝。需实际 NPU 传输适配，不能仅绕过检查。 | [a3c574b8](https://github.com/vLLM-HUST/pegaflow-hust/tree/a3c574b8526969b70654715d86976474a4cc1b58) |
| PegaFlow vLLM Connectors | 普通连接器未声明 HMA 且只使用第 0 缓存组；NIXL 路径虽支持 HMA，但固定版本设备表无 NPU，共同 Ascend 平台未扩展该表，会被设备检查拒绝。需实际 NPU 传输适配，不能仅绕过检查。 | [a3c574b8](https://github.com/vLLM-HUST/pegaflow-hust/tree/a3c574b8526969b70654715d86976474a4cc1b58) |
| BidKV | 新共同运行时下 C1/C2/C4/C8/C16 与 Native 配对测试全部完成，原始记录校验与设备释放通过，已由 PR #283 发布。未触发抢占，不能宣称抢占收益。 | [a0cba97d](https://github.com/vLLM-HUST/vllm-hust-bidkv/tree/a0cba97d9abdc99908e46616db622f0e0099127f) |
| DiffSpec | 当前载体要求 EAGLE3/TP4 且关闭 APC、async，不能直接替代本轮 MTP2/APC/async 配置。 | [42e5909f](https://github.com/vLLM-HUST/vllm-ascend-hust-diffspec/tree/42e5909fc6fe276ba0defe1901257a523653aefb) |
| vSpec | 发现针对 Qwen3.5-35B-A3B 的 EAGLE3 草稿模型；实际 EAGLE3 导入/属性 ABI 检查 13/13 通过；草稿权重下载仍遇 TLS 失败，补丁激活与硬件正确性尚未验证。 | [d4c4f659](https://github.com/vLLM-HUST/vllm-hust-vSpec/tree/d4c4f659495826e64802eedb195de52019282b47) |
| LatchMoE | 当前启动器拒绝 APC；已执行对应拒绝路径测试。 | [9b2d4acd](https://github.com/vLLM-HUST/vllm-ascend-hust-LatchMoE/tree/9b2d4acdbfbe6463a22dd0bb8e6ca5bfda47e2c1) |
| Adaptive Quantized KV | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [ddd306fc](https://github.com/vLLM-HUST/vllm-ascend-adaptive-quantized-kv-hust/tree/ddd306fce8d885b9b9cfeb8c947ed576c5269e66) |
| Ascend Quant Toolkit | 工具是离线检查点量化；运行时描述器仅校验元数据，不加载模型或设备。缺少量化产物加载和算子选择的宿主接入，不能作为本轮 BF16 在线优化开关。 | [f161daab](https://github.com/vLLM-HUST/vllm-ascend-quant-hust/tree/f161daab91b2b558bc8ee65d2b1bc76cd78e00b6) |
| Ascend Quant Runtime Descriptor | 工具是离线检查点量化；运行时描述器仅校验元数据，不加载模型或设备。缺少量化产物加载和算子选择的宿主接入，不能作为本轮 BF16 在线优化开关。 | [f161daab](https://github.com/vLLM-HUST/vllm-ascend-quant-hust/tree/f161daab91b2b558bc8ee65d2b1bc76cd78e00b6) |
| Ascend KV Compression | 当前 provider 拒绝混合模型、MTP、APC、async 和多卡并行组合。 | [7c0d2114](https://github.com/vLLM-HUST/vllm-ascend-kvcompress-hust/tree/7c0d21144d99096736138812f727d6f59a93028a) |
| Prefix Router | 固定版本没有可运行发布；不能以安装或导入代替实测。 | [4e007c4f](https://github.com/vLLM-HUST/vllm-hust-prefix-router/tree/4e007c4fc1bd376a6dccfefbc1fd851019c8ceb6) |
| KV Tiering | 固定版本完整 Git 树仅含四个文档/维护文件，没有运行实现。 | [3a73c7e1](https://github.com/vLLM-HUST/vllm-hust-kv-tiering/tree/3a73c7e1628801ea5d4f585bcc9d06260161a78c) |
| KNorm | 固定版本完整 Git 树仅含四个文档/维护文件，没有运行实现。 | [e0e872ab](https://github.com/vLLM-HUST/vllm-hust-knorm/tree/e0e872abfc9fa88659b3e83c1c8b8b2b3de88fc0) |
| PyramidKV Ascend | 除 import_only 和缺少宿主接入外，固定实现只接受 Llama/Qwen2 全注意力单缓存组，拒绝 MTP、TP2 和 FULL_AND_PIECEWISE；本轮配置被多项独立检查拒绝（源码核查）。 | [77b0862c](https://github.com/vLLM-HUST/vllm-ascend-pyramidkv-hust/tree/77b0862c1e5be8c883fda934cdb383c57cf7ad0d) |
| SliceGPT | 固定版本完整 Git 树仅含四个文档/维护文件，没有运行实现。 | [6acf19d9](https://github.com/vLLM-HUST/vllm-hust-slicegpt/tree/6acf19d9cbb3ed6caa3f5e6341b1da41941f9f2e) |
| Quantized KV Cache | 当前包仅实现 dtype 与打包布局计算；缺少启用中的量化/反量化/注意力算子和宿主分配、传输接入，历史补丁归档不等于当前运行实现。 | [8dd24cdc](https://github.com/vLLM-HUST/vllm-ascend-quantized-kv-cache-hust/tree/8dd24cdce248519c173710993f6c633a96107c0d) |
| SimLLM | 完整源码树仅含来源校验和非激活描述器；该模块明确不含 SimLLM 实现，没有可测的相似度索引、嵌入或请求改写执行路径。 | [dcdc6edf](https://github.com/vLLM-HUST/vllm-ascend-simllm-hust/tree/dcdc6edf7bdcc68bdf35058888ebfd9752ae3566) |
| Unified Communication | 策略/注册表存在，但尚缺宿主 collective 接入。 | [f00d1ef4](https://github.com/vLLM-HUST/vllm-hust-unified-comm/tree/f00d1ef4c19a992d67ef8012952a9405d52dd447) |
| Split-Batch / Full-Graph Parallel | 除缺少宿主执行接口外，实际纯函数预检查在开启推测解码时返回 speculative_decode_conflict，与本轮 MTP2 冲突；关闭推测解码的同参数控制通过该检查。 | [b46de46e](https://github.com/vLLM-HUST/vllm-ascend-split-batch-hust/tree/b46de46e90204a0a7636a1dbc952f73178859ada) |
| KV Transfer Observability | 已有独立事件/观察器设施，所需生命周期、区域描述、身份和观察注册协议未见于共同核心；诊断设施不能冒充传输优化。 | [ec3446d9](https://github.com/vLLM-HUST/vllm-hust-kv-transfer-observability/tree/ec3446d936b6ac148e0be33b1dba831f9ecfc0c4) |
| Layered Prefill | 固定版本的扩展清单声明 import_only，activation.entry_points 为空；尚缺可测运行入口。 | [a45e4170](https://github.com/vLLM-HUST/vllm-ascend-layered-prefill-hust/tree/a45e41709ccacc3d7c736910b93c1b5985d9ee94) |
| Activation Sparsity | 当前包仅含配置验证和哈希；实际 CPU 兼容检查拒绝 TP2（TP1 控制通过），且缺少投影变换/稀疏算子的宿主接入。 | [0e4d0628](https://github.com/vLLM-HUST/vllm-hust-activation-sparsity/tree/0e4d0628c1972d5086a217b0007576c1fd8998a3) |
| Pipeline Microbatch | C1/C2/C4/C8/C16 的 Native 配对观测已发布；每点仍为单次观测，不能据此宣称稳定加速。 | [a15a2296](https://github.com/vLLM-HUST/vllm-hust-pipeline-microbatch/tree/a15a22961a0e4858da74a0ab806575c82cb254e6) |
| QoS Scheduler | 已有请求期限模型和排序函数，但缺少 QoS API 元数据、排序注册和输出观察接入；本轮请求未携带 SLO，第一阶段契约尚未覆盖 MTP。 | [13d376a7](https://github.com/vLLM-HUST/vllm-hust-qos-scheduler/tree/13d376a7d8990c4dcf5c0903cb6fbf2398ef0fb0) |
| StateHarbor | 当前只提供协调器/工作进程参考状态机和窗口策略；调度、KV 分配、传输和设备集成尚未接入，没有 vLLM 激活钩子。 | 内部来源，详见覆盖账本 |
| Scheduler Policy Lab | 已有独立策略函数，尚缺策略注册、KV 预算/请求快照、完成事件和调度后观察接入；共同核心中未找到所需的四个协议标识。 | 内部来源，详见覆盖账本 |
| Request Lifecycle Causal Profiler | 插件依赖当前共同核心缺少的 kv_recovery_profile 观察接口；诊断功能不等于优化收益。 | [e32a0e91](https://github.com/vLLM-HUST/vllm-hust-request-lifecycle-profiler/tree/e32a0e91027ae7a2b96bf48d2dcb7db1b3c42c87) |
| KV Materialization Arrival Control | 需要特定请求元数据和分段复用宿主接口；无元数据的软件探针只选择重新计算，不能据此生成优化成绩。 | [10428b81](https://github.com/vLLM-HUST/vllm-hust-kv-materialization-arrival-control/tree/10428b81e2b383cdcb183d4548f38a98929fd0e4) |
| BetterScale | 网站已有实测；本轮不冒充新增结果。 | [仓库](https://github.com/vLLM-HUST/BetterScale)；账本已记录网页 40 点的四个逐点来源版本 |
| DLA | 已知输出预算版本的五档并发全部完成并通过原始记录校验，已由 PR #283 发布。准入检查已执行，延后与抢占为零；不是学习型长度预测或已证实收益。 | [dc20d0f8](https://github.com/vLLM-HUST/vllm-hust-dla/tree/dc20d0f8ea8d09106f77571e1947b9a2f8702545) |
| TraceLoom | 当前版本是离线 C++ 分析器，没有在线推理优化入口；不生成虚构的服务性能曲线。 | [37323af5](https://github.com/vLLM-HUST/vllm-hust-perf-analyzer/tree/37323af55aeb5851b9a70b97155f5eacf104eafc) |

已发布的新增对照点见网站 PR [#279](https://github.com/vLLM-HUST/vllm-hust-website/pull/279) 、[#280](https://github.com/vLLM-HUST/vllm-hust-website/pull/280) 与补齐 Pipeline 五档并发的 [#282](https://github.com/vLLM-HUST/vllm-hust-website/pull/282)。环境归组修正见 [#281](https://github.com/vLLM-HUST/vllm-hust-website/pull/281)。单次观测不能证明稳定加速；未触发的优化机制须明确标注。

Native/BidKV/DLA 的 15 个共同运行时观测已由 [#283](https://github.com/vLLM-HUST/vllm-hust-website/pull/283) 发布。Mooncake 原安装版导入退出 SIGABRT 的失败证据已保留；固定源码新构建已通过导入、四类传输和原始 Store 读写。实际服务在 131K 冷请求答对、复用缓存后连续输出 48 个 `!`，同时观察到 Store 容量不足和退出时堆损坏；尚未证明根因。原始失败归档与 SHA256 见覆盖账本。缺少 hccn.conf 未阻止已通过的传输测试，不能再单独据此判定不可运行。

16 GiB/rank 对照已完成：Native 26/26 通过，Mooncake 在第 10 项 warm-262080 再次返回 48 个 `!`，而对应冷请求通过。此次没有记录到 Store put/get 失败，失败请求日志的外部 `need_to_load=0`，所以不能直接归因为外部读取错误。退出时两个 worker 被 SIGKILL，仍有堆损坏日志；最终设备均释放。2744 个源文件哈希复核一致，完整归档 SHA256 为 `637405d49011869855793b8aa200c864ff736716e32e332bd704041f708cbfab`。扩大容量不足以解决资格失败，未进行 Mooncake 性能测量。

已针对运行中 Mamba 跟踪器未传入已计算 token 数的问题制作并验证修复（Ascend `03766ac696fde5ab1980d80ca0b8543d3580c989`，相关调度测试 68 项通过）。独立硬件复测中 Native 26/26 通过，但 Mooncake 仍在 warm-262080 失败，退出堆损坏也仍存在，因此该修复不足以解决服务资格问题。修复版完整回执归档 SHA256：`557cbf246b158b037f27896e276657dd4c32a7f0ff6dd11cb722fd021c7647f4`；3895 个来源哈希一致，设备已释放，无性能测量。
