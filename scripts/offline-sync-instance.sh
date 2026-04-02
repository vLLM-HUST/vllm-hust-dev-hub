#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"

BASTION_ALIAS="${BASTION_ALIAS:-cgcl-bastion}"
BASTION_STAGE_ROOT="${BASTION_STAGE_ROOT:-/home/user/offline-sync-stage/vllm-hust}"
CONTAINER_HOST="${CONTAINER_HOST:-11.11.10.27}"
CONTAINER_PORT="${CONTAINER_PORT:-2222}"
CONTAINER_USER="${CONTAINER_USER:-shuhao}"
CONTAINER_WORKSPACE_ROOT="${CONTAINER_WORKSPACE_ROOT:-/workspace}"
CONTAINER_ENV_NAME="${CONTAINER_ENV_NAME:-vllm-hust-dev}"
CONTAINER_ASSET_ROOT="${CONTAINER_ASSET_ROOT:-$CONTAINER_WORKSPACE_ROOT/offline-assets/vllm-hust}"
CONTAINER_MODEL_ROOT="${CONTAINER_MODEL_ROOT:-$CONTAINER_WORKSPACE_ROOT/models}"

TARGET_PLATFORM="${TARGET_PLATFORM:-manylinux2014_aarch64}"
TARGET_PYTHON_VERSION="${TARGET_PYTHON_VERSION:-310}"
TARGET_ABI="${TARGET_ABI:-cp310}"
TARGET_IMPLEMENTATION="${TARGET_IMPLEMENTATION:-cp}"
TARGET_PLATFORM_MACHINE="${TARGET_PLATFORM_MACHINE:-aarch64}"
TARGET_SYS_PLATFORM="${TARGET_SYS_PLATFORM:-linux}"
TARGET_PLATFORM_SYSTEM="${TARGET_PLATFORM_SYSTEM:-Linux}"
TARGET_PYTHON_FULL_VERSION="${TARGET_PYTHON_FULL_VERSION:-3.10.20}"
TARGET_PYTHON_VERSION_DOTTED="${TARGET_PYTHON_VERSION_DOTTED:-3.10}"

CACHE_ROOT="${CACHE_ROOT:-$HOME/.cache/vllm-hust-dev-hub/offline-sync}"
ARTIFACT_NAME="${ARTIFACT_NAME:-aarch64-cp310}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$CACHE_ROOT/$ARTIFACT_NAME}"
WHEELHOUSE_DIR="$ARTIFACT_ROOT/wheelhouse"
REQUIREMENT_BUNDLE="$ARTIFACT_ROOT/requirements-target.txt"
MODEL_STAGE_ROOT="$ARTIFACT_ROOT/models"

MODEL_ID="${MODEL_ID:-}"
MODEL_REVISION="${MODEL_REVISION:-}"
MODEL_LOCAL_PATH="${MODEL_LOCAL_PATH:-}"
MODEL_ALLOW_PATTERNS="${MODEL_ALLOW_PATTERNS:-}"
MODEL_IGNORE_PATTERNS="${MODEL_IGNORE_PATTERNS:-}"

SYNC_MODEL=1
SYNC_REPOS=1
PREPARE_WHEELHOUSE=1
INSTALL_IN_CONTAINER=1
RUN_IMPORT_CHECK=1
AUTO_YES=0

LOCAL_REPOS=(
  "ascend-runtime-manager"
  "vllm-hust"
  "vllm-ascend-hust"
  "vllm-hust-benchmark"
  "vllm-hust-dev-hub"
)

log() {
  printf '[offline-sync] %s\n' "$1"
}

fail() {
  printf '[offline-sync] %s\n' "$1" >&2
  exit 1
}

