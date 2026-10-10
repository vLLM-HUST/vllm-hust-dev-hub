# A1—A4 测试指标、公式与报价口径

> 适用范围：A1—A4 中所有公开数据集、授权数据集和可重复生成 workload。
>
> 执行原则：每个“数据集 × 场景 × B0/B1 × lifecycle”单独计算，不把不同数据集、吞吐口径或请求类型混成一个 TPS。
>
> 财务原则：本文只定义公式和字段；910B 资源单价、填平率、运营费率及利润参数由授权人员通过独立私密配置提供，不写入公开证据包。

## 指标分档

对外结果只分两档，并按该顺序排列：

| 档位 | 定义 | 对正式结论的影响 |
|---|---|---|
| `REQUIRED` | 第三方必须交付、能够直接形成验收结论的指标 | 适用但缺失时，对应结论为 `CANNOT_DETERMINE` |
| `ADDITIONAL` | 根因诊断、硬件观察、稳定性趋势或备选财务口径 | 可附加报告，不影响必交完成率，不得代替 `REQUIRED` |

“适用即必交”仍属于 `REQUIRED`。例如没有冻结 oracle 的数据集，其正确率填
`NOT_APPLICABLE`；长上下文测试必须报告静默截断率，普通短请求则可以填
`NOT_APPLICABLE`。不适用不能写成数值 0。

### REQUIRED：19 个必交指标

| 指标组 | REQUIRED 指标 |
|---|---|
| 吞吐（4） | 请求吞吐、输入吞吐、输出吞吐、总吞吐 |
| 时延（3） | TTFT、TPOT、端到端时延 |
| 质量与可靠性（4） | 成功率、正确率/官方任务得分、OOM、静默截断率 |
| B0/B1 对比（4） | B1/B0 吞吐比、吞吐提升率、时延改善率、跨场景几何平均 |
| 成本与报价（4） | 极限百万 token 成本、SLO 百万 token 成本、峰值填平率、加价率口径报价 |

### ADDITIONAL：10 个附加指标

| 指标组 | ADDITIONAL 指标 |
|---|---|
| 容量/机制（2） | SLO Goodput、Cache 命中率 |
| 硬件效率（3） | HBM 峰值、NPU 平均利用率、MFU |
| 备选财务口径（1） | 会计毛利率口径报价 |
| 稳定性与能耗（3） | 三轮变异系数、平均功耗、每百万 token 能耗 |
| 多租户诊断（1） | Jain 公平指数 |

详细采集日志可以继续保存 send lag、ITL、队列、错误分类、硬件时间序列等底层
字段，但它们不是大矩阵中的独立必交行。每个矩阵结果字段必须带
`metric_tier=REQUIRED|ADDITIONAL`；条件必交字段另带
`applicability=APPLICABLE|NOT_APPLICABLE` 和理由。不能在看到 B0/B1 结果后修改档位。

## 1. 符号、样本与统计规则

对一个 lifecycle 的正式测量窗口定义：

| 符号 | 含义 | 单位 |
|---|---|---|
| `N_plan` | arrival 文件中计划请求数 | request |
| `N_sent` | 实际发送请求数 | request |
| `N_done` | 收到终止事件的请求数 | request |
| `N_ok` | 满足完整成功定义的请求数 | request |
| `N_slo` | 成功且满足该场景全部 SLO 的请求数 | request |
| `I_i`、`O_i` |请求 `i` 的实际 prompt/completion token 数 | token |
| `t_nom,i` | arrival 文件中的计划发送时刻 | s |
| `t_send,i` | 客户端实际开始发送时刻 | s |
| `t_first,i` | 收到首个有效输出 token 的时刻 | s |
| `t_last,i` | 收到最后一个输出 token 的时刻 | s |
| `t_end,i` | 收到 `[DONE]` 或协议终止事件的时刻 | s |
| `T` | 从首个实际发送到最后一个计划请求终止/超时的墙钟测量时间 | s |

成功请求必须同时满足：HTTP 200、流内无 error、至少一个有效输出、收到协议终止事件、最终 usage 完整、没有静默截断。超时、空响应、解析失败、OOM、取消及连接错误均不计入 `N_ok`，但保留在 `N_plan` 和质量分母中。

统计规则：

1. 每个 lifecycle 先独立计算指标，三轮结果取数值中位数：`x_role = median(x_1,x_2,x_3)`。
2. 分位数使用 nearest-rank：升序样本 `x_(1)…x_(n)` 的 `p` 分位为 `Q_p=x_(ceil(pn))`。
3. mean、p50、p95、p99 同时报；样本不足时仍按实际分母报告，并显示 `n`。
4. 验收使用未舍入值，展示值不反向参与判定。
5. 不把 commissioning、warmup、replacement 或历史探索结果放进正式中位数。

