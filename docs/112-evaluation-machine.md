# 112 集中评测机

112 是项目的集中性能评测机，不再是 GitHub Actions self-hosted runner。普通 CI 只运行静态检查、单元测试、构建和评测请求合同校验；需要 NPU
的任务通过签名请求进入 112 队列，由本机服务统一分配设备、执行、留存证据并返回状态。

## 不变量

- CI workflow 中不得出现 `runs-on: self-hosted`。
- 请求必须绑定完整 Core/Plugin commit、target registry 版本、target id、卡数和重复数。
- 正式请求至少三次独立生命周期；失败 attempt 原样保留。
- 只有机器可读 target registry 中的目标可以执行；任意 shell、容器命令和模型路径不能由请求方注入。
- API 使用 Bearer token、五分钟时间窗 HMAC 和幂等键；服务端只接受仓库 allowlist。
- worker 使用每卡文件锁，并在分配前检查 NPU 进程。维护文件 `/data/vllm-hust-evaluation/state/MAINTENANCE` 会停止接收和调度新任务。
- artifact 写入独立 job 目录，包含 canonical request、runner log、worker identity 和 bundle SHA256。
- worker 封包后必须调用 benchmark 仓的独立 verifier；runner exit 0 仍是 `UNVERIFIED`， verifier 失败会令 API job
  失败，不能静默降级。
- 历史 Actions runner 目录不删除；凭据和服务被可恢复地禁用，并写入独占标记。

## 请求流程

1. GitHub-hosted CI 校验代码、spec、target version 和提交者权限。
1. 可复用 workflow `.github/workflows/evaluation-request.yml` 解析完整 commit SHA，生成签名请求。
1. API 以幂等方式写入 SQLite 队列。
1. worker 按 `release > required > normal > diagnostic` 调度，获取资源锁后启动官方 runner。
1. runner 解析 registry，不接受请求方命令；完成后生成 raw、日志、resolved spec、runtime/input provenance、repeat suite 和
   checksums。
1. verifier 重算 bundle 树哈希并核对 terminal job、schedule、三次重复和每份 artifact， 然后只在 state 目录写 bundle 外部
   attestation。
1. CI 轮询状态或接收后续回调；只有 API `succeeded` 且存在匹配 job ID 和 bundle SHA256 的 `VERIFIED` attestation 才可以进入
   leaderboard snapshot 和网站。

## 生产部署

`scripts/install-112-evaluation-machine.sh` 会先确认没有活跃 Actions runner，再禁用遗留
runner、安装服务和生成本地密钥。密钥文件不会打印到日志。反向代理必须启用 TLS，并限制 到 GitHub-hosted 出口或项目 VPN；生产 URL 与两个密钥配置为组织级 Actions
secrets。

worker 的 `runner_command` 必须指向 benchmark 仓提供的 fail-closed adapter。adapter 只接受
`EVALUATION_REQUEST_FILE`、`EVALUATION_ASSIGNED_NPUS` 和 `EVALUATION_OUTPUT_DIR`，并在启动前 复核 #218
snapshot 完整性、#220 target version、#247 scheduled spec/model 和 #221 runtime provenance 门禁。

`admission_command` 同样由管理员静态配置。worker 在命令尾部追加 `--bundle`、 `--job-record` 和
`--attestation`；请求方不能控制这些路径。verifier 先写 `attestation.json.pending`，worker 成功提交 terminal SQLite
状态后才原子改名为 `attestation.json`。bundle 在写入 `BUNDLE_SHA256` 后不再修改，验真日志、候选 job record 和 attestation 均保存在
`state/admission/<job-id>/`。缺少 attestation 必须按未验真处理， 即使 API 曾因进程崩溃留下 `succeeded` 状态也不例外。
