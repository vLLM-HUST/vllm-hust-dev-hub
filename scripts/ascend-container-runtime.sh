#!/usr/bin/env bash

set -euo pipefail

if [[ -x /usr/sbin/sshd && -f /etc/ssh/sshd_config.d/vllm-ascend.conf ]]; then
  mkdir -p /run/sshd
  pkill sshd >/dev/null 2>&1 || true
  /usr/sbin/sshd -f /etc/ssh/sshd_config
fi

trap : TERM INT
sleep infinity & wait