## 2. 所有 A1—A4 共用的服务指标

### 2.1 吞吐、完成率与 Goodput

| 指标 | 公式 | 单位/方向 |
|---|---|---|
| 请求吞吐 | `Q_req=N_ok/T` | request/s，越高越好 |
| 输出 token 吞吐 | `Q_out=(Σ_{i∈ok} O_i)/T` | output token/s，越高越好 |
| 输入 token 吞吐 | `Q_in=(Σ_{i∈ok} I_i)/T` | input token/s，越高越好 |
| 总 token 吞吐 | `Q_total=(Σ_{i∈ok}(I_i+O_i))/T` | total token/s，越高越好 |
| Offered load | `Q_offer=N_plan/T_schedule` | request/s，仅描述施加负载 |
| 发送完成率 | `R_sent=N_sent/N_plan` | 比例，越高越好 |
| 完成率 | `R_done=N_done/N_plan` | 比例，越高越好 |
| 成功率 | `R_success=N_ok/N_plan` | 比例，越高越好 |
| 错误率 | `R_error=(N_plan-N_ok)/N_plan=1-R_success` | 比例，越低越好 |
| 拒绝率 | `R_reject=N_rejected/N_plan` | 比例，越低越好 |
| SLO Goodput | `G_slo=N_slo/T` | compliant request/s，越高越好 |
| SLO 达标率 | `R_slo=N_slo/N_plan` | 比例，越高越好 |
| 瞬时输出峰值 | `Q_out,peak=max_b(tokens_completed_in_bucket_b/Δt)` | output token/s；固定 `Δt=1s` 并冻结桶边界 |

`Q_out`、`Q_in`、`Q_total` 和 `Q_req` 必须分栏，不允许通过字段 fallback 合并成一个“TPS”。自然 EOS 导致 B0/B1 输出数不同的场景，同时以 `Q_req` 和完成 token 分布交叉解释。

### 2.2 时延

对每个成功请求 `i`：

| 指标 | 公式 | 单位/方向 |
|---|---|---|
| 客户端排队/send lag | `L_send,i=t_send,i-t_nom,i` | ms，越低越好 |
| TTFT | `L_TTFT,i=t_first,i-t_send,i` | ms，越低越好 |
| E2E latency | `L_E2E,i=t_end,i-t_send,i` | ms，越低越好 |
| TPOT | `L_TPOT,i=(t_last,i-t_first,i)/(O_i-1)`，仅 `O_i≥2` | ms/output-token，越低越好 |
| 第 `j` 个 ITL | `L_ITL,i,j=t_token(i,j)-t_token(i,j-1)` | ms，越低越好 |
| 输出生成速率 | `S_decode,i=(O_i-1)/(t_last,i-t_first,i)=1/L_TPOT,i` | output token/s/request，越高越好 |

TTFT 从“实际发送时刻”计算；`send lag` 单列，不能混入服务 TTFT。TPOT 先按请求计算，再对请求取 mean/分位数；ITL 另外报告所有 token 间隔的全局分布，不与 TPOT 混称。

### 2.3 容量与排队

- 最大合规容量：`C_max=max{λ_k | 该冻结 rate 点满足成功率、TTFT、TPOT、Goodput 和稳定性全部门槛}`，单位 request/s。
- 并发平均值：`C_avg=(1/T)∫_0^T C(t)dt`。
- 并发峰值：`C_peak=max_t C(t)`。
- 平均队列深度：`W_avg=(1/T)∫_0^T W(t)dt`。
- 饱和率：`R_sat=(处于 waiting>0 或达到并发上限的时间)/T`。
- Little 定律交叉校验：稳定区间应近似满足 `C_avg≈Q_req×mean(L_E2E)`。

### 2.4 生命周期波动与置信区间

- 三轮极差：`range(x)=max(x_1,x_2,x_3)-min(x_1,x_2,x_3)`。
- 变异系数：`CV=s/mean(x)`，其中 `s=sqrt(Σ(x_j-x̄)^2/(n-1))`。
- 中位数绝对偏差：`MAD=median(|x_j-median(x)|)`。
- 单 lifecycle 请求分布标准差：`s=sqrt(Σ(x_i-x̄)^2/(n-1))`；必须与三轮 lifecycle 波动分开命名。
- 二项比例 `p̂=k/n` 的 Wilson 95% 区间：

  `center=(p̂+z²/(2n))/(1+z²/n)`

  `half=z/(1+z²/n)×sqrt(p̂(1-p̂)/n+z²/(4n²))`

  其中 `z=1.96`，区间为 `[center-half, center+half]`。

## 3. B0/B1 比较和总体聚合

三轮中位数计算完成后再比较。

