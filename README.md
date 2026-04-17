# vllm-hust-dev-hub

`vllm-hust-dev-hub` is a lightweight meta repository for daily development.

It provides a single VS Code multi-root workspace centered on `vllm-hust`, with room for related repositories that are commonly opened together during development, debugging, and upstream-sync work.

It also ships with a bootstrap script that can clone the common workspace repositories in parallel.

Team onboarding reference: [docs/team-onboarding.md](docs/team-onboarding.md)

## Included Repositories

The default workspace includes these repositories when they exist under `/home/<your name>`:

- `vllm-hust`
- `vllm-hust-workstation`
- `vllm-hust-website`
- `vllm-hust-docs`
- `vllm-ascend-hust`
- `reference-repos/vllm`
- `reference-repos/sglang`
- `reference-repos/vllm-ascend`
- `EvoScientist`
- `vllm-hust-benchmark`

## Files

- `vllm-hust-dev-hub.code-workspace`: main multi-root workspace for VS Code.
- `scripts/clone-workspace-repos.sh`: clone the common workspace repositories in parallel.
- `scripts/install-miniconda.sh`: download and install Miniconda into the current user's home directory.
- `scripts/quickstart.sh`: interactive one-command bootstrap for clone + conda environment setup, plus menu option 6 for the official Ascend container and container SSH setup.
- `scripts/ascend-official-container.sh`: start, reuse, and enter the official Ascend vLLM container from the host.
- `scripts/enable-existing-container-ssh.sh`: fallback helper for an already-running custom container when you need to turn on direct SSH access and surface mounted repos under the login home.
- `scripts/offline-sync-instance.sh`: prepare offline wheels and model assets on the local machine, sync them through the bastion host into the docker instance, then install local repos inside the container without public network access.

## Usage

Open the workspace directly in VS Code:

```bash
code /home/<your name>/vllm-hust-dev-hub/vllm-hust-dev-hub.code-workspace
```

If you want to add more repositories, edit the workspace file and append another entry to `folders`.

To bootstrap the common repositories under the parent directory of this repo:

```bash
bash scripts/clone-workspace-repos.sh
```

If a repository already exists locally, the clone script checks for remote updates and asks whether to run `git pull --ff-only`.

Upstream `reference-repos/*` clones are also confirmed interactively before cloning.

For an interactive bootstrap (clone repositories and create/update a conda environment):

```bash
bash scripts/quickstart.sh
```

Interactive mode keeps the common paths at the top level:

- `Recommended bootstrap`: sync repositories, prepare the conda env, and refresh core local installs
- `Refresh local repositories in existing env`: reinstall selected local repos without recloning or recreating the env
- `Sync repositories only`: update or clone workspace repositories without touching the env
- `Advanced options`: conda-only repair, install-missing mode, and bashrc-only registration

Interactive menu option 6 is the recommended entrypoint for the official Ascend container workflow:

- it can prompt for an extra SSH public key and persist it under `~/.ssh/vllm-ascend-extra-authorized_keys`
- it auto-enables `sshd` inside the container when host SSH key material is available
- it aligns the container SSH user with the mounted workspace owner so `/workspace` is directly usable after login
- it reuses `ProxyJump`-friendly SSH access on host port `2222`
- when Docker storage under `/var/lib/docker` is too small and `/data` has space, it can migrate Docker data-root to `/data/docker`

The advanced install flows still support two install actions:

- `install`: only install packages that are missing from the selected conda environment
- `refresh`: reinstall selected editable local repositories even if they are already present

Then they let you choose a scope:

- `core`: `ascend-runtime-manager`, `vllm-hust`, `vllm-ascend-hust`, `vllm-hust-benchmark`
- `full`: core repos plus extra local repos such as workstation, docs, website, and EvoScientist when they are installable

If `conda` is not available yet, `quickstart.sh` can automatically call the Miniconda installer script for flows that include conda setup (for example `--conda` / `--all`).

Install-only runs (`--install` without `--conda`) will not auto-install Miniconda; they fail fast and ask you to run a conda setup flow first.

If a copied or relocated Miniconda prefix is present but unusable because its embedded interpreter path is stale, `quickstart.sh` now ignores that broken executable, backs up the bad prefix, and reinstalls Miniconda before continuing.

By default, `quickstart.sh` does not update `~/.bashrc`.

If you want new interactive shells to auto-activate the selected conda environment, opt in explicitly with either:

- `bash scripts/quickstart.sh --update-bashrc ...`
- interactive menu option `7` (only update `~/.bashrc` auto-activation)
- `export HUST_DEV_HUB_UPDATE_BASHRC=1` before running quickstart

