# ascend-runtime-manager

Lightweight manager for Ascend runtime setup and diagnostics.

## Why

This repository isolates system-level Ascend dependency management from runtime repos.
`vllm-hust` can call this manager so end users keep a single install entrypoint.

## Commands

- `hust-ascend-manager doctor`
- `hust-ascend-manager doctor --json`
- `hust-ascend-manager env --shell`
- `hust-ascend-manager setup --manifest manifests/euleros-910b.json --dry-run`
- `hust-ascend-manager setup --manifest manifests/euleros-910b.json --install-python-stack`
- `hust-ascend-manager setup --manifest manifests/euleros-910b.json --apply-system`
- `hust-ascend-manager launch Qwen/Qwen2.5-1.5B-Instruct`
- `hust-ascend-manager container install --host-workspace-root /home/shuhao`
- `hust-ascend-manager container shell --host-workspace-root /home/shuhao`
- `hust-ascend-manager container exec --host-workspace-root /home/shuhao -- python -c 'import torch; import torch_npu; print(torch.npu.device_count())'`
- `hust-ascend-manager container ssh-deploy --host-workspace-root /home/shuhao --ssh-user shuhao --ssh-port 2222`
- `hust-ascend-manager container ssh-enable --host-workspace-root /home/shuhao --ssh-user shuhao --ssh-port 2222`

Default `euleros-910b` manifest includes:

- `conda config --add channels https://repo.huaweicloud.com/ascend/repos/conda/`
- `conda install ascend::cann-toolkit==8.5.0`
- `conda install ascend::cann-910b-ops==8.5.0`
- `conda install ascend::cann-nnal==8.5.0`

When a system step declares `requires_group: HwHiAiUser`, manager will run it via
`sg HwHiAiUser -c ...` automatically when needed.

`env --shell` is the source of truth for Ascend runtime exports. Runtime repos
should consume this output instead of carrying duplicated shell logic.

The manager also normalizes non-standard Ascend installs, for example when the
host only has directories like `/usr/local/Ascend/ascend-toolkit.bak.8.1/latest`
instead of the canonical `/usr/local/Ascend/ascend-toolkit/latest` symlink.
`doctor` verifies whether `torch_npu` can be imported under the manager-generated
environment, and `launch` always runs with that normalized environment.

`launch` also enables a prefill compatibility mode by default on Ascend: it
injects `--no-enable-prefix-caching` and `--no-enable-chunked-prefill` unless
you already passed explicit prefill flags yourself. This is a pragmatic
workaround for known `npu_fused_infer_attention_score` dimension crashes on some
model/runtime combinations. To opt out, pass `--no-prefill-compat-mode`.

`container` is the source of truth for the official Huawei Ascend container
workflow. `container install` is the one-click path: it pulls the configured
image when needed, mounts Ascend devices and driver paths from the host, mounts
your workspace into `/workspace`, and creates or starts a persistent container.
Use `container shell` to enter that environment later without rebuilding the
mount list, and `container exec -- ...` to run one-off checks or launches.
If you want a single-command deployment for direct SSH access into the container,
run `container ssh-deploy`. It creates or starts the container, installs
`openssh-server` inside it when needed, configures a dedicated SSH port, and
copies your mounted `authorized_keys` into the container user home.
`container ssh-enable` remains available when the container is already running
and you only want to refresh the in-container SSH setup.

The design follows upstream vLLM's plugin philosophy: hardware-specific setup
and runtime adaptation should live outside the upstream core runtime path.

## Install

```bash
cd /home/shuhao/vllm-hust-dev-hub/ascend-runtime-manager
python -m pip install -e .
```

Or install from PyPI (recommended for teammates):

```bash
python -m pip install --upgrade hust-ascend-manager
```

## Publish

Local publish with token:

```bash
cd /home/shuhao/vllm-hust-dev-hub/ascend-runtime-manager
PYPI_TOKEN=pypi-xxxxx bash scripts/publish_pypi.sh
```

CI publish:

- set repository secret `PYPI_TOKEN`
- push a tag like `v0.1.0` or run workflow dispatch

## Notes

- `setup --apply-system` executes commands from manifest and may require sudo.
- Use `setup --non-interactive` when calling manager from automation. It will fail fast instead of hanging on an interactive `sg` or `sudo` password prompt.
- `container` uses `docker` directly when available, otherwise falls back to `sudo -n docker`.
- `container ssh-deploy` is the one-click path for direct SSH-to-container access.
- `container ssh-enable` defaults to host port `2222`, user `shuhao`, and `authorized_keys` source `/workspace/.ssh/authorized_keys`.
- Keep binary payloads out of this repository. Use internal mirrors/artifact stores.
- If your account was newly added to `HwHiAiUser`, re-login is still recommended.
- `setup` is intentionally tolerant of a partially broken initial Ascend install: it can still reconcile the Python stack and planned CANN steps even when `doctor` cannot yet build a complete runtime env.
