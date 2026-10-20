# 实验数据统一归档

数据集、实测结果、原始请求轨迹、计时、指标、实验日志和证据附件统一提交到
[vllm-hust-benchmark](https://github.com/vLLM-HUST/vllm-hust-benchmark)。
dev-hub、website 和 MOD 仓库保留实现代码、测试方法及固定版本的来源引用。
不得用其他仓库的 Release、PR 附件或压缩包绕过这一规则。

## 2026-10-20 迁移批次

以下目录的 358 个已提交文件已完成逐文件 SHA256 校验：

- `results/`
- `docs/evidence/`
- `Ascend-Machine/results/`
- `Ascend-Machine/910B2/results/`

[唯一来源索引](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/evidence-devhub-20261020-v1/archive/dev-hub-20261020/manifest.json)
保留原始仓库 commit、路径、字节数和 SHA256。15 个文件复用 benchmark 内已有的
固定 commit 文件；343 个文件原样保存在
[benchmark Release](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/tag/evidence-devhub-20261020-v1)。
归档已经远端回下载验证。

旧文档中的上述路径是归档成员名，不再是 dev-hub 工作树内的文件路径。
按索引中的 `path` 查找；`destination` 指明固定 commit 文件或 Release 内的成员。
失败尝试也保留，不因归档而变为正式测试结果，不跨实验拼接曲线。

SZYN 汇总工具仍接受显式的本地 `--qualification-root`。需要复核旧 qualification 时，
先用 `python3 scripts/fetch_benchmark_qualification.py /tmp/szyn-qualification`
从固定 benchmark commit 下载索引并校验归档及每个成员，再将该缓存目录传入工具。
不要把下载缓存重新提交到本仓库。相关集成测试现在走同一下载校验流程，需要网络访问。

## 提交流程

1. 在 benchmark 提交数据、配置、来源和校验清单；大附件放在该仓库 Release。
2. 验证远端内容与源文件一致，固定 commit 或归档版本。
3. 在 dev-hub 提交方法或引用更新，不携带第二份实验数据。

代码单元测试的人工合成 fixture 不是实测数据集，允许留在 `tests/fixtures/`，
但不得将真实实验记录改名为 fixture。CI 检查覆盖常见数据路径和后缀；
文档中夹带结果、任意改名的二进制仍须人工审查。

本批次不是全组织迁移完成声明。索引中的 `outside_scope_review` 路径及其他仓库
仍需逐项核对。已发布历史 commit 不改写。
