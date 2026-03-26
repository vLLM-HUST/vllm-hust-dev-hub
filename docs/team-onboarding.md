# vLLM-HUST 团队开发环境全流程说明

本文档用于发给团队成员，统一说明从 Docker instance 到源码环境的完整搭建流程。

适用场景：

- 需要在 Ascend 官方容器里开发或调试 `vllm-hust`
- 需要通过 SSH 直接连到容器里的开发环境
- 需要一键拉齐 `vllm-hust-dev-hub` 相关仓库并创建 `conda` 开发环境

## 结论先说

推荐主流程如下：

1. 在目标机器上准备或创建官方 Ascend Docker instance。
2. 如果需要从本地直接连进容器，在本地配置 `~/.ssh/config` 指向该 instance。
3. 在容器内或目标开发机上克隆 `vllm-hust-dev-hub`。
4. 执行 `bash scripts/quickstart.sh`，选择 `Setup user-space environment -> Full bootstrap (sync repos + conda env)`。
5. 如果需要启动 `vllm-hust-workstation`，复制 `.env.example` 为 `.env` 并填写实例地址。
6. 需要时执行 `conda activate vllm-hust-dev` 进入环境。
7. 只有在补装、重装或刷新源码安装时，才需要再次运行 `quickstart.sh` 或手动 `pip install -e .`。

注意：`quickstart.sh` 已经会负责“克隆相关仓库 + 创建 conda 环境 + 安装核心仓库 editable 包”。
不需要把“先建 conda，再手工去 `vllm-hust` 里装源码”当成默认主流程。

## 第 1 步：建立 Docker instance

`vllm-hust-dev-hub` 里的官方入口是：

- `scripts/ascend-official-container.sh`
- `ascend-runtime-manager` 的 `container` 子命令

如果你已经在目标机器上有可用容器，可直接跳到下一步。

### 方式 A：使用 hub 脚本创建或复用容器

在目标机器执行：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh start
```

需要直接进入容器时：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh shell
```

说明：

- 默认容器名是 `vllm-ascend-dev`
- 默认镜像是 `quay.io/ascend/vllm-ascend:v0.13.0-a3`
- 宿主机工作区根目录会挂载到容器内的 `/workspace`
- 容器内的默认工作目录是 `/workspace/vllm-hust-dev-hub`

### 方式 B：需要直接 SSH 到容器时，用 manager 做一键部署

如果团队成员需要通过 VS Code Remote SSH 或终端直接连进容器，而不是先 SSH 到宿主机再 `docker exec`，在目标机器执行一次：

```bash
cd /home/<your-user>/vllm-hust-dev-hub/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/<your-user> \
  --ssh-user <your-user> \
  --ssh-port 2222
```

这一步会：

- 创建或启动官方 Ascend 容器
- 在容器里安装并启动 `sshd`
- 暴露容器 SSH 端口到宿主机，例如 `2222`
- 复制 `authorized_keys` 到容器用户目录

## 第 2 步：配置 config，连接 instance

这一步最容易混淆。这里有两类完全不同的“配置文件”：

### 场景 A：连接开发容器

如果你的意思是“本地机器要直连 Docker instance”，要配置的是本地 `~/.ssh/config`，不是工作站的 `config.ini`。

示例：