print_help() {
  cat <<'EOF'
Usage: bash scripts/offline-sync-instance.sh [options]

Prepare offline Python artifacts and a model on the local machine, then sync
them into the Ascend docker instance through the bastion host and install the
local repos inside the container without public network access.

Model options:
  --model-id ID              Hugging Face model repo id to download locally.
  --model-revision REV       Optional model revision for --model-id.
  --model-path PATH          Reuse an existing local model directory instead of downloading.
  --model-allow PATTERNS     Comma-separated allow patterns for snapshot download.
  --model-ignore PATTERNS    Comma-separated ignore patterns for snapshot download.
  --skip-model               Skip model download and sync.

Workflow options:
  --skip-wheelhouse          Skip local Python artifact preparation.
  --skip-repos               Skip syncing local source repositories.
  --skip-install             Skip the container-side offline install step.
  --skip-import-check        Skip the final import validation inside the container.
  --artifact-root PATH       Local artifact directory (default: ~/.cache/.../aarch64-cp310).
  --container-asset-root P   Destination root in the container for offline assets.
  --container-model-root P   Destination root in the container for models.
  --env-name NAME            Conda env name inside the container (default: vllm-hust-dev).
  -y, --yes                  Auto-install local helper packages when needed.
  -h, --help                 Show this help.

Examples:
  bash scripts/offline-sync-instance.sh \
    --model-id Qwen/Qwen2.5-1.5B-Instruct

  bash scripts/offline-sync-instance.sh \
    --model-path /data/models/Qwen2.5-1.5B-Instruct \
    --skip-wheelhouse
EOF
}

ask_yes_no() {
  local prompt="$1"
  local answer=""

  if (( AUTO_YES == 1 )); then
    return 0
  fi

  while true; do
    read -r -p "$prompt [y/n]: " answer
    case "$answer" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO) return 1 ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Required command not found: $cmd"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --model-id)
        MODEL_ID="$2"
        shift
        ;;
      --model-revision)
        MODEL_REVISION="$2"
        shift
        ;;
      --model-path)
        MODEL_LOCAL_PATH="$2"
        shift
        ;;
      --model-allow)
        MODEL_ALLOW_PATTERNS="$2"
        shift
        ;;
      --model-ignore)
        MODEL_IGNORE_PATTERNS="$2"
        shift
        ;;
      --skip-model)
        SYNC_MODEL=0
        ;;
      --skip-wheelhouse)
        PREPARE_WHEELHOUSE=0
        ;;
      --skip-repos)
        SYNC_REPOS=0
        ;;
      --skip-install)
        INSTALL_IN_CONTAINER=0
        ;;
      --skip-import-check)
        RUN_IMPORT_CHECK=0
        ;;
      --artifact-root)
        ARTIFACT_ROOT="$2"
        WHEELHOUSE_DIR="$ARTIFACT_ROOT/wheelhouse"
        REQUIREMENT_BUNDLE="$ARTIFACT_ROOT/requirements-target.txt"
        MODEL_STAGE_ROOT="$ARTIFACT_ROOT/models"
        shift
        ;;
      --container-asset-root)
        CONTAINER_ASSET_ROOT="$2"
        shift
        ;;
      --container-model-root)
        CONTAINER_MODEL_ROOT="$2"
        shift
        ;;
      --env-name)
        CONTAINER_ENV_NAME="$2"
        shift
        ;;
      -y|--yes)
        AUTO_YES=1
        ;;
      -h|--help)
        print_help
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
    shift
  done
}

sanitize_model_name() {
  local value="$1"
  value="${value##*/}"
  value="${value%/}"
  printf '%s\n' "$value"
}

ssh_target() {
  printf '%s@%s\n' "$CONTAINER_USER" "$CONTAINER_HOST"
}

bastion_ssh_args() {
  printf '%s\0' \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new
}

container_ssh_args() {
  printf '%s\0' \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -p "$CONTAINER_PORT"
}

run_bastion_cmd() {
  local -a args=()
  while IFS= read -r -d '' entry; do
    args+=("$entry")
  done < <(bastion_ssh_args)
  ssh "${args[@]}" "$BASTION_ALIAS" "$@"
}

run_container_cmd() {
  local target
  target="$(ssh_target)"
  local -a args=(ssh)
  while IFS= read -r -d '' entry; do
    args+=("$entry")
  done < <(container_ssh_args)
  run_bastion_cmd "${args[@]}" "$target" "$@"
}