| 类型 | 公式 | 解释 |
|---|---|---|
| 越高越好指标比值 | `R_x=x_B1/x_B0` | `>1` 表示 B1 更好 |
| 越高越好提升率 | `Δ_x=(x_B1/x_B0-1)×100%` | 正数为提升 |
| 越低越好指标比值 | `R_L=L_B1/L_B0` | `<1` 表示 B1 更好 |
| 时延改善率 | `Δ_L=(1-L_B1/L_B0)×100%` | 正数为改善 |
| 成功率/正确率百分点差 | `Δ_pp=100×(p_B1-p_B0)` | 单位百分点，不是相对百分比 |

跨 `K` 个性能场景的吞吐几何平均比：

`GM=exp((1/K)Σ_{k=1..K} ln(Q_out,B1,k/Q_out,B0,k))`

只有预声明的 `K` 项均具备有效 B0/B1 三轮中位数时才计算；缺失项不能从分母删除。不同数据集的绝对 token/s 不做算术平均。

## 4. A1：有效计算、固定形状与基础开销

### 4.1 有效 FLOPs 与 MFU

每个 A1 形状生成不可变 `effective_compute_spec`。算子 FLOPs 使用以下合同累加：

- GEMM/线性层 `M×K` 乘 `K×N`：`F_gemm=2MKN`；
- attention 的 `QKᵀ` 与 `PV`：分别 `2BH L_q L_k d`，合计 `F_attn=4BH L_q L_k d`；
- 其他归一化、激活、rope、softmax 等是否计入必须在 spec 中逐项声明，B0/B1 使用同一口径；
- 总有效计算：`F_eff=Σ F_op`；不得用实测性能反推 FLOPs。

便于容量估算的近似式 `F≈2P_active×N_token` 只能标为 approximation，不能替代逐算子 spec 或 profiler 校准。

| 指标 | 公式 |
|---|---|
| 有效计算吞吐 | `TFLOPS_eff=F_eff/(T×10^12)` |
| 实测算子计算吞吐 | `TFLOPS_prof=F_msprof/(T×10^12)` |
| FLOPs 校准偏差 | `E_flops=|F_eff-F_msprof|/F_msprof×100%` |
| MFU | `MFU=TFLOPS_eff/TFLOPS_peak` |

`TFLOPS_peak` 取同一 910B2 独占设备三次 `ascend-dmi` 的中位数。A1 另报主形状 4096×8 和全部辅助形状的 wall latency、samples/s、input/output/total tokens/s、HBM 峰值、功耗与温度；辅助形状不替换主形状结论。

### 4.2 启动与图编译

- 容器启动时间：`L_container=t_process_start-t_container_create`。
- 服务就绪时间：`L_ready=t_first_healthy-t_process_start`。
- 权重加载时间、compile 时间、graph capture 时间由结构化日志边界相减。
- 首次/第二次请求暖机差：`Δ_warm=(L_first-L_second)/L_first×100%`。
- 捕图数量、capture size 覆盖率、测量期新增捕图数、eager fallback 次数按计数报告；要求为零的场景不能只看启动参数。

## 5. A2：业务功能、质量与在线服务

所有 A2 数据集都报告第 2 节通用指标，并按数据集适用的 oracle 报告以下质量指标。质量分母固定为全部计划样本，超时、空响应、协议错误和 oracle 解析失败均计错。

### 5.1 对话与多轮

- 协议成功率：`N_protocol_ok/N_plan`。
- 有效非空回复率：`N_nonempty/N_plan`。
- 角色顺序正确率：`N_role_order_ok/N_plan`。
- 多轮连续性率：`N_continuity_ok/N_session`。
- 完整会话成功率：`N_all_turns_ok/N_session`。
- usage 一致率：`N_usage_match/N_plan`，其中客户端 tokenizer 复算值与服务 usage 的容许规则必须预冻结。
- EOS/stop reason 分布：各原因计数除以 `N_plan`；异常结束单列。

UltraChat、ShareGPT、OASST、LMSYS、WildChat 及企业 normal-chat 均分别给出上述分子/分母，不能合并成一个对话分数。

### 5.2 Tool Calling 与 Agent

- 工具调用触发率：`N_has_tool_call/N_applicable`。
- 函数名正确率：`N_function_name_correct/N_applicable`。
- 参数合法 JSON 率：`N_args_json_valid/N_applicable`。
- 参数 schema 合规率：`N_args_schema_valid/N_applicable`。
- 完整 tool-call 正确率：`N_exact_tool_call_correct/N_applicable`。
- BFCL 分类准确率：`Acc_c=N_correct,c/N_c`；总体准确率 `Acc=ΣN_correct,c/ΣN_c`，同时报告 macro average `mean_c(Acc_c)`。
- parallel/multiple 集合匹配采用冻结 oracle；调用数量、函数集合和每个参数均正确才算该 case 正确。
- Agent turn 成功率：`N_turn_ok/N_turn`。
- Agent session 完成率：`N_all_required_turns_and_state_ok/N_session`。
- 状态连续性率：`N_state_transition_valid/N_transition`。
- 工具错误恢复率：`N_recovered/N_injected_or_observed_tool_error`。
- 任务完成率：`N_final_goal_satisfied/N_task`。

