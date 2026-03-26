# train8 Container Quickstart

This note is the shortest path for team members who need direct SSH access to
the official Ascend container running on `train8`.

## What This Gives You

- A persistent official Ascend container on `train8`
- An SSH port exposed from inside the container
- A normal host alias and a separate container alias

Use the normal host alias when you want the bare machine.
Use the container alias when you want to land directly inside Docker.

## One-Time Host Setup

Run this on `train8` once:

```bash
cd /home/shuhao/vllm-hust-dev-hub/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/shuhao \
  --ssh-user <ssh-user> \
  --ssh-port 2222
```

What it does:

- creates or starts the official Ascend container
- installs and starts `sshd` inside the container
- copies `authorized_keys` into the container user home
- exposes the container SSH service on host port `2222`
- ensures future container restarts also bring `sshd` back automatically

## Windows SSH Config

Add a second SSH alias in Windows `~/.ssh/config`.

Example:

```sshconfig
Host train8-container
    HostName 11.11.10.27
    User <ssh-user>
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

Keep your existing `train8` host entry unchanged for normal host access.

## Daily Use

Connect straight to the container with:

```bash
ssh train8-container
```

Connect to the host with your existing host alias:

```bash
ssh train8
```

## Quick Check

After logging into `train8-container`, run:

```bash
python -c "import torch; import torch_npu; print(torch.npu.device_count())"
```

If everything is correct, you should see the available NPU count.

## If You Need To Change the Port

If `2222` is already used on the host, redeploy with another port:

```bash
cd /home/shuhao/vllm-hust-dev-hub/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/shuhao \
  --ssh-user <ssh-user> \
  --ssh-port 22022
```

Then update the Windows SSH alias to match the new port.

## Notes

- The default container name is `vllm-ascend-dev`.
- The container image is managed by `ascend-runtime-manager`.
- The first run is slower because the container installs `openssh-server`.