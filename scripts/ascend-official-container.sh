#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"
MANAGER_SRC="$HUB_ROOT/ascend-runtime-manager/src"

IMAGE="${IMAGE:-quay.io/ascend/vllm-ascend:v0.13.0-a3}"
CONTAINER_NAME="${CONTAINER_NAME:-vllm-ascend-dev}"
HOST_WORKSPACE_ROOT="${HOST_WORKSPACE_ROOT:-$WORKSPACE_ROOT}"
CONTAINER_WORKSPACE_ROOT="${CONTAINER_WORKSPACE_ROOT:-/workspace}"
CONTAINER_WORKDIR="${CONTAINER_WORKDIR:-$CONTAINER_WORKSPACE_ROOT/vllm-hust-dev-hub}"
HOST_CACHE_DIR="${HOST_CACHE_DIR:-$HOME/.cache}"
SHM_SIZE="${SHM_SIZE:-16g}"

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  echo "python3 or python is required" >&2
  return 1
}

main() {
  local action="${1:-install}"
  local python_bin
  python_bin="$(find_python)"

  case "$action" in
    help|-h|--help)
      PYTHONPATH="$MANAGER_SRC${PYTHONPATH:+:$PYTHONPATH}" \
        "$python_bin" -m hust_ascend_manager.cli container -h
      return 0
      ;;
  esac

  PYTHONPATH="$MANAGER_SRC${PYTHONPATH:+:$PYTHONPATH}" \
    "$python_bin" -m hust_ascend_manager.cli \
    container \
    "$action" \
    --image "$IMAGE" \
    --container-name "$CONTAINER_NAME" \
    --host-workspace-root "$HOST_WORKSPACE_ROOT" \
    --container-workspace-root "$CONTAINER_WORKSPACE_ROOT" \
    --container-workdir "$CONTAINER_WORKDIR" \
    --host-cache-dir "$HOST_CACHE_DIR" \
    --shm-size "$SHM_SIZE" \
    "${@:2}"
}

main "$@"