BFCL、tau2、ToolBench、EvoScientist、SyFi 和 HotpotQA/ReAct 必须使用各自冻结 oracle，不能用“有 JSON 输出”代替任务正确。

### 5.3 推理

- Exact Match：`EM=N_normalized_exact/N_plan`。
- 数值答案准确率：`Acc_num=N_extracted_equal_gold/N_plan`；抽取失败计错。
- 多选准确率：`Acc_mcq=N_choice_equal_gold/N_plan`。
- F1：对单样本 `F1_i=2P_iR_i/(P_i+R_i)`，数据集分数为 `mean_i(F1_i)`；`P_i+R_i=0` 时按冻结官方规则处理。
- GSM8K、MATH、GPQA、BBH、MMLU-Pro、ARC、AIME、HotpotQA 和 LongBench-v2 分别使用官方任务 scorer，并报告原始分子/分母。

### 5.4 结构化输出

- JSON parse rate：`R_parse=N_json_parse_ok/N_plan`。
- Schema conformance：`R_schema=N_schema_valid/N_plan`。
- 必填字段完整率：`R_required=Σ present_required_fields/Σ required_fields`。
- 字段值正确率：`R_value=N_fields_value_correct/N_fields_scored`。
- 严格 case 成功率：`R_strict=N_parse_and_schema_and_value_ok/N_plan`。
- 额外属性违规率：`R_extra=N_cases_with_forbidden_extra/N_plan`。

SchemaStore、JSONSchemaBench、StructEval、BFCL 参数 JSON 和企业 JSON 数据分别报告；schema dialect、外部 `$ref` 解析和 whitespace 规则须冻结。

### 5.5 代码

- compile rate：`N_compile_ok/N_plan`。
- execution pass rate：`N_all_tests_pass/N_plan`。
- 单测通过率：`Σ passed_tests/Σ total_tests`。
- deterministic `pass@1=N_pass/N_problem`。
- 存在每题 `n` 个候选、其中 `c` 个正确时：`pass@k=1-C(n-c,k)/C(n,k)`；若 `n-c<k` 则为 1。
- LiveCodeBench、HumanEval、MBPP、InstructCoder 及 SyFi 分别报告 compile error、runtime error、timeout、wrong answer 和 pass。

### 5.6 长上下文质量与截断

- 上下文接收率：`R_context=N_prompt_tokens_match/N_plan`。
- 静默截断率：`R_trunc=N_silent_truncation/N_plan`，正式要求为 0。
- canary 保留率：`R_canary=N_tail_canary_verified/N_canary_cases`。
- 长文本任务得分：先按数据集官方 scorer 逐任务计算，再报告 macro average；不得把不同 scorer 的原始分数直接相加。
- 长度桶分别报告：`<8K`、`8–16K`、`16–32K`、超过模型上限；不支持项记 `UNSUPPORTED_CONTEXT_LENGTH` 并保留在完成率分母。

## 6. A3：KV Cache、长上下文与稳定性

### 6.1 HBM 与 KV Cache

| 指标 | 公式 |
|---|---|
| HBM 使用率 | `U_HBM(t)=HBM_used(t)/HBM_total` |
| HBM 峰值 | `HBM_peak=max_t HBM_used(t)` |
| 可用 KV 内存 | `KV_available_bytes(t)`，报告测量前、峰值压力时和测量后的值 |
| KV 使用率 | `U_KV(t)=KV_blocks_used(t)/KV_blocks_total` |
| KV 峰值 | `U_KV,peak=max_t U_KV(t)` |
| KV block 分配成功率 | `N_block_alloc_ok/N_block_alloc_request` |
| KV 驱逐率 | `N_evicted_blocks/N_allocated_blocks` |
| 抢占率 | `N_preempted_requests/N_sent` |
| 恢复成功率 | `N_resume_ok/N_preempted_requests` |

KV 指标同时报告 block 数和折算 token 数；不同 block size 的百分比不能直接横比。

### 6.2 Prefix Cache

