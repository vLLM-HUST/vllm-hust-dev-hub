# A1—A4 全量数据集测试矩阵

> 状态：派欧云八项物理资产已校验并纳入统一资产清单；授权、oracle、固定 tokenizer 与确定性转换资格项仍保持阻塞
>
> 组织原则：每个指标配置维护一组符合其合同的数据集；测试只分 `REQUIRED`（必测）与 `SUPPLEMENTARY`（补充）两档，不按数据来源设置优先级。
>
> 执行原则：冻结到同一指标配置的多个数据集必须分别执行、分别报告；不得加权平均掩盖任何失败。`SUPPLEMENTARY` 不能代替 `REQUIRED`，公共工程健康数据与 A1—A4 验收合同保持分离。

## 1. 共通规则

1. 数据文件只保存一份；同一数据集用于多个场景时，由 manifest 引用同一冻结资产。
2. 每个“数据集 × 指标配置 × B0/B1 × 冷启动生命周期”均有独立结果，不以混合成绩掩盖单项成绩。
3. 除数据集官方固定 split 外，不抽样、不筛选、不静默丢弃超长请求。模型上下文不足时记为明确的 `UNSUPPORTED_CONTEXT_LENGTH`，仍计入完成率。
4. 官方版本必须冻结仓库、revision/commit、许可、原始文件 SHA-256、记录数和字段说明。
5. 合成负载不是自然数据集，但作为 A1/A3 的完整 workload profile 执行；生成器提交版本、随机种子和生成后请求 manifest。
6. 受控访问、已下架或需要企业授权的资产不得冒名；状态保留为 `AUTH_REQUIRED`、`UPSTREAM_UNAVAILABLE` 或 `SOURCE_TRANSFER_REQUIRED`，取得后才能开始对应正式测试。
7. 当前模型为文本模型，视觉数据不得转成纯文本冒充多模态结果；VisionArena 记为 `MODEL_MODALITY_NOT_APPLICABLE`，待多模态模型测试项执行。
8. `coverage_role` 说明数据补充了哪种业务或机制覆盖，`contract_role` 说明它能否参与该指标合同；两者均不是优先级。正式 `config_id` 生成前从适用数据集组冻结合同所需资产，之后不得根据 B0/B1 结果换题。
9. 企业接口请求、API 生成文本和 hybrid/synthetic 数据分别标识，不统称真实线上 trace。原始请求中的 `model`、`max_tokens`、`stream` 不直接重放。
10. `test_tier` 在请求物化前冻结。`REQUIRED` 缺失或未完成使对应合同为 `CANNOT_DETERMINE`；`SUPPLEMENTARY` 单独报告，不进入硬门槛、几何平均或必测完成率。

### 两档分配规则

1. 本矩阵 A1—A4 表内条目默认是 `REQUIRED`：资产和模型适用时必须执行；处于授权、资产、qualification 或模型模态阻塞状态时保留在必测清单并如实报告，不能自动降档。
2. 下列明确配置为 `SUPPLEMENTARY`：
   - `PAIO-LONG-PREFILL-5000` 在 A1 代表性 Prefill 配置中的运行；其进入 A2 Long capacity 的合格配置仍为 `REQUIRED`；
   - `PAIO-PREFIX-SHARED-5000` 的机制扩展运行；
   - `PAIO-SEMANTIC-SIMILAR-5000` 的 similarity/稳定性扩展运行；
   - `PAIO-CODE-EVAL-1000` 在 A2 Code 的 extension-only 引用；其 A2 Reasoning/TTFT 配置仍为 `REQUIRED`；
   - `by-scope/extensions/` 中没有被正式合同提升为必测的其他配置。
3. 同一物理数据集可以在不同 `config_id` 下有不同档位；结果中必须同时记录 `dataset_id`、`config_id`、`test_tier`、`contract_role` 和 `coverage_role`。
4. 任何补充项要提升为必测，必须在查看 B0/B1 结果前完成书面变更、阈值冻结和重新 commissioning；测试后不得改档。

统一资产入口：`/data/shared_datasets/vllm-hust-evaluation/a1-a4/assets/`。八个派欧云数据集以 `assets/paio-*` 与 ShareGPT、BFCL、LongBench 等原有资产并列存放；`assets/paio-cloud/20260820/` 只保存来源包、清单、README 和回指链接。按指标整理的只读引用位于 `by-scope/A1/`、`by-scope/A2/`、`by-scope/A3/`、`by-scope/A4/` 和 `by-scope/extensions/`。

## 2. A1：有效计算、固定形状与基础服务开销