Quickstart now installs conda activate/deactivate hooks for the selected environment. On each `conda activate`, the hook probes `https://hf-mirror.com` and auto-sets `HF_ENDPOINT=https://hf-mirror.com` when reachable; otherwise it unsets `HF_ENDPOINT` so Hugging Face clients fall back to the default upstream endpoint.

To disable this auto-switch behavior for a shell/session, set:

```bash
export HUST_DEV_HUB_DISABLE_HF_MIRROR_AUTOSET=1
```

The hook preserves your previous `HF_ENDPOINT` and restores it on `conda deactivate`.

To keep activation deterministic and avoid unintended environment drift, the conda activate hook does not apply `hust-ascend-manager env --shell` by default.

If you need manager-provided env exports during `conda activate`, opt in with:

```bash
export HUST_DEV_HUB_ENABLE_MANAGER_ENV_HOOK=1
```

When enabled, the hook only applies a conservative allowlist of Ascend runtime variables (`ASCEND_*`, `TORCH_DEVICE_BACKEND_AUTOLOAD`, `HUST_ASCEND_*`, plus `LD_LIBRARY_PATH` / `PYTHONPATH`) and still restores saved values on `conda deactivate`.

When conda supports channel Terms of Service checks, `quickstart.sh` only asks for acceptance when it actually needs to create a new conda environment. Install-only flows on an existing environment do not prompt for Anaconda channel ToS. It also isolates conda operations from a pre-existing `PYTHONPATH` to reduce Miniconda runtime warnings.

After ToS is accepted, quickstart records a local marker under `~/.config/vllm-hust-dev-hub/` so install-only runs do not keep asking for the same acceptance.

During environment setup, `quickstart.sh` installs both sibling repositories in editable mode when available:

- `ascend-runtime-manager`
- `vllm-hust`
- `vllm-ascend-hust`
- `vllm-hust-benchmark`

`ascend-runtime-manager` now lives as a sibling repository under the workspace root, not inside `vllm-hust-dev-hub`.

On Ascend-capable hosts, quickstart treats `ascend-runtime-manager` as the source of truth for user-space Python stack repair. After the core repos are installed, it calls `hust-ascend-manager setup --install-python-stack` with the local workspace manifest so `torch` and `torch-npu` stay aligned without attempting host-level CANN or group-managed system changes.

`quickstart.sh` is intentionally user-space only. It does not attempt `sudo`, `sg`, `HwHiAiUser`, or other system-level setup by default. If a machine still needs host-level Ascend packages or permissions, run `hust-ascend-manager setup` manually with the appropriate privileges outside quickstart. If you explicitly want quickstart to invoke manager system steps, set `HUST_DEV_HUB_APPLY_ASCEND_SYSTEM_STEPS=1` first.

`reference-repos/*` is for upstream comparison only and is not installed by quickstart.

Long-running installs now emit verbose pip output when possible, plus periodic heartbeat logs, so the script does not look stuck on large packages like `vllm-hust`.

When quickstart installs `vllm-ascend-hust`, it now always ensures `triton-ascend` is present, including lightweight plugin mode (`COMPILE_CUSTOM_KERNELS=0`).

Quickstart conda activate hooks no longer prepend `${CONDA_PREFIX}/lib` to `LD_LIBRARY_PATH`, which avoids breaking host system tools such as `git` and `curl` in activated shells.

Ascend custom-kernel selection now uses auto-detection by default and is not persisted into conda env vars. To force behavior explicitly, set `HUST_DEV_HUB_ASCEND_COMPILE_CUSTOM_KERNELS=1` (always compile) or `HUST_DEV_HUB_ASCEND_COMPILE_CUSTOM_KERNELS=0` (always lightweight mode) before running quickstart.

If repositories are already cloned and conda environment is already created, use install-only mode to refresh local editable installs without recloning or recreating the env.

Non-interactive examples:

```bash
# clone + conda setup in one command
bash scripts/quickstart.sh --all -y

# only conda setup with custom env name and python version
bash scripts/quickstart.sh --conda --env-name vllm-hust-dev --python 3.11 -y

# only install missing local repositories into an existing conda env
bash scripts/quickstart.sh --install --env-name vllm-hust-dev -y

# refresh core local repositories into an existing conda env
bash scripts/quickstart.sh --install --install-mode refresh --env-name vllm-hust-dev -y

# install missing core + extra local repos into an existing conda env
bash scripts/quickstart.sh --install --install-mode install --install-scope full --env-name vllm-hust-dev -y

# clone without prompts
bash scripts/clone-workspace-repos.sh --yes

# install Miniconda explicitly
bash scripts/install-miniconda.sh

# create or start the official Ascend container on this host
bash scripts/ascend-official-container.sh start

# enter the container with Ascend env sourced and workspace mounted at /workspace
bash scripts/ascend-official-container.sh shell

# create or start the official Ascend container through the interactive menu
bash scripts/quickstart.sh

# run a quick sanity check without opening a shell
bash scripts/ascend-official-container.sh exec -- python -c 'import torch; import torch_npu; print(torch.npu.device_count())'

# helper for SSH RemoteCommand: open the container directly after SSH login
bash scripts/ssh-into-ascend-container.sh
```

For direct host-to-container development on the official Huawei image, use `scripts/ascend-official-container.sh`.

- It uses `docker` directly when available, otherwise falls back to `sudo -n docker`.
- If `IMAGE` is unset, it now asks for the Ascend device profile and chooses a matching official `quay.io/ascend/vllm-ascend:v0.9.1-dev` variant.
- It mounts the whole workspace parent directory into `/workspace`, so sibling repos like `/home/<your name>/vllm-hust` become available inside the container at `/workspace/vllm-hust`.
- It also mounts resolved external symlink targets under the workspace root, so sibling repos symlinked into `/data/...` remain valid inside the container.
- It reuses a persistent container named `vllm-ascend-dev` by default, so repeated `shell` and `exec` calls do not need to rebuild the mount/device list.
- It sources `/usr/local/Ascend/ascend-toolkit/set_env.sh` and `/usr/local/Ascend/nnal/atb/set_env.sh` automatically before dropping you into the shell or running your command.
- It can auto-configure container SSH on `start` or `install`, using host `authorized_keys`, discovered `*.pub` files, and `~/.ssh/vllm-ascend-extra-authorized_keys`.
- If you already have a running custom container and only need direct SSH plus home-directory links back to the mounted repos, use `bash scripts/enable-existing-container-ssh.sh`.
- When direct public access to host port `2222` is unavailable, use a client-side SSH alias with `HostName 127.0.0.1`, `Port 2222`, and `ProxyJump <host-alias>`.
- If you need to recreate the container with different settings, run `bash scripts/ascend-official-container.sh rm` first.
- For remote Windows SSH, see [docs/train8-container-quickstart.md](docs/train8-container-quickstart.md) for the generic team setup for direct SSH-to-container access.

## Offline Container Sync

If the Ascend docker instance cannot access the public network, use the local helper below from an internet-connected development machine.

It performs four steps in one run:

- downloads an `aarch64` / Python `3.10` wheelhouse for `vllm-hust` and `vllm-ascend-hust`
- downloads a Hugging Face model snapshot locally, or reuses an existing model directory
- syncs the local repositories, wheelhouse, and model into the docker instance through `cgcl-bastion`
- installs the editable local repos inside the container's `vllm-hust-dev` conda environment without using the container network

Example:

```bash
bash scripts/offline-sync-instance.sh \
	--model-id Qwen/Qwen2.5-1.5B-Instruct
```

If the model already exists locally:

```bash
bash scripts/offline-sync-instance.sh \
	--model-path /data/models/Qwen2.5-1.5B-Instruct
```

Notes:

- The script expects the sibling repositories `ascend-runtime-manager`, `vllm-hust`, `vllm-ascend-hust`, `vllm-hust-benchmark`, and `vllm-hust-dev-hub` to exist under the workspace root.
- It assumes the container already has the `vllm-hust-dev` conda environment with `torch` and `torch_npu` available.
- The script syncs `ascend-runtime-manager` into `/workspace/ascend-runtime-manager`, which closes the gap left by the standard dev-hub sync scope.

The script skips destinations that already exist. Set `CLONE_JOBS` to control the parallelism level, for example:

```bash
CLONE_JOBS=6 bash scripts/clone-workspace-repos.sh
```

The `reference-repos` directory is reserved for upstream repositories used for comparison and sync work. The bootstrap script clones:

- `vllm-project/vllm`
- `sgl-project/sglang`
- `vllm-project/vllm-ascend`

These upstream repositories are kept under `/home/<your name>/reference-repos` and are not cloned as top-level siblings of `vllm-hust`.

The localized fork `vllm-ascend-hust` is cloned as a sibling repository under `/home/<your name>/vllm-ascend-hust`, not under `reference-repos`.
