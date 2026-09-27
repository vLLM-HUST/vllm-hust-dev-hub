# vllm-hust-dev-hub

`vllm-hust-dev-hub` is the daily development hub for the vLLM-HUST workspace.
It keeps the commonly used repositories, VS Code workspace, bootstrap scripts,
Ascend container helpers, and one-command engine service management in one
place.

Use this repo when you need to:

- clone or refresh the standard vLLM-HUST multi-repo workspace
- create or repair the optional host-side `vllm-hust-dev` tooling environment
- start the official Ascend 0.23 development/runtime container
- launch or manage a host-managed vLLM-HUST engine service
- prepare offline assets for an Ascend docker instance
- install a GitHub Actions self-hosted runner for the workspace

The approved ARM64 Ascend image, CANN/HDK, Python and vLLM compatibility
baseline is maintained in the
[Ascend official runtime support matrix](docs/ascend-official-runtime-support-matrix.zh-CN.md).
Use its immutable OCI digests for reproducible runs; image tags are display
aliases only.

For the exact core/plugin lock, derived-image labels, deployment receipt and
rollback procedure used by Sage Mate, see the
[Sage Mate production runtime profile](docs/sage-mate-production-runtime.md).

The reviewed Workstation Mod inventory is generated from
[`config/extension-catalog-v1.json`](config/extension-catalog-v1.json). It keeps
functional qualification, measured effect, expected scenarios, recommendation,
resource tradeoffs, conflicts, and rollback separate. Regenerate it with
`python3 scripts/generate_extension_catalog.py`; unverified entries remain
visible previews and cannot be enabled.

Agent workflow note: on any prepared dev-hub Ascend development machine,
use this repo's `./manage.sh` as the first-choice entrypoint for launching,
restarting, health-checking, and testing the prepared vLLM-HUST service. Avoid
ad-hoc host accelerator environments: NPU execution belongs in the official
container, while the host supplies Docker, NPU devices, and driver interfaces.

For product-facing lifecycle integration, use the [unified lifecycle API](docs/instance-lifecycle-v1.md).
It provides allocation/approval, start/stop, ownership transfer, audit and recovery
through an authenticated local socket. The supplied policy is disabled and the
production adapter is separately [default-off and allowlisted](docs/production-lifecycle-backend.md);
no existing service is enrolled.

## Quick Start

Open the multi-root workspace:

```bash
code /home/<your name>/vllm-hust-dev-hub/vllm-hust-dev-hub.code-workspace
```

Run the interactive bootstrap:

```bash
bash scripts/quickstart.sh
```

The recommended interactive paths are:

- `Recommended bootstrap`: sync repositories, prepare the conda environment,
  and refresh core local editable installs.
- `Refresh local repositories in existing env`: reinstall selected local repos
  without recloning or recreating the environment.
- `Sync repositories only`: clone or update workspace repositories.
- `Option 6`: create or reuse the official Ascend Docker container, configure
  SSH when key material is available, and mount the workspace at `/workspace`.

For non-interactive setup:

```bash
# clone + conda setup + core local installs
bash scripts/quickstart.sh --all -y

# clone or update repositories only
bash scripts/clone-workspace-repos.sh --yes

# install Miniconda explicitly
bash scripts/install-miniconda.sh
```

## Workspace Layout

The workspace expects sibling repositories under `/home/<your name>` and keeps
upstream comparison repositories under `reference-repos/`.

Core and engine repositories:

- `ascend-runtime-manager`
- `vllm-hust`
- `vllm-ascend-hust`
- `vllm-ascend-quant-hust`
- `triton-ascend-hust`

Services, apps, tooling, and docs:

- `vllm-hust-workstation`
- `vllm-hust-website`
- `vllm-hust-docs`
- `vllm-hust-benchmark`
- `vllm-hust-perf-analyzer`
- `claude-code-hust`
- `EvoScientist`
- `vllm-hust-org-profile`

Papers and surveys:

- `cccf-domestic-inference-engine-survey`
- `fcs-domestic-chip-llm-recsys`

Upstream reference clones:

- `reference-repos/vllm`
- `reference-repos/sglang`
- `reference-repos/vllm-ascend`

To add another repository to VS Code, edit
`vllm-hust-dev-hub.code-workspace` and append an entry to `folders`.

## Common Workflows

### Refresh Local Repositories

```bash
bash scripts/clone-workspace-repos.sh
```

If a repository already exists, the script fetches remote updates and asks
whether to run `git pull --ff-only`. Fresh clones prefer SSH and fall back to
HTTPS when SSH auth is unavailable.