| ID | 数据集或 workload | 必测范围 | 主要目的 | 当前状态 |
|---|---|---|---|---|
| A1-COMPUTE-4096 | tokenizer-exact synthetic | input=4096、output=1、batch=8，全量生成请求 | Prefill 有效计算 | `GENERATOR_READY` |
| A1-COMPUTE-1024 | tokenizer-exact synthetic | input=1024、output=1、batch=32，全量生成请求 | 短输入高批处理 | `GENERATOR_READY` |
| A1-COMPUTE-8192 | tokenizer-exact synthetic | input=8192、output=1、batch=4，全量生成请求 | 长 Prefill | `GENERATOR_READY` |
| A1-RANDOM | vLLM random workload | registry 中全部 A1 形状 | 调度、批处理、decode 基础开销 | `GENERATOR_READY` |
| A1-PREFIX | prefix-repetition workload | registry 中全部 prefix profile | Prefix Cache 和重复上下文复用 | `GENERATOR_READY` |
| A1-SONNET | vLLM `sonnet.txt` | 整个原始文本文件生成的完整请求集 | 固定文本吞吐 | `READY_LOCAL` |
| A1-LATENCY | random-latency workload | registry 中全部 batch/shape | 单请求和批请求 latency | `GENERATOR_READY` |
| A1-LOGPROBS | logprobs-online workload | registry 全部请求 | logprobs 服务路径 | `GENERATOR_READY` |
| A1-SPEC | spec-decode-online workload | registry 全部请求 | speculative decoding | `GENERATOR_READY` |
| A1-SLICEGPT | slicegpt-compression-online workload | registry 全部请求 | 压缩模型服务路径 | `MODEL_ARTIFACT_REQUIRED` |
| PAIO-LONG-PREFILL-5000 | 派欧云混合合成长 Prefill | 5,000 条经固定 tokenizer 确定性窗口化的请求 | 代表性 Prefill 内容；不替代固定 4096×8 MFU 主形状 | `QUALIFICATION_REQUIRED` |
| PAIO-PREFIX-SHARED-5000 | 派欧云混合合成共享前缀 | 5,000 条按冻结生成属性分层报告 | Prefix/KV 机制补充；不进入 A1—A4 硬门槛 | `QUALIFICATION_REQUIRED_NON_GATE` |

A1 不把语义问答数据强行填充成固定 token 形状；否则会改变原始数据。ShareGPT、UltraChat 等自然数据集在 A2/A4 原样执行。

## 3. A2：功能、业务形态与在线服务

### A2-D：对话与多轮

| ID | 数据集 | 必测范围 | 官方来源/许可 | 当前状态 |
|---|---|---|---|---|
| A2-D-SHAREGPT | ShareGPT V3 unfiltered cleaned | 完整文件全部会话 | `anon8231489123/ShareGPT_Vicuna_unfiltered`；许可凭证待补 | `READY_PROVENANCE_REVIEW` |
| A2-D-ULTRACHAT | UltraChat 200k | `train_sft`、`test_sft`、`train_gen`、`test_gen` 全部 split | `HuggingFaceH4/ultrachat_200k`；MIT | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A2-D-OASST1 | OpenAssistant OASST1 | ready/all messages、ready/all trees、prompts、train、validation 全部资产 | `OpenAssistant/oasst1`；Apache-2.0 | `READY_LOCAL` |
| A2-D-LMSYS | LMSYS-Chat-1M | 官方完整数据文件 | `lmsys/lmsys-chat-1m`；受控访问 | `AUTH_REQUIRED_HTTP_401` |
| A2-D-WILDCHAT | WildChat | 官方完整 1M 快照 | `allenai/WildChat`；ODC-BY | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A2-D-WILDCHAT48 | WildChat-4.8M | 官方 4.8M 全部 86 个 parquet 分片 | `allenai/WildChat-4.8M`；ODC-BY | `READY_OFFICIAL_FULL_SNAPSHOT` |
| PAIO-CHAT-1000 | `normal_chat_1000.jsonl` | 1,000 条全部请求 | 派欧云企业场景接口请求；授权回执待归档 | `ASSET_VERIFIED_QUALIFICATION_REQUIRED` |
| PAIO-REUSE-CONV-5000 | `reuse_conversation.jsonl` | 5,000 条，按高/中/低复用层级固定分层 | 派欧云 hybrid/synthetic | `ASSET_VERIFIED_QUALIFICATION_REQUIRED` |
| PAIO-SEMANTIC-SIMILAR-5000 | `semantic_similar.jsonl` | 5,000 条，单列稳定性分析 | 派欧云 hybrid/synthetic | `ASSET_VERIFIED_NON_GATE` |

### A2-T：Tool Calling 与 Agent