- block 查询命中率：`H_block=N_hit_blocks/N_queried_blocks`。
- token 加权命中率：`H_token=N_reused_prefix_tokens/N_cache_eligible_prefix_tokens`。
- 请求命中率：`H_req=N_requests_with_any_hit/N_cache_eligible_requests`。
- 实际复用 token 比例：`R_reuse=N_reused_tokens/ΣI_i`。
- Prefill 节省率：`R_prefill_saved=1-prefill_tokens_computed_with_cache/prefill_tokens_required_without_cache`。
- 误复用率：`R_false_reuse=N_reuse_events_failing_identity_or_oracle/N_reuse_events`，exact-prefix cache 正式要求为 0。
- 分层收益：对冻结的 high/medium/low reuse 或 similarity bucket 分别计算吞吐、TTFT、命中率和质量，不按结果重新划桶。

必须注明指标来自 block、token 还是 request；不能只写“cache hit rate”。

### 6.3 KV 传输、卸载与通信

- KV 传输延迟：`L_kv=t_transfer_end-t_transfer_start`。
- 有效带宽：`BW_kv=bytes_transferred/L_kv`。
- 迁移中断时间：从请求停止产生 token 到恢复产生 token 的时间。
- 传输成功率：`N_transfer_ok/N_transfer_attempt`。
- 多卡 speedup：`S_n=Q_n/Q_1`。
- 扩展效率：`E_n=Q_n/(nQ_1)=S_n/n`。
- 通信占比：`R_comm=T_communication/T_measurement`。

### 6.4 长稳与故障

- OOM、服务崩溃、死锁、健康检查失败、超时、静默截断分别报告事件数和受影响请求率。
- HBM 增长斜率：对稳定测量段拟合 `HBM(t)=a+bt`，报告 `b`（MiB/hour）。
- 吞吐衰减：`D_Q=(Q_first_window-Q_last_window)/Q_first_window×100%`。
- 时延恶化：`D_L=(L_last_window/L_first_window-1)×100%`。
- 无故障运行时间：`MTTF=总运行时间/不可恢复故障数`；没有故障时只报告“右删失 ≥ 实际时长”，不伪造无限值。
- 恢复时间：`MTTR=Σ recovery_duration/N_recoverable_failure`。

## 7. A4：多租户混合调度

对每个 tenant、角色和源数据集分别计算第 2、5、6 节指标，并增加：

- tenant 吞吐份额：`share_j=Q_req,j/ΣQ_req,k`。
- tenant SLO 达标率：`R_slo,j=N_slo,j/N_plan,j`。
- Jain 公平指数：`J=(Σx_j)^2/(mΣx_j^2)`，`x_j` 使用预冻结的归一化 tenant goodput；范围 `(0,1]`，越高越公平。
- 混跑吞吐损失：`D_mix,j=1-Q_mixed,j/Q_isolated,j`。
- 混跑时延膨胀：`I_mix,j=L_mixed,j/L_isolated,j-1`。
- 最差 tenant SLO：`min_j R_slo,j`。
- starvation rate：`N_wait_exceeds_threshold/N_plan`，threshold 在测试前冻结。
- 路由命中率：`N_routed_to_intended_worker/N_routed`。
- session affinity：`N_session_turns_on_affine_worker/N_session_turns_after_first`。
- 跨 tenant 状态串扰：事件数，正式要求为 0。

专用单租户参考测试必须与混跑使用同一请求、服务配置和资源份额，否则 `D_mix`/`I_mix` 只作描述性数据，不进入验收。

## 8. 专项优化路径指标

### 8.1 Logprobs

- token logprob 误差：`E_logp=|logp_B1-logp_reference|`，报告 mean/max/p99。
- top-k token 集合一致率：`|TopK_result∩TopK_reference|/k`。
- top-k 排名完全一致率：`N_exact_rank_match/N_scored_position`。
- logprobs 吞吐开销：`Overhead_Q=1-Q_logprobs/Q_no_logprobs`。
- logprobs 时延开销：`Overhead_L=L_logprobs/L_no_logprobs-1`。

参考输出、容许误差、dtype 和 tokenizer 必须冻结；性能对照必须保持除 logprobs 开关外其余配置一致。

### 8.2 Speculative decoding

- draft 接受率：`R_accept=N_accepted_draft_tokens/N_proposed_draft_tokens`。
- 每 target step 平均接受长度：`L_accept=N_accepted_draft_tokens/N_target_verification_steps`。
- target 调用节省率：`R_target_saved=1-N_target_steps_spec/N_target_steps_without_spec`。
- speculative speedup：`S_spec=Q_out,spec/Q_out,non-spec`。
- 质量一致率：`N_outputs_meeting_frozen_equivalence/N_plan`；不得只报接受率而不报最终质量。

### 8.3 模型/KV 压缩