Set clone parallelism with `CLONE_JOBS`:

```bash
CLONE_JOBS=6 bash scripts/clone-workspace-repos.sh --yes
```

### Prepare Conda and Editable Installs

Create or update the default development environment:

```bash
bash scripts/quickstart.sh --conda --env-name vllm-hust-dev --python 3.11 -y
```

Install missing local repositories into an existing environment:

```bash
bash scripts/quickstart.sh --install --env-name vllm-hust-dev -y
```

Refresh editable installs:

```bash
bash scripts/quickstart.sh \
  --install \
  --install-mode refresh \
  --env-name vllm-hust-dev \
  -y
```

Install the wider local workspace when extra repos are available:

```bash
bash scripts/quickstart.sh \
  --install \
  --install-mode install \
  --install-scope full \
  --env-name vllm-hust-dev \
  -y
```

Install scopes:

- `core`: `ascend-runtime-manager`, `vllm-hust`, `vllm-ascend-hust`,
  `vllm-hust-benchmark`
- `full`: core repos plus installable extra local repos such as workstation,
  docs, website, EvoScientist, and TraceLoom

Quickstart is intentionally user-space first. It does not run `sudo`, `sg`, or
`HwHiAiUser` setup by default. Formal NPU runs do not require a host CANN
Toolkit/ops installation: the official image owns CANN, HCCL, Torch-NPU, vLLM,
and vLLM-Ascend. Host-side CANN setup is a legacy bare-metal path only.

### Use the Official Ascend Container

Create or start the default container:

```bash
bash scripts/ascend-official-container.sh start
```

Enter the container with Ascend environment variables sourced and the workspace
mounted at `/workspace`:

```bash
bash scripts/ascend-official-container.sh shell
```

Run a quick sanity check:

```bash
bash scripts/ascend-official-container.sh exec -- \
  python -c 'import torch; import torch_npu; print(torch.npu.device_count())'
```

Container behavior:

- Uses `docker` directly when available, otherwise falls back to `sudo -n docker`.
- Mounts the whole workspace parent directory into `/workspace`.
- Mounts resolved external symlink targets under the workspace root.
- Menu option 6 prompts for a container name. Pressing Enter uses the image
  basename/tag plus the current login username, normalized for Docker (for
  example, `vllm-ascend-v0.23.0-openeuler-<username>`).
- If `ascend-runtime-manager` is missing, menu option 6 clones that dependency
  on demand.
- `VLLM_ENGINE_CONTAINER_NAME` selects the container for later helper and
  engine commands. The old `VLLM_ENGINE_CONTAINER` variable remains available
  as a deprecated compatibility alias.
- Sources Ascend toolkit and ATB environment scripts before shell or command
  execution.
- Uses the image's CANN Toolkit/ops/HCCL and never bind-mounts a host CANN
  Toolkit or host ops tree. Only driver/device interfaces come from the host.
- Can auto-configure container SSH using host `authorized_keys`, discovered
  public keys, and `~/.ssh/vllm-ascend-extra-authorized_keys`.
- Uses host port `2222` for ProxyJump-friendly SSH access when configured.

If you need to recreate the container with different settings:

```bash
bash scripts/ascend-official-container.sh rm
bash scripts/ascend-official-container.sh start
```

For direct SSH-to-container setup from remote Windows clients, see
[docs/train8-container-quickstart.md](docs/train8-container-quickstart.md).

### Launch an Ascend Model Service

Host mode is retained only for legacy bare-metal debugging. It is not the
formal or recommended NPU evidence path. Prefer `./manage.sh`, which launches
inside `quay.io/ascend/vllm-ascend:v0.23.0-openeuler` using its native Python
and CANN stack.

```bash
bash scripts/launch_ascend_model_service.sh \
  --env vllm-hust-dev \
  --model Qwen/Qwen3-235B-A22B-Instruct-2507 \
  --tp 8 \
  --port 8000
```

Use a preset:

```bash
# W8A8 quantized model: download from ModelScope and launch
bash scripts/launch_ascend_model_service.sh --preset w8a8 --download-model

# print the command without launching
bash scripts/launch_ascend_model_service.sh --preset w8a8 --dry-run
```

Docker mode runs inside an existing container and avoids mixing host conda
runtime libraries with the container CANN stack:

```bash
bash scripts/launch_ascend_model_service.sh \
  --preset coder \
  --docker vllm-ascend-dev
```

Available presets include:

- `w8a8`: Qwen3-235B-A22B-W8A8, quantized, TP=8
- `coder`: Qwen2.5-Coder-32B-Instruct, dense coding model, TP=4
- `qwen3-32b`: Qwen3-32B, dense model, TP=4