| ID | 数据集 | 必测范围 | 官方来源/许可 | 当前状态 |
|---|---|---|---|---|
| A2-T-BFCL3 | BFCL v3 | 25 个任务分组、possible answers、multi-turn function docs 全部执行 | `gorilla-llm/Berkeley-Function-Calling-Leaderboard`；Apache-2.0 | `READY_LOCAL` |
| A2-T-BFCL4 | BFCL v4 | 官方发布的全部 v4 分组 | `bfcl-eval==2025.12.17`；Berkeley 排行榜指定复现包 | `READY_OFFICIAL_PYPI_SNAPSHOT` |
| A2-T-TAU2 | tau2-bench | 官方仓库所含全部 domain 和任务 | `sierra-research/tau2-bench`；MIT | `READY_OFFICIAL_REPOSITORY` |
| A2-T-TOOLBENCH | ToolBench | G1/G2/G3、工具环境、官方 test instruction 与评测数据 | `OpenBMB/ToolBench`；Apache-2.0 | `READY_OFFICIAL_FULL_DATA` |
| A2-T-EVOSCIENTIST | EvoScientist traces | custom 32 条及 ShareGPT 格式 trace 全部执行 | 本地 benchmark 仓库；授权凭证待补 | `READY_PROVENANCE_REVIEW` |
| A2-T-SYFI | SyFi coding trace | gzip 中全部 session、round 和 tool event | 本地 benchmark Trace；授权凭证待补 | `READY_PROVENANCE_REVIEW` |
| A2-T-HOTPOT-REACT | HotpotQA/ReAct | 本地 100 条 ReAct 资产及官方 HotpotQA 完整 split 分别执行 | HotpotQA CC-BY-SA-4.0 | `READY_LOCAL_SUBSET_AND_OFFICIAL_FULL` |
| A2-T-AGENT-CACHE | agent-cache-pressure workload | registry 生成的全部请求 | benchmark 仓库生成器 | `GENERATOR_READY` |
| SZYN-OPENCODE-SWEBENCH-VERIFIED-500 | 中国移动苏州（苏州云能）OpenCode 开源 Issue 解决生产优化数据集 | 500 个真实开源 Issue；实际执行后保留完整 agent/tool/patch/test/失败轨迹 | SWE-bench Verified + OpenCode；逐仓库保留上游许可 | `SINGLE_CASE_QUALIFICATION_PASSED_BATCH_PENDING`（1/1 qualification 通过；生产优化扩展，不替代 BFCL/tau2 硬门槛） |

BFCL v3 的 25 个任务分组不得合并为一个抽样测试：`simple`、`multiple`、`parallel`、`parallel_multiple`、`irrelevance`、`chatable`、`java`、`javascript`、`rest`、`sql`、`exec_simple`、`exec_multiple`、`exec_parallel`、`exec_parallel_multiple`、`live_simple`、`live_multiple`、`live_parallel`、`live_parallel_multiple`、`live_relevance`、`live_irrelevance`、`multi_turn_base`、`multi_turn_composite`、`multi_turn_long_context`、`multi_turn_miss_func`、`multi_turn_miss_param`。

### A2-R：推理

| ID | 数据集 | 必测范围 | 官方来源/许可 | 当前状态 |
|---|---|---|---|---|
| A2-R-GSM8K-MAIN | GSM8K main | train/test 全部 split | `openai/gsm8k`；MIT | `READY_LOCAL` |
| A2-R-GSM8K-SOCRATIC | GSM8K socratic | train/test 全部 split | `openai/gsm8k`；MIT | `READY_LOCAL` |
| A2-R-MATH500 | MATH-500 | 500 条全部执行 | `HuggingFaceH4/MATH-500` | `READY_DOWNLOADED` |
| A2-R-GPQA | GPQA | main、diamond、experts、extended 全部公开 split | `idavidrein/gpqa`；数据内置 CC-BY-4.0 | `READY_OFFICIAL_GITHUB` |
| A2-R-BBH | BIG-Bench Hard | 23 个任务全部执行 | Google BIG-bench 数据派生发布；许可待逐任务核验 | `READY_DATA_LICENSE_REVIEW` |
| A2-R-MMLUPRO | MMLU-Pro | validation/test 全部执行 | `TIGER-Lab/MMLU-Pro`；MIT | `READY_DOWNLOADED` |
| A2-R-ARC | AI2 ARC | ARC-Challenge 与 ARC-Easy 的 train/validation/test 全部执行 | `allenai/ai2_arc`；CC-BY-SA-4.0 | `READY_DOWNLOADED` |
| A2-R-AIME24 | AIME 2024 | 官方快照全部题目 | `HuggingFaceH4/aime_2024`；许可待补 | `READY_DATA_LICENSE_REVIEW` |
| A2-R-HOTPOT | HotpotQA | distractor/fullwiki 的全部公开 split | `hotpotqa/hotpot_qa`；CC-BY-SA-4.0 | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A2-R-LONGV2 | LongBench-v2 | 503 条全部执行 | `THUDM/LongBench-v2`；Apache-2.0 | `READY_LOCAL` |
| PAIO-CODE-EVAL-1000 | `code_eval_ttft_1000.jsonl` | 1,000 条短输出/TTFT 请求 | 派欧云企业场景接口请求 | `ASSET_VERIFIED_PERFORMANCE_ONLY`（缺独立 gold 时不承担质量主判；不得标为 Tool） |

### A2-S：结构化输出