```sshconfig
Host train8-container
    HostName 11.11.10.27
    User <your-user>
    Port 2222
    ProxyJump <jump-host-alias>
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    PreferredAuthentications publickey
    PubkeyAuthentication yes
    ConnectTimeout 10
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

之后即可：

```bash
ssh train8-container
```

如果使用 VS Code，直接通过 Remote SSH 连接这个 host alias 即可。

### 场景 B：连接工作站前端到某个 vLLM-HUST 服务实例

如果你的意思是“让 `vllm-hust-workstation` 指向某个已有实例”，优先配置的是：

- `vllm-hust-workstation/.env`

最关键的字段是：

```dotenv
VLLM_HUST_BASE_URL=http://localhost:8080
VLLM_HUST_API_KEY=not-required
DEFAULT_MODEL=Qwen2.5-7B-Instruct
```

说明：

- 这套 `.env` 配置是当前 `vllm-hust-workstation` README 里主推的入口
- 仓库里虽然还有 `config.ini.example`，但它对应的是旧的 Python `server.py` 路径，不应和容器 SSH 配置混为一步
- 如果只是给团队做开发环境 onboarding，通常先完成容器与源码环境即可，不必在主流程里强制要求配置工作站 `.env`

## 第 3 步：克隆 `vllm-hust-dev-hub`

在容器内或目标开发机上执行：

```bash
cd /home/<your-user>
git clone <your-vllm-hust-dev-hub-repo-url>
cd vllm-hust-dev-hub
```

说明：

- 推荐把仓库放在 `/home/<your-user>` 这一层
- `quickstart.sh` 会把其他相关仓库克隆为它的同级目录
- 不要求先进入 `scripts/` 目录，直接在仓库根目录运行 `bash scripts/quickstart.sh` 更直观

## 第 4 步：运行 quickstart，自动克隆相关仓库并建立 conda 环境

在 `vllm-hust-dev-hub` 根目录执行：

```bash
bash scripts/quickstart.sh
```

交互菜单请选择：

```text
1) Setup user-space environment
1) Full bootstrap (sync repos + conda env)
```

这一步会自动完成：

- 同步/克隆常用工作区仓库
- 安装或检测 Miniconda
- 创建 `vllm-hust-dev` conda 环境（默认 Python 3.10）
- 安装基础工具：`pip`、`setuptools`、`wheel`、`pytest`、`pre-commit`
- 以 editable 方式安装核心本地仓库

默认会安装的核心仓库包括：

- `ascend-runtime-manager`
- `vllm-hust`
- `vllm-ascend-hust`
- `vllm-hust-benchmark`

如果机器检测到 Ascend 运行时，脚本还会调用 `hust-ascend-manager setup --install-python-stack` 做 Python 栈对齐。

说明：

- 脚本会把 conda 自动激活逻辑写入 `~/.bashrc`
- `~/.bashrc` 的自动激活只对新的交互式 shell 生效，不会立刻改变当前正在运行的终端
- `quickstart.sh` 只处理用户态环境，不会尝试 `sudo`、`sg`、`HwHiAiUser` 或其他系统级修改
- 相关上游对照仓库会被克隆到 `reference-repos/`，用于对比，不会自动安装进当前环境

补充说明：

- `Setup user-space environment` 流程会执行完整的用户态 Python 环境准备，并在 Ascend 场景下做 Python 栈对齐
- 纯 `--install` 或 `Install repositories into existing env` 流程默认只处理本地 editable 安装，不再重复触发 Python 栈对齐
- 如果只是想补装或刷新仓库，同时希望把当前环境名写入 `~/.bashrc` 自动激活块，也可以直接运行 install-only 流程

如果某台宿主机还缺少系统级 Ascend 组件，或需要 `HwHiAiUser` 组权限，那是宿主机初始化问题，不属于 `quickstart.sh` 的职责范围。请单独使用 `hust-ascend-manager setup` 或宿主机运维流程处理。

### 非交互用法

如果希望一次性自动执行，可用：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/quickstart.sh --all -y
```

## 第 5 步：进入 conda 环境，并按需继续安装或刷新源码

如果团队成员还要使用 `vllm-hust-workstation`，建议在这一步之前或之后补上 `.env` 配置：

```bash
cd /home/<your-user>/vllm-hust-workstation
cp .env.example .env
```

最少需要确认这些字段：

```dotenv
VLLM_HUST_BASE_URL=http://localhost:8080
VLLM_HUST_API_KEY=not-required
DEFAULT_MODEL=Qwen2.5-7B-Instruct
```