### Manage the Host-Managed vLLM-HUST Engine

`manage.sh` installs and controls a user-level systemd service. The service is
always launched from the host through `scripts/run_vllm_hust_engine.sh`, which
then enters the configured Docker container. This keeps day-to-day launch,
debugging, and service management on the same path.

Prepare local configuration:

```bash
cp .env.template .env
# edit .env and set a real VLLM_HUST_API_KEY
```

Keep `.env` for local secrets and machine-private defaults. Put model,
topology, plugin, and smoke-test choices in a non-secret profile, then select it
per launch:

```bash
VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env ./manage.sh start
```

Start and inspect the service:

```bash
./manage.sh start
./manage.sh status
./manage.sh health
./manage.sh logs
./manage.sh restart
./manage.sh stop
```

Managed units run a bounded, port-scoped container cleanup through `ExecStop`
before systemd terminates the host launcher. Missing or already-stopped
containers are idempotent success; Docker errors or verified surviving workers
fail the stop instead of being hidden. Because container workers are not owned
by the user unit's cgroup, generated units use `KillMode=process` only after
that explicit cleanup contract.

Current vLLM-Ascend releases deprecate the legacy
`VLLM_ASCEND_ENABLE_FLASHCOMM1` and `VLLM_ASCEND_ENABLE_FUSED_MC2` environment
switches, so the launcher removes them by default. An older, separately verified
plugin profile may set `VLLM_ENGINE_ENABLE_LEGACY_ASCEND_ENV=1` to forward
explicit legacy values during a bounded migration.

Common `.env` knobs:

```bash
VLLM_ENGINE_CONTAINER_NAME=vllm-ascend-dev
VLLM_ENGINE_AUTO_CREATE_CONTAINER=true
VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env
VLLM_ENGINE_MODEL_PATH=/data/shared_models/modelscope_cache/Qwen/Qwen3-32B
VLLM_ENGINE_SERVED_MODEL_NAME=qwen3-32b
VLLM_ENGINE_PORT=8000
VLLM_ENGINE_TP_SIZE=4
VLLM_ENGINE_NPU_DEVICES=0,1,2,3
VLLM_ENGINE_PYTHON=/usr/local/python3.12.13/bin/python
VLLM_ENGINE_CONDA_ENV=vllm-hust-dev
COMPILE_CUSTOM_KERNELS=0
VLLM_PLUGINS=ascend
```

If the container is missing or stopped, `manage.sh start` pulls/creates it automatically through `scripts/ascend-official-container.sh`.

### Record a Verified Deployment Receipt

After health, model-card, dialogue, device-mapping, and import-origin checks
pass, write those sanitized results to the versioned receipt contract. The
tool rejects unknown or credential-like fields and adds a deterministic ID plus
a SHA-256 content digest:

```bash
python3 scripts/deployment_receipt.py create \
  --input verified-deployment.json \
  --output artifacts/deployment-receipt.json
python3 scripts/deployment_receipt.py verify artifacts/deployment-receipt.json
```

The input contains exactly these sections: `status`, `model`, `engine`,
`hardware`, `parallelism`, `execution`, `speculative`, and `provenance`.
Lifecycle state is one of `active`, `superseded`, or `failed`. Import origins
belong in `provenance.import_origins`; API keys, tokens, passwords, private
keys, and arbitrary extra fields are rejected. The receipt only proves the
facts supplied by a successful verifier—it must not be emitted before the
online acceptance gates pass.

### Use Optimization Repositories

`manage.sh` is intentionally optimization-repo agnostic. Keep repo-specific
plugin names, Python paths, and feature flags in the caller environment or in a
local `.env`.

For an optimization repository mounted at `/workspace/<repo-name>` inside the
container:

```bash
export VLLM_ENGINE_CONTAINER_NAME=<unique-container-name>
export VLLM_ENGINE_SYSTEMD_UNIT=<unique-unit-name>.service
export VLLM_ENGINE_PORT=<free-port>
export VLLM_ENGINE_NPU_DEVICES=<dedicated-npus>
export VLLM_ENGINE_PYTHON=/usr/local/python3.12.13/bin/python
export VLLM_OPTIMIZATION_REPO_CONTAINER=/workspace/<repo-name>
export VLLM_OPTIMIZATION_SRC_SUBDIR=src
export VLLM_OPTIMIZATION_PLUGIN=<plugin-entrypoint-name>
export VLLM_OPTIMIZATION_ENTRYPOINT_GROUP=vllm.general_plugins
export VLLM_OPTIMIZATION_AUTO_INSTALL=true
export VLLM_OPTIMIZATION_ENV_PREFIX=<PLUGIN_PREFIX>_
export <PLUGIN_PREFIX>_ENABLE=1

./manage.sh restart
```