- 权重压缩比：`R_size=bytes_compressed/bytes_original`。
- 权重节省率：`Saving_size=1-R_size`。
- HBM 节省率：`Saving_HBM=1-HBM_peak,compressed/HBM_peak,original`。
- Perplexity：`PPL=exp(-(1/N)Σ_t log p(x_t|x_<t))`。
- PPL 相对变化：`Δ_PPL=PPL_compressed/PPL_original-1`。
- 任务质量变化仍使用第 5 节正确率百分点差；SliceGPT、W8A8 或 KV compression 的性能收益不能掩盖质量回退。

### 8.4 Scheduler、batch 与 preemption

- 平均实际 batch：`B_avg=Σ_step batch_size_step/N_scheduler_step`。
- batch 利用率：`U_batch=B_avg/max_num_seqs`。
- batch size 直方图：各 batch size 的 scheduler step 数/总 step 数。
- 排队请求比例：`N_requests_ever_waiting/N_sent`。
- preemption、resume、eviction 指标沿用第 6 节；同时报告默认策略回退次数和目标策略实际命中次数。

### 8.5 RAG、memory 与异步 workflow

- 检索命中率：`N_gold_evidence_retrieved/N_gold_evidence`。
- 答案证据支持率：`N_answers_supported_by_retrieved_context/N_answered`。
- 语料新鲜度正确率：`N_answers_using_required_corpus_epoch/N_epoch_sensitive_cases`。
- memory 写入成功率：`N_memory_write_ok/N_memory_write`。
- memory 复用准确率：`N_correct_memory_recall/N_memory_recall`。
- pipeline stage 成功率：`Σ completed_required_stages/Σ required_stages`。
- 端到端 workflow 成功率：`N_all_stages_and_final_oracle_ok/N_workflow`。

`realtime-voice-assistant token-budget proxy` 只报告文本 token 服务指标和 workflow 完成率，不报告音频首包、实时因子、MOS 或语音质量，除非另有真实音频 transport 和 oracle。

### 8.6 MoE、EPLB 与 All-to-All

- expert token load `l_e`；load CV：`CV_expert=std(l_e)/mean(l_e)`。
- expert 最大不均衡：`I_expert=max(l_e)/mean(l_e)`，理想值为 1。
- 空闲 expert 比例：`N_expert_with_zero_tokens/N_expert`。
- rebalance 有效迁移率：`N_migrations_reducing_declared_imbalance/N_migrations`。
- rebalance 开销：`T_rebalance/T_measurement`。
- All-to-All 有效带宽：`BW_a2a=total_payload_bytes/T_a2a`。
- 通信计算重叠率：`R_overlap=T_comm_hidden_by_compute/T_comm`。
- EPLB/MoE 项只有在模型和硬件实际适用时计算；单卡稠密模型记 `HARDWARE_OR_MODEL_NOT_APPLICABLE`，不能填 0 冒充测量值。

## 9. NPU、能耗与资源效率

### 9.1 技术利用率

- NPU 平均利用率：`U_NPU=(1/T)∫U_NPU(t)dt`。
- NPU p95/峰值：对固定采样间隔的监控样本取 p95/max。
- HBM 带宽利用率：`U_BW=BW_measured/BW_peak`，仅在 profiler 有可复算字节数时报告。
- 平均功耗：`P_avg=(1/T)∫P(t)dt`。
- 能耗：`E=∫P(t)dt`，换算 `kWh=J/3.6×10^6`。
- 每百万 token 能耗：`E_1M=E/(N_token/10^6)`。
- 能效：`Eff_token=processed_tokens/E`，单位 token/J。

这里的 `U_NPU` 是正式测量窗口内的技术指标，不等同于第 10 节商业“峰值填平率”。

## 10. 910B 百万 token 极限成本与报价模型

### 10.1 极限跑满成本

单一 910B 资源、不混跑时定义：

| 符号 | 含义 |
|---|---|
| `H` | 该测试资源完整小时成本，货币/NPU-hour；口径可含 910B 租赁或折旧、电力、配套主机及网络，但组成必须声明 |
| `Q_raw` | 对应冻结 workload 的极限跑满 token 吞吐，不要求满足线上 SLO，token/s |
| `Q_slo` | 同 workload 最高完整 SLO 合规点的 token 吞吐，token/s |
| `C_limit` | 满载时每百万 token 极限成本，货币/1M token |

公式：

技术极限成本下界：

`C_raw_limit=H×10^6/(3600Q_raw)`

可用于正式业务报价的 SLO 合规满载成本：

`C_slo_limit=H×10^6/(3600Q_slo)`

若后文简称 `C_limit`，报价默认指 `C_slo_limit`；`C_raw_limit` 只作为极限能力和成本下界展示。

小时成本建议按不重叠科目形成：

`H=H_depreciation_or_lease+H_power+H_host_share+H_network_share+H_software+H_other`

其中：