| ID | 数据集 | 必测范围 | 官方来源/许可 | 当前状态 |
|---|---|---|---|---|
| A2-S-SCHEMASTORE | SchemaStore | 仓库全部 schema；逐 schema 记录 draft 与外部 `$ref` 状态 | SchemaStore；Apache-2.0 | `READY_LOCAL` |
| A2-S-JSONSCHEMABENCH | JSONSchemaBench | Github 各难度、Glaive、SchemaStore、Kubernetes、Snowplow、WashingtonPost 全部目录 | `guidance-ai/jsonschemabench`；仓库许可待补 | `READY_LICENSE_REVIEW` |
| A2-S-STRUCTEVAL | StructEval | 2,035 条、44 类任务、18 种格式全部执行 | `TIGER-Lab/StructEval`；MIT | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A2-S-BFCL-JSON | BFCL 函数参数 JSON | BFCL v3/v4 中全部适用记录 | 同 BFCL | `READY_BFCL3_AND_BFCL4` |
| PAIO-JSON-500 | `json_requests_500.jsonl` | 500 条全部请求；328 `json_object`、172 `json_schema` | 派欧云企业场景接口请求；授权回执待归档 | `ASSET_VERIFIED_QUALIFICATION_REQUIRED`（不含 tools） |

### A2-C：代码

| ID | 数据集 | 必测范围 | 官方来源/许可 | 当前状态 |
|---|---|---|---|---|
| A2-C-INSTRUCTCODER | InstructCoder | train/validation 及官方 seed 文件全部记录 | `likaixin/InstructCoder`；许可待补 | `READY_OFFICIAL_FULL_SNAPSHOT_LICENSE_REVIEW` |
| A2-C-LIVECODEBENCH | LiveCodeBench | code generation、execution、test generation 的全部冻结 release | LiveCodeBench 官方仓库与 HF 数据 | `READY_OFFICIAL_FULL_SNAPSHOTS` |
| A2-C-HUMANEVAL | HumanEval | 164 条全部执行 | `openai/openai_humaneval`；MIT | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A2-C-MBPP | MBPP | full 与 sanitized 的全部 split | `google-research-datasets/mbpp`；CC-BY-4.0 | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A2-C-SYFI | SyFi coding trace | 全部 session/round | 本地 Trace | `READY_PROVENANCE_REVIEW` |
| PAIO-CODE-EVAL-1000 | `code_eval_ttft_1000.jsonl` | 1,000 条全部请求 | 同一物理资产的 Code 扩展引用 | `ASSET_VERIFIED_EXTENSION_ONLY` |
| A2-C-NGRAM | ngram-instructcoder-online | InstructCoder 全部记录 | benchmark 仓库 + InstructCoder | `DATA_READY_FEATURE_VERIFY_REQUIRED` |
| SZYN-OPENCODE-SWEBENCH-VERIFIED-500 | OpenCode issue-resolution | 500 个冻结任务，按 case_key 顺序执行并逐项目报告 | 中国移动苏州（苏州云能）生产优化数据集；Issue 内容归属各上游项目 | `SINGLE_CASE_QUALIFICATION_PASSED_BATCH_PENDING` |

### A2-V：多模态对话

| ID | 数据集 | 必测范围 | 官方来源/许可 | 当前状态 |
|---|---|---|---|---|
| A2-V-VISIONARENA | VisionArena-Chat | 冻结 parquet 的全部记录及图像引用；只能由正式支持图像输入的模型执行 | LMSYS VisionArena；许可与图像可访问性按冻结 manifest 核验 | `MODEL_MODALITY_NOT_APPLICABLE`（当前 Qwen2.5-14B-Instruct 为文本模型；资产保留，不产生通过结果） |

### A2-W：仓库可重复生成的业务 workload

以下条目同样全部执行，但结果注明 `synthetic/repo-generated`，不冒充公开自然数据集：

| ID | workload family | 场景 |
|---|---|---|
| A2-W-SESSION | session-affine multi-turn | 多轮会话与会话亲和性 |
| A2-W-BURSTY | session-affine bursty | 多轮突发流量 |
| A2-W-RAG | RAG follow-up | 检索后追问和前缀复用 |
| A2-W-TOOL | tool-scaffold agent | 工具描述与 Agent scaffold |
| A2-W-CODING | repo-aware coding assistant | 仓库上下文代码助手 |
| A2-W-EXPERIMENT | experiment-planning assistant | 实验规划 Agent |
| A2-W-SIMULATION | simulation-analysis-verification | 分析、验证和状态传递 |
| A2-W-ASYNC-DOC | asynchronous document pipeline | 异步文档流水线 |
| A2-W-VOICE-PROXY | realtime voice assistant token-budget proxy | 文本 token-budget 代理；不冒充音频质量测试 |
| A2-W-CONTINUATION | session-continuation maintenance | 长会话延续 |
| A2-W-DYNAMIC-RAG | dynamic RAG corpus update | 动态语料更新后的状态一致性 |
| A2-W-MEMORY | memory-write-then-reuse | 写入后记忆复用 |
| A2-W-CODE-JUDGE | code-eval-judge | 代码生成、判题和结果返回 |
| A2-W-STRUCTURED | structured-json-generation | JSON Schema 约束生成 |
| A2-W-SUPPORT | multi-turn-support-chat | 多轮客服与状态传递 |