The launcher installs the repository into `VLLM_ENGINE_PYTHON` in editable,
`--no-deps` mode when the requested entry point is missing, then verifies the
exact entry-point group and name before starting vLLM. Set
`VLLM_OPTIMIZATION_AUTO_INSTALL=false` to require a preinstalled package.

For BidKV, use:

```bash
export VLLM_OPTIMIZATION_REPO_CONTAINER=/workspace/vllm-hust-bidkv
export VLLM_OPTIMIZATION_PLUGIN=bidkv
export VLLM_OPTIMIZATION_ENTRYPOINT_GROUP=vllm.victim_selector
export VLLM_OPTIMIZATION_ENV_PREFIX=BIDKV_UTILITY_
export BIDKV_UTILITY_ENABLE=1
```

The launcher also builds `PYTHONPATH` from:

- `$VLLM_OPTIMIZATION_REPO_CONTAINER/src`
- `$VLLM_OPTIMIZATION_REPO_CONTAINER`
- `VLLM_ENGINE_BASE_PYTHONPATH`

For `vllm.general_plugins` and `vllm.platform_plugins`, it adds the optimization
plugin to `VLLM_PLUGINS`. This Ascend launcher always retains `ascend`, even
when a caller provides an explicit plugin filter. Custom groups such as
`vllm.victim_selector` are selected by their owning runtime component and are
not added to `VLLM_PLUGINS`.

When `VLLM_PLUGINS` is not explicitly provided, the launcher retains the full
Ascend plugin set, including model and loader entry points. Use
`VLLM_ENGINE_PYTHONPATH` or `VLLM_PLUGINS` only when you need full manual
control. By default, inherited `PYTHONPATH` entries that contain another
`vllm` or `vllm_ascend` package are removed, while CANN-only runtime paths are
retained. Set `VLLM_ENGINE_INHERIT_PYTHONPATH=1` only for an intentional
overlay; startup validates that both engine packages resolve from the first
declared source roots before serving traffic.

### Sync into an Offline Container

Use this helper from an internet-connected development machine when the target
Ascend docker instance cannot access the public network:

```bash
bash scripts/offline-sync-instance.sh \
  --model-id Qwen/Qwen2.5-1.5B-Instruct
```

If the model already exists locally:

```bash
bash scripts/offline-sync-instance.sh \
  --model-path /data/models/Qwen2.5-1.5B-Instruct
```

The helper:

- prepares an `aarch64` / Python 3.10 wheelhouse for `vllm-hust` and
  `vllm-ascend-hust`
- downloads or reuses a local model snapshot
- syncs local repositories, wheels, and model assets through `cgcl-bastion`
- installs editable local repos inside the container's `vllm-hust-dev` conda
  environment without public network access

Expected sibling repositories:

- `ascend-runtime-manager`
- `vllm-hust`
- `vllm-ascend-hust`
- `vllm-hust-benchmark`
- `vllm-hust-dev-hub`

### Install a GitHub Actions Runner

```bash
export GITHUB_RUNNER_URL=https://github.com/vLLM-HUST
export GITHUB_RUNNER_TOKEN=<temporary-registration-token>
bash scripts/setup-github-actions-runner.sh install --labels train8,ascend
```

See
[docs/github-actions-self-hosted-runner.md](docs/github-actions-self-hosted-runner.md)
for details.

## Environment Notes

### `.env`

Copy `.env.template` to `.env` for local secrets and service knobs:

```bash
cp .env.template .env
```

Important values:

- `GITHUB_TOKEN`: optional helper token for private GitHub access.
- `HF_ENDPOINT` / `HF_TOKEN`: optional Hugging Face download configuration.
- `VLLM_HUST_API_KEY`: required by `manage.sh`; must be a real non-placeholder
  key.
- `VLLM_ENGINE_ENV_FILE`: optional non-secret profile with model/topology/plugin
  settings for a specific service or smoke test.
- `VLLM_ENGINE_*`: host-managed engine and container launch settings. Prefer
  profiles for reusable model/topology choices instead of hard-coding them in
  `.env`.
- `CONTAINER_SSH_*`: direct SSH access into configured containers.

Do not commit `.env`.

### Conda Activation Hooks

Quickstart installs activate/deactivate hooks for the selected conda
environment.