copy_bastion_stage_to_container() {
  local stage_src="$1"
  local dst="$2"
  local is_dir="$3"
  local delete_mode="${4:-0}"

  if [[ "$is_dir" == "1" ]]; then
    if [[ "$delete_mode" == "1" ]]; then
      run_container_cmd rm -rf "$dst"
    fi
    run_container_cmd mkdir -p "$dst"
    run_bastion_cmd scp -q -P "$CONTAINER_PORT" -r "$stage_src/." "$(ssh_target):$dst"
    return 0
  fi

  run_container_cmd mkdir -p "$(dirname -- "$dst")"
  if [[ "$delete_mode" == "1" ]]; then
    run_container_cmd rm -f "$dst"
  fi
  run_bastion_cmd scp -q -P "$CONTAINER_PORT" "$stage_src" "$(ssh_target):$dst"
}

sync_to_container() {
  local src="$1"
  local dst="$2"
  local delete_mode="${3:-0}"
  local follow_links="${4:-0}"
  local stage_dst="$BASTION_STAGE_ROOT/staging$dst"
  local is_dir=0

  if [[ "$src" == */ ]]; then
    is_dir=1
  fi

  local -a rsync_args=(
    -az
    --info=progress2
  )

  if [[ "$follow_links" == "1" ]]; then
    rsync_args+=(-L)
  fi

  if [[ "$delete_mode" == "1" ]]; then
    rsync_args+=(--delete)
  fi

  run_bastion_cmd mkdir -p "$(dirname -- "$stage_dst")"
  rsync "${rsync_args[@]}" "$src" "$BASTION_ALIAS:$stage_dst"
  copy_bastion_stage_to_container "$stage_dst" "$dst" "$is_dir" "$delete_mode"
}

sync_repo_to_container() {
  local src="$1"
  local dst="$2"
  local stage_dst="$BASTION_STAGE_ROOT/staging$dst"
  local -a excludes=(
    --exclude .git
    --exclude .venv
    --exclude __pycache__
    --exclude .pytest_cache
    --exclude .mypy_cache
    --exclude .ruff_cache
    --exclude build
    --exclude dist
    --exclude '*.pyc'
  )

  run_bastion_cmd mkdir -p "$(dirname -- "$stage_dst")"
  rsync -az --delete --info=progress2 "${excludes[@]}" "$src" "$BASTION_ALIAS:$stage_dst"
  copy_bastion_stage_to_container "$stage_dst" "$dst" 1 1
}

ensure_local_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "$(command -v python3)"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "$(command -v python)"
    return 0
  fi
  fail "python3 or python is required on the local machine"
}

ensure_local_python_module() {
  local module_name="$1"
  local package_name="$2"
  local python_bin="$3"

  if "$python_bin" -c "import $module_name" >/dev/null 2>&1; then
    return 0
  fi

  if ! ask_yes_no "Install local helper package '$package_name' into the current user site-packages?"; then
    fail "Local Python module missing: $module_name"
  fi

  "$python_bin" -m pip install --user "$package_name"
}