- 自有设备折旧：`H_depreciation=(CAPEX-residual_value)/economic_life_hours`；租赁设备直接使用合同小时价，二者不能重复计入；
- 电力：`H_power=P_avg(kW)×PUE×electricity_price_per_kWh`；若租赁单价已含电力则不再加入；
- 主机、网络和软件按该 910B 实际占用份额分摊，分摊规则随报价版本冻结。

必须分别计算：

- 输入百万 token 成本：`C_in=H×10^6/(3600Q_in,limit)`；
- 输出百万 token 成本：`C_out=H×10^6/(3600Q_out,limit)`；
- 固定业务 mix 总 token 成本：`C_total=H×10^6/(3600Q_total,limit)`。

这里的 `limit` 必须注明采用 raw 还是 SLO 口径；正式报价默认采用 SLO。三者不能混称。`C_in` 与 `C_out` 是同一固定业务 mix 下分别观察的等效单位成本，不能相加，否则会重复计算小时成本。若要分别制定输入价 `P_in` 和输出价 `P_out`，至少应满足该 mix 的收入覆盖式：

`P_in×N_in/10^6+P_out×N_out/10^6≥目标总收入`

输入/输出成本分摊权重必须另行冻结。若使用 `n` 张卡或包含主机固定成本，则 `H=ΣH_NPU+H_host+H_network+H_power`，吞吐使用同一整套资源的对应 `Q_limit`。

### 10.2 峰值填平率

商业峰值填平率记为 `φ`：

`φ=计费周期内实际承载的等效 token 容量/同周期按合规饱和吞吐可提供的 token 容量`

取值范围 `(0,1]`。业内参考 50%–70%、默认建议 60% 可作为报价假设，但不得声称它是一次满载 benchmark 测得的 NPU 利用率。填平后的单位成本：

`C_filled=C_limit/φ`

例如默认 `φ=0.60` 时，`C_filled=C_limit/0.60`。

### 10.3 云服务附加运营成本

令云服务附加运营费率为 `c_cloud`，建议范围 `0.05–0.08`。对应倍率为：

`K_cloud=1+c_cloud=1.05–1.08`

运营成本后的成本基数：

`C_operated=(C_limit/φ)×K_cloud=(C_limit/φ)×(1+c_cloud)`

因此你给出的“乘以云服务成本”公式中，`云服务成本` 应填倍率 `1.05–1.08`，不能直接填 `0.05–0.08`。

### 10.4 利润口径与最终报价

存在两种不同定义，报价单必须二选一并写明：

1. 按你给定公式，把 `r_markup` 定义成成本加价率：

   `Price_1M=(C_limit/φ)×K_cloud×(1+r_markup)`

2. 若 `m_gross` 是严格会计目标毛利率，定义为 `(Price-Cost)/Price`：

   `Price_1M=(C_limit/φ)×K_cloud/(1-m_gross)`

`(1+r_markup)` 与 `1/(1-m_gross)` 不相等。例如 20% 加价率对应毛利率 `20%/120%=16.67%`；目标毛利率 20% 则需成本乘 `1/0.8=1.25`。

采用常用假设 `φ=0.60`、`c_cloud=0.06` 时：

- 加价率口径：`Price_1M=C_limit/0.60×1.06×(1+r_markup)`；
- 会计毛利率口径：`Price_1M=C_limit/0.60×1.06/(1-m_gross)`。

税费、渠道折扣、承诺用量折扣、退款准备金和币种汇率若未纳入 `H`、`c_cloud` 或利润参数，必须在报价外单列，不能隐含。

### 10.5 B0/B1 成本收益

同资源小时成本、填平率、云运营倍率和利润参数相同时：

- 极限成本比：`C_limit,B1/C_limit,B0=Q_limit,B0/Q_limit,B1`；
- 单位成本下降：`Saving_cost=(1-C_limit,B1/C_limit,B0)×100%`；
- 报价保持不变时的单位毛利增量必须基于实际成本重新计算，不能直接等同吞吐提升率。

若 B0/B1 资源小时成本不同：

`C_limit,B1/C_limit,B0=(H_B1/H_B0)×(Q_limit,B0/Q_limit,B1)`

价格模型必须绑定具体 workload mix、精度、模型、卡数、成功率和 SLO 合规饱和点。不能拿 random synthetic 的最高 token/s 给长上下文、Agent 或结构化输出直接定价。

## 11. V5.4 SLO 与验收指标

V5.4 的必须交付 16 位基线固定为 BF16（`bfloat16`），A3 数值为固定验收合同，不再从 B0 Prefill 吞吐动态生成。其余负载的数值仅在对应签名 config 中冻结后生效；任何字段均不得在看到结果后调整。

### 11.1 绝对 SLO

对话、Tool/Agent、推理、结构化和代码在线负载：

- TTFT mean/p95/p99：不高于 `1000/2000/4000 ms`；
- TPOT mean/p95/p99：不高于 `40/60/80 ms/token`。

长上下文：

- 8192 输入 TTFT mean/p95/p99：不高于 `8/12/16 s`；
- 16384 输入 TTFT mean/p95/p99：不高于 `16/24/32 s`；
- TPOT mean/p95/p99：不高于 `40/60/80 ms/token`。

A3 30720-token 输入、2048-token 输出、30 分钟测量区间固定为：

- TTFT mean/p95/p99：不高于 `30/45/60 s`；
- TPOT mean/p95/p99：不高于 `40/60/80 ms/token`；
- B0 的 30720-token Prefill throughput 只保存为诊断项，不得生成、放宽或改变验收阈值。

A4 单位 token 成本固定按“完整生命周期成本 / 30 分钟测量区间内满足冻结 SLO 的成功输出 token”计算；生命周期从服务启动计至服务停止，不能只截取稳态窗口作为成本分子。

所有 rate 点：`N_done≥0.99N_plan`；总样本小于 1000 时要求 0 失败，达到 1000 时错误率不高于 0.1%。最大合规容量严格使用第 2.3 节公式，不插值、不外推。

### 11.2 A1 与 B0/B1 总门禁

- A1 主形状 `MFU≥90%`，且 `E_flops≤3%`；
- 性能项吞吐比几何平均 `GM≥1.05`；
- 任一性能项 `Q_out,B1/Q_out,B0≥0.90`；
- 至少两项 `Q_out,B1/Q_out,B0≥1.10`；
- 每项 B1 成功率相对 B0 下降不超过 `1.00 pp`；
- 每项适用质量正确率相对 B0 下降不超过 `1.00 pp`；
- 长上下文/KV 压力：0 OOM、0 静默截断、0 服务崩溃或死锁；
- TTFT、TPOT、吞吐分别判读，不要求三者同时改善。

## 12. 按 A1—A4 的 REQUIRED 必报指标表

| 场景 | 必报主指标 | 必报护栏/诊断指标 |
|---|---|---|
| A1 固定形状 | `TFLOPS_eff`、MFU、主形状 latency、input/output/total tokens/s | profiler FLOPs 偏差、HBM、NPU 利用率、功耗、启动/捕图、辅助形状 |
| A2 对话 | 三种 token 吞吐、request/s、TTFT/TPOT/ITL/E2E、成功率 | 角色顺序、多轮连续性、usage、stop reason、SLO Goodput |
| A2 Tool/Agent | 同上 | 函数名、参数 JSON/schema、BFCL 分类准确率、任务/会话/状态完成率 |
| A2 推理 | 同上 | EM、数值/多选准确率、F1、抽取失败、官方 scorer |
| A2 Structured | 同上 | parse、schema conformance、字段完整/正确、额外属性违规 |
| A2 Code | 同上 | compile、execution、unit-test pass、pass@1/pass@k、错误分类 |
| A2 多模态 | 同上，前提是双方支持相同模态 | 图像可访问率、协议成功率和对应官方任务得分；当前文本模型为不适用 |
| A3 长上下文/KV | 三种吞吐、TTFT/TPOT、成功率、长度桶 | HBM/KV 峰值、cache、驱逐、抢占、OOM、截断、canary、长稳衰减 |
| A4 多租户 | 每 tenant 吞吐、Goodput、TTFT/TPOT、成功率 | Jain、公平性、混跑损失、SLO 最差租户、starvation、affinity、串扰 |
| 商业定价 | `C_in`、`C_out`、`C_total`、`Price_1M` | `H` 组成、`φ`、`c_cloud/K_cloud`、利润定义、SLO 与业务 mix |

## 13. 最低逐请求与聚合字段

逐请求必须保存：`dataset_id`、`case_id`、`session_id/turn_id`、`tenant_id`、计划/实际发送时间、首/末 token 和结束时间、输入/输出 token、HTTP/stream 状态、usage、stop reason、TTFT、TPOT、E2E、send lag、oracle 结果、错误分类、OOM/截断标记。

每 lifecycle 必须保存：三种 token 吞吐、request/s、Goodput、mean/p50/p95/p99 TTFT/TPOT/ITL/E2E/send-lag、成功/错误分子分母、质量分子分母、HBM/KV/NPU/功耗时间序列摘要、配置和请求 hash。

最终报告必须保存全部适用的 `REQUIRED` 字段、三轮原值与中位数、完整分子分母、配置/请求哈希和价格模型版本。`ADDITIONAL` 字段取得后同样保留，但不因其优劣改变硬门槛。私密价格数值可进入单独受限附件，公开报告必须保留非敏感公式、单位和所采用的利润定义。