## 4. A3：长上下文、KV 压力与稳定性

| ID | 数据集或 workload | 必测范围 | 当前状态 |
|---|---|---|---|
| A3-LONGV2 | LongBench-v2 | 503 条全部执行；超出模型上限的请求不得静默删除 | `READY_LOCAL` |
| A3-LONGBENCH | LongBench/LongBench-Chat | 官方全部任务与 split | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A3-INFINITE | InfiniteBench | 官方全部 12 类长上下文任务 | `READY_OFFICIAL_FULL_SNAPSHOT` |
| A3-RULER | RULER | 适配模型上限的全部任务，在 4K/8K/16K/32K 分层完整生成 | `GENERATOR_CODE_READY` |
| A3-BFCL-LONG | BFCL multi-turn long-context | v3 与 v4 全部长上下文记录 | `READY_BFCL3_AND_BFCL4` |
| A3-SYFI | SyFi 长会话 | 全部 trace，按原 session 边界执行 | `READY_PROVENANCE_REVIEW` |
| A3-OASST | OASST1 长对话树 | 所有树；不得只选满足固定轮数的树 | `READY_LOCAL` |
| A3-KV | kv-pressure synthetic | registry 全部形状 | `GENERATOR_READY` |
| A3-PREFIX | prefix/KV repetition synthetic | registry 全部形状 | `GENERATOR_READY` |
| PAIO-LONGTEXT-4000 | 派欧云 API 生成长文本 | 授权、敏感信息、固定 tokenizer、目标事实/oracle 全部通过后生成 30720 输入 + 2048 输出上限请求 | `ASSET_VERIFIED_A3_QUALIFICATION_REQUIRED` |
| A3-DOC-GEN | long-context document analysis | 仓库生成器的完整冻结请求集 | `GENERATOR_READY` |
| A3-RAG-UPDATE | dynamic RAG corpus update | 仓库生成器的完整冻结请求集 | `GENERATOR_READY` |
| A3-MEMORY | memory-write-then-reuse | 仓库生成器的完整冻结请求集 | `GENERATOR_READY` |
| A3-PREEMPT | preemption-resume long decode | 仓库生成器的完整冻结请求集 | `GENERATOR_READY` |
| A3-ATTN | attention-boundary online | registry 全部形状 | `GENERATOR_READY` |
| A3-KV-TIER | kv-tiering-prefix online | registry 全部形状 | `GENERATOR_READY` |
| A3-WARM | saturated-warm-cache online | registry 全部形状 | `GENERATOR_READY` |
| A3-KNORM | KNorm/KV-compression long-context | registry 全部形状 | `GENERATOR_READY` |
| A3-KV-TRANSFER | KV transfer latency | registry 全部形状 | `GENERATOR_READY` |

A3 按模型声明的最大上下文执行。若数据原始上下文超过模型上限，记录不支持数量和比例；不得截断后声称完成原任务。

## 5. A4：多租户混合调度

A4 不是重新抽样四份小数据，而是把 A2 已冻结的完整请求流按租户角色重放。每个源数据集均保留 `dataset_id`、`record_id`、`session_id` 和租户标签，并分别出具成功率、TTFT、TPOT、吞吐与正确率。

| 租户角色 | 纳入的全部数据集 |
|---|---|
| Dialogue | ShareGPT、UltraChat、OASST1、LMSYS-Chat-1M、WildChat、WildChat-4.8M、PAIO-CHAT-1000、PAIO-REUSE-CONV-5000；PAIO-SEMANTIC-SIMILAR-5000 仅作单列稳定性扩展 |
| Tool/Agent | BFCL v3、BFCL v4、tau2-bench、ToolBench、EvoScientist、SyFi、HotpotQA/ReAct |
| Reasoning | GSM8K main、GSM8K socratic、MATH-500、GPQA、BBH、MMLU-Pro、ARC、AIME 2024、HotpotQA、LongBench-v2 reasoning tasks、PAIO-CODE-EVAL-1000（缺 gold 时只作性能证据） |
| Structured | SchemaStore、JSONSchemaBench、StructEval、BFCL 参数 JSON、PAIO-JSON-500 |
| Code | InstructCoder、LiveCodeBench、HumanEval、MBPP、SyFi、PAIO-CODE-EVAL-1000（扩展引用，不另存文件） |

BurstGPT 和 SyFi 的到达时间、会话边界及 burst 信息作为 A4 调度 trace 全量重放；它们不覆盖上述语义数据集的来源身份。VisionArena 只在参与比较的 B0/B1 模型均正式支持同一图像输入协议时纳入 A4；当前文本模型记为 `MODEL_MODALITY_NOT_APPLICABLE`。

`SZYN-OPENCODE-SWEBENCH-VERIFIED-500`作为中国移动苏州（苏州云能）生产优化扩展，可用于 A2 Tool/Agent、A2 Reasoning/Code、A4 Tool/Reasoning 租户及长程代码 Agent；其真实开源 Issue 与实际 OpenCode 执行轨迹分别保留 provenance。它不是中国移动苏州（苏州云能）原始 issue 内容或真实线上流量，不进入 A1—A4 硬门槛，也不替代 BFCL/tau2。2026-10-02 已完成首个确定性样本的单题 qualification；完整 500 题批量仍待执行。