On `conda activate`, the hook probes `https://hf-mirror.com` and sets
`HF_ENDPOINT=https://hf-mirror.com` when reachable. Otherwise it unsets
`HF_ENDPOINT` so Hugging Face clients fall back to upstream. On deactivate, the
previous value is restored.

Disable this behavior for a shell/session:

```bash
export HUST_DEV_HUB_DISABLE_HF_MIRROR_AUTOSET=1
```

The hook does not apply `hust-ascend-manager env --shell` by default. To opt in
to manager-provided environment exports:

```bash
export HUST_DEV_HUB_ENABLE_MANAGER_ENV_HOOK=1
```

When enabled, only a conservative allowlist is applied:

- `ASCEND_*`
- `TORCH_DEVICE_BACKEND_AUTOLOAD`
- `HUST_ASCEND_*`
- `LD_LIBRARY_PATH`
- `PYTHONPATH`

### Bashrc Auto-Activation

Quickstart does not update `~/.bashrc` by default. To auto-activate the selected
conda environment in new interactive shells, opt in explicitly:

```bash
bash scripts/quickstart.sh --update-bashrc ...
```

or:

```bash
export HUST_DEV_HUB_UPDATE_BASHRC=1
bash scripts/quickstart.sh ...
```

Interactive menu option `7` only updates `~/.bashrc` auto-activation.

### Logs and Install Behavior

Quickstart writes timestamped logs to:

```text
~/.cache/vllm-hust-dev-hub/logs/
```

Override log paths with:

```bash
export HUST_DEV_HUB_QUICKSTART_LOG_DIR=/path/to/logs
export HUST_DEV_HUB_QUICKSTART_LOG_FILE=/path/to/quickstart.log
```

Other behavior worth knowing:

- Conda operations are isolated from pre-existing `PYTHONPATH` to reduce
  Miniconda runtime warnings.
- Anaconda channel Terms of Service prompts only appear when quickstart needs
  to create a new conda environment.
- Accepted ToS markers are recorded under
  `~/.config/vllm-hust-dev-hub/`.
- Broken relocated Miniconda prefixes are backed up and reinstalled before
  continuing.
- Long-running installs emit verbose pip output and heartbeat logs.
- `reference-repos/*` is for upstream comparison only and is not installed by
  quickstart.

## Script Index

| Path | Purpose |
| --- | --- |
| `vllm-hust-dev-hub.code-workspace` | VS Code multi-root workspace. |
| `manage.sh` | Install/start/restart/stop/log/check the host-managed vLLM-HUST engine service. |
| `scripts/quickstart.sh` | Interactive and non-interactive workspace bootstrap. |
| `scripts/clone-workspace-repos.sh` | Clone or refresh standard workspace repositories. |
| `scripts/install-miniconda.sh` | Install Miniconda into the current user's home directory. |
| `scripts/ascend-official-container.sh` | Start, reuse, enter, or remove the official Ascend vLLM container. |
| `scripts/ssh-into-ascend-container.sh` | SSH helper for entering a running Ascend dev container. |
| `scripts/ascend-container-runtime.sh` | SSH keepalive helper for Ascend dev containers. |
| `scripts/enable-existing-container-ssh.sh` | Enable SSH and home-directory repo links in an already-running custom container. |
| `scripts/run_vllm_hust_engine.sh` | Docker/container launcher used by `manage.sh`. |
| `scripts/cleanup_vllm_hust_engine.sh` | Cleanup helper used when stopping the managed engine. |
| `scripts/launch_ascend_model_service.sh` | Launch an Ascend model service with host and Docker modes. |
| `scripts/offline-sync-instance.sh` | Sync repos, wheels, and model assets into an offline docker instance. |
| `scripts/setup-github-actions-runner.sh` | Install and manage a rootless GitHub Actions runner. |
| `scripts/sync-env.sh` | Propagate the canonical `.env` from this repo to sibling workspace repos. |
| `scripts/create_cloudflare_api_token.py` | Create a scoped Cloudflare API token from bootstrap credentials. |
| `scripts/ci/` | CI helpers for quickstart, smoke tests, and benchmark install. |

## References

- Team onboarding: [docs/team-onboarding.md](docs/team-onboarding.md)
- Git workflow: [docs/contribution-git-workflow.md](docs/contribution-git-workflow.md)
- GitHub Actions runner:
  [docs/github-actions-self-hosted-runner.md](docs/github-actions-self-hosted-runner.md)
- Train8 container quickstart:
  [docs/train8-container-quickstart.md](docs/train8-container-quickstart.md)
- Performance follow-up roadmap: [ROADMAP.md](ROADMAP.md)
