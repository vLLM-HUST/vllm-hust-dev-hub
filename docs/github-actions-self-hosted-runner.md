# GitHub Actions Self-Hosted Runner

本文档说明如何在 Linux 开发机上，把 GitHub Actions self-hosted runner 以用户态服务方式部署起来。

推荐使用仓库内脚本 [scripts/setup-github-actions-runner.sh](../scripts/setup-github-actions-runner.sh)，而不是手工逐条敲 GitHub 页面上的命令。这样更容易重复执行，也不会把一次性 token 硬编码到仓库文件里。

## 适用场景

- 给整个组织配置 runner，例如 `https://github.com/intellistream`
- 给单个仓库配置 runner，例如 `https://github.com/intellistream/<repo>`
- 希望 runner 作为当前用户的 `systemd --user` 服务运行，不依赖 root

## 前提条件

- Linux 主机
- 当前用户可以访问 GitHub
- 系统里有 `bash`、`tar`，以及 `curl` 或 `wget`
- 从 GitHub 页面生成一枚临时 runner token

如果会话中可以使用 `systemctl --user`，脚本会自动把 runner 注册成用户服务。

如果当前会话拿不到用户态 `systemd`，脚本会自动退回到 `nohup` 后台模式，依然可以把 runner 拉起来。

脚本默认会在启动 runner 时清空当前 shell 里的代理环境变量，避免把本地开发代理错误继承给 GitHub Actions runner。如果你的宿主机必须通过代理访问 GitHub，可显式设置：

```bash
export GITHUB_RUNNER_PRESERVE_PROXY=1
```

如果希望在 SSH 退出后 runner 仍然保持运行，通常还需要宿主机执行一次：

```bash
sudo loginctl enable-linger $USER
```

## 一键安装

在仓库根目录执行：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
export GITHUB_RUNNER_URL=https://github.com/intellistream
export GITHUB_RUNNER_TOKEN=<temporary-registration-token>
bash scripts/setup-github-actions-runner.sh install --labels train8,ascend
```

说明：

- `GITHUB_RUNNER_URL` 可以是组织 URL，也可以是具体仓库 URL
- `GITHUB_RUNNER_TOKEN` 必须使用 GitHub 页面当前生成的临时 token
- `--labels` 是附加标签，建议写上机器名、硬件类型或用途

默认行为：

- runner 安装目录：`~/.local/share/github-actions-runner`
- runner 名称：当前主机 hostname
- runner group：`Default`
- work 目录：`_work`
- 服务名：`github-actions-runner`

## 常用命令

查看状态：

```bash
bash scripts/setup-github-actions-runner.sh status
```

启动服务：

```bash
bash scripts/setup-github-actions-runner.sh start
```

停止服务：

```bash
bash scripts/setup-github-actions-runner.sh stop
```

重启服务：

```bash
bash scripts/setup-github-actions-runner.sh restart
```

## 自定义安装目录或 runner 名称

```bash
export GITHUB_RUNNER_URL=https://github.com/intellistream
export GITHUB_RUNNER_TOKEN=<temporary-registration-token>
bash scripts/setup-github-actions-runner.sh install \
  --runner-dir "$HOME/actions-runner-intellistream" \
  --name train8-runner-01 \
  --labels train8,ascend,910b
```

## Workflow 写法

如果安装时没有传 `--labels`，最简写法是：

```yaml
runs-on: [self-hosted, Linux, x64]
```

如果你的机器是 `arm64`，则改成：

```yaml
runs-on: [self-hosted, Linux, arm64]
```

如果你配置了附加标签，例如 `train8,ascend`，则推荐写成：

```yaml
runs-on: [self-hosted, Linux, x64, train8, ascend]
```

说明：GitHub 会自动给 runner 附加 `self-hosted`、操作系统和架构标签；你只需要额外补充业务标签。

## 卸载或注销 runner

GitHub 删除 runner 需要一枚新的 remove token，不是最初 install 时那枚 token。

示例：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
export GITHUB_RUNNER_TOKEN=<temporary-remove-token>
bash scripts/setup-github-actions-runner.sh remove
```

脚本会：

- 停掉并移除用户服务
- 调用 `config.sh remove` 向 GitHub 注销 runner
- 询问是否删除本地安装目录

## 常见问题

### 1. `systemd --user is not available in this session`

说明当前 shell 没有可用的用户态 systemd 会话。脚本会自动退回到后台模式；你仍然可以直接用下面的命令查看状态：

```bash
bash scripts/setup-github-actions-runner.sh status
```

如果你只是想临时前台调试 runner，也可以手工运行：

```bash
cd ~/.local/share/github-actions-runner
./run.sh
```

后续再切回支持 `systemctl --user` 的登录方式，重新执行安装命令即可。

### 2. 退出 SSH 后 runner 停了

优先检查是否已经执行：

```bash
sudo loginctl enable-linger $USER
```

### 3. 安装目录里已经有旧 runner

脚本默认会对同名 runner 传 `--replace` 重新注册；但如果目录不是标准 runner 目录，会直接拒绝覆盖，避免误删其他内容。

### 4. 页面给的是 `runs-on: self-hosted`，还要不要加别的标签

可以只写：

```yaml
runs-on: self-hosted
```

但只要组织里有多台 runner，最好显式加上 OS、架构和业务标签，否则很容易把任务调度到不合适的机器上。

### 5. runner 已注册，但日志里出现 SSL 或 TLS 错误

先检查当前 shell 是否注入了本地代理，例如 `http_proxy`、`https_proxy`、`all_proxy`。本仓库脚本默认会在启动 runner 时清空这些代理变量，因为很多开发机场景下代理只适合浏览器或终端，不适合 runner 长连接。

如果你的环境确实必须经过代理访问 GitHub，再显式设置：

```bash
export GITHUB_RUNNER_PRESERVE_PROXY=1
```