A4 还必须分别执行 `shared-prefix-multi-tenant-assistant`、`session-affine-bursty`、`multi-nic-throughput`、`unified-comm-online`、`eplb-expert-rebalance-online` 和 `moe-alltoall-online`。若当前单卡稠密模型与某项硬件/模型前提不匹配，结果为明确的 `HARDWARE_OR_MODEL_NOT_APPLICABLE`，不得伪造性能值。

## 6. 正式开跑前的资产门禁

每个表项必须具备：

- 官方 URL 与不可变 revision/commit；
- 许可文件或数据卡许可字段；
- 原始文件清单、字节数、SHA-256；
- parquet/json/jsonl/gzip/zip 可读取验证；
- split、记录数、唯一 ID 规则；
- 全量转换后的请求数以及一一对应的原始记录 ID；
- 适用的 scorer、成功判定和正确率算法；
- 不支持项、授权缺失项和上游缺失项的原始错误证据。

任何状态不是 `READY_*` 或 `GENERATOR_READY` 的表项都不能被伪造为已完成；但也不能从必测矩阵删除。

## 7. A1—A4 资产落盘与取得证据

机器可读逐文件清单统一写入 `/data/shared_datasets/vllm-hust-evaluation/a1-a4/asset-inventory.json`；既有资产的独立核验记录为 `/data/shared_datasets/vllm-hust-evaluation/a1-a4/existing-asset-verification.json`。V4.5 派欧云逻辑资产合同为 `config/v4.5-paio-cloud-dataset-assets.json`。代码生成器只记录冻结提交，不作为数据 payload 重复计算。

### A1 资产

- `sonnet.txt` 已在统一入口建立只读引用；正式请求集合由冻结生成器产生。
- random、prefix、latency、logprobs、spec-decode 等没有外部自然数据文件，正式前冻结生成器提交、参数、随机种子及生成后请求清单。
- SliceGPT 仍缺与模型对应的压缩模型资产，不能以普通权重结果代替。

### A2 资产

官方入口：