如果 `VLLM_HUST_BASE_URL` 指向远端服务，`vllm-hust-workstation/quickstart.sh` 会按远端模式处理，不会擅自帮你在本机拉起服务。

### 默认推荐

优先检查 `quickstart.sh` 是否已经完成安装，而不是一上来手动重装。

新开一个 shell 后通常会自动进入：

```bash
conda activate vllm-hust-dev
```

可用以下命令验证环境：

```bash
conda run -n vllm-hust-dev vllm --help
```

### 什么时候还需要再次执行 `quickstart.sh`

以下情况建议继续使用 hub 脚本，而不是手工逐仓库安装：

- 第一次安装中断，需要补装缺失仓库
- `git pull` 后需要刷新 editable 安装
- 想把 `workstation`、`website`、`docs`、`EvoScientist` 也一起装进环境

命令示例：

```bash
cd /home/<your-user>/vllm-hust-dev-hub

# 只安装当前环境里缺失的本地仓库
bash scripts/quickstart.sh --install --env-name vllm-hust-dev -y

# 强制刷新核心仓库的 editable 安装
bash scripts/quickstart.sh --install --install-mode refresh --env-name vllm-hust-dev -y

# 刷新核心仓库 + 额外本地仓库
bash scripts/quickstart.sh --install --install-mode refresh --install-scope full --env-name vllm-hust-dev -y
```

### 什么时候可以手工 `pip install -e .`

只有在以下场景才建议手工执行：

- 你明确只想重装某一个仓库
- 你在调试某个仓库自己的依赖安装问题
- 你不想让 hub 脚本处理整套工作区

示例：

```bash
conda activate vllm-hust-dev

cd /home/<your-user>/vllm-hust
python -m pip install -e .

cd /home/<your-user>/vllm-ascend-hust
python -m pip install -e .
```

注意：这不是团队默认推荐主流程，只是补充手段。

## 团队统一推荐流程

建议对团队成员直接发下面这版简化流程：

```text
1. 在目标机器上准备官方 Ascend Docker 容器。
2. 如果需要从本地直连容器，在本地 ~/.ssh/config 增加容器别名。
3. 在容器内克隆 vllm-hust-dev-hub 到 /home/<user>/vllm-hust-dev-hub。
4. 在仓库根目录执行 bash scripts/quickstart.sh。
5. 菜单选择 Setup user-space environment -> Full bootstrap (sync repos + conda env)。
6. 完成后进入 conda activate vllm-hust-dev。
7. 如需补装或刷新源码，优先再次运行 quickstart.sh --install；只有特殊情况再手工 pip install -e .。
```

## 常见问题

### 1. 必须先 `cd scripts/` 吗？

不需要。推荐在仓库根目录执行：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/quickstart.sh
```

### 2. `quickstart.sh` 会不会自动安装源码？

会。默认 conda 环境创建完成后，会自动把核心仓库以 editable 方式安装进去。

### 3. `quickstart.sh` 会不会再尝试改系统环境？

不会。`quickstart.sh` 现在只负责用户态 conda 环境、Python 栈和本地 editable 安装。

如果宿主机还需要安装系统级 Ascend 组件、切换组权限或做运维初始化，需要单独执行 `hust-ascend-manager setup` 或走宿主机初始化流程。

### 4. `reference-repos/*` 会装进环境吗？

不会。它们只用于上游对照和同步分析。

### 5. 一定要手工 `pip install -e .` 吗？

不一定。大多数成员只需要跑完 `quickstart.sh` 即可。

### 6. 容器和工作站配置是同一个 config 文件吗？

不是。

- 连接容器看的是本地 `~/.ssh/config`
- 连接 `vllm-hust` 服务实例看的是 `vllm-hust-workstation/.env`
- `config.ini.example` 属于旧的 Python server 路径，不建议放进默认 onboarding 主流程
