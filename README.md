# vllm-hust-dev-hub

`vllm-hust-dev-hub` is a lightweight meta repository for daily development.

It provides a single VS Code multi-root workspace centered on `vllm-hust`, with room for related repositories that are commonly opened together during development, debugging, and upstream-sync work.

It also ships with a bootstrap script that can clone the common workspace repositories in parallel.

## Included Repositories

The default workspace includes these repositories when they exist under `/home/shuhao`:

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
- `scripts/quickstart.sh`: interactive one-command bootstrap for clone + conda environment setup.
- `scripts/ascend-official-container.sh`: start, reuse, and enter the official Ascend vLLM container from the host.

## Usage

Open the workspace directly in VS Code:

```bash
code /home/shuhao/vllm-hust-dev-hub/vllm-hust-dev-hub.code-workspace
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

Interactive mode is organized into two main flows:

- `Setup environment`: sync repositories and/or create or repair the conda environment
- `Install repositories into existing env`: install or reinstall local repositories without recloning or recreating the env

The install flow first lets you choose an action:

- `install`: only install packages that are missing from the selected conda environment
- `refresh`: reinstall selected editable local repositories even if they are already present

Then it lets you choose a scope:

- `core`: `ascend-runtime-manager`, `vllm-hust`, `vllm-ascend-hust`, `vllm-hust-benchmark`
- `full`: core repos plus extra local repos such as workstation, docs, website, and EvoScientist when they are installable

If `conda` is not available yet, `quickstart.sh` can automatically call the Miniconda installer script for you.

After conda environment setup, `quickstart.sh` also updates `~/.bashrc` so new interactive shells auto-activate the selected environment.

When conda supports channel Terms of Service checks, `quickstart.sh` only asks for acceptance when it actually needs to create a new conda environment. Install-only flows on an existing environment do not prompt for Anaconda channel ToS. It also isolates conda operations from a pre-existing `PYTHONPATH` to reduce Miniconda runtime warnings.

After ToS is accepted, quickstart records a local marker under `~/.config/vllm-hust-dev-hub/` so install-only runs do not keep asking for the same acceptance.

During environment setup, `quickstart.sh` installs both sibling repositories in editable mode when available:

- `ascend-runtime-manager`
- `vllm-hust`
- `vllm-ascend-hust`
- `vllm-hust-benchmark`

On Ascend-capable hosts, quickstart now treats `ascend-runtime-manager` as the source of truth for environment repair. After the core repos are installed, it calls `hust-ascend-manager setup --install-python-stack --apply-system` with the local workspace manifest so Python stack reconciliation and CANN package installation stay centralized in the manager rather than being reimplemented in `vllm-hust` or `vllm-ascend-hust`.

In non-interactive mode, manager now fails fast instead of hanging on `Password:` when a system step requires `HwHiAiUser` membership or sudo authentication. This keeps quickstart observable and makes the missing permission explicit.

`reference-repos/*` is for upstream comparison only and is not installed by quickstart.

Long-running installs now emit verbose pip output when possible, plus periodic heartbeat logs, so the script does not look stuck on large packages like `vllm-hust`.

If repositories are already cloned and conda environment is already created, use install-only mode to refresh local editable installs without recloning or recreating the env.

Non-interactive examples:

```bash
# clone + conda setup in one command
bash scripts/quickstart.sh --all -y

# only conda setup with custom env name and python version
bash scripts/quickstart.sh --conda --env-name vllm-hust-dev --python 3.10 -y

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

# run a quick sanity check without opening a shell
bash scripts/ascend-official-container.sh exec -- python -c 'import torch; import torch_npu; print(torch.npu.device_count())'

# helper for SSH RemoteCommand: open the container directly after SSH login
bash scripts/ssh-into-ascend-container.sh
```

For direct host-to-container development on the official Huawei image, use `scripts/ascend-official-container.sh`.

- It uses `docker` directly when available, otherwise falls back to `sudo -n docker`.
- It mounts the whole workspace parent directory into `/workspace`, so sibling repos like `/home/shuhao/vllm-hust` become available inside the container at `/workspace/vllm-hust`.
- It reuses a persistent container named `vllm-ascend-dev` by default, so repeated `shell` and `exec` calls do not need to rebuild the mount/device list.
- It sources `/usr/local/Ascend/ascend-toolkit/set_env.sh` and `/usr/local/Ascend/nnal/atb/set_env.sh` automatically before dropping you into the shell or running your command.
- If you need to recreate the container with different settings, run `bash scripts/ascend-official-container.sh rm` first.
- For remote Windows SSH, see [docs/train8-container-quickstart.md](docs/train8-container-quickstart.md) for the generic team setup for direct SSH-to-container access.

The script skips destinations that already exist. Set `CLONE_JOBS` to control the parallelism level, for example:

```bash
CLONE_JOBS=6 bash scripts/clone-workspace-repos.sh
```

The `reference-repos` directory is reserved for upstream repositories used for comparison and sync work. The bootstrap script clones:

- `vllm-project/vllm`
- `sgl-project/sglang`
- `vllm-project/vllm-ascend`

These upstream repositories are kept under `/home/shuhao/reference-repos` and are not cloned as top-level siblings of `vllm-hust`.

The localized fork `vllm-ascend-hust` is cloned as a sibling repository under `/home/shuhao/vllm-ascend-hust`, not under `reference-repos`.