- Dialogue：[UltraChat](https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k)、[OASST1](https://huggingface.co/datasets/OpenAssistant/oasst1)、[LMSYS-Chat-1M](https://huggingface.co/datasets/lmsys/lmsys-chat-1m)、[WildChat](https://huggingface.co/datasets/allenai/WildChat)、[WildChat-4.8M](https://huggingface.co/datasets/allenai/WildChat-4.8M)。ShareGPT 当前按已冻结原文件登记，原发布入口可用性与许可尚未完成复核。
- Tool/Agent：[BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html)、[tau2-bench](https://github.com/sierra-research/tau2-bench)、[ToolBench](https://github.com/OpenBMB/ToolBench)、[GPQA](https://github.com/idavidrein/gpqa)、[HotpotQA](https://huggingface.co/datasets/hotpotqa/hotpot_qa)。
- Reasoning：[GSM8K](https://huggingface.co/datasets/openai/gsm8k)、[MATH-500](https://huggingface.co/datasets/HuggingFaceH4/MATH-500)、[BBH](https://huggingface.co/datasets/lukaemon/bbh)、[MMLU-Pro](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro)、[AI2 ARC](https://huggingface.co/datasets/allenai/ai2_arc)、[AIME 2024](https://huggingface.co/datasets/HuggingFaceH4/aime_2024)、[LongBench-v2](https://huggingface.co/datasets/THUDM/LongBench-v2)。
- Structured：[SchemaStore](https://github.com/SchemaStore/schemastore)、[JSONSchemaBench](https://huggingface.co/datasets/guidance-ai/jsonschemabench)、[StructEval](https://huggingface.co/datasets/TIGER-Lab/StructEval)。
- Code：[InstructCoder](https://huggingface.co/datasets/likaixin/InstructCoder)、[LiveCodeBench](https://github.com/LiveCodeBench/LiveCodeBench)、[HumanEval](https://huggingface.co/datasets/openai/openai_humaneval)、[MBPP](https://huggingface.co/datasets/google-research-datasets/mbpp)。

| 数据集 | 冻结版本或取得证据 | 落盘状态 |
|---|---|---|
| ShareGPT V3 | 原文件 672,837,942 bytes；SHA-256 `35f0e213ce091ed9b9af2a1f0755e9d39f9ccec34ab281cd4ca60d70f6479ba4` | 已落盘；许可/来源凭证复核中 |
| UltraChat 200k | HF revision `8049631c405ae6576f93f445c6b8166f76f5505a`；10 文件；1,624,055,929 bytes | 官方完整快照已落盘 |
| OASST1 | `OpenAssistant/oasst1` 全资产，详见机器清单 | 已落盘 |
| LMSYS-Chat-1M | HF revision `200748d9d3cddcc9d782887541057aca0b18c5da`；数据请求返回 HTTP 401 | 数据卡已保存；须由接受条款且获授权的账号下载 |
| WildChat | HF revision `f66566ceaaeb619dd98ffb0f3bf3ce1f86775ac4`；9 文件；1,586,578,132 bytes | 官方完整快照已落盘 |
| WildChat-4.8M | HF revision `c827c6df8fcf008219ffaffa4d1dd77491099367`；86 个 parquet 分片；共 89 文件、15,282,330,794 bytes | 官方完整快照已落盘 |
| BFCL v3 | 25 个任务组及配套答案/函数文档均通过既有资产核验 | 已落盘 |
| BFCL v4 | 官方包 `bfcl-eval==2025.12.17`；wheel SHA-256 `8555bc9407a56682ceb7d969e87eb724f6b679deb0ef05114d9c6e786406b103` | v4 全部分组已从官方 wheel 解包落盘 |
| tau2-bench | 官方仓库 commit `a2c024725189473d2d7cea3a5cfdbcc67478e41f` | 全部仓库 domain/data 已落盘 |
| ToolBench | 官方仓库 commit `d56fdd89faf8c91fa135090b212bb9057ee5cfc2`；官方 Drive 文件 ID `1ceLQ9S1IkFTiWeJ3G1FArsD4zY6WYiLa`；ZIP 1,761,298,101 bytes；SHA-256 `df035ef91551d5cdc9e66d782dc12c821c81e830da2e7d05f633c7b26ae06016` | 官方完整数据已落盘；G1/G2/G3 instruction 分别 88,995 / 87,070 / 25,709 条，六个 test split 共 1,100 条 |
| HotpotQA | HF revision `1908d6afbbead072334abe2965f91bd2709910ab`；9 文件；746,637,047 bytes | 官方完整快照及本地 ReAct 100 条均已落盘 |
| GSM8K | HF revision `740312add88f781978c0658806c59bc2815b9866` | main/socratic 全 split 已落盘 |
| MATH-500 | HF revision `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`；500 条 | 已落盘；数据卡未声明许可，凭证复核中 |
| GPQA | 官方仓库 commit `56686c06f5e19865c153de0fdb11be3890014df7`；main 448、diamond 198、experts 60、extended 546 | 官方受密码保护归档已按项目说明解包；数据内许可 CC-BY-4.0 |
| BBH | HF revision `982bb89fd79532a8ac676a61fc42eb1aeec63f99`；29 文件 | 已落盘；逐任务许可复核中 |
| MMLU-Pro | HF revision `b189ec765aa7ed75c8acfea42df31fdae71f97be`；7 文件；4,207,360 bytes | 官方完整快照已落盘 |
| AI2 ARC | HF revision `210d026faf9955653af8916fad021475a3f00453`；8 文件；1,222,570 bytes | 官方完整快照已落盘 |
| AIME 2024 | HF revision `2fe88a2f1091d5048c0f36abc874fb997b3dd99a`；30 条 | 已落盘；数据卡未声明许可，凭证复核中 |
| LongBench-v2 | HF revision `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`；503 条；数据 SHA-256 `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2` | 已落盘并通过记录数核验 |
| SchemaStore | 68 个 draft-2020-12 schema，其中 63 个无外部引用 | 已落盘并核验 |
| JSONSchemaBench | 9,558 个 schema，其中 50 个原生 draft-2020-12 | 已落盘；仓库许可凭证复核中 |
| StructEval | HF revision `936be10548688c6d417cd435dd906158f19ba14b`；3 文件；2,341,049 bytes；代码归档 commit `788a40c0bf41aa7b2cbc6a480015c842353a2492` | 2,035 条官方数据与冻结代码均已落盘 |
| InstructCoder | HF revision `6a778a720284d6520b56bd03d5c3070930d41071`；6 文件；149,816,345 bytes | 官方完整快照已落盘；许可复核中 |
| LiveCodeBench | code-generation `0fe84c3912ea0c4d4a78037083943e8f0c4dd505`、execution `fcf5430809253fd78c5dc5b57573ca673e6e43c2`、test-generation `6f3ac40bbecf81eba15899139d279b077f2816fd`；官方代码 commit `28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24` | 三类数据与代码均已完整落盘 |
| HumanEval | HF revision `7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544`；164 条 | 官方完整快照已落盘 |
| MBPP | HF revision `4bb6404fdc6cacfda99d4ac4205087b89d32030c`；10 文件 | full/sanitized 全 split 已落盘 |
| VisionArena | 冻结 manifest 和 parquet 已保留 | 当前文本模型不适用，禁止转成文本冒充执行 |
| 派欧云企业接口三文件 | PAIO-CHAT-1000、PAIO-JSON-500、PAIO-CODE-EVAL-1000 均已逐文件 SHA-256、记录数和字节数核验 | 已落盘；授权回执、确定性转换、ordered case/token manifest 与所需 oracle 仍待资格化 |
| 派欧云 hybrid/synthetic 四文件 | PAIO-LONG-PREFILL-5000、PAIO-PREFIX-SHARED-5000、PAIO-REUSE-CONV-5000、PAIO-SEMANTIC-SIMILAR-5000 | 已落盘；保留生成属性，不表述为真实线上 trace；固定 tokenizer/生成器 provenance/转换 manifest 待资格化 |
| 派欧云 API 长文本 | PAIO-LONGTEXT-4000 | 已落盘；授权、敏感信息、固定 tokenizer 精确计数、目标事实/oracle 通过前不得进入 A3 主判 |

### A3 资产

官方入口：[LongBench](https://huggingface.co/datasets/THUDM/LongBench)、[InfiniteBench](https://github.com/OpenBMB/InfiniteBench)、[RULER](https://github.com/NVIDIA/RULER)。其余 A3 条目引用上方同一冻结资产或由冻结生成器产生。

| 数据集或生成器 | 冻结版本或取得证据 | 落盘状态 |
|---|---|---|
| LongBench | HF revision `5e628be450b7e67fb7ae6e201bd6d8f7056f7672`；4 文件；113,954,856 bytes | 官方完整快照已落盘 |
| InfiniteBench | 数据 revision `90f0394333616266d9fe85824ceaf505093cbaa5`；14 文件；2,499,845,074 bytes；代码 commit `51d9b37b0f1790ead936df2243abbf7f0420e439` | 官方完整数据与代码已落盘 |
| RULER | 官方仓库 commit `c3f5e3b4f87f97e048793bb510a3a6b19a46bf3a` | 生成器已落盘；正式请求须按 4K/8K/16K/32K 冻结 |
| LongBench-v2、BFCL long、SyFi、OASST1 | 与 A2 引用同一冻结文件 | 不复制数据；按 A3 协议形成独立请求和结果 |
| KV/prefix/long-document 等合成负载 | `vllm-hust-benchmark` 与 `llm-serving-workloads` 冻结代码 | 正式前冻结生成请求、种子和参数 |

### A4 资产

A4 不建立另一套数据目录：引用 A2/A3 的同一文件 SHA-256，并为 Dialogue、Tool/Agent、Reasoning、Structured、Code 分别生成完整 tenant manifest。BurstGPT 和 SyFi trace 已落盘；到达计划、租户映射和混合顺序必须在 B0/B1 之前一次冻结，两个角色严格复用。

## 8. V4.5 派欧云资产的指标配置引用

下表只表达适用关系，不表达数据优先级。每个 `asset_id` 在机器清单中只绑定一个物理文件；跨 A 项、cell、租户和扩展项均引用该身份。

| asset_id | 指标配置引用 | coverage_role | contract_role | 不可越过的边界 |
|---|---|---|---|---|
| PAIO-CHAT-1000 | A2 Dialogue；A4 Dialogue | 企业问答接口覆盖 | 数据集组成员，单列报告 | 以单轮为主，不替代多轮合同 |
| PAIO-CODE-EVAL-1000 | A2 Reasoning/TTFT；A4 Reasoning；Code 扩展 | 短输出、TTFT、代码评判覆盖 | 无独立 gold 时只作性能证据 | 不得标成 Tool，不承担质量主判 |
| PAIO-JSON-500 | A2 Structured；A4 Structured | 企业 JSON object/schema 覆盖 | 数据集组成员，单列报告 | 不含 tools，不能替代工具调用合同 |
| PAIO-LONG-PREFILL-5000 | A1 代表性 Prefill；A2 Long capacity | 长 Prefill 内容与容量覆盖 | A1 补充；A2 精确窗口化后使用 | 不替代 4096×8 MFU；不能承担 A3 主判 |
| PAIO-PREFIX-SHARED-5000 | A1/A2 机制补充；High-KV 扩展 | 共享前缀与高 KV 复用 | 非硬门槛扩展 | 结果单列，不进入 A1—A4 判定 |
| PAIO-REUSE-CONV-5000 | A2 Dialogue；A4 Dialogue；High-KV 扩展 | 会话复用分层覆盖 | 数据集组成员及扩展，分别报告 | 不按结果筛选复用层级 |
| PAIO-SEMANTIC-SIMILAR-5000 | A2/A4 稳定性扩展 | 语义相似、误命中、混合批稳定性 | 非硬门槛扩展 | 不表述为真实线上 trace |
| PAIO-LONGTEXT-4000 | A2 Long capacity；资格化后 A3 32K | 授权业务长文本容量与稳定性 | A2 窗口化成员；A3 资格待定 | A3 前须授权、敏感信息、tokenizer、目标事实/oracle 全部通过 |

八项均不含视觉输入，不能替代 VisionArena；整个包没有 `tools` 字段，不能替代 BFCL 或 tau2。原始 `model=qwen3`、`max_tokens`、`stream` 只作为来源证据保存，正式请求由 V4.5 固定转换器生成，并同时保存原始层、转换层、rendered token IDs 及各层 SHA-256。正式测量当前保持关闭。
