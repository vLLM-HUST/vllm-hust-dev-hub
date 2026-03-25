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
- `scripts/quickstart.sh`: interactive one-command bootstrap for clone + conda environment setup.

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

Non-interactive examples:

```bash
# clone + conda setup in one command
bash scripts/quickstart.sh --all -y

# only conda setup with custom env name and python version
bash scripts/quickstart.sh --conda --env-name vllm-hust-dev --python 3.10 -y

# clone without prompts
bash scripts/clone-workspace-repos.sh --yes
```

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