#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"

cd "$HUB_ROOT"

exec env HOST_WORKSPACE_ROOT="${HOST_WORKSPACE_ROOT:-$WORKSPACE_ROOT}" \
  CONTAINER_NAME="${CONTAINER_NAME:-vllm-ascend-dev}" \
  bash "$SCRIPT_DIR/ascend-official-container.sh" shell