build_target_requirement_bundle() {
  local python_bin="$1"

  mkdir -p "$ARTIFACT_ROOT"

  "$python_bin" - <<'PY' \
    "$WORKSPACE_ROOT" \
    "$REQUIREMENT_BUNDLE" \
    "$TARGET_PLATFORM_MACHINE" \
    "$TARGET_SYS_PLATFORM" \
    "$TARGET_PLATFORM_SYSTEM" \
    "$TARGET_PYTHON_VERSION_DOTTED" \
    "$TARGET_PYTHON_FULL_VERSION"
from pathlib import Path
import sys

from packaging.requirements import Requirement

workspace_root = Path(sys.argv[1])
output_path = Path(sys.argv[2])
platform_machine = sys.argv[3]
sys_platform = sys.argv[4]
platform_system = sys.argv[5]
python_version = sys.argv[6]
python_full_version = sys.argv[7]

input_files = [
    workspace_root / "vllm-hust" / "requirements" / "common.txt",
    workspace_root / "vllm-hust" / "requirements" / "build.txt",
    workspace_root / "vllm-ascend-hust" / "requirements.txt",
]

supplemental_requirements = [
  "annotated-doc>=0.0.2",
  "annotated-types>=0.7.0",
  "aiohappyeyeballs>=2.4.0",
  "aiosignal>=1.3.1",
  "async-timeout>=4.0.3",
  "anyio>=4.8.0",
  "attrs>=23.2.0",
  "certifi>=2024.7.4",
  "charset-normalizer>=3.4.0",
  "click>=8.1.8",
  "dnspython>=2.7.0",
  "distro>=1.9.0",
  "email-validator>=2.2.0",
  "filelock>=3.16.1",
  "frozenlist>=1.5.0",
  "fsspec>=2024.6.1",
  "h11>=0.14.0",
  "httpcore>=1.0.7",
  "httpx>=0.28.1",
  "huggingface-hub==0.34.4",
  "idna>=3.10",
  "jiter>=0.8.2",
  "MarkupSafe>=3.0.2",
  "multidict>=6.1.0",
  "orjson>=3.10.15",
  "propcache>=0.2.0",
  "pydantic-core==2.41.5",
  "python-dotenv>=1.0.1",
  "python-multipart>=0.0.20",
  "safetensors>=0.4.3",
  "sniffio>=1.3.1",
  "starlette>=0.40.0,<0.51.0",
  "tokenizers>=0.22.0,<=0.23.0",
  "typing-inspection>=0.4.0",
  "urllib3>=2.2.3",
  "uvicorn>=0.34.0",
  "websockets>=15.0",
  "yarl>=1.18.0",
]

skip_names = {
    "torch",
    "torch-npu",
    "torch_npu",
    "torchaudio",
    "torchvision",
    "pip",
}

optional_names_to_skip = {
    ("aarch64", "xgrammar"),
    ("aarch64", "arctic-inference"),
  ("aarch64", "triton-ascend"),
    ("aarch64", "lm-format-enforcer"),
    ("aarch64", "outlines_core"),
  ("aarch64", "compressed-tensors"),
  ("aarch64", "compressed_tensors"),
  ("aarch64", "mistral-common"),
  ("aarch64", "mistral_common"),
  ("aarch64", "depyf"),
  ("aarch64", "model-hosting-container-standards"),
  ("aarch64", "mcp"),
  ("aarch64", "opentelemetry-sdk"),
  ("aarch64", "opentelemetry-api"),
  ("aarch64", "opentelemetry-exporter-otlp"),
  ("aarch64", "opentelemetry-semantic-conventions-ai"),
  ("aarch64", "anthropic"),
}

target_specific_overrides = {
  ("aarch64", "fastapi"): "fastapi<0.124.0",
  ("aarch64", "setuptools-scm"): "setuptools-scm==8.1.0",
}

marker_env = {
    "implementation_name": "cpython",
    "implementation_version": python_full_version,
    "os_name": "posix",
    "platform_machine": platform_machine,
    "platform_release": "",
    "platform_system": platform_system,
    "platform_version": "",
    "python_full_version": python_full_version,
    "python_version": python_version,
    "sys_platform": sys_platform,
    "extra": "",
}

requirements = []
seen = set()

for path in input_files:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--"):
            continue
        if " #" in line:
            line = line.split(" #", 1)[0].rstrip()
        req = Requirement(line)
        if req.marker and not req.marker.evaluate(marker_env):
            continue
        if req.name in skip_names:
            continue
        if (platform_machine, req.name) in optional_names_to_skip:
          continue
        override = target_specific_overrides.get((platform_machine, req.name))
        if override is not None:
          req = Requirement(override)
        normalized = str(req)
        if normalized not in seen:
            seen.add(normalized)
            requirements.append(normalized)

    for raw_requirement in supplemental_requirements:
      req = Requirement(raw_requirement)
      normalized = str(req)
      if normalized not in seen:
        seen.add(normalized)
        requirements.append(normalized)

output_path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
PY
}

download_requirement() {
  local python_bin="$1"
  local requirement="$2"

  if "$python_bin" -m pip download \
      --dest "$WHEELHOUSE_DIR" \
      --platform "$TARGET_PLATFORM" \
      --python-version "$TARGET_PYTHON_VERSION" \
      --implementation "$TARGET_IMPLEMENTATION" \
      --abi "$TARGET_ABI" \
      --only-binary=:all: \
      --no-deps \
      "$requirement" >/dev/null; then
    return 0
  fi

  if "$python_bin" -m pip download \
      --dest "$WHEELHOUSE_DIR" \
      --no-binary=:all: \
      --no-deps \
      "$requirement" >/dev/null; then
    return 0
  fi

  return 1
}

prepare_wheelhouse() {
  local python_bin="$1"
  local requirement
  local -a failures=()
  local -a skipped_optional=(
    "xgrammar (structured outputs backend; skipped on aarch64 offline path)"
    "arctic-inference (suffix speculative decoding; skipped on aarch64 offline path)"
    "triton-ascend (optional Triton kernels; skipped on aarch64 offline path)"
    "lm-format-enforcer (structured outputs backend; skipped on aarch64 offline path)"
    "outlines_core (structured outputs backend; skipped on aarch64 offline path)"
    "compressed-tensors (quantization support; skipped on aarch64 offline path)"
    "mistral-common (Mistral-specific support; skipped on aarch64 offline path)"
    "depyf (compile/debug helper; skipped on aarch64 offline path)"
    "model-hosting-container-standards (serving integration; skipped on aarch64 offline path)"
    "mcp (serving integration; skipped on aarch64 offline path)"
    "OpenTelemetry packages (observability integration; skipped on aarch64 offline path)"
    "anthropic (serving integration; skipped on aarch64 offline path)"
  )

  mkdir -p "$WHEELHOUSE_DIR"
  rm -f "$ARTIFACT_ROOT/download-failures.txt"

  build_target_requirement_bundle "$python_bin"

  if [[ "$TARGET_PLATFORM_MACHINE" == "aarch64" ]]; then
    for requirement in "${skipped_optional[@]}"; do
      log "Skipping optional dependency $requirement"
    done
  fi

  while IFS= read -r requirement; do
    [[ -z "$requirement" ]] && continue
    log "Downloading $requirement for $TARGET_PLATFORM/$TARGET_ABI"
    if ! download_requirement "$python_bin" "$requirement"; then
      failures+=("$requirement")
    fi
  done < "$REQUIREMENT_BUNDLE"

  if (( ${#failures[@]} > 0 )); then
    printf '%s\n' "${failures[@]}" > "$ARTIFACT_ROOT/download-failures.txt"
    fail "Failed to prepare some offline dependencies. See $ARTIFACT_ROOT/download-failures.txt"
  fi
}

ensure_huggingface_hub() {
  local python_bin="$1"
  ensure_local_python_module huggingface_hub 'huggingface_hub[hf_transfer]' "$python_bin"
}

download_model_locally() {
  local python_bin="$1"
  local model_dir
  local cache_repo_dir=""
  local cached_snapshot=""

  if (( SYNC_MODEL == 0 )); then
    MODEL_LOCAL_PATH=""
    return 0
  fi

  if [[ -n "$MODEL_LOCAL_PATH" ]]; then
    [[ -d "$MODEL_LOCAL_PATH" ]] || fail "Local model directory not found: $MODEL_LOCAL_PATH"
    MODEL_LOCAL_PATH="$(cd -- "$MODEL_LOCAL_PATH" && pwd)"
    return 0
  fi

  [[ -n "$MODEL_ID" ]] || fail "Provide --model-id or --model-path, or use --skip-model"

  cache_repo_dir="$HOME/.cache/huggingface/hub/models--${MODEL_ID//\//--}"
  if [[ -d "$cache_repo_dir/snapshots" ]]; then
    cached_snapshot="$(find "$cache_repo_dir/snapshots" -mindepth 1 -maxdepth 1 -type d | head -n 1 || true)"
    if [[ -n "$cached_snapshot" ]]; then
      log "Reusing cached Hugging Face snapshot for $MODEL_ID"
      MODEL_LOCAL_PATH="$cached_snapshot"
      return 0
    fi
  fi

  ensure_huggingface_hub "$python_bin"
  mkdir -p "$MODEL_STAGE_ROOT"
  model_dir="$MODEL_STAGE_ROOT/$(sanitize_model_name "$MODEL_ID")"

  "$python_bin" - <<'PY' \
    "$MODEL_ID" \
    "$MODEL_REVISION" \
    "$model_dir" \
    "$MODEL_ALLOW_PATTERNS" \
    "$MODEL_IGNORE_PATTERNS"
import os
import sys

from huggingface_hub import snapshot_download

model_id = sys.argv[1]
revision = sys.argv[2] or None
local_dir = sys.argv[3]
allow_patterns = [item for item in sys.argv[4].split(',') if item] or None
ignore_patterns = [item for item in sys.argv[5].split(',') if item] or None

os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

snapshot_download(
    repo_id=model_id,
    revision=revision,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    resume_download=True,
    allow_patterns=allow_patterns,
    ignore_patterns=ignore_patterns,
)
PY

  MODEL_LOCAL_PATH="$model_dir"
}

resolved_model_name() {
  if [[ -n "$MODEL_ID" ]]; then
    sanitize_model_name "$MODEL_ID"
    return 0
  fi

  sanitize_model_name "$MODEL_LOCAL_PATH"
}

sync_local_repositories() {
  local repo_name
  local src
  local dst

  (( SYNC_REPOS == 1 )) || return 0

  for repo_name in "${LOCAL_REPOS[@]}"; do
    src="$WORKSPACE_ROOT/$repo_name/"
    [[ -d "$src" ]] || fail "Required local repository not found: $WORKSPACE_ROOT/$repo_name"
    dst="$CONTAINER_WORKSPACE_ROOT/$repo_name/"
    log "Syncing repository $repo_name to the container"
    sync_repo_to_container "$src" "$dst"
  done
}

sync_offline_artifacts() {
  (( PREPARE_WHEELHOUSE == 1 )) || return 0
  log "Syncing offline wheelhouse to the container"
  sync_to_container "$WHEELHOUSE_DIR/" "$CONTAINER_ASSET_ROOT/wheelhouse/" 1
  sync_to_container "$REQUIREMENT_BUNDLE" "$CONTAINER_ASSET_ROOT/requirements-target.txt" 0
}

sync_model_assets() {
  local model_name
  (( SYNC_MODEL == 1 )) || return 0

  model_name="$(resolved_model_name)"
  log "Syncing model directory $model_name to the container"
  sync_to_container "$MODEL_LOCAL_PATH/" "$CONTAINER_MODEL_ROOT/$model_name/" 1 1
}

install_in_container() {
  local model_name="__NO_MODEL__"
  if (( SYNC_MODEL == 1 )); then
    model_name="$(resolved_model_name)"
  fi

  (( INSTALL_IN_CONTAINER == 1 )) || return 0

  log "Running offline install inside the container"
  run_container_cmd bash -s -- \
    "$CONTAINER_ENV_NAME" \
    "$CONTAINER_ASSET_ROOT" \
    "$CONTAINER_MODEL_ROOT" \
    "$model_name" \
    "$RUN_IMPORT_CHECK" <<'SH'
set -euo pipefail

env_name="$1"
asset_root="$2"
model_root="$3"
model_name="$4"
run_import_check="$5"

if [[ "$model_name" == "__NO_MODEL__" ]]; then
  model_name=""
fi

if [[ -d /workspace/miniconda3 ]] && [[ ! -e /home/shuhao/miniconda3 ]]; then
  ln -sfn /workspace/miniconda3 /home/shuhao/miniconda3
fi

find_first_executable() {
  local path=""
  for path in "$@"; do
    if [[ -n "$path" && -x "$path" ]]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

find_first_directory() {
  local path=""
  for path in "$@"; do
    if [[ -n "$path" && -d "$path" ]]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

conda_root="$(find_first_directory \
  /home/shuhao/miniconda3 \
  /workspace/miniconda3 \
  /opt/conda \
  "$HOME/miniconda3")" || {
  echo "[offline-sync] unable to locate a Miniconda root in the container" >&2
  exit 1
}

base_python="$(find_first_executable \
  "$conda_root/bin/python" \
  "$conda_root/bin/python3" \
  "$conda_root/bin/python3.13" \
  "$conda_root/bin/python3.12" \
  "$conda_root/bin/python3.11" \
  "$conda_root/bin/python3.10")" || {
  echo "[offline-sync] unable to locate the base Miniconda Python under: $conda_root" >&2
  exit 1
}

env_root="$conda_root/envs/$env_name"
if [[ ! -d "$env_root" ]]; then
  echo "[offline-sync] conda env not found in container: $env_name" >&2
  exit 1
fi

env_python="$(find_first_executable \
  "$env_root/bin/python" \
  "$env_root/bin/python3" \
  "$env_root/bin/python3.10" \
  "$env_root/bin/python3.11" \
  "$env_root/bin/python3.12" \
  "$env_root/bin/python3.13")" || {
  echo "[offline-sync] unable to locate the env Python under: $env_root" >&2
  exit 1
}

run_env_python() {
  "$env_python" "$@"
}

prepend_ld_library_path() {
  local candidate=""
  for candidate in "$@"; do
    if [[ -d "$candidate" ]]; then
      case ":${LD_LIBRARY_PATH:-}:" in
        *":$candidate:"*) ;;
        *) LD_LIBRARY_PATH="$candidate${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
      esac
    fi
  done
}

if [[ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]]; then
  # The offline install and later runtime checks need the Ascend shared libraries.
  set +u
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
  set -u
fi

if [[ -f /usr/local/Ascend/nnal/atb/set_env.sh ]]; then
  set +u
  source /usr/local/Ascend/nnal/atb/set_env.sh
  set -u
fi

# The stock toolkit env scripts in this container do not expose all runtime
# libraries needed by torch_npu and npu-smi.
export LD_LIBRARY_PATH="/usr/local/Ascend/driver/lib64/driver:/usr/local/Ascend/ascend-toolkit/latest/aarch64-linux/lib64:/usr/local/Ascend/ascend-toolkit/latest/aarch64-linux/devlib:/usr/local/Ascend/ascend-toolkit/latest/compiler/lib64:${LD_LIBRARY_PATH:-}"
prepend_ld_library_path /usr/local/lib64 /usr/local/lib
prepend_ld_library_path \
  /usr/local/Ascend/nnal/atb/latest/atb/cxx_abi_0/lib \
  /usr/local/Ascend/nnal/atb/latest/atb/cxx_abi_1/lib
for atb_lib_dir in /usr/local/Ascend/nnal/atb/*/atb/cxx_abi_0/lib /usr/local/Ascend/nnal/atb/*/atb/cxx_abi_1/lib; do
  prepend_ld_library_path "$atb_lib_dir"
done
export LD_LIBRARY_PATH

if [[ -f "$asset_root/requirements-target.txt" ]]; then
  if find "$asset_root/wheelhouse" -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' -o -name '*.zip' \) | grep -q .; then
    run_env_python -m pip install \
      --no-index \
      --find-links "$asset_root/wheelhouse" \
      --no-build-isolation \
      -r "$asset_root/requirements-target.txt"
  fi
fi

if [[ -f /workspace/ascend-runtime-manager/pyproject.toml ]]; then
  run_env_python -m pip install -e /workspace/ascend-runtime-manager --no-build-isolation --no-deps
fi

if [[ -f /workspace/vllm-hust-benchmark/pyproject.toml ]]; then
  run_env_python -m pip install -e /workspace/vllm-hust-benchmark --no-build-isolation --no-deps
fi

VLLM_TARGET_DEVICE=empty \
  TORCH_DEVICE_BACKEND_AUTOLOAD=0 \
  run_env_python -m pip install -e /workspace/vllm-hust --no-build-isolation --no-deps

COMPILE_CUSTOM_KERNELS=0 \
  TORCH_DEVICE_BACKEND_AUTOLOAD=0 \
  run_env_python -m pip install -e /workspace/vllm-ascend-hust --no-build-isolation --no-deps

if [[ "$run_import_check" == "1" ]]; then
  run_env_python - <<'PY'
import importlib.util

modules = ["torch", "torch_npu", "vllm"]
for module_name in modules:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        raise SystemExit(f"[offline-sync] missing module after install: {module_name}")
    print(f"[offline-sync] {module_name}: {spec.origin}")
PY
fi

if [[ -n "$model_name" ]]; then
  echo "[offline-sync] model ready at: $model_root/$model_name"
fi
SH
}

main() {
  local python_bin

  parse_args "$@"

  require_cmd ssh
  require_cmd rsync
  python_bin="$(ensure_local_python)"
  ensure_local_python_module packaging packaging "$python_bin"

  mkdir -p "$ARTIFACT_ROOT"

  if (( PREPARE_WHEELHOUSE == 1 )); then
    prepare_wheelhouse "$python_bin"
  fi

  if (( SYNC_MODEL == 1 )); then
    download_model_locally "$python_bin"
  fi

  sync_local_repositories
  sync_offline_artifacts
  sync_model_assets
  install_in_container

  log "Completed offline sync workflow"
}

main "$@"