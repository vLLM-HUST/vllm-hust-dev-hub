#!/usr/bin/env bash
# quickstart.sh — Interactive one-command bootstrap: clone repos + conda env + container setup.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"
CLONE_SCRIPT="$SCRIPT_DIR/clone-workspace-repos.sh"
MINICONDA_INSTALL_SCRIPT="$SCRIPT_DIR/install-miniconda.sh"
MANAGER_REPO="$WORKSPACE_ROOT/ascend-runtime-manager"
MANAGER_REPO_SSH_URL="git@github.com:vLLM-HUST/ascend-runtime-manager.git"
MANAGER_REPO_HTTPS_URL="https://github.com/vLLM-HUST/ascend-runtime-manager.git"
CONTAINER_NAME_SCRIPT="$SCRIPT_DIR/container-name.sh"
if [[ ! -f "$CONTAINER_NAME_SCRIPT" ]] && command -v git >/dev/null 2>&1; then
  QUICKSTART_GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "$QUICKSTART_GIT_ROOT" && -f "$QUICKSTART_GIT_ROOT/scripts/container-name.sh" ]]; then
    CONTAINER_NAME_SCRIPT="$QUICKSTART_GIT_ROOT/scripts/container-name.sh"
  fi
fi

# shellcheck source=scripts/container-name.sh
source "$CONTAINER_NAME_SCRIPT"

# ── CANN version detection ────────────────────────────────────────────────────
# Detects the installed CANN toolkit major version (8 or 9) by reading
# version.info from well-known toolkit paths.  Used to select the matching
# manifest (torch/torch_npu stack) and decide whether CANN-9-specific patches
# (e.g. triton-ascend npu_utils.cpp) are required.
detect_cann_major_version() {
  local candidates=(
    "${ASCEND_HOME_PATH:-}/version.info"
    "${ASCEND_HOME_PATH:-}/runtime/version.info"
    "${ASCEND_HOME_PATH:-}/compiler/version.info"
    "${ASCEND_HOME_PATH:-}/opp/version.info"
    "/usr/local/Ascend/cann/version.info"
    "/usr/local/Ascend/cann/runtime/version.info"
    "/usr/local/Ascend/cann/compiler/version.info"
    "/usr/local/Ascend/cann/opp/version.info"
    "/usr/local/Ascend/cann-9.0.0/version.info"
    "/usr/local/Ascend/cann-9.0.0/runtime/version.info"
    "/usr/local/Ascend/cann-9.0.0/compiler/version.info"
    "/usr/local/Ascend/cann-9.0.0/opp/version.info"
    "/usr/local/Ascend/ascend-toolkit/latest/version.info"
    "/usr/local/Ascend/ascend-toolkit/latest/runtime/version.info"
    "/usr/local/Ascend/ascend-toolkit/latest/compiler/version.info"
    "/usr/local/Ascend/ascend-toolkit/latest/opp/version.info"
    "${CONDA_PREFIX:-}/Ascend/cann/version.info"
    "${CONDA_PREFIX:-}/Ascend/cann/runtime/version.info"
    "${CONDA_PREFIX:-}/Ascend/cann/compiler/version.info"
    "${CONDA_PREFIX:-}/Ascend/cann/opp/version.info"
  )
  local f ver major
  for f in "${candidates[@]}"; do
    if [[ -f "$f" ]]; then
      ver="$(grep -oP '[0-9]+\.[0-9]+(\.[0-9]+)?' "$f" 2>/dev/null | head -1)"
      if [[ -n "$ver" ]]; then
        major="${ver%%.*}"
        printf '%s\n' "$major"
        return 0
      fi
    fi
  done
  return 1
}

# Resolve the default manager manifest based on the detected CANN version.
# CANN 9.x → euleros-910b-cann9.json (torch 2.10.0, torch_npu 2.10.0)
# CANN 8.x or unknown → euleros-910b.json (torch 2.9.0, torch_npu 2.9.0)
resolve_default_manifest() {
  local cann_major
  cann_major="$(detect_cann_major_version 2>/dev/null || true)"
  case "$cann_major" in
    9)
      if [[ -f "$MANAGER_REPO/manifests/euleros-910b-cann9.json" ]]; then
        printf '%s\n' "$MANAGER_REPO/manifests/euleros-910b-cann9.json"
        return
      fi
      ;;
  esac
  printf '%s\n' "$MANAGER_REPO/manifests/euleros-910b.json"
}

MANAGER_MANIFEST_DEFAULT="$(resolve_default_manifest)"

ENV_NAME="vllm-hust-dev"
PYTHON_VERSION="3.11"
AUTO_YES=0
PERF_TIMESTAMPS="${HUST_DEV_HUB_PERF_TIMESTAMPS:-0}"
PERF_SUMMARY_LIMIT="${HUST_DEV_HUB_PERF_SUMMARY_LIMIT:-10}"
PERF_SUMMARY_PRINTED=0
declare -a PERF_SUMMARY_ENTRIES=()
DO_CLONE=0
DO_CONDA=0
DO_INSTALL=0
INSTALL_MODE="install"
INSTALL_SCOPE="core"
MENU_CONFIRMED=0
UPDATE_BASHRC=0
BASHRC_BEGIN="# >>> vllm-hust-dev-hub auto-activate >>>"
BASHRC_END="# <<< vllm-hust-dev-hub auto-activate <<<"
BASHRC_CONDA_INIT_BEGIN="# >>> vllm-hust-dev-hub conda-init >>>"
BASHRC_CONDA_INIT_END="# <<< vllm-hust-dev-hub conda-init <<<"
CONDA_MAIN_CHANNEL="https://repo.anaconda.com/pkgs/main"
CONDA_R_CHANNEL="https://repo.anaconda.com/pkgs/r"
CONDA_ASCEND_CHANNEL="https://repo.huaweicloud.com/ascend/repos/conda/"
CONDA_FORGE_MIRROR_CHANNEL="https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/"
CONDA_FORGE_FALLBACK_CHANNEL="conda-forge"
PIP_INDEX_MIRROR_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_ASCEND_TRITON_EXTRA_INDEX_URL="https://triton-ascend.osinfra.cn/pypi/simple"
QUICKSTART_SETUPTOOLS_VERSION="77.0.3"
ASCEND_PLUGIN_PYPI_PACKAGE="vllm-ascend-hust"
CURRENT_USER_NAME="$(id -un 2>/dev/null || printf '%s' "${USER:-}")"
CURRENT_USER_HOME="$(getent passwd "$CURRENT_USER_NAME" 2>/dev/null | cut -d: -f6 || true)"
if [[ -z "$CURRENT_USER_HOME" ]]; then
  CURRENT_USER_HOME="${HOME:-}"
fi
CURRENT_USER_CACHE_HOME="$CURRENT_USER_HOME/.cache"
CURRENT_USER_CONFIG_HOME="$CURRENT_USER_HOME/.config"
TOS_MARKER_ROOT="$CURRENT_USER_CONFIG_HOME/vllm-hust-dev-hub"
QUICKSTART_LOG_DIR_DEFAULT="$CURRENT_USER_CACHE_HOME/vllm-hust-dev-hub/logs"
QUICKSTART_LOG_DIR="${HUST_DEV_HUB_QUICKSTART_LOG_DIR:-$QUICKSTART_LOG_DIR_DEFAULT}"
QUICKSTART_LOG_FILE="${HUST_DEV_HUB_QUICKSTART_LOG_FILE:-}"
QUICKSTART_LOGGING_INITIALIZED=0
CONDA_RUN_STREAM_FLAG=""
CONTAINER_EXTRA_AUTH_KEYS_FILE="$WORKSPACE_ROOT/.ssh/vllm-ascend-extra-authorized_keys"
# Keep this human-readable default aligned with
# config/ascend-official-runtime-matrix.json. Formal evidence should set IMAGE
# to the matrix's immutable digest reference.
DEFAULT_ASCEND_CONTAINER_IMAGE="quay.io/ascend/vllm-ascend:v0.23.0-openeuler"
PIP_DEFAULTS_INITIALIZED=0
PIP_SELECTED_INDEX_URL=""
PIP_SELECTED_EXTRA_INDEX_URL=""
PIP_INSTALL_RETRIES=""
PIP_INSTALL_TIMEOUT=""
PIP_INSTALL_RESUME_RETRIES=""
QUICKSTART_START_EPOCH="$(date +%s)"
QUICKSTART_TOTAL_TIME_PRINTED=0
PIP_SUPPORTS_RESUME_RETRIES="unknown"
ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE=""
CONDA_BIN=""
CONDA_BASE=""
BROKEN_CONDA_PREFIX=""

if [[ "${HUST_DEV_HUB_UPDATE_BASHRC:-0}" == "1" ]]; then
  UPDATE_BASHRC=1
fi

print_help() {
  cat <<'EOF'
用法: bash scripts/quickstart.sh [选项]

选项:
  --clone                  同步工作区仓库。
  --conda                  创建或更新 conda 环境。
  --install                在已有 conda 环境中安装本地仓库。
  --install-mode MODE      安装模式: install 或 refresh (默认: install)。
  --install-scope SCOPE    安装范围: core 或 full (默认: core)。
  --ascend-lightweight     Ascend 插件使用轻量模式安装 (等价于 COMPILE_CUSTOM_KERNELS=0)。
  --ascend-custom-kernels VALUE
                           显式设置 Ascend 插件 COMPILE_CUSTOM_KERNELS 值。
  --all                    执行 clone + conda + install(core)。
  --env-name NAME          conda 环境名 (默认: vllm-hust-dev)。
  --python VERSION         conda 环境 Python 版本 (默认: 3.11)。
  --update-bashrc          更新 ~/.bashrc，在新交互 shell 自动激活 conda 环境。
  --perf-timestamps       为关键步骤开始阶段打印时间戳，用于性能分析（默认关闭）。
  -y, --yes                非交互模式；容器公钥可通过 VLLM_HUST_CONTAINER_PUBKEY 传入。
  -h, --help               显示本帮助。

未提供动作参数时，将进入交互式菜单。
交互菜单的选项 6 会创建或复用官方 Ascend Docker instance，并在检测到宿主机公钥材料时自动配置容器 SSH。
EOF
}

log() {
  printf '[quickstart] %s\n' "$1"
}

log_perf_step_start() {
  local description="$1"
  local timestamp=""

  if [[ "$PERF_TIMESTAMPS" != "1" ]]; then
    return 0
  fi

  timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
  printf '[quickstart][perf][%s] start: %s\n' "$timestamp" "$description"
}

log_perf_step_end() {
  local description="$1"
  local start_epoch="$2"
  local exit_code="${3:-0}"
  local timestamp=""
  local end_epoch=""
  local duration=""
  local status="ok"

  if [[ "$PERF_TIMESTAMPS" != "1" ]]; then
    return 0
  fi

  timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
  end_epoch="$(date +%s)"
  duration=$(( end_epoch - start_epoch ))
  if [[ "$exit_code" != "0" ]]; then
    status="failed($exit_code)"
  fi
  PERF_SUMMARY_ENTRIES+=("${duration}|${status}|${description}")
  printf '[quickstart][perf][%s] end: %s | duration=%ss | status=%s\n' \
    "$timestamp" "$description" "$duration" "$status"
}

print_perf_summary() {
  local limit="$PERF_SUMMARY_LIMIT"
  local sorted_entries=""
  local line=""
  local duration=""
  local status=""
  local description=""

  if [[ "$PERF_TIMESTAMPS" != "1" ]]; then
    return 0
  fi

  if (( PERF_SUMMARY_PRINTED == 1 )); then
    return 0
  fi

  PERF_SUMMARY_PRINTED=1

  if (( ${#PERF_SUMMARY_ENTRIES[@]} == 0 )); then
    printf '[quickstart][perf] summary: no recorded timed steps\n'
    return 0
  fi

  if [[ ! "$limit" =~ ^[0-9]+$ ]] || (( limit <= 0 )); then
    limit=10
  fi

  printf '[quickstart][perf] summary: top %s slowest recorded steps\n' "$limit"
  sorted_entries="$(printf '%s\n' "${PERF_SUMMARY_ENTRIES[@]}" | sort -t'|' -k1,1nr | head -n "$limit")"
  while IFS='|' read -r duration status description; do
    if [[ -z "$duration" && -z "$status" && -z "$description" ]]; then
      continue
    fi
    printf '[quickstart][perf] %ss | %s | %s\n' "$duration" "$status" "$description"
  done <<< "$sorted_entries"
}

print_perf_summary_on_exit() {
  local exit_code="$?"
  local end_epoch
  local duration

  if (( QUICKSTART_TOTAL_TIME_PRINTED == 0 )); then
    QUICKSTART_TOTAL_TIME_PRINTED=1
    end_epoch="$(date +%s)"
    duration=$(( end_epoch - QUICKSTART_START_EPOCH ))
    log "Total elapsed time: ${duration}s"
  fi

  print_perf_summary
  return "$exit_code"
}

# Install system-level build tools required for compiling C/C++ extensions
# (psutil, triton-ascend JIT, _C_ascend, etc.).  Supports dnf/yum (openEuler,
# RHEL, Fedora) and apt-get (Ubuntu, Debian).
ensure_system_build_packages() {
  local pkg_manager=""
  local packages=()
  local missing=()
  local pkg

  if command -v dnf >/dev/null 2>&1; then
    pkg_manager="dnf"
    packages=(gcc gcc-c++ python3-devel zlib-devel git make ccache)
  elif command -v yum >/dev/null 2>&1; then
    pkg_manager="yum"
    packages=(gcc gcc-c++ python3-devel zlib-devel git make ccache)
  elif command -v apt-get >/dev/null 2>&1; then
    pkg_manager="apt-get"
    packages=(gcc g++ python3-dev zlib1g-dev git make ccache)
  else
    log "Warning: no supported package manager found (dnf/yum/apt-get); skipping system package install"
    return 0
  fi

  # Check which packages are already installed
  for pkg in "${packages[@]}"; do
    if [[ "$pkg_manager" == "apt-get" ]]; then
      if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        missing+=("$pkg")
      fi
    else
      if ! rpm -q "$pkg" >/dev/null 2>&1; then
        missing+=("$pkg")
      fi
    fi
  done

  if (( ${#missing[@]} == 0 )); then
    log "System build packages already present ($pkg_manager): ${packages[*]}"
    return 0
  fi

  log "Installing missing system build packages via $pkg_manager: ${missing[*]}"
  if [[ "$pkg_manager" == "apt-get" ]]; then
    apt-get update -qq && apt-get install -y --no-install-recommends "${missing[@]}"
  else
    $pkg_manager install -y "${missing[@]}"
  fi
  log "System build packages installed successfully"
}

init_quickstart_logging() {
  local timestamp

  if (( QUICKSTART_LOGGING_INITIALIZED == 1 )); then
    return 0
  fi

  mkdir -p "$QUICKSTART_LOG_DIR"

  if [[ -z "$QUICKSTART_LOG_FILE" ]]; then
    timestamp="$(date +%Y%m%d-%H%M%S)"
    QUICKSTART_LOG_FILE="$QUICKSTART_LOG_DIR/quickstart-${timestamp}.log"
  fi

  exec > >(tee -a "$QUICKSTART_LOG_FILE") 2>&1
  QUICKSTART_LOGGING_INITIALIZED=1
  log "Writing console output to log file: $QUICKSTART_LOG_FILE"
}

is_valid_ssh_public_key() {
  local key_line="$1"

  [[ "$key_line" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com)[[:space:]]+[A-Za-z0-9+/=]+([[:space:]].*)?$ ]]
}

ensure_container_extra_key_dir() {
  mkdir -p "$(dirname -- "$CONTAINER_EXTRA_AUTH_KEYS_FILE")"
}

append_container_public_key() {
  local public_key="$1"
  local tmp_file

  ensure_container_extra_key_dir
  tmp_file="$(mktemp)"

  {
    if [[ -f "$CONTAINER_EXTRA_AUTH_KEYS_FILE" ]]; then
      sed -e '$a\' "$CONTAINER_EXTRA_AUTH_KEYS_FILE"
    fi
    printf '%s\n' "$public_key"
  } | awk 'NF && !seen[$0]++' > "$tmp_file"

  chmod 600 "$tmp_file"
  mv "$tmp_file" "$CONTAINER_EXTRA_AUTH_KEYS_FILE"
}

prompt_and_store_container_public_key() {
  local public_key="${VLLM_HUST_CONTAINER_PUBKEY:-}"

  if [[ -n "$public_key" ]]; then
    if ! is_valid_ssh_public_key "$public_key"; then
      echo "[quickstart] 环境变量 VLLM_HUST_CONTAINER_PUBKEY 不是有效的 SSH 公钥。" >&2
      return 2
    fi
    append_container_public_key "$public_key"
    log "已将环境变量中的 SSH 公钥写入 $CONTAINER_EXTRA_AUTH_KEYS_FILE"
    return 0
  fi

  if (( AUTO_YES == 1 )); then
    return 0
  fi

  if ! ask_yes_no "是否现在粘贴一个宿主机 SSH 公钥，用于直接连接 Docker instance？"; then
    return 0
  fi

  while true; do
    echo "请粘贴一整行 SSH 公钥，然后回车提交。直接回车表示跳过。"
    read -r public_key

    if [[ -z "$public_key" ]]; then
      log "已跳过额外 SSH 公钥录入。"
      return 0
    fi

    if is_valid_ssh_public_key "$public_key"; then
      append_container_public_key "$public_key"
      log "已将 SSH 公钥写入 $CONTAINER_EXTRA_AUTH_KEYS_FILE"
      return 0
    fi

    echo "[quickstart] 输入看起来不是有效的 SSH 公钥，请重新粘贴。" >&2
  done
}

prompt_for_ascend_container_name() {
  local configured_name=""
  local default_name
  local selected_name=""

  if configured_name="$(configured_vllm_engine_container_name)"; then
    validate_docker_container_name "$configured_name"
    printf '%s\n' "$configured_name"
    return 0
  fi

  default_name="$(container_name_from_image_and_user "${IMAGE:-$DEFAULT_ASCEND_CONTAINER_IMAGE}" "$CURRENT_USER_NAME")"
  while true; do
    read -r -p "Press Enter to use the default [$default_name], or input a container name: " selected_name
    selected_name="${selected_name:-$default_name}"
    if validate_docker_container_name "$selected_name"; then
      printf '%s\n' "$selected_name"
      return 0
    fi
  done
}

ensure_ascend_container_manager_source() {
  local manager_module="$MANAGER_REPO/src/hust_ascend_manager/cli.py"

  if [[ -f "$manager_module" ]]; then
    return 0
  fi

  if [[ -e "$MANAGER_REPO" ]]; then
    echo "[quickstart] $MANAGER_REPO 已存在，但缺少 $manager_module。请修复或移走该目录后重试。" >&2
    return 1
  fi

  if ! command -v git >/dev/null 2>&1; then
    echo "[quickstart] 选项 6 需要 ascend-runtime-manager，但系统中未找到 git。" >&2
    return 1
  fi

  log "未检测到 ascend-runtime-manager，正在克隆容器管理依赖。"
  if env -u LD_LIBRARY_PATH git clone "$MANAGER_REPO_SSH_URL" "$MANAGER_REPO"; then
    return 0
  fi

  log "SSH 克隆失败，改用 HTTPS 重试。"
  if env -u LD_LIBRARY_PATH git clone "$MANAGER_REPO_HTTPS_URL" "$MANAGER_REPO"; then
    return 0
  fi

  echo "[quickstart] 无法克隆 ascend-runtime-manager；请检查 GitHub 网络或 SSH 凭据后重试。" >&2
  return 1
}

run_conda_cmd() {
  # Keep conda operations isolated from external PYTHONPATH overrides.
  local conda_runner=(conda)

  if [[ -n "$CONDA_BIN" ]]; then
    conda_runner=("$CONDA_BIN")
  fi

  mkdir -p "$CURRENT_USER_CACHE_HOME" "$CURRENT_USER_CONFIG_HOME"
  (
    unset PYTHONPATH
    env \
      HOME="$CURRENT_USER_HOME" \
      XDG_CACHE_HOME="$CURRENT_USER_CACHE_HOME" \
      XDG_CONFIG_HOME="$CURRENT_USER_CONFIG_HOME" \
      "${conda_runner[@]}" "$@"
  )
}

get_conda_env_prefix() {
  local env_name="$1"

  run_conda_cmd env list | awk -v target_env="$env_name" '$1 == target_env { print $NF; exit }'
}

get_conda_env_python_bin() {
  local env_name="$1"
  local env_prefix=""

  env_prefix="$(get_conda_env_prefix "$env_name")"
  if [[ -z "$env_prefix" ]]; then
    return 1
  fi

  printf '%s\n' "$env_prefix/bin/python"
}

conda_package_installed_in_env() {
  local env_name="$1"
  local package_name="$2"

  run_conda_cmd list -n "$env_name" | awk -v package_name="$package_name" '$1 == package_name { found = 1 } END { exit(found ? 0 : 1) }'
}

remove_conflicting_conda_torch_packages_in_env() {
  local env_name="$1"
  local package_name
  local packages_to_remove=()

  for package_name in pytorch pytorch-cpu pytorch-mutex; do
    if conda_package_installed_in_env "$env_name" "$package_name"; then
      packages_to_remove+=("$package_name")
    fi
  done

  if (( ${#packages_to_remove[@]} == 0 )); then
    return 0
  fi

  log "Removing conflicting conda torch packages from '$env_name': ${packages_to_remove[*]}"
  run_with_heartbeat \
    "removing conflicting conda torch packages from $env_name" \
    run_conda_cmd remove -n "$env_name" -y "${packages_to_remove[@]}"
}

detect_conda_run_stream_flag() {
  if [[ -n "$CONDA_RUN_STREAM_FLAG" ]]; then
    return 0
  fi

  local help_text
  help_text="$(run_conda_cmd run --help 2>/dev/null || true)"
  if grep -q -- '--no-capture-output' <<< "$help_text"; then
    CONDA_RUN_STREAM_FLAG="--no-capture-output"
  elif grep -q -- '--live-stream' <<< "$help_text"; then
    CONDA_RUN_STREAM_FLAG="--live-stream"
  else
    CONDA_RUN_STREAM_FLAG=""
  fi
}

run_conda_env_cmd() {
  local env_name="$1"
  shift
  local env_prefix=""
  local runtime_ld_library_path=""
  local wrapped_cmd=("$@")

  detect_conda_run_stream_flag
  env_prefix="$(get_conda_env_prefix "$env_name")"
  runtime_ld_library_path="$(build_runtime_ld_library_path_for_env "$env_name" || true)"
  if [[ -n "$runtime_ld_library_path" ]]; then
    wrapped_cmd=(env "LD_LIBRARY_PATH=$runtime_ld_library_path" "$@")
  elif [[ -n "$env_prefix" && -d "$env_prefix/lib" ]]; then
    wrapped_cmd=(env "LD_LIBRARY_PATH=$env_prefix/lib" "$@")
  fi

  if [[ -n "$CONDA_RUN_STREAM_FLAG" ]]; then
    run_conda_cmd run "$CONDA_RUN_STREAM_FLAG" -n "$env_name" "${wrapped_cmd[@]}"
  else
    run_conda_cmd run -n "$env_name" "${wrapped_cmd[@]}"
  fi
}

build_runtime_ld_library_path_for_env() {
  local env_name="$1"
  local env_prefix=""
  local raw_ld_library_path="${LD_LIBRARY_PATH:-}"
  local path_entries=()
  local prepend_entries=()
  local filtered_entries=()
  local combined_entries=()
  local entry
  local env_python_bin=""
  local torch_lib=""
  local torch_npu_lib=""
  local ascend_root=""
  local ascend_runtime_dir=""
  local ascend_runtime_candidates=()
  local seen_entries=""

  env_prefix="$(get_conda_env_prefix "$env_name" 2>/dev/null || true)"
  if [[ -z "$env_prefix" || ! -d "$env_prefix" ]]; then
    return 0
  fi

  prepend_entries+=("$env_prefix/lib")

  env_python_bin="$(get_conda_env_python_bin "$env_name" 2>/dev/null || true)"
  if [[ -n "$env_python_bin" && -x "$env_python_bin" ]]; then
    torch_lib="$("$env_python_bin" - <<'PY' 2>/dev/null || true
import importlib.util
import os

spec = importlib.util.find_spec("torch")
if spec and spec.origin:
    print(os.path.join(os.path.dirname(spec.origin), "lib"))
PY
)"
    torch_npu_lib="$("$env_python_bin" - <<'PY' 2>/dev/null || true
import importlib.util
import os

spec = importlib.util.find_spec("torch_npu")
if spec and spec.origin:
    print(os.path.join(os.path.dirname(spec.origin), "lib"))
PY
)"
  fi

  if [[ -n "$torch_lib" && -d "$torch_lib" ]]; then
    prepend_entries+=("$torch_lib")
  fi
  if [[ -n "$torch_npu_lib" && -d "$torch_npu_lib" ]]; then
    prepend_entries+=("$torch_npu_lib")
  fi

  # A user-space CANN install lives inside the conda environment.  Conda's
  # activate hook may discover it, but run_conda_env_cmd deliberately supplies
  # a sanitized LD_LIBRARY_PATH and would otherwise hide those paths again.
  # Keep the driver support libraries before CANN, matching ascend-manager's
  # runtime ordering, then include the layouts used by both pip and conda CANN.
  for ascend_runtime_dir in \
    /usr/local/Ascend/driver/lib64/common \
    /usr/local/Ascend/driver/lib64/driver \
    /usr/local/Ascend/driver/lib64; do
    [[ -d "$ascend_runtime_dir" ]] && prepend_entries+=("$ascend_runtime_dir")
  done

  for ascend_root in \
    "$env_prefix/Ascend/cann" \
    "$env_prefix/Ascend/ascend-toolkit/latest"; do
    [[ -d "$ascend_root" ]] || continue
    ascend_runtime_candidates=(
      "$ascend_root/runtime/lib64"
      "$ascend_root/lib64"
      "$ascend_root/compiler/lib64"
      "$ascend_root/hccl/lib64"
      "$ascend_root/aarch64-linux/lib64"
    )
    for ascend_runtime_dir in "${ascend_runtime_candidates[@]}"; do
      [[ -d "$ascend_runtime_dir" ]] && prepend_entries+=("$ascend_runtime_dir")
    done
    break
  done

  if [[ -n "$raw_ld_library_path" ]]; then
    IFS=':' read -r -a path_entries <<< "$raw_ld_library_path"
    for entry in "${path_entries[@]}"; do
      if [[ -z "$entry" ]]; then
        continue
      fi

      case "$entry" in
        "$env_prefix"|"$env_prefix"/*)
          continue
          ;;
        */envs/*/lib/python*/site-packages/torch/lib|*/envs/*/lib/python*/site-packages/torch_npu/lib|*/envs/*/lib)
          continue
          ;;
      esac

      filtered_entries+=("$entry")
    done
  fi

  combined_entries=("${prepend_entries[@]}" "${filtered_entries[@]}")
  filtered_entries=()
  for entry in "${combined_entries[@]}"; do
    if [[ -z "$entry" || ! -d "$entry" ]]; then
      continue
    fi
    case ":$seen_entries:" in
      *":$entry:"*)
        continue
        ;;
    esac
    filtered_entries+=("$entry")
    if [[ -z "$seen_entries" ]]; then
      seen_entries="$entry"
    else
      seen_entries="${seen_entries}:$entry"
    fi
  done

  if (( ${#filtered_entries[@]} == 0 )); then
    return 0
  fi

  printf '%s\n' "$(IFS=':'; printf '%s' "${filtered_entries[*]}")"
}

run_with_heartbeat() {
  local description="$1"
  shift
  local pid
  local heartbeat_pid
  local start_epoch
  local exit_code

  start_epoch="$(date +%s)"
  log_perf_step_start "$description"
  "$@" &
  pid=$!

  (
    local now_epoch
    local elapsed
    while kill -0 "$pid" >/dev/null 2>&1; do
      sleep 30
      if kill -0 "$pid" >/dev/null 2>&1; then
        now_epoch="$(date +%s)"
        elapsed=$(( now_epoch - start_epoch ))
        log "Still running: $description (elapsed=${elapsed}s)"
      fi
    done
  ) &
  heartbeat_pid=$!

  wait "$pid"
  exit_code=$?
  kill "$heartbeat_pid" >/dev/null 2>&1 || true
  wait "$heartbeat_pid" >/dev/null 2>&1 || true
  log_perf_step_end "$description" "$start_epoch" "$exit_code"
  return "$exit_code"
}

get_first_nonempty_env() {
  local variable_name
  local value

  for variable_name in "$@"; do
    value="${!variable_name:-}"
    if [[ -n "$value" ]]; then
      printf '%s\n' "$value"
      return 0
    fi
  done

  return 1
}

extra_env_args_include_var() {
  local variable_name="$1"
  shift
  local env_arg

  for env_arg in "$@"; do
    if [[ "$env_arg" == "$variable_name="* ]]; then
      return 0
    fi
  done

  return 1
}

default_ascend_compile_custom_kernels() {
  if [[ -n "$ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE" ]]; then
    printf '%s\n' "$ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE"
    return 0
  fi

  if [[ -n "${HUST_DEV_HUB_ASCEND_COMPILE_CUSTOM_KERNELS:-}" ]]; then
    printf '%s\n' "$HUST_DEV_HUB_ASCEND_COMPILE_CUSTOM_KERNELS"
    return 0
  fi

  if ascend_custom_kernel_build_prereqs_present \
    && (should_reconcile_ascend_runtime || [[ -n "${SOC_VERSION:-}" ]]); then
    printf '1\n'
    return 0
  fi

  printf '0\n'
}

ascend_custom_kernel_build_prereqs_present() {
  local tool

  for tool in git cmake make; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      return 1
    fi
  done

  if ! command -v g++ >/dev/null 2>&1 && ! command -v c++ >/dev/null 2>&1; then
    return 1
  fi

  return 0
}

ascend_compile_custom_kernels_configured_explicitly() {
  [[ -n "${HUST_DEV_HUB_ASCEND_COMPILE_CUSTOM_KERNELS:-}" ]]
}

sanitize_ld_library_path_for_system_tools() {
  local original_ld_library_path="$1"
  local path_entries=()
  local filtered_entries=()
  local entry

  if [[ -z "$original_ld_library_path" ]]; then
    return 0
  fi

  IFS=':' read -r -a path_entries <<< "$original_ld_library_path"
  for entry in "${path_entries[@]}"; do
    if [[ -z "$entry" ]]; then
      continue
    fi

    case "$entry" in
      /opt/conda|/opt/conda/*)
        continue
        ;;
    esac

    if [[ -n "${CONDA_PREFIX:-}" ]]; then
      case "$entry" in
        "$CONDA_PREFIX"|"$CONDA_PREFIX"/*)
          continue
          ;;
      esac
    fi

    if [[ -n "$CONDA_BASE" ]]; then
      case "$entry" in
        "$CONDA_BASE"|"$CONDA_BASE"/*)
          continue
          ;;
      esac
    fi

    filtered_entries+=("$entry")
  done

  if (( ${#filtered_entries[@]} == 0 )); then
    return 0
  fi

  local joined_entries
  joined_entries="$(IFS=':'; printf '%s' "${filtered_entries[*]}")"
  printf '%s\n' "$joined_entries"
}

run_system_command_with_sanitized_ld_library_path() {
  local sanitized_ld_library_path

  sanitized_ld_library_path="$(sanitize_ld_library_path_for_system_tools "${LD_LIBRARY_PATH:-}")"
  if [[ -n "$sanitized_ld_library_path" ]]; then
    env LD_LIBRARY_PATH="$sanitized_ld_library_path" "$@"
    return 0
  fi

  env -u LD_LIBRARY_PATH "$@"
}

read_build_requirement_spec_from_pyproject() {
  local repo_path="$1"
  local package_name="$2"

  awk -v package_name="$package_name" '
    match($0, /"[^"]+"/) {
      spec = substr($0, RSTART + 1, RLENGTH - 2)
      if (spec ~ ("^" package_name "([<>=!~].*)?$")) {
        print spec
        exit
      }
    }
  ' "$repo_path/pyproject.toml"
}

resolve_local_triton_ascend_repo() {
  local candidate

  for candidate in "${HUST_TRITON_ASCEND_REPO:-}" "$WORKSPACE_ROOT/triton-ascend-hust"; do
    if [[ -n "$candidate" && -f "$candidate/pyproject.toml" && -f "$candidate/setup.py" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

ensure_ascend_build_python_packages() {
  local repo_path="$1"
  local compile_custom_kernels="$2"
  local perf_description="Ascend build dependency check in $ENV_NAME"
  local perf_start_epoch
  local pybind11_spec
  local local_pybind11_spec="pybind11>=2.13.1"
  local local_nanobind_spec="nanobind>=2.4"
  local triton_ascend_repo
  local triton_ascend_spec
  local bootstrap_specs=(
    "setuptools-scm>=8"
  )
  local companion_specs=(
    "decorator==5.1.1"
    "scipy==1.13.1"
  )
  local batch_specs=()
  local package_spec
  local missing_batch_specs=()
  local rc=0

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  for package_spec in "${bootstrap_specs[@]}"; do
    ensure_pip_package_in_env "$ENV_NAME" "$package_spec"
    rc=$?
    if (( rc != 0 )); then
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
      return "$rc"
    fi
  done

  if triton_ascend_repo="$(resolve_local_triton_ascend_repo)"; then
    # Local editable installs use --no-build-isolation, so every requirement
    # from the local project's build-system.requires must already be present.
    # In particular, setup.py imports pybind11 while pip is only preparing
    # editable metadata; installing it in the batch below would be too late.
    for package_spec in cmake ninja pybind11 nanobind; do
      package_spec="$(read_build_requirement_spec_from_pyproject "$triton_ascend_repo" "$package_spec" || true)"
      if [[ -n "$package_spec" ]]; then
        batch_specs+=("$package_spec")
      fi
      if [[ "$package_spec" == pybind11* ]]; then
        local_pybind11_spec="$package_spec"
      fi
      if [[ "$package_spec" == nanobind* ]]; then
        local_nanobind_spec="$package_spec"
      fi
    done
  else
    triton_ascend_spec="$(read_build_requirement_spec_from_pyproject "$repo_path" "triton-ascend" || true)"
    batch_specs+=("${triton_ascend_spec:-triton-ascend}")
  fi
  batch_specs+=("${companion_specs[@]}")

  # pybind11 is a runtime dependency of triton-ascend's Ascend backend
  # (triton.backends.ascend.utils imports pybind11 at module load time).
  # Without it, `import triton.backends` fails and HAS_TRITON evaluates to
  # False, which silently disables all triton-ascend kernels including
  # the fused qkv_rmsnorm_rope op. Must be installed unconditionally
  # regardless of whether we're compiling custom C++ kernels.
  if [[ -z "$triton_ascend_repo" ]]; then
    pybind11_spec="$(read_build_requirement_spec_from_pyproject "$repo_path" "pybind11" || true)"
    batch_specs+=("${pybind11_spec:-pybind11}")
  fi

  if [[ "$compile_custom_kernels" == "0" || -n "$triton_ascend_repo" ]]; then
    :
  else
    batch_specs+=("cmake" "nanobind>=2.4")
  fi

  mapfile -t missing_batch_specs < <(list_missing_pip_requirements_in_env "$ENV_NAME" "${batch_specs[@]}" || true)

  if (( ${#missing_batch_specs[@]} == 0 )); then
    log "Ascend build Python dependencies already satisfied in '$ENV_NAME'"
  else
    log "Installing missing or incompatible Ascend build Python dependencies into '$ENV_NAME': ${missing_batch_specs[*]}"
    run_with_heartbeat \
      "installing Ascend build Python dependencies into $ENV_NAME" \
      run_pip_install_in_env "$ENV_NAME" -- "${missing_batch_specs[@]}"
    rc=$?
    if (( rc != 0 )); then
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
      return "$rc"
    fi
  fi

  if [[ -n "$triton_ascend_repo" ]]; then
    # Validate the exact interpreter used by the upcoming editable install.
    # Distribution metadata alone is insufficient: a stale or partial
    # pybind11 installation can look installed while setup.py fails at import.
    if ! run_conda_env_cmd "$ENV_NAME" python -c 'import pybind11' >/dev/null 2>&1; then
      log "pybind11 is not importable in '$ENV_NAME'; force reinstalling $local_pybind11_spec"
      run_with_heartbeat \
        "repairing pybind11 in $ENV_NAME" \
        run_pip_install_in_env "$ENV_NAME" -- --force-reinstall --no-cache-dir "$local_pybind11_spec"
      rc=$?
      if (( rc != 0 )); then
        log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
        return "$rc"
      fi
    fi
    if ! run_conda_env_cmd "$ENV_NAME" python -c 'import pybind11' >/dev/null 2>&1; then
      log "Error: pybind11 remains unavailable in '$ENV_NAME' after repair"
      log_perf_step_end "$perf_description" "$perf_start_epoch" 1
      return 1
    fi

    # AscendNPU-IR uses nanobind's CMake package, not only its Python
    # metadata. Verify both the import and the package configuration path.
    if ! run_conda_env_cmd "$ENV_NAME" python -c \
      'import nanobind; from pathlib import Path; p = Path(nanobind.cmake_dir()); assert any((p / name).is_file() for name in ("nanobindConfig.cmake", "nanobind-config.cmake"))' \
      >/dev/null 2>&1; then
      log "nanobind CMake package is unavailable in '$ENV_NAME'; force reinstalling $local_nanobind_spec"
      run_with_heartbeat \
        "repairing nanobind in $ENV_NAME" \
        run_pip_install_in_env "$ENV_NAME" -- --force-reinstall --no-cache-dir "$local_nanobind_spec"
      rc=$?
      if (( rc != 0 )); then
        log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
        return "$rc"
      fi
    fi
    if ! run_conda_env_cmd "$ENV_NAME" python -c \
      'import nanobind; from pathlib import Path; p = Path(nanobind.cmake_dir()); assert any((p / name).is_file() for name in ("nanobindConfig.cmake", "nanobind-config.cmake"))' \
      >/dev/null 2>&1; then
      log "Error: nanobind CMake package remains unavailable in '$ENV_NAME' after repair"
      log_perf_step_end "$perf_description" "$perf_start_epoch" 1
      return 1
    fi

    log "Installing triton-ascend from local HUST source: $triton_ascend_repo"
    run_with_heartbeat \
      "installing local triton-ascend from $triton_ascend_repo" \
      run_pip_install_in_env "$ENV_NAME" \
        "TRITON_WHEEL_NAME=triton-ascend" \
        "TRITON_CODEGEN_BACKENDS=ascend" \
        "MAX_JOBS=${HUST_TRITON_ASCEND_MAX_JOBS:-32}" \
        -- --no-build-isolation -v -e "$triton_ascend_repo"
    rc=$?
    if (( rc != 0 )); then
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
      return "$rc"
    fi
  fi

  log_perf_step_end "$perf_description" "$perf_start_epoch" 0
}

# Patch triton-ascend's JIT-compiled npu_utils.cpp for CANN 9.0.0+ compatibility.
# triton-ascend 3.2.0 references RT_LIMIT_TYPE_SIMT_WARP_STACK_SIZE which was
# renamed to RT_LIMIT_TYPE_SIMT_DVG_WARP_STACK_SIZE in CANN 9.0.0.  Without this
# patch, the JIT compilation fails with "‘RT_LIMIT_TYPE_SIMT_WARP_STACK_SIZE’
# was not declared in this scope".
patch_triton_ascend_for_cann9() {
  local env_prefix
  local npu_utils=""
  local triton_backends=""

  env_prefix="$(get_conda_env_prefix "$ENV_NAME")"
  if [[ -z "$env_prefix" || ! -d "$env_prefix" ]]; then
    return 0
  fi

  triton_backends="$env_prefix/lib/python$(ls "$env_prefix/lib/" | grep -oP 'python\d+\.\d+' | head -1)/site-packages/triton/backends/ascend"
  if [[ ! -d "$triton_backends" ]]; then
    return 0
  fi

  npu_utils="$triton_backends/npu_utils.cpp"
  if [[ ! -f "$npu_utils" ]]; then
    return 0
  fi

  # Only patch for CANN >= 9.0.0; skip on CANN 8.x where the symbol still exists.
  local _cann_major
  _cann_major="$(detect_cann_major_version 2>/dev/null || echo "")"
  if [[ "$_cann_major" != "9" ]]; then
    return 0
  fi

  if grep -q 'RT_LIMIT_TYPE_SIMT_WARP_STACK_SIZE' "$npu_utils" 2>/dev/null; then
    log "Patching triton-ascend npu_utils.cpp for CANN 9.0.0 compatibility"
    sed -i '/RT_LIMIT_TYPE_SIMT_WARP_STACK_SIZE/d' "$npu_utils"
    # Clear JIT cache so the patched source is recompiled on next import
    find "$triton_backends" -name '*.so' -path '*npu_utils*' -delete 2>/dev/null || true
    log "Patched: removed RT_LIMIT_TYPE_SIMT_WARP_STACK_SIZE from npu_utils.cpp"
  fi
}

read_requirement_spec_from_requirements_file() {
  local repo_path="$1"
  local package_name="$2"
  local requirements_file="$repo_path/requirements.txt"

  if [[ ! -f "$requirements_file" ]]; then
    return 1
  fi

  awk -v package_name="$package_name" '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    {
      line = $0
      sub(/[[:space:]]+#.*$/, "", line)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      if (line ~ ("^" package_name "([<>=!~].*)?$")) {
        print line
        exit
      }
    }
  ' "$requirements_file"
}

list_requirement_specs_from_file() {
  local requirements_file="$1"
  if [[ ! -f "$requirements_file" ]]; then
    return 1
  fi

  awk '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    {
      line = $0
      sub(/[[:space:]]+#.*$/, "", line)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      if (line == "" || line ~ /^-/) {
        next
      }
      print line
    }
  ' "$requirements_file"
}

list_requirement_specs_from_requirements_file() {
  local repo_path="$1"

  list_requirement_specs_from_file "$repo_path/requirements.txt"
}

requirement_name_from_spec() {
  local package_spec="$1"
  local package_name="${package_spec%%[<>=!~; ]*}"

  printf '%s\n' "${package_name,,}"
}

ascend_runtime_requirement_is_optional_for_quickstart() {
  local package_spec="$1"
  local package_name

  package_name="$(requirement_name_from_spec "$package_spec")"
  case "$package_name" in
    arctic-inference|fastapi|memcache_hybrid|memfabric_hybrid|numba|pandas-stubs|quart|torch|torch-npu|torchaudio|torchvision|transformers)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

ensure_ascend_catlass_submodule_ready() {
  local repo_path="$1"
  local perf_description="Ascend catlass submodule check in $(basename "$repo_path")"
  local perf_start_epoch
  local submodule_relative_path="csrc/third_party/catlass"
  local submodule_path="$repo_path/$submodule_relative_path"
  local rc=0

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  if [[ -e "$submodule_path/CMakeLists.txt" || -e "$submodule_path/README.md" ]]; then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  if [[ ! -d "$repo_path/.git" && ! -f "$repo_path/.git" ]]; then
    log "Warning: skipping $submodule_relative_path initialization because '$repo_path' has no git metadata"
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "Initializing Ascend submodule: $submodule_relative_path"
  run_system_command_with_sanitized_ld_library_path \
    git -C "$repo_path" submodule update --init --recursive "$submodule_relative_path"
  rc=$?
  log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
  return "$rc"
}

resolve_ascend_expected_cmake_generator() {
  local use_ninja_lower=""

  use_ninja_lower="$(printf '%s' "${USE_NINJA:-${VLLM_ASCEND_USE_NINJA:-auto}}" | tr '[:upper:]' '[:lower:]')"
  if [[ "$use_ninja_lower" == "0" || "$use_ninja_lower" == "false" || "$use_ninja_lower" == "off" || "$use_ninja_lower" == "no" ]]; then
    return 0
  fi

  if command -v ninja >/dev/null 2>&1; then
    printf 'Ninja\n'
  fi
}

repair_ascend_cmake_generator_cache() {
  local repo_path="$1"
  local perf_description="Ascend CMake generator cache check in $(basename "$repo_path")"
  local perf_start_epoch
  local build_dir="$repo_path/csrc/build"
  local cache_file="$build_dir/CMakeCache.txt"
  local cmake_files_dir="$build_dir/CMakeFiles"
  local cached_generator=""
  local expected_generator=""

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  if [[ ! -f "$cache_file" ]]; then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  cached_generator="$(awk -F= '
    /^CMAKE_GENERATOR:INTERNAL=/ { print $2; exit }
    /^CMAKE_GENERATOR:STRING=/ { print $2; exit }
  ' "$cache_file" 2>/dev/null || true)"
  expected_generator="$(resolve_ascend_expected_cmake_generator || true)"

  if [[ -z "$cached_generator" || -z "$expected_generator" || "$cached_generator" == "$expected_generator" ]]; then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "Detected stale Ascend CMake generator cache in '$build_dir' (cached=$cached_generator, expected=$expected_generator); clearing generator metadata"
  rm -f -- "$cache_file" "$build_dir/Makefile" "$build_dir/build.ninja" "$build_dir/cmake_install.cmake"
  rm -rf -- "$cmake_files_dir"
  log_perf_step_end "$perf_description" "$perf_start_epoch" 0
}

validate_ascend_custom_op_in_env() {
  local env_name="$1"

  run_conda_env_cmd "$env_name" env TORCH_DEVICE_BACKEND_AUTOLOAD=0 python - >/dev/null 2>&1 <<'PY'
import torch  # noqa: F401
from vllm_ascend.utils import enable_custom_op

raise SystemExit(0 if enable_custom_op() else 1)
PY
}

validate_torch_npu_runtime_in_env() {
  local env_name="$1"

  run_conda_env_cmd "$env_name" env TORCH_DEVICE_BACKEND_AUTOLOAD=0 python - >/dev/null 2>&1 <<'PY'
import torch  # noqa: F401
import torch_npu  # noqa: F401
PY
}

log_torch_npu_runtime_validation_failure_details() {
  local env_name="$1"
  local stage_label="${2:-runtime validation}"

  log "Detailed torch/torch-npu runtime validation traceback for '$env_name' ($stage_label):"
  run_conda_env_cmd "$env_name" env TORCH_DEVICE_BACKEND_AUTOLOAD=0 python - <<'PY'
import traceback

try:
    import torch  # noqa: F401
    import torch_npu  # noqa: F401
except Exception:
    traceback.print_exc()
    raise SystemExit(1)
PY
}

read_ascend_python_stack_specs_from_manifest() {
  local env_name="$1"
  local manifest_path="${2:-$MANAGER_MANIFEST_DEFAULT}"

  if [[ ! -f "$manifest_path" ]]; then
    return 1
  fi

  run_conda_env_cmd "$env_name" python - "$manifest_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    manifest = json.load(f)

stack = manifest.get("python_stack", {})
torch_version = stack.get("torch")
torch_npu_version = stack.get("torch_npu")

if torch_version:
    print(f"torch=={torch_version}")
if torch_npu_version:
    print(f"torch-npu=={torch_npu_version}")
PY
}

force_reinstall_ascend_python_stack_in_env() {
  local env_name="$1"
  local stack_specs=()
  local runtime_support_specs=(
    "decorator"
    "scipy"
  )
  local package_spec

  remove_conflicting_conda_torch_packages_in_env "$env_name"

  mapfile -t stack_specs < <(read_ascend_python_stack_specs_from_manifest "$env_name" || true)
  if (( ${#stack_specs[@]} == 0 )); then
    stack_specs=("torch" "torch-npu")
  fi

  log "Force reinstalling Ascend Python stack in '$env_name': ${stack_specs[*]}"
  run_with_heartbeat \
    "force reinstalling Ascend Python stack in $env_name" \
    run_pip_install_in_env "$env_name" -- --upgrade --ignore-installed "${stack_specs[@]}"

  log "Reinstalling Ascend runtime support Python dependencies in '$env_name': ${runtime_support_specs[*]}"
  for package_spec in "${runtime_support_specs[@]}"; do
    ensure_pip_package_in_env "$env_name" "$package_spec"
  done
}

ensure_ascend_torch_runtime_healthy() {
  local env_name="$1"
  local perf_description="Ascend torch runtime health check in $env_name"
  local perf_start_epoch

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  if validate_torch_npu_runtime_in_env "$env_name"; then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log_torch_npu_runtime_validation_failure_details "$env_name" "initial validation failure" || true

  if should_reconcile_ascend_runtime; then
    log "Torch/torch-npu runtime import validation failed in '$env_name'; re-running Ascend Python stack reconciliation"
    reconcile_ascend_runtime_with_manager
    if validate_torch_npu_runtime_in_env "$env_name"; then
      log_perf_step_end "$perf_description" "$perf_start_epoch" 0
      return 0
    fi
  fi

  force_reinstall_ascend_python_stack_in_env "$env_name"
  if validate_torch_npu_runtime_in_env "$env_name"; then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log_torch_npu_runtime_validation_failure_details "$env_name" "post-reinstall validation failure" || true
  log "Warning: torch/torch-npu runtime import validation is still failing in '$env_name'"
  log_perf_step_end "$perf_description" "$perf_start_epoch" 1
  return 1
}

validate_ascend_platform_plugin_in_env() {
  local env_name="$1"

  run_conda_env_cmd "$env_name" python - <<'PY'
from importlib.metadata import entry_points

raise SystemExit(0 if any(ep.name == "ascend" for ep in entry_points(group="vllm.platform_plugins")) else 1)
PY
}

find_ascend_custom_op_extension_in_env() {
  local env_name="$1"

  run_conda_env_cmd "$env_name" python - <<'PY'
import glob
import os

import vllm_ascend

package_dir = os.path.dirname(vllm_ascend.__file__)
matches = sorted(glob.glob(os.path.join(package_dir, "vllm_ascend_C*.so")))
if matches:
    print(matches[0])
PY
}

repair_ascend_custom_op_runpath_in_env() {
  local env_name="$1"
  local extension_path
  local runpath='$ORIGIN:$ORIGIN/lib:$ORIGIN/_cann_ops_custom/vendors/vllm-ascend/op_api/lib'

  if ! command -v patchelf >/dev/null 2>&1; then
    log "Warning: patchelf is unavailable, skipping Ascend custom-op RUNPATH repair"
    return 1
  fi

  extension_path="$(find_ascend_custom_op_extension_in_env "$env_name")"
  if [[ -z "$extension_path" || ! -f "$extension_path" ]]; then
    log "Warning: could not locate vllm_ascend_C extension for RUNPATH repair"
    return 1
  fi

  log "Repairing RUNPATH for Ascend custom op: $extension_path"
  patchelf --set-rpath "$runpath" "$extension_path"
}

install_ascend_repo_into_env() {
  local repo_path="$1"
  local compile_custom_kernels="$2"
  local pip_args=(-v --no-build-isolation --no-deps -e "$repo_path")
  local build_ld_library_path
  local rc_build_python_packages=20
  local rc_runtime_python_packages=21
  local rc_catlass_submodule=22
  local rc_editable_install=23
  local rc_plugin_validation=24
  local rc_custom_op_validation=25
  local perf_description_plugin="Ascend plugin/custom op validation in $ENV_NAME"
  local perf_description_platform_plugin="Ascend platform plugin validation in $ENV_NAME"
  local perf_description_custom_op_import="Ascend custom op import validation in $ENV_NAME"
  local perf_description_custom_op_runpath="Ascend custom op RUNPATH repair in $ENV_NAME"
  local perf_start_epoch_plugin
  local perf_start_epoch_platform_plugin
  local perf_start_epoch_custom_op_import
  local perf_start_epoch_custom_op_runpath

  if ! ensure_ascend_build_python_packages "$repo_path" "$compile_custom_kernels"; then
    log "Warning: failed to prepare Ascend build Python dependencies for '$repo_path'"
    return "$rc_build_python_packages"
  fi
  patch_triton_ascend_for_cann9
  if ! ensure_ascend_runtime_python_packages "$repo_path"; then
    log "Warning: failed to prepare Ascend runtime Python dependencies for '$repo_path'"
    return "$rc_runtime_python_packages"
  fi

  if [[ "$compile_custom_kernels" != "0" ]]; then
    if ! ensure_ascend_catlass_submodule_ready "$repo_path"; then
      log "Warning: failed to initialize Ascend submodule(s) for '$repo_path'"
      return "$rc_catlass_submodule"
    fi

    repair_ascend_cmake_generator_cache "$repo_path"
  fi

  build_ld_library_path="$(sanitize_ld_library_path_for_system_tools "${LD_LIBRARY_PATH:-}")"

  log "Installing editable package from: $repo_path"
  if ! ascend_compile_custom_kernels_configured_explicitly; then
    log "Auto-selected COMPILE_CUSTOM_KERNELS=$compile_custom_kernels for Ascend repo '$repo_path'"
  fi
  if [[ "$compile_custom_kernels" == "0" ]]; then
    log "Using Ascend lightweight plugin mode: COMPILE_CUSTOM_KERNELS=0, --no-deps"
  else
    log "Using Ascend custom-kernel mode: COMPILE_CUSTOM_KERNELS=$compile_custom_kernels"
  fi

  # vllm-ascend-hust's setup.py imports the sibling module build_version at
  # module import time. pip's in-process PEP 517/660 hook execs setup.py without
  # adding the project root to sys.path, which makes that import fail during
  # editable-metadata generation. Expose the repo root via PYTHONPATH (prefixing
  # rather than replacing so any caller-provided PYTHONPATH entries are kept) so
  # the upstream setup.py does not need to be patched.
  if ! run_with_heartbeat \
    "installing editable package from $repo_path" \
    run_pip_install_in_env "$ENV_NAME" \
      "COMPILE_CUSTOM_KERNELS=$compile_custom_kernels" \
      "TORCH_DEVICE_BACKEND_AUTOLOAD=0" \
      "LD_LIBRARY_PATH=$build_ld_library_path" \
      "PYTHONPATH=${repo_path}${PYTHONPATH:+:$PYTHONPATH}" \
      -- "${pip_args[@]}"; then
    log "Warning: editable Ascend install failed for '$repo_path' (COMPILE_CUSTOM_KERNELS=$compile_custom_kernels)"
    return "$rc_editable_install"
  fi

  perf_start_epoch_plugin="$(date +%s)"
  log_perf_step_start "$perf_description_plugin"
  perf_start_epoch_platform_plugin="$(date +%s)"
  log_perf_step_start "$perf_description_platform_plugin"
  if ! validate_ascend_platform_plugin_in_env "$ENV_NAME"; then
    log "Warning: Ascend platform plugin entry point validation failed in '$ENV_NAME'"
    log_perf_step_end "$perf_description_platform_plugin" "$perf_start_epoch_platform_plugin" "$rc_plugin_validation"
    log_perf_step_end "$perf_description_plugin" "$perf_start_epoch_plugin" "$rc_plugin_validation"
    return "$rc_plugin_validation"
  fi
  log_perf_step_end "$perf_description_platform_plugin" "$perf_start_epoch_platform_plugin" 0

  log "Verified Ascend platform plugin entry point in '$ENV_NAME'"

  if [[ "$compile_custom_kernels" == "0" ]]; then
    log_perf_step_end "$perf_description_plugin" "$perf_start_epoch_plugin" 0
    return 0
  fi

  perf_start_epoch_custom_op_import="$(date +%s)"
  log_perf_step_start "$perf_description_custom_op_import"
  if validate_ascend_custom_op_in_env "$ENV_NAME"; then
    log "Verified Ascend custom op import in '$ENV_NAME'"
    log_perf_step_end "$perf_description_custom_op_import" "$perf_start_epoch_custom_op_import" 0
    log_perf_step_end "$perf_description_plugin" "$perf_start_epoch_plugin" 0
    return 0
  fi
  log_perf_step_end "$perf_description_custom_op_import" "$perf_start_epoch_custom_op_import" 1

  log "Ascend custom op validation failed; attempting RUNPATH repair"
  perf_start_epoch_custom_op_runpath="$(date +%s)"
  log_perf_step_start "$perf_description_custom_op_runpath"
  if repair_ascend_custom_op_runpath_in_env "$ENV_NAME" && validate_ascend_custom_op_in_env "$ENV_NAME"; then
    log "Verified Ascend custom op import in '$ENV_NAME' after RUNPATH repair"
    log_perf_step_end "$perf_description_custom_op_runpath" "$perf_start_epoch_custom_op_runpath" 0
    log_perf_step_end "$perf_description_plugin" "$perf_start_epoch_plugin" 0
    return 0
  fi
  log_perf_step_end "$perf_description_custom_op_runpath" "$perf_start_epoch_custom_op_runpath" 1
  log_perf_step_end "$perf_description_plugin" "$perf_start_epoch_plugin" "$rc_custom_op_validation"

  log "Warning: Ascend custom op validation is still failing in '$ENV_NAME'"
  return "$rc_custom_op_validation"
}

ensure_ascend_runtime_python_packages() {
  local repo_path="$1"
  local perf_description="Ascend runtime dependency check in $ENV_NAME"
  local perf_start_epoch
  local requirement_specs=()
  local missing_requirement_specs=()
  local requirement_spec
  local required_specs=()
  local rc=0

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  mapfile -t requirement_specs < <(list_requirement_specs_from_requirements_file "$repo_path" || true)
  if (( ${#requirement_specs[@]} == 0 )); then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  for requirement_spec in "${requirement_specs[@]}"; do
    if ascend_runtime_requirement_is_optional_for_quickstart "$requirement_spec"; then
      continue
    fi
    required_specs+=("$requirement_spec")
  done

  if (( ${#required_specs[@]} == 0 )); then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  mapfile -t missing_requirement_specs < <(list_missing_pip_requirements_in_env "$ENV_NAME" "${required_specs[@]}" || true)

  if (( ${#missing_requirement_specs[@]} == 0 )); then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "Installing missing or incompatible Ascend runtime Python dependencies into '$ENV_NAME'"
  run_with_heartbeat \
    "installing Ascend runtime Python dependencies into $ENV_NAME" \
    run_pip_install_in_env "$ENV_NAME" -- "${missing_requirement_specs[@]}"
  rc=$?
  log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
  return "$rc"
}

read_positive_int_env_with_fallback() {
  local default_value="$1"
  shift
  local variable_name
  local raw_value

  for variable_name in "$@"; do
    raw_value="${!variable_name:-}"
    if [[ "$raw_value" =~ ^[1-9][0-9]*$ ]]; then
      printf '%s\n' "$raw_value"
      return 0
    fi
  done

  printf '%s\n' "$default_value"
}

select_pip_index_url() {
  local explicit_index_url
  local disable_auto_mirror
  local mirror_url
  local probe_timeout

  explicit_index_url="$(get_first_nonempty_env PIP_INDEX_URL HUST_DEV_HUB_PIP_INDEX_URL HUST_ASCEND_MANAGER_PIP_INDEX_URL || true)"
  if [[ -n "$explicit_index_url" ]]; then
    printf '%s\n' "$explicit_index_url"
    return 0
  fi

  disable_auto_mirror="$(get_first_nonempty_env HUST_DEV_HUB_DISABLE_PYPI_MIRROR_AUTOSET HUST_ASCEND_MANAGER_DISABLE_PYPI_MIRROR_AUTOSET || true)"
  if [[ "$disable_auto_mirror" == "1" ]]; then
    return 0
  fi

  mirror_url="$(get_first_nonempty_env HUST_DEV_HUB_PIP_MIRROR_URL HUST_ASCEND_MANAGER_PIP_MIRROR_URL || true)"
  mirror_url="${mirror_url:-$PIP_INDEX_MIRROR_URL}"
  probe_timeout="$(read_positive_int_env_with_fallback 3 HUST_DEV_HUB_PIP_MIRROR_TIMEOUT HUST_ASCEND_MANAGER_PIP_MIRROR_TIMEOUT)"

  if command -v curl >/dev/null 2>&1 \
    && curl -fsSIL --connect-timeout "$probe_timeout" --max-time "$((probe_timeout + 2))" "${mirror_url%/}/" >/dev/null 2>&1; then
    printf '%s\n' "$mirror_url"
  fi
}

select_pip_extra_index_url() {
  local explicit_extra_index_url

  explicit_extra_index_url="$(get_first_nonempty_env PIP_EXTRA_INDEX_URL HUST_DEV_HUB_PIP_EXTRA_INDEX_URL HUST_ASCEND_MANAGER_PIP_EXTRA_INDEX_URL || true)"
  if [[ -n "$explicit_extra_index_url" ]]; then
    printf '%s\n' "$explicit_extra_index_url"
    return 0
  fi

  # vllm-ascend-hust pins triton-ascend==3.2.1, which is currently published
  # on the official Triton-Ascend index but not on the mirrored Tsinghua PyPI
  # index that quickstart auto-selects as the primary index on many CN hosts.
  # Default this extra index only for Ascend quickstart flows, while still
  # allowing explicit user/environment overrides to take precedence.
  if should_reconcile_ascend_runtime; then
    printf '%s\n' "$PIP_ASCEND_TRITON_EXTRA_INDEX_URL"
  fi
}

ensure_pip_install_defaults() {
  if (( PIP_DEFAULTS_INITIALIZED == 1 )); then
    return 0
  fi

  PIP_SELECTED_INDEX_URL="$(select_pip_index_url || true)"
  PIP_SELECTED_EXTRA_INDEX_URL="$(select_pip_extra_index_url || true)"
  PIP_INSTALL_RETRIES="$(read_positive_int_env_with_fallback 8 HUST_DEV_HUB_PIP_RETRIES HUST_ASCEND_MANAGER_PIP_RETRIES)"
  PIP_INSTALL_TIMEOUT="$(read_positive_int_env_with_fallback 120 HUST_DEV_HUB_PIP_TIMEOUT HUST_ASCEND_MANAGER_PIP_TIMEOUT)"
  PIP_INSTALL_RESUME_RETRIES="$(read_positive_int_env_with_fallback 8 HUST_DEV_HUB_PIP_RESUME_RETRIES HUST_ASCEND_MANAGER_PIP_RESUME_RETRIES)"

  if [[ -n "$PIP_SELECTED_INDEX_URL" ]]; then
    log "Using pip index for quickstart installs: $PIP_SELECTED_INDEX_URL"
  fi
  if [[ -n "$PIP_SELECTED_EXTRA_INDEX_URL" ]]; then
    log "Using pip extra index for quickstart installs: $PIP_SELECTED_EXTRA_INDEX_URL"
  fi

  PIP_DEFAULTS_INITIALIZED=1
}

pip_install_supports_option() {
  local env_name="$1"
  local option="$2"

  run_conda_env_cmd "$env_name" python -m pip install --help 2>/dev/null | grep -q -- "$option"
}

python_bin_pip_install_supports_option() {
  local python_bin="$1"
  local option="$2"

  "$python_bin" -m pip install --help 2>/dev/null | grep -q -- "$option"
}

run_pip_install_with_python_bin() {
  local python_bin="$1"
  shift
  local extra_env_args=()
  local pip_args=()
  local pip_install_args=()
  local command_args=()
  local python_supports_resume_retries="unknown"

  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--" ]]; then
      shift
      break
    fi
    extra_env_args+=("$1")
    shift
  done
  pip_args=("$@")

  ensure_pip_install_defaults
  pip_install_args=(
    --retries "$PIP_INSTALL_RETRIES"
    --timeout "$PIP_INSTALL_TIMEOUT"
  )

  if python_bin_pip_install_supports_option "$python_bin" "--resume-retries"; then
    python_supports_resume_retries="1"
  else
    python_supports_resume_retries="0"
  fi

  if [[ "$python_supports_resume_retries" == "1" ]]; then
    pip_install_args+=(--resume-retries "$PIP_INSTALL_RESUME_RETRIES")
  fi

  mkdir -p "$CURRENT_USER_CACHE_HOME/pip" "$CURRENT_USER_CONFIG_HOME"
  command_args=(env PIP_DISABLE_PIP_VERSION_CHECK=1)
  command_args+=(
    "HOME=$CURRENT_USER_HOME"
    "XDG_CACHE_HOME=$CURRENT_USER_CACHE_HOME"
    "XDG_CONFIG_HOME=$CURRENT_USER_CONFIG_HOME"
    "PIP_CACHE_DIR=$CURRENT_USER_CACHE_HOME/pip"
  )
  if ! extra_env_args_include_var "LD_LIBRARY_PATH" "${extra_env_args[@]}"; then
    command_args+=("LD_LIBRARY_PATH=")
  fi
  if [[ -n "$PIP_SELECTED_INDEX_URL" && -z "${PIP_INDEX_URL:-}" ]]; then
    command_args+=("PIP_INDEX_URL=$PIP_SELECTED_INDEX_URL")
  fi
  if [[ -n "$PIP_SELECTED_EXTRA_INDEX_URL" && -z "${PIP_EXTRA_INDEX_URL:-}" ]]; then
    command_args+=("PIP_EXTRA_INDEX_URL=$PIP_SELECTED_EXTRA_INDEX_URL")
  fi
  command_args+=("${extra_env_args[@]}" "$python_bin" -m pip install "${pip_install_args[@]}" "${pip_args[@]}")

  "${command_args[@]}"
}

run_pip_install_in_env() {
  local env_name="$1"
  shift
  local extra_env_args=()
  local pip_args=()
  local pip_install_args=()
  local command_args=()

  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--" ]]; then
      shift
      break
    fi
    extra_env_args+=("$1")
    shift
  done
  pip_args=("$@")

  ensure_pip_install_defaults
  pip_install_args=(
    --retries "$PIP_INSTALL_RETRIES"
    --timeout "$PIP_INSTALL_TIMEOUT"
  )

  if [[ "$PIP_SUPPORTS_RESUME_RETRIES" == "unknown" ]]; then
    if pip_install_supports_option "$env_name" "--resume-retries"; then
      PIP_SUPPORTS_RESUME_RETRIES="1"
    else
      PIP_SUPPORTS_RESUME_RETRIES="0"
    fi
  fi

  if [[ "$PIP_SUPPORTS_RESUME_RETRIES" == "1" ]]; then
    pip_install_args+=(--resume-retries "$PIP_INSTALL_RESUME_RETRIES")
  fi

  command_args=(env PIP_DISABLE_PIP_VERSION_CHECK=1)
  command_args+=(
    "HOME=$CURRENT_USER_HOME"
    "XDG_CACHE_HOME=$CURRENT_USER_CACHE_HOME"
    "XDG_CONFIG_HOME=$CURRENT_USER_CONFIG_HOME"
    "PIP_CACHE_DIR=$CURRENT_USER_CACHE_HOME/pip"
  )
  if ! extra_env_args_include_var "LD_LIBRARY_PATH" "${extra_env_args[@]}"; then
    command_args+=("LD_LIBRARY_PATH=")
  fi
  if [[ -n "$PIP_SELECTED_INDEX_URL" && -z "${PIP_INDEX_URL:-}" ]]; then
    command_args+=("PIP_INDEX_URL=$PIP_SELECTED_INDEX_URL")
  fi
  if [[ -n "$PIP_SELECTED_EXTRA_INDEX_URL" && -z "${PIP_EXTRA_INDEX_URL:-}" ]]; then
    command_args+=("PIP_EXTRA_INDEX_URL=$PIP_SELECTED_EXTRA_INDEX_URL")
  fi
  command_args+=("${extra_env_args[@]}" python -m pip install "${pip_install_args[@]}" "${pip_args[@]}")

  run_conda_env_cmd "$env_name" "${command_args[@]}"
}

resolve_conda_root_from_bin() {
  local conda_bin="$1"

  cd -- "$(dirname -- "$conda_bin")/.." && pwd
}

conda_bin_is_usable() {
  local conda_bin="$1"

  [[ -x "$conda_bin" ]] || return 1
  (unset PYTHONPATH; "$conda_bin" info --base >/dev/null 2>&1)
}

record_broken_conda_prefix() {
  local conda_bin="$1"
  local conda_root=""

  conda_root="$(resolve_conda_root_from_bin "$conda_bin")"
  if [[ -n "$conda_root" && -z "$BROKEN_CONDA_PREFIX" ]]; then
    BROKEN_CONDA_PREFIX="$conda_root"
  fi
}

accept_conda_candidate() {
  local conda_bin="$1"

  [[ -n "$conda_bin" ]] || return 1
  [[ -x "$conda_bin" ]] || return 1

  if conda_bin_is_usable "$conda_bin"; then
    printf '%s\n' "$conda_bin"
    return 0
  fi

  record_broken_conda_prefix "$conda_bin"
  return 1
}

find_conda_bin() {
  local resolved_path=""
  local candidates=(
    "$WORKSPACE_ROOT/miniconda3/bin/conda"
    "$HOME/miniconda3/bin/conda"
    "$HOME/anaconda3/bin/conda"
    "$HOME/miniforge3/bin/conda"
    "$HOME/mambaforge/bin/conda"
  )
  local path

  if accept_conda_candidate "${CONDA_EXE:-}"; then
    return 0
  fi

  resolved_path="$(type -P conda 2>/dev/null || true)"
  if accept_conda_candidate "$resolved_path"; then
    return 0
  fi

  for path in "${candidates[@]}"; do
    if accept_conda_candidate "$path"; then
      return 0
    fi
  done

  return 1
}

get_conda_base() {
  local conda_bin="${1:-$CONDA_BIN}"

  [[ -n "$conda_bin" ]] || return 0
  (unset PYTHONPATH; "$conda_bin" info --base 2>/dev/null || true)
}

ensure_conda_available() {
  local bootstrap_mode="${1:-allow-bootstrap}"
  local conda_bin
  local install_prefix=""

  BROKEN_CONDA_PREFIX=""
  if conda_bin="$(find_conda_bin)"; then
    CONDA_BIN="$conda_bin"
    CONDA_BASE="$(get_conda_base "$conda_bin")"
    if [[ -z "$CONDA_BASE" ]]; then
      CONDA_BASE="$(resolve_conda_root_from_bin "$conda_bin")"
    fi
    return 0
  fi

  if [[ "$bootstrap_mode" == "no-bootstrap" ]]; then
    log "conda is not available and auto-install is disabled for this flow."
    return 1
  fi

  log "conda was not found or is unusable."
  if [[ -n "$BROKEN_CONDA_PREFIX" ]]; then
    install_prefix="$BROKEN_CONDA_PREFIX"
    log "Detected a broken conda prefix; quickstart will attempt to repair it in place: $install_prefix"
  fi

  if [[ ! -f "$MINICONDA_INSTALL_SCRIPT" ]]; then
    echo "[quickstart] Miniconda installer script not found: $MINICONDA_INSTALL_SCRIPT" >&2
    return 1
  fi

  if (( AUTO_YES == 1 )) || ask_yes_no "Download and install Miniconda automatically now?"; then
    local install_args=()
    if [[ -n "$install_prefix" ]]; then
      install_args+=(--prefix "$install_prefix")
    fi
    if (( AUTO_YES == 1 )); then
      install_args+=(--yes)
    fi

    bash "$MINICONDA_INSTALL_SCRIPT" "${install_args[@]}"

    if conda_bin="$(find_conda_bin)"; then
      CONDA_BIN="$conda_bin"
      CONDA_BASE="$(get_conda_base "$conda_bin")"
      if [[ -z "$CONDA_BASE" ]]; then
        CONDA_BASE="$(resolve_conda_root_from_bin "$conda_bin")"
      fi
      return 0
    fi
  fi

  echo "[quickstart] conda is still unavailable after installation attempt." >&2
  return 1
}

clone_repositories() {
  local perf_description="clone workspace repositories"
  local perf_start_epoch=""
  local exit_code=0

  perf_start_epoch="$(date +%s)"
  if [[ ! -f "$CLONE_SCRIPT" ]]; then
    log "clone script not found: $CLONE_SCRIPT"
    log_perf_step_end "$perf_description" "$perf_start_epoch" 2
    return 2
  fi
  log_perf_step_start "$perf_description"
  log "Cloning workspace repositories..."
  if (( AUTO_YES == 1 )); then
    if ! bash "$CLONE_SCRIPT" --yes; then
      exit_code=$?
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$exit_code"
      return "$exit_code"
    fi
    if [[ -d "$WORKSPACE_ROOT/vllm-hust-org-profile" ]]; then
      log "Organization profile repo is available at $WORKSPACE_ROOT/vllm-hust-org-profile (special repo: vLLM-HUST/.github)."
    fi
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi
  if ! bash "$CLONE_SCRIPT"; then
    exit_code=$?
    log_perf_step_end "$perf_description" "$perf_start_epoch" "$exit_code"
    return "$exit_code"
  fi
  if [[ -d "$WORKSPACE_ROOT/vllm-hust-org-profile" ]]; then
    log "Organization profile repo is available at $WORKSPACE_ROOT/vllm-hust-org-profile (special repo: vLLM-HUST/.github)."
  fi
  log_perf_step_end "$perf_description" "$perf_start_epoch" 0
}

conda_env_exists() {
  run_conda_cmd env list | awk '{print $1}' | grep -Fxq "$ENV_NAME"
}

get_conda_env_python_version() {
  local env_name="$1"

  local env_python_bin=""

  env_python_bin="$(get_conda_env_python_bin "$env_name" 2>/dev/null || true)"
  if [[ -n "$env_python_bin" && -x "$env_python_bin" ]]; then
    "$env_python_bin" - <<'PY'
import sys

print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
    return 0
  fi

  run_conda_env_cmd "$env_name" python - <<'PY'
import sys

print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

reconcile_conda_env_python_version() {
  local current_python_version=""

  current_python_version="$(get_conda_env_python_version "$ENV_NAME" 2>/dev/null || true)"
  if [[ -z "$current_python_version" ]]; then
    log "Warning: could not determine Python version for conda env '$ENV_NAME'; quickstart will continue with the existing interpreter."
    return 0
  fi

  if [[ "$current_python_version" == "$PYTHON_VERSION" ]]; then
    log "Conda env '$ENV_NAME' already matches requested python=$PYTHON_VERSION"
    return 0
  fi

  accept_conda_tos_if_needed
  log "Conda env '$ENV_NAME' uses python=$current_python_version, but quickstart requested python=$PYTHON_VERSION"
  log "Updating '$ENV_NAME' in place to python=$PYTHON_VERSION..."
  log "Using explicit channels for Python reconciliation:"
  log "  - $CONDA_ASCEND_CHANNEL"
  log "  - $CONDA_FORGE_MIRROR_CHANNEL"
  if ! run_conda_cmd install -y -n "$ENV_NAME" \
    --override-channels \
    -c "$CONDA_ASCEND_CHANNEL" \
    -c "$CONDA_FORGE_MIRROR_CHANNEL" \
    "python=$PYTHON_VERSION" pip; then
    log "Mirror-based Python reconciliation failed; retrying with fallback channel '$CONDA_FORGE_FALLBACK_CHANNEL'"
    run_conda_cmd install -y -n "$ENV_NAME" \
      --override-channels \
      -c "$CONDA_ASCEND_CHANNEL" \
      -c "$CONDA_FORGE_FALLBACK_CHANNEL" \
      "python=$PYTHON_VERSION" pip
  fi

  current_python_version="$(get_conda_env_python_version "$ENV_NAME" 2>/dev/null || true)"
  if [[ "$current_python_version" == "$PYTHON_VERSION" ]]; then
    log "Conda env '$ENV_NAME' is now using python=$current_python_version"
    return 0
  fi

  log "Warning: conda env '$ENV_NAME' still reports python=${current_python_version:-unknown} after reconciliation attempt"
  return 1
}

ensure_hust_ascend_manager_bootstrap_in_env() {
  local env_python_bin=""

  env_python_bin="$(get_conda_env_python_bin "$ENV_NAME" 2>/dev/null || true)"
  if [[ -z "$env_python_bin" || ! -x "$env_python_bin" ]]; then
    log "Warning: could not locate Python interpreter for conda env '$ENV_NAME' while checking hust-ascend-manager bootstrap state"
    return 1
  fi

  if "$env_python_bin" -c 'import hust_ascend_manager.cli' >/dev/null 2>&1; then
    return 0
  fi

  if [[ ! -f "$MANAGER_REPO/pyproject.toml" ]]; then
    log "Warning: hust-ascend-manager source repo is unavailable at '$MANAGER_REPO'; bootstrap repair skipped"
    return 1
  fi

  log "Installing bootstrap Python packaging tools into '$ENV_NAME'"
  run_with_heartbeat \
    "installing bootstrap Python packaging tools into $ENV_NAME" \
    run_pip_install_with_python_bin "$env_python_bin" -- --upgrade pip "setuptools==$QUICKSTART_SETUPTOOLS_VERSION" wheel

  log "Repairing hust-ascend-manager bootstrap install in '$ENV_NAME'"
  run_with_heartbeat \
    "repairing hust-ascend-manager bootstrap install in $ENV_NAME" \
    run_pip_install_with_python_bin "$env_python_bin" -- --no-build-isolation -e "$MANAGER_REPO"

  if "$env_python_bin" -c 'import hust_ascend_manager.cli' >/dev/null 2>&1; then
    log "Verified hust-ascend-manager bootstrap install in '$ENV_NAME'"
    return 0
  fi

  log "Warning: hust-ascend-manager is still unavailable in '$ENV_NAME' after bootstrap repair"
  return 1
}

accept_conda_tos_if_needed() {
  if ! run_conda_cmd tos --help >/dev/null 2>&1; then
    return 0
  fi

  local conda_base
  local safe_base
  local marker_file
  conda_base="$(run_conda_cmd info --base 2>/dev/null || true)"
  safe_base="${conda_base:-default}"
  safe_base="${safe_base//\//_}"
  safe_base="${safe_base// /_}"
  marker_file="$TOS_MARKER_ROOT/conda_tos_${safe_base}.marker"

  if [[ -f "$marker_file" ]] \
     && grep -Fxq "$CONDA_MAIN_CHANNEL" "$marker_file" \
     && grep -Fxq "$CONDA_R_CHANNEL" "$marker_file"; then
    return 0
  fi

  local accepted=0

  if (( AUTO_YES == 1 )); then
    log "Accepting conda channel Terms of Service in non-interactive mode..."
    if run_conda_cmd tos accept --override-channels --channel "$CONDA_MAIN_CHANNEL" >/dev/null 2>&1 \
      && run_conda_cmd tos accept --override-channels --channel "$CONDA_R_CHANNEL" >/dev/null 2>&1; then
      accepted=1
    fi
  elif ask_yes_no "Accept Anaconda channel Terms of Service automatically?"; then
    if run_conda_cmd tos accept --override-channels --channel "$CONDA_MAIN_CHANNEL" >/dev/null 2>&1 \
      && run_conda_cmd tos accept --override-channels --channel "$CONDA_R_CHANNEL" >/dev/null 2>&1; then
      accepted=1
    fi
  fi

  if (( accepted == 1 )); then
    mkdir -p "$TOS_MARKER_ROOT"
    {
      printf '%s\n' "$CONDA_MAIN_CHANNEL"
      printf '%s\n' "$CONDA_R_CHANNEL"
    } > "$marker_file"
    log "Recorded conda ToS acceptance marker: $marker_file"
  elif (( AUTO_YES == 1 )); then
    log "Warning: could not confirm conda ToS acceptance automatically"
  fi
}

create_or_update_conda_env() {
  local perf_description=""
  local perf_start_epoch=""
  ensure_conda_available
  ensure_system_build_packages

  if conda_env_exists; then
    perf_description="update conda environment $ENV_NAME"
    perf_start_epoch="$(date +%s)"
    log_perf_step_start "$perf_description"
    log "Conda env '$ENV_NAME' already exists. Updating core tools..."
    reconcile_conda_env_python_version
    ensure_hust_ascend_manager_bootstrap_in_env
  else
    accept_conda_tos_if_needed
    perf_description="create conda environment $ENV_NAME"
    perf_start_epoch="$(date +%s)"
    log_perf_step_start "$perf_description"
    log "Creating conda env '$ENV_NAME' (python=$PYTHON_VERSION)..."
    log "Using explicit channels for env creation:"
    log "  - $CONDA_ASCEND_CHANNEL"
    log "  - $CONDA_FORGE_MIRROR_CHANNEL"
    if ! run_conda_cmd create -y -n "$ENV_NAME" \
      --override-channels \
      -c "$CONDA_ASCEND_CHANNEL" \
      -c "$CONDA_FORGE_MIRROR_CHANNEL" \
      "python=$PYTHON_VERSION" pip; then
      log "Mirror-based env creation failed; retrying with fallback channel '$CONDA_FORGE_FALLBACK_CHANNEL'"
      run_conda_cmd create -y -n "$ENV_NAME" \
        --override-channels \
        -c "$CONDA_ASCEND_CHANNEL" \
        -c "$CONDA_FORGE_FALLBACK_CHANNEL" \
        "python=$PYTHON_VERSION" pip
    fi
  fi

  log "Installing baseline tools into '$ENV_NAME'..."
  run_with_heartbeat \
    "installing baseline Python tooling into $ENV_NAME" \
    run_pip_install_in_env "$ENV_NAME" -- --upgrade pip "setuptools==$QUICKSTART_SETUPTOOLS_VERSION" wheel
  run_with_heartbeat \
    "installing pytest and pre-commit into $ENV_NAME" \
    run_pip_install_in_env "$ENV_NAME" -- pytest pre-commit

  install_workspace_repos_into_env "refresh" "$INSTALL_SCOPE" "with-runtime-reconcile"
  local install_rc=$?
  if [[ "$install_rc" -ne 0 ]]; then
    log "Conda env '$ENV_NAME' setup stopped because repository installation failed (rc=$install_rc)"
    return "$install_rc"
  fi

  configure_bashrc_conda_init
  maybe_update_bashrc_auto_activate_env

  log "Conda env ready: $ENV_NAME"
  log "Activate with: conda activate $ENV_NAME"
  if [[ -n "$perf_description" && -n "$perf_start_epoch" ]]; then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
  fi
}

read_project_name_from_pyproject() {
  local repo_path="$1"

  awk '
    /^\[project\]/ { in_project=1; next }
    /^\[/ && in_project { exit }
    in_project && $1 == "name" {
      match($0, /"[^"]+"/)
      if (RSTART > 0) {
        print substr($0, RSTART + 1, RLENGTH - 2)
        exit
      }
    }
  ' "$repo_path/pyproject.toml"
}

read_project_name_from_setup_py() {
  local repo_path="$1"

  awk '
    /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=[[:space:]]*["\047]/ {
      line = $0
      variable_name = line
      sub(/[[:space:]]*=.*/, "", variable_name)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", variable_name)
      sub(/^[^=]*=[[:space:]]*["\047]/, "", line)
      sub(/["\047][[:space:]]*$/, "", line)
      setup_py_string_vars[variable_name] = line
    }
    /setup[[:space:]]*\(/ { in_setup=1 }
    in_setup && /^[[:space:]]*name[[:space:]]*=/ {
      line = $0
      if (line ~ /^[[:space:]]*name[[:space:]]*=[[:space:]]*["\047]/) {
        sub(/^[[:space:]]*name[[:space:]]*=[[:space:]]*["\047]/, "", line)
        sub(/["\047][[:space:]]*,?[[:space:]]*$/, "", line)
        print line
        exit
      }

      sub(/^[[:space:]]*name[[:space:]]*=[[:space:]]*/, "", line)
      sub(/[[:space:]]*,?[[:space:]]*$/, "", line)
      if (line in setup_py_string_vars) {
        print setup_py_string_vars[line]
        exit
      }
      print line
      exit
    }
  ' "$repo_path/setup.py"
}

read_project_name() {
  local repo_path="$1"
  local project_name=""

  if [[ -f "$repo_path/pyproject.toml" ]]; then
    project_name="$(read_project_name_from_pyproject "$repo_path")"
    if [[ -n "$project_name" ]]; then
      printf '%s\n' "$project_name"
      return 0
    fi
  fi

  if [[ -f "$repo_path/setup.py" ]]; then
    project_name="$(read_project_name_from_setup_py "$repo_path")"
    if [[ -n "$project_name" ]]; then
      printf '%s\n' "$project_name"
      return 0
    fi
  fi
}

build_installable_repo_entries() {
  local scope="$1"
  local core_repo_candidates=(
    "$MANAGER_REPO"
    "$WORKSPACE_ROOT/vllm-hust"
    "$WORKSPACE_ROOT/vllm-ascend-hust"
    "$WORKSPACE_ROOT/vllm-hust-benchmark"
  )

  local extra_repo_candidates=(
    "$WORKSPACE_ROOT/vllm-hust-workstation"
    "$WORKSPACE_ROOT/vllm-hust-docs"
    "$WORKSPACE_ROOT/vllm-hust-website"
    "$WORKSPACE_ROOT/EvoScientist"
    "$WORKSPACE_ROOT/vllm-hust-perf-analyzer"
  )

  local repo_candidates=()
  repo_candidates+=("${core_repo_candidates[@]}")
  if [[ "$scope" == "full" ]]; then
    repo_candidates+=("${extra_repo_candidates[@]}")
  fi

  local repo_path
  local project_name
  for repo_path in "${repo_candidates[@]}"; do
    if [[ ! -d "$repo_path" || ! -f "$repo_path/pyproject.toml" ]]; then
      continue
    fi

    project_name="$(read_project_name "$repo_path")"
    if [[ -z "$project_name" ]]; then
      log "Warning: could not determine project name from $repo_path metadata, skipped" >&2
      continue
    fi

    printf '%s|%s\n' "$repo_path" "$project_name"
  done
}

is_package_installed_in_env() {
  local env_name="$1"
  local project_name="$2"

  run_conda_env_cmd "$env_name" python -m pip show "$project_name" >/dev/null 2>&1
}

has_vllm_cli_in_env() {
  local env_name="$1"
  run_conda_env_cmd "$env_name" python -c 'import shutil, sys; sys.exit(0 if shutil.which("vllm") else 1)'
}

report_vllm_cli_status() {
  local env_name="$1"
  local perf_description="report_vllm_cli_status in $env_name"
  local perf_description_lookup="report_vllm_cli_status lookup in $env_name"
  local perf_description_import="report_vllm_cli_status cli import in $env_name"
  local perf_start_epoch
  local perf_start_epoch_lookup
  local perf_start_epoch_import

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  perf_start_epoch_lookup="$(date +%s)"
  log_perf_step_start "$perf_description_lookup"
  if ! has_vllm_cli_in_env "$env_name"; then
    log "Warning: 'vllm' command is unavailable in conda env '$env_name'"
    log_perf_step_end "$perf_description_lookup" "$perf_start_epoch_lookup" 1
    log_perf_step_end "$perf_description" "$perf_start_epoch" 1
    return 1
  fi
  log_perf_step_end "$perf_description_lookup" "$perf_start_epoch_lookup" 0

  perf_start_epoch_import="$(date +%s)"
  log_perf_step_start "$perf_description_import"
  if run_conda_env_cmd "$env_name" env TORCH_DEVICE_BACKEND_AUTOLOAD=0 python - >/dev/null 2>&1 <<'PY'
from shutil import which

assert which("vllm-hust") or which("vllm")
from vllm.entrypoints.cli.main import _resolve_cli_version

print(_resolve_cli_version())
PY
  then
    log "Verified: 'vllm' command is available in conda env '$env_name'"
    log_perf_step_end "$perf_description_import" "$perf_start_epoch_import" 0
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "Warning: 'vllm' command exists in '$env_name' but runtime validation failed (for example missing backend/runtime libs)."
  log_perf_step_end "$perf_description_import" "$perf_start_epoch_import" 1
  log_perf_step_end "$perf_description" "$perf_start_epoch" 1
  return 1
}
ensure_pip_package_in_env() {
  local env_name="$1"
  local package_spec="$2"

  if pip_requirement_satisfied_in_env "$env_name" "$package_spec"; then
    return 0
  fi

  log "Installing missing Python dependency '$package_spec' into '$env_name'"
  run_with_heartbeat \
    "installing $package_spec into $env_name" \
    run_pip_install_in_env "$env_name" -- "$package_spec"
}

pip_requirement_satisfied_in_env() {
  local env_name="$1"
  local package_spec="$2"
  local check_script=''

  check_script='
import sys
from importlib.metadata import PackageNotFoundError, version

try:
    from packaging.requirements import Requirement
except ImportError:
    raise SystemExit(1)

requirement = Requirement(sys.argv[1])

if requirement.marker and not requirement.marker.evaluate():
    raise SystemExit(0)

try:
    installed_version = version(requirement.name)
except PackageNotFoundError:
    raise SystemExit(1)

if requirement.name.lower() == "pybind11":
    try:
        import pybind11  # noqa: F401
    except ImportError:
        raise SystemExit(1)

if requirement.specifier and not requirement.specifier.contains(installed_version, prereleases=True):
    raise SystemExit(1)

raise SystemExit(0)
'

  run_conda_env_cmd "$env_name" python -c "$check_script" "$package_spec" >/dev/null 2>&1
}

list_missing_pip_requirements_in_env() {
  local env_name="$1"
  shift
  local requirement_specs=("$@")
  local check_script=''

  if (( ${#requirement_specs[@]} == 0 )); then
    return 0
  fi

  check_script='
import sys
from importlib.metadata import PackageNotFoundError, version

try:
    from packaging.requirements import Requirement
except ImportError:
    raise SystemExit(1)

for raw_spec in sys.argv[1:]:
    requirement = Requirement(raw_spec)

    if requirement.marker and not requirement.marker.evaluate():
        continue

    try:
        installed_version = version(requirement.name)
    except PackageNotFoundError:
        print(raw_spec)
        continue

    if requirement.name.lower() == "pybind11":
        try:
            import pybind11  # noqa: F401
        except ImportError:
            print(raw_spec)
            continue

    if requirement.specifier and not requirement.specifier.contains(installed_version, prereleases=True):
        print(raw_spec)
'

  # conda run does not reliably forward heredoc stdin to its child process.
  # Pass the checker via -c so an EOF in the wrapper cannot be mistaken for a
  # successful dependency check.
  run_conda_env_cmd "$env_name" python -c "$check_script" "${requirement_specs[@]}"
}

repo_requires_ascend_runtime() {
  local repo_path="$1"

  [[ "$repo_path" == "$WORKSPACE_ROOT/vllm-ascend-hust" ]]
}

has_local_ascend_plugin_checkout() {
  [[ -f "$WORKSPACE_ROOT/vllm-ascend-hust/pyproject.toml" ]]
}

repo_prefers_no_build_isolation() {
  local repo_path="$1"

  [[ "$repo_path" == "$MANAGER_REPO" || "$repo_path" == "$WORKSPACE_ROOT/vllm-hust" || "$repo_path" == "$WORKSPACE_ROOT/vllm-hust-benchmark" ]]
}

ensure_vllm_hust_editable_build_python_packages() {
  local repo_path="$1"
  local perf_description="vllm-hust requirement check (editable build) in $ENV_NAME"
  local perf_start_epoch
  local package_name
  local package_spec
  local build_package_specs=()
  local missing_package_specs=()
  local build_packages=(
    cmake
    ninja
    packaging
    setuptools
    setuptools-scm
    setuptools-rust
    torch
    wheel
    jinja2
  )
  local rc=0

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  for package_name in "${build_packages[@]}"; do
    package_spec="$(read_build_requirement_spec_from_pyproject "$repo_path" "$package_name" || true)"
    if [[ -z "$package_spec" ]]; then
      package_spec="$package_name"
    fi
    build_package_specs+=("$package_spec")
  done

  log "Checking vllm-hust editable build requirements in '$ENV_NAME' (${#build_package_specs[@]} packages)"
  mapfile -t missing_package_specs < <(list_missing_pip_requirements_in_env "$ENV_NAME" "${build_package_specs[@]}" || true)

  if (( ${#missing_package_specs[@]} == 0 )); then
    log "vllm-hust editable build requirements already satisfied in '$ENV_NAME'"
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "Missing vllm-hust editable build requirements: ${missing_package_specs[*]}"
  log "Installing missing vllm-hust editable build requirements into '$ENV_NAME' (${#missing_package_specs[@]} packages)"
  for package_spec in "${missing_package_specs[@]}"; do
    ensure_pip_package_in_env "$ENV_NAME" "$package_spec"
    rc=$?
    if (( rc != 0 )); then
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
      return "$rc"
    fi
  done

  log_perf_step_end "$perf_description" "$perf_start_epoch" 0
}

ensure_vllm_hust_runtime_python_packages() {
  local repo_path="$1"
  local perf_description="vllm-hust requirement check (runtime) in $ENV_NAME"
  local perf_start_epoch
  local requirements_file="$repo_path/requirements/common.txt"
  local requirement_specs=()
  local missing_requirement_specs=()
  local rc=0

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  if ! mapfile -t requirement_specs < <(list_requirement_specs_from_file "$requirements_file" || true); then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi
  if (( ${#requirement_specs[@]} == 0 )); then
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "Checking vllm-hust common runtime Python dependencies in '$ENV_NAME' (${#requirement_specs[@]} packages)"
  mapfile -t missing_requirement_specs < <(list_missing_pip_requirements_in_env "$ENV_NAME" "${requirement_specs[@]}" || true)

  if (( ${#missing_requirement_specs[@]} == 0 )); then
    log "vllm-hust common runtime Python dependencies already satisfied in '$ENV_NAME'"
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "Missing vllm-hust common runtime Python dependencies: ${missing_requirement_specs[*]}"
  log "Installing missing vllm-hust common runtime Python dependencies into '$ENV_NAME' (${#missing_requirement_specs[@]} packages)"
  run_with_heartbeat \
    "installing vllm-hust common runtime Python dependencies into $ENV_NAME" \
    run_pip_install_in_env "$ENV_NAME" -- "${missing_requirement_specs[@]}"
  rc=$?
  if (( rc != 0 )); then
    log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
    return "$rc"
  fi

  log_perf_step_end "$perf_description" "$perf_start_epoch" 0
}

install_editable_repo_into_env() {
  local repo_path="$1"
  local reconcile_mode="${2:-without-runtime-reconcile}"
  local editable_target="$repo_path"
  local pip_args=()
  local compile_custom_kernels
  local ascend_install_rc=0

  compile_custom_kernels="$(default_ascend_compile_custom_kernels)"

  if repo_requires_ascend_runtime "$repo_path"; then
    if ! should_reconcile_ascend_runtime; then
      log "Skipping Ascend-only repo '$repo_path' because no Ascend runtime was detected on this host."
      return 10
    fi

    if ! is_package_installed_in_env "$ENV_NAME" "torch-npu"; then
      if [[ "$reconcile_mode" == "with-runtime-reconcile" ]]; then
        log "Skipping Ascend-only repo '$repo_path' because torch-npu is still unavailable after runtime reconciliation."
      else
        log "Skipping Ascend-only repo '$repo_path' because torch-npu is not installed in '$ENV_NAME'. Run quickstart with --conda to reconcile the Ascend Python stack first."
      fi
      return 11
    fi

    if ! ensure_ascend_torch_runtime_healthy "$ENV_NAME"; then
      log "Skipping Ascend-only repo '$repo_path' because torch/torch-npu runtime imports are unhealthy in '$ENV_NAME'."
      return 11
    fi

    install_ascend_repo_into_env "$repo_path" "$compile_custom_kernels"
    ascend_install_rc=$?
    if [[ "$ascend_install_rc" -eq 0 ]]; then
      return 0
    fi

    if [[ "$compile_custom_kernels" != "0" ]] && ! ascend_compile_custom_kernels_configured_explicitly; then
      case "$ascend_install_rc" in
        23|25)
          log "Ascend custom-kernel install failed in auto mode; falling back to lightweight plugin mode"
          install_ascend_repo_into_env "$repo_path" "0"
          return $?
          ;;
      esac
    fi

    return "$ascend_install_rc"
  fi

  local pip_env=()
  if [[ "$(basename "$repo_path")" == "vllm-hust" ]]; then
    editable_target="${repo_path}[ci-smoke]"
    log "Preparing vllm-hust editable install in '$ENV_NAME'"
    # Build vllm-hust from source with no CUDA/HIP C extensions.
    # VLLM_USE_PRECOMPILED=0 prevents setup.py from trying to download
    # CUDA-only prebuilt wheels from wheels.vllm.ai (not available for Ascend/aarch64).
    # Disable backend entrypoint auto-loading while generating editable
    # metadata; otherwise torch imports can eagerly pull in torch_npu and fail
    # on missing Ascend runtime libs such as libhccl.so before runtime setup.
    pip_env+=(
      "VLLM_TARGET_DEVICE=empty"
      "VLLM_USE_PRECOMPILED=0"
      "TORCH_DEVICE_BACKEND_AUTOLOAD=0"
    )
    # Reuse the current conda env for editable metadata/build hooks instead of
    # letting pip create an isolated env that re-resolves torch/CUDA build deps.
    ensure_vllm_hust_editable_build_python_packages "$repo_path"
    if should_reconcile_ascend_runtime; then
      # On Ascend hosts, keep torch/torch-npu/triton stack under the manager
      # manifest and vllm-ascend-hust requirements.  Install vllm-hust common
      # runtime deps separately, then do editable install with --no-deps to
      # avoid pulling the upstream CUDA torch pin into the shared env.
      ensure_vllm_hust_runtime_python_packages "$repo_path"
    fi
  fi

  pip_args=(-v -e "$editable_target")
  if [[ "$(basename "$repo_path")" == "vllm-hust" ]]; then
    pip_args=(--no-deps "${pip_args[@]}")
  fi
  if repo_prefers_no_build_isolation "$repo_path"; then
    pip_args=(--no-build-isolation "${pip_args[@]}")
  fi
  if [[ "$(basename "$repo_path")" == "vllm-hust" ]] && should_reconcile_ascend_runtime; then
    pip_args=(--no-deps "${pip_args[@]}")
  fi

  log "Installing editable package from: $repo_path"
  run_with_heartbeat \
    "installing editable package from $repo_path" \
    run_pip_install_in_env "$ENV_NAME" "${pip_env[@]}" -- "${pip_args[@]}"
}

should_reconcile_ascend_runtime() {
  if [[ ! -f "$WORKSPACE_ROOT/vllm-ascend-hust/pyproject.toml" ]]; then
    return 1
  fi

  if command -v npu-smi >/dev/null 2>&1; then
    return 0
  fi

  if [[ -n "${ASCEND_HOME_PATH:-}" || -d "/usr/local/Ascend" ]]; then
    return 0
  fi

  if [[ -n "${CONDA_PREFIX:-}" && -d "${CONDA_PREFIX}/Ascend" ]]; then
    return 0
  fi

  return 1
}

should_apply_ascend_system_steps_in_quickstart() {
  if [[ "${HUST_DEV_HUB_SKIP_ASCEND_SYSTEM_APPLY:-0}" == "1" ]]; then
    return 1
  fi

  if [[ "${HUST_DEV_HUB_APPLY_ASCEND_SYSTEM_STEPS:-0}" == "1" ]]; then
    return 0
  fi

  return 1
}

reconcile_ascend_runtime_with_manager() {
  if ! should_reconcile_ascend_runtime; then
    log "Skipping Ascend Python stack reconciliation because no Ascend runtime was detected on this host."
    return 0
  fi

  # Log detected CANN version and selected manifest for transparency
  local _cann_ver
  _cann_ver="$(detect_cann_major_version 2>/dev/null || echo "unknown")"
  log "CANN detection: major_version=$_cann_ver, manifest=$(basename "$MANAGER_MANIFEST_DEFAULT")"

  if ! is_package_installed_in_env "$ENV_NAME" "hust-ascend-manager"; then
    if [[ -f "$MANAGER_REPO/pyproject.toml" ]]; then
      log "Installing ascend-runtime-manager before Ascend runtime reconciliation"
      run_with_heartbeat \
        "installing editable package from $MANAGER_REPO" \
        run_pip_install_in_env "$ENV_NAME" -- --no-build-isolation -v -e "$MANAGER_REPO"
    else
      log "Warning: hust-ascend-manager is not installed and local repo is unavailable; skipping Ascend runtime reconciliation"
      return 0
    fi
  fi

  local manager_args=(setup --install-python-stack)
  if should_apply_ascend_system_steps_in_quickstart; then
    manager_args+=(--apply-system)
    log "Opt-in enabled: quickstart will also apply system-level Ascend setup steps"
  else
    log "Quickstart keeps Ascend reconciliation in user space only; set HUST_DEV_HUB_APPLY_ASCEND_SYSTEM_STEPS=1 to opt into system-level steps"
  fi
  if [[ -f "$MANAGER_MANIFEST_DEFAULT" ]]; then
    manager_args+=(--manifest "$MANAGER_MANIFEST_DEFAULT")
  fi

  if (( AUTO_YES == 1 )); then
    manager_args+=(--non-interactive)
  fi

  log "Starting Ascend Python stack reconciliation via hust-ascend-manager"
  log "Reconciling Ascend Python stack via hust-ascend-manager (user-space only; no system changes)"
  run_with_heartbeat \
    "reconciling Ascend Python stack via hust-ascend-manager" \
    run_conda_env_cmd "$ENV_NAME" python -m hust_ascend_manager.cli "${manager_args[@]}"
}

install_ascend_plugin_pypi_fallback_with_manager() {
  local env_python_bin
  local command_args=(
    env
    "HOME=$CURRENT_USER_HOME"
    "XDG_CACHE_HOME=$CURRENT_USER_CACHE_HOME"
    "XDG_CONFIG_HOME=$CURRENT_USER_CONFIG_HOME"
    "PIP_CACHE_DIR=$CURRENT_USER_CACHE_HOME/pip"
    LD_LIBRARY_PATH=
  )

  if ! should_reconcile_ascend_runtime; then
    return 0
  fi

  if has_local_ascend_plugin_checkout; then
    return 0
  fi

  if [[ ! -f "$WORKSPACE_ROOT/vllm-hust/pyproject.toml" ]]; then
    log "Warning: vllm-hust repo is unavailable, skipped PyPI fallback install for $ASCEND_PLUGIN_PYPI_PACKAGE"
    return 1
  fi

  env_python_bin="$(get_conda_env_python_bin "$ENV_NAME" 2>/dev/null || true)"
  if [[ -z "$env_python_bin" || ! -x "$env_python_bin" ]]; then
    log "Warning: could not resolve Python interpreter for '$ENV_NAME'; skipped PyPI fallback install for $ASCEND_PLUGIN_PYPI_PACKAGE"
    return 1
  fi

  mkdir -p "$CURRENT_USER_CACHE_HOME/pip" "$CURRENT_USER_CONFIG_HOME"
  ensure_pip_install_defaults
  if [[ -n "$PIP_SELECTED_INDEX_URL" && -z "${PIP_INDEX_URL:-}" ]]; then
    command_args+=("PIP_INDEX_URL=$PIP_SELECTED_INDEX_URL")
  fi
  if [[ -n "$PIP_SELECTED_EXTRA_INDEX_URL" && -z "${PIP_EXTRA_INDEX_URL:-}" ]]; then
    command_args+=("PIP_EXTRA_INDEX_URL=$PIP_SELECTED_EXTRA_INDEX_URL")
  fi

  log "Local vllm-ascend-hust checkout is unavailable; installing $ASCEND_PLUGIN_PYPI_PACKAGE from PyPI fallback via hust-ascend-manager"
  command_args+=(
    "$env_python_bin"
    -m
    hust_ascend_manager.cli
    runtime
    repair
    --repo
    "$WORKSPACE_ROOT/vllm-hust"
    --python
    "$env_python_bin"
    --skip-torch-install
    --skip-build-deps
    --skip-rebuild
    --install-plugin
    --plugin-package
    "$ASCEND_PLUGIN_PYPI_PACKAGE"
  )

  run_with_heartbeat \
    "installing $ASCEND_PLUGIN_PYPI_PACKAGE from PyPI fallback" \
    "${command_args[@]}"
}

ensure_git_safe_directory_for_workspace() {
  # When running inside a Docker container, host-mounted repos may be owned by a
  # different UID than the current user (e.g. host UID 1002 vs container root).
  # Git refuses to operate on such repos with "dubious ownership" errors.
  # Auto-detect UID mismatches and mark affected repos as safe directories.
  local current_uid
  current_uid="$(id -u 2>/dev/null || echo -1)"

  local repo_dir
  local repo_owner_uid
  local fixed_any=0
  for repo_dir in "$WORKSPACE_ROOT"/*/; do
    repo_dir="${repo_dir%/}"
    if [[ ! -d "$repo_dir/.git" ]]; then
      continue
    fi
    repo_owner_uid="$(stat -c '%u' "$repo_dir" 2>/dev/null || echo -1)"
    if [[ "$repo_owner_uid" != "$current_uid" && "$repo_owner_uid" != "-1" ]]; then
      if ! git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$repo_dir"; then
        git config --global --add safe.directory "$repo_dir"
        fixed_any=1
      fi
    fi
  done

  if (( fixed_any )); then
    log "Auto-configured git safe.directory for host-mounted repos with UID mismatch (host=$repo_owner_uid, container=$current_uid)"
  fi
}

# Pin fastapi to a version compatible with both starlette >=1.0.0 (vllm-hust pin)
# and prometheus-fastapi-instrumentator >=7.0.0.  fastapi >=0.135.0 introduces
# _IncludedRouter which breaks instrumentator's route iteration.  fastapi <0.124.0
# requires starlette <0.51.0 which conflicts with vllm-hust's starlette >=1.0.0 pin.
# The compatible window is fastapi 0.130.x–0.134.x with starlette 1.0.x–1.2.x.
ensure_fastapi_instrumentator_compat() {
  local perf_description="ensure_fastapi_instrumentator_compat in $ENV_NAME"
  local perf_start_epoch
  local fastapi_version=""
  local rc=0

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  fastapi_version="$(run_conda_env_cmd "$ENV_NAME" python -c 'import fastapi; print(fastapi.__version__)' 2>/dev/null || true)"

  # Check if fastapi is missing or in the incompatible range
  if [[ -z "$fastapi_version" ]]; then
    log "Installing fastapi and prometheus-fastapi-instrumentator (compatible set)"
    run_pip_install_in_env "$ENV_NAME" -- "fastapi>=0.130.0,<0.135.0" "prometheus-fastapi-instrumentator>=7.0.0"
    rc=$?
    if (( rc != 0 )); then
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
      return "$rc"
    fi
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  # If fastapi >= 0.135.0, downgrade to compatible version
  local major minor patch
  IFS='.' read -r major minor patch <<< "${fastapi_version%%+*}"
  if (( minor >= 135 )); then
    log "Pinning fastapi from $fastapi_version to <0.135.0 for instrumentator compatibility"
    run_pip_install_in_env "$ENV_NAME" -- "fastapi>=0.130.0,<0.135.0" "prometheus-fastapi-instrumentator>=7.0.0"
    rc=$?
    if (( rc != 0 )); then
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
      return "$rc"
    fi
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  # If prometheus-fastapi-instrumentator is missing, install it
  if ! is_package_installed_in_env "$ENV_NAME" "prometheus-fastapi-instrumentator"; then
    log "Installing prometheus-fastapi-instrumentator (fastapi $fastapi_version is compatible)"
    run_pip_install_in_env "$ENV_NAME" -- "prometheus-fastapi-instrumentator>=7.0.0"
    rc=$?
    if (( rc != 0 )); then
      log_perf_step_end "$perf_description" "$perf_start_epoch" "$rc"
      return "$rc"
    fi
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  log "FastAPI/instrumentator compatibility: OK (fastapi=$fastapi_version)"
  log_perf_step_end "$perf_description" "$perf_start_epoch" 0
}

install_workspace_repos_into_env() {
  local install_mode="${1:-$INSTALL_MODE}"
  local install_scope="${2:-$INSTALL_SCOPE}"
  local reconcile_mode="${3:-without-runtime-reconcile}"
  local perf_description="install workspace repositories into $ENV_NAME (mode=$install_mode, scope=$install_scope)"
  local perf_start_epoch

  perf_start_epoch="$(date +%s)"
  log_perf_step_start "$perf_description"

  if ! ensure_conda_available "no-bootstrap"; then
    log "Install-only flow requires an existing conda setup. Run quickstart with --conda (or --all) first."
    log_perf_step_end "$perf_description" "$perf_start_epoch" 2
    return 2
  fi

  ensure_git_safe_directory_for_workspace

  if ! conda_env_exists; then
    log "Conda env '$ENV_NAME' does not exist yet. Create it first with --conda."
    log_perf_step_end "$perf_description" "$perf_start_epoch" 2
    return 2
  fi

  configure_conda_env_library_hooks

  if [[ "$install_mode" != "install" && "$install_mode" != "refresh" ]]; then
    echo "Invalid install mode: $install_mode" >&2
    log_perf_step_end "$perf_description" "$perf_start_epoch" 2
    return 2
  fi

  if [[ "$install_scope" != "core" && "$install_scope" != "full" ]]; then
    echo "Invalid install scope: $install_scope" >&2
    log_perf_step_end "$perf_description" "$perf_start_epoch" 2
    return 2
  fi

  local installed_any=0
  local installed_list=()
  local skipped_list=()
  local fatal_failure_messages=()
  local repo_result_messages=()
  local repo_entries=()
  local install_rc=0
  local fatal_failure_rc=0
  mapfile -t repo_entries < <(build_installable_repo_entries "$install_scope")

  if (( ${#repo_entries[@]} == 0 )); then
    log "No installable local repositories found (pyproject.toml missing or project name unavailable)."
    log_perf_step_end "$perf_description" "$perf_start_epoch" 0
    return 0
  fi

  local entry
  local manager_entry=""
  local non_manager_entries=()
  local repo_path
  local project_name
  local total_repo_count=0
  local repo_index=0
  for entry in "${repo_entries[@]}"; do
    repo_path="${entry%%|*}"
    project_name="${entry#*|}"
    if [[ "$project_name" == "hust-ascend-manager" ]]; then
      manager_entry="$entry"
    else
      non_manager_entries+=("$entry")
    fi
  done
  total_repo_count="${#non_manager_entries[@]}"
  if [[ -n "$manager_entry" ]]; then
    total_repo_count=$(( total_repo_count + 1 ))
  fi
  log "Planned editable repository installs into '$ENV_NAME': $total_repo_count repositories"

  if [[ -n "$manager_entry" ]]; then
    repo_path="${manager_entry%%|*}"
    project_name="${manager_entry#*|}"
    repo_index=$(( repo_index + 1 ))
    log "Repository install progress [$repo_index/$total_repo_count]: $project_name from $repo_path"

    if [[ "$install_mode" == "install" ]] && is_package_installed_in_env "$ENV_NAME" "$project_name"; then
      log "Skipping already installed package '$project_name' from: $repo_path"
      skipped_list+=("$repo_path ($project_name)")
      repo_result_messages+=("[$repo_index/$total_repo_count] skipped: $project_name")
    else
      if install_editable_repo_into_env "$repo_path" "$reconcile_mode"; then
        install_rc=0
      else
        install_rc=$?
      fi
      if [[ "$install_rc" -ne 0 ]]; then
        case "$install_rc" in
          10)
            skipped_list+=("$repo_path ($project_name)")
            repo_result_messages+=("[$repo_index/$total_repo_count] skipped: $project_name (host has no Ascend runtime)")
            ;;
          *)
            fatal_failure_rc="$install_rc"
            fatal_failure_messages+=("$repo_path ($project_name) failed with rc=$install_rc")
            repo_result_messages+=("[$repo_index/$total_repo_count] failed: $project_name (rc=$install_rc)")
            ;;
        esac
      fi
      installed_any=1
      if [[ "$install_rc" -eq 0 ]]; then
        installed_list+=("$repo_path ($project_name)")
        repo_result_messages+=("[$repo_index/$total_repo_count] installed: $project_name")
      fi
    fi
  fi

  if (( fatal_failure_rc != 0 )); then
    log "Aborting repository installation because a critical setup step failed."
    local failure_item
    for failure_item in "${fatal_failure_messages[@]}"; do
      log "  - $failure_item"
    done
    return "$fatal_failure_rc"
  fi

  if [[ "$reconcile_mode" == "with-runtime-reconcile" ]]; then
    log "Repository install progress: running Ascend Python stack reconciliation before remaining repositories"
    reconcile_ascend_runtime_with_manager
  else
    log "Skipping Ascend Python stack reconciliation for install-only flow. Use --conda to refresh the user-space environment."
  fi

  for entry in "${non_manager_entries[@]}"; do
    repo_path="${entry%%|*}"
    project_name="${entry#*|}"
    repo_index=$(( repo_index + 1 ))
    log "Repository install progress [$repo_index/$total_repo_count]: $project_name from $repo_path"

    if [[ "$install_mode" == "install" ]] && is_package_installed_in_env "$ENV_NAME" "$project_name"; then
      log "Skipping already installed package '$project_name' from: $repo_path"
      skipped_list+=("$repo_path ($project_name)")
      repo_result_messages+=("[$repo_index/$total_repo_count] skipped: $project_name")
      continue
    fi

    if install_editable_repo_into_env "$repo_path" "$reconcile_mode"; then
      install_rc=0
    else
      install_rc=$?
    fi
    if [[ "$install_rc" -ne 0 ]]; then
      case "$install_rc" in
        10)
          skipped_list+=("$repo_path ($project_name)")
          repo_result_messages+=("[$repo_index/$total_repo_count] skipped: $project_name (host has no Ascend runtime)")
          continue
          ;;
        *)
          fatal_failure_rc="$install_rc"
          fatal_failure_messages+=("$repo_path ($project_name) failed with rc=$install_rc")
          repo_result_messages+=("[$repo_index/$total_repo_count] failed: $project_name (rc=$install_rc)")
          break
          ;;
      esac
    fi
    installed_any=1
    installed_list+=("$repo_path ($project_name)")
    repo_result_messages+=("[$repo_index/$total_repo_count] installed: $project_name")
  done

  if (( fatal_failure_rc != 0 )); then
    log "Aborting repository installation because a critical setup step failed."
    local failure_item
    for failure_item in "${fatal_failure_messages[@]}"; do
      log "  - $failure_item"
    done
    return "$fatal_failure_rc"
  fi

  if install_ascend_plugin_pypi_fallback_with_manager; then
    if ! has_local_ascend_plugin_checkout && should_reconcile_ascend_runtime; then
      installed_any=1
      installed_list+=("$ASCEND_PLUGIN_PYPI_PACKAGE (PyPI fallback)")
    fi
  elif ! has_local_ascend_plugin_checkout && should_reconcile_ascend_runtime; then
    skipped_list+=("$ASCEND_PLUGIN_PYPI_PACKAGE (PyPI fallback failed)")
  fi

  if (( installed_any == 0 )); then
    if [[ "$install_mode" == "install" && ${#skipped_list[@]} -gt 0 ]]; then
      log "All selected repositories are already installed in '$ENV_NAME' (scope=$install_scope)."
    else
      log "No repositories were installed into '$ENV_NAME' (mode=$install_mode, scope=$install_scope)."
    fi
  else
    log "Installed editable repositories into '$ENV_NAME' (mode=$install_mode, scope=$install_scope):"
    local item
    for item in "${installed_list[@]}"; do
      log "  - $item"
    done
  fi

  if (( ${#repo_result_messages[@]} > 0 )); then
    log "Repository install result summary:"
    local repo_result_message
    for repo_result_message in "${repo_result_messages[@]}"; do
      log "  - $repo_result_message"
    done
  fi

  if [[ "$install_mode" == "install" && ${#skipped_list[@]} -gt 0 ]]; then
    local skipped_item
    log "Skipped already installed repositories:"
    for skipped_item in "${skipped_list[@]}"; do
      log "  - $skipped_item"
    done
  fi

  if [[ -d "$WORKSPACE_ROOT/vllm-ascend-hust" && ! -f "$WORKSPACE_ROOT/vllm-ascend-hust/pyproject.toml" ]]; then
    log "Warning: vllm-ascend-hust exists but has no pyproject.toml; quickstart used or will use the PyPI fallback when Ascend plugin install is required"
  fi

  ensure_fastapi_instrumentator_compat

  report_vllm_cli_status "$ENV_NAME" || true
  log_perf_step_end "$perf_description" "$perf_start_epoch" 0
  return 0
}

configure_conda_env_library_hooks() {
  local env_prefix
  local activate_dir
  local deactivate_dir
  local activate_script
  local deactivate_script

  env_prefix="$(get_conda_env_prefix "$ENV_NAME")"
  if [[ -z "$env_prefix" || ! -d "$env_prefix" ]]; then
    log "Skip conda activate hook setup because env prefix was not found for '$ENV_NAME'"
    return 0
  fi

  activate_dir="$env_prefix/etc/conda/activate.d"
  deactivate_dir="$env_prefix/etc/conda/deactivate.d"
  activate_script="$activate_dir/vllm-hust-dev-hub-libpath.sh"
  deactivate_script="$deactivate_dir/vllm-hust-dev-hub-libpath.sh"

  mkdir -p "$activate_dir" "$deactivate_dir"

  cat > "$activate_script" <<'EOF'
_hust_dev_hub_save_var() {
  local var_name="$1"
  local saved_name="HUST_DEV_HUB_SAVED_${var_name}"

  if [[ -n "${!saved_name+x}" ]]; then
    return 0
  fi

  if [[ -n "${!var_name+x}" ]]; then
    printf -v "$saved_name" '%s' "${!var_name}"
  else
    printf -v "$saved_name" '%s' "__UNSET__"
  fi
  export "$saved_name"
}

_hust_dev_hub_needs_user_cache_reset() {
  local value="$1"

  if [[ -z "$value" ]]; then
    return 0
  fi

  if [[ "$value" == /root || "$value" == /root/* ]]; then
    [[ "$(id -u)" != "0" ]]
    return $?
  fi

  return 1
}

_hust_dev_hub_resolve_user_home() {
  local user_name
  local user_home

  user_name="$(id -un 2>/dev/null || printf '%s' "${USER:-}")"
  user_home="$(getent passwd "$user_name" 2>/dev/null | cut -d: -f6 || true)"
  if [[ -n "$user_home" ]]; then
    printf '%s\n' "$user_home"
    return 0
  fi

  printf '%s\n' "${HOME:-$PWD}"
}

if [[ -z "${HUST_DEV_HUB_SAVED_LD_LIBRARY_PATH+x}" ]]; then
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    export HUST_DEV_HUB_SAVED_LD_LIBRARY_PATH="$LD_LIBRARY_PATH"
  else
    export HUST_DEV_HUB_SAVED_LD_LIBRARY_PATH="__UNSET__"
  fi
fi

if [[ -z "${HUST_DEV_HUB_SAVED_PATH+x}" ]]; then
  if [[ -n "${PATH:-}" ]]; then
    export HUST_DEV_HUB_SAVED_PATH="$PATH"
  else
    export HUST_DEV_HUB_SAVED_PATH="__UNSET__"
  fi
fi

for _hust_dev_hub_var in \
  HOME \
  XDG_CACHE_HOME \
  XDG_CONFIG_HOME \
  HF_HOME \
  HF_HUB_CACHE \
  HF_TOKEN_PATH \
  ASCEND_HOME_PATH \
  ASCEND_TOOLKIT_HOME \
  ASCEND_OPP_PATH \
  ASCEND_AICPU_PATH \
  TORCH_DEVICE_BACKEND_AUTOLOAD \
  HUST_ASCEND_RUNTIME_VERSION \
  HUST_ASCEND_HAS_STREAM_ATTR \
  HUST_ASCEND_OPP_OVERLAY_ROOT \
  HUST_ATB_SET_ENV; do
  _hust_dev_hub_save_var "$_hust_dev_hub_var"
done

_hust_dev_hub_runtime_home="$(_hust_dev_hub_resolve_user_home)"
if _hust_dev_hub_needs_user_cache_reset "${HOME:-}"; then
  export HOME="$_hust_dev_hub_runtime_home"
fi

if _hust_dev_hub_needs_user_cache_reset "${XDG_CACHE_HOME:-}"; then
  export XDG_CACHE_HOME="$HOME/.cache"
fi

if _hust_dev_hub_needs_user_cache_reset "${XDG_CONFIG_HOME:-}"; then
  export XDG_CONFIG_HOME="$HOME/.config"
fi

if _hust_dev_hub_needs_user_cache_reset "${HF_HOME:-}"; then
  export HF_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/huggingface"
fi

if _hust_dev_hub_needs_user_cache_reset "${HF_HUB_CACHE:-}"; then
  export HF_HUB_CACHE="${HF_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/huggingface}/hub"
fi

if _hust_dev_hub_needs_user_cache_reset "${HF_TOKEN_PATH:-}"; then
  export HF_TOKEN_PATH="${HF_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/huggingface}/token"
fi

mkdir -p \
  "${XDG_CACHE_HOME:-$HOME/.cache}" \
  "${XDG_CONFIG_HOME:-$HOME/.config}" \
  "${HF_HUB_CACHE:-${HF_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/huggingface}/hub}" \
  "$(dirname -- "${HF_TOKEN_PATH:-${HF_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/huggingface}/token}")"

if [[ "${HUST_DEV_HUB_ENABLE_MANAGER_ENV_HOOK:-0}" == "1" ]] \
  && command -v hust-ascend-manager >/dev/null 2>&1; then
  _hust_dev_hub_manager_env="$(hust-ascend-manager env --shell 2>/dev/null || true)"
  if [[ -n "$_hust_dev_hub_manager_env" ]]; then
    _hust_dev_hub_manager_env_filtered="$(printf '%s\n' "$_hust_dev_hub_manager_env" | \
      grep -E '^[[:space:]]*export[[:space:]]+(ASCEND_HOME_PATH|ASCEND_TOOLKIT_HOME|ASCEND_OPP_PATH|ASCEND_AICPU_PATH|TORCH_DEVICE_BACKEND_AUTOLOAD|HUST_ASCEND_RUNTIME_VERSION|HUST_ASCEND_HAS_STREAM_ATTR|HUST_ASCEND_OPP_OVERLAY_ROOT|HUST_ATB_SET_ENV|LD_LIBRARY_PATH|PYTHONPATH)=' || true)"
    if [[ -n "$_hust_dev_hub_manager_env_filtered" ]]; then
      eval "$_hust_dev_hub_manager_env_filtered"
    fi
  fi
  unset _hust_dev_hub_manager_env _hust_dev_hub_manager_env_filtered
fi

if [[ -n "${CONDA_PREFIX:-}" && -n "${LD_LIBRARY_PATH:-}" ]]; then
  _hust_dev_hub_ld_entries=()
  _hust_dev_hub_ld_filtered=()
  IFS=':' read -r -a _hust_dev_hub_ld_entries <<< "$LD_LIBRARY_PATH"
  for _hust_dev_hub_ld_entry in "${_hust_dev_hub_ld_entries[@]}"; do
    if [[ -z "$_hust_dev_hub_ld_entry" ]]; then
      continue
    fi
    case "$_hust_dev_hub_ld_entry" in
      "$CONDA_PREFIX"|"$CONDA_PREFIX"/*)
        continue
        ;;
      */envs/*/lib/python*/site-packages/torch/lib|*/envs/*/lib/python*/site-packages/torch_npu/lib|*/envs/*/lib)
        continue
        ;;
    esac
    _hust_dev_hub_ld_filtered+=("$_hust_dev_hub_ld_entry")
  done

  if (( ${#_hust_dev_hub_ld_filtered[@]} == 0 )); then
    unset LD_LIBRARY_PATH
  else
    export LD_LIBRARY_PATH="$(IFS=':'; printf '%s' "${_hust_dev_hub_ld_filtered[*]}")"
  fi

  unset _hust_dev_hub_ld_entries _hust_dev_hub_ld_filtered _hust_dev_hub_ld_entry
fi

# Re-prepend $CONDA_PREFIX/lib to LD_LIBRARY_PATH so that conda's newer
# libstdc++.so.6 (with CXXABI_1.3.15+) is found before the system's older
# /lib64/libstdc++.so.6.  Without this, torch_npu import fails on systems
# where the host libstdc++ is too old for ICU / torch_npu shared objects.
if [[ -n "${CONDA_PREFIX:-}" && -d "${CONDA_PREFIX}/lib" ]]; then
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH}"
  else
    export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib"
  fi
fi

# Prefer a complete user-space CANN installation carried by this environment.
# This is required on hosts where the system toolkit is compiler-only or lacks
# libhccl.so.  Keep host driver libraries ahead of the env-local CANN runtime.
_hust_dev_hub_ascend_root=""
for _candidate in \
  "${CONDA_PREFIX:-}/Ascend/cann" \
  "${CONDA_PREFIX:-}/Ascend/ascend-toolkit/latest"; do
  if [[ -n "${CONDA_PREFIX:-}" && -d "$_candidate" ]]; then
    _hust_dev_hub_ascend_root="$_candidate"
    break
  fi
done
if [[ -n "$_hust_dev_hub_ascend_root" ]]; then
  export ASCEND_HOME_PATH="$_hust_dev_hub_ascend_root"
  export ASCEND_TOOLKIT_HOME="$_hust_dev_hub_ascend_root"
  export ASCEND_AICPU_PATH="$_hust_dev_hub_ascend_root"
  if [[ -d "$_hust_dev_hub_ascend_root/opp" ]]; then
    export ASCEND_OPP_PATH="$_hust_dev_hub_ascend_root/opp"
  fi

  _hust_dev_hub_ascend_prepend=()
  for _candidate in \
    /usr/local/Ascend/driver/lib64/common \
    /usr/local/Ascend/driver/lib64/driver \
    /usr/local/Ascend/driver/lib64 \
    "$_hust_dev_hub_ascend_root/runtime/lib64" \
    "$_hust_dev_hub_ascend_root/lib64" \
    "$_hust_dev_hub_ascend_root/compiler/lib64" \
    "$_hust_dev_hub_ascend_root/hccl/lib64" \
    "$_hust_dev_hub_ascend_root/aarch64-linux/lib64"; do
    [[ -d "$_candidate" ]] && _hust_dev_hub_ascend_prepend+=("$_candidate")
  done
  if (( ${#_hust_dev_hub_ascend_prepend[@]} > 0 )); then
    _hust_dev_hub_ascend_ld="$(IFS=':'; printf '%s' "${_hust_dev_hub_ascend_prepend[*]}")"
    if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
      export LD_LIBRARY_PATH="${_hust_dev_hub_ascend_ld}:${LD_LIBRARY_PATH}"
    else
      export LD_LIBRARY_PATH="$_hust_dev_hub_ascend_ld"
    fi
  fi
fi
unset _hust_dev_hub_ascend_root _hust_dev_hub_ascend_prepend _hust_dev_hub_ascend_ld _candidate

# Prepend torch / torch_npu lib directories to LD_LIBRARY_PATH so that
# compiled C extensions (e.g. vllm_ascend_C.so) can find libtorch.so and
# libtorch_npu.so at import time.
_hust_dev_hub_torch_lib=""
_hust_dev_hub_torch_npu_lib=""
if command -v python3 >/dev/null 2>&1; then
  _hust_dev_hub_torch_lib="$(python3 -c "import torch, os; print(os.path.join(os.path.dirname(torch.__file__), 'lib'))" 2>/dev/null || true)"
  _hust_dev_hub_torch_npu_lib="$(python3 -c "import torch_npu, os; print(os.path.join(os.path.dirname(torch_npu.__file__), 'lib'))" 2>/dev/null || true)"
fi
_hust_dev_hub_torch_prepend=()
if [[ -n "$_hust_dev_hub_torch_lib" && -d "$_hust_dev_hub_torch_lib" ]]; then
  _hust_dev_hub_torch_prepend+=("$_hust_dev_hub_torch_lib")
fi
if [[ -n "$_hust_dev_hub_torch_npu_lib" && -d "$_hust_dev_hub_torch_npu_lib" ]]; then
  _hust_dev_hub_torch_prepend+=("$_hust_dev_hub_torch_npu_lib")
fi
if (( ${#_hust_dev_hub_torch_prepend[@]} > 0 )); then
  _hust_dev_hub_torch_ld="$(IFS=':'; printf '%s' "${_hust_dev_hub_torch_prepend[*]}")"
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    export LD_LIBRARY_PATH="${_hust_dev_hub_torch_ld}:${LD_LIBRARY_PATH}"
  else
    export LD_LIBRARY_PATH="${_hust_dev_hub_torch_ld}"
  fi
fi
unset _hust_dev_hub_torch_lib _hust_dev_hub_torch_npu_lib _hust_dev_hub_torch_prepend _hust_dev_hub_torch_ld

if [[ -z "${HUST_DEV_HUB_SAVED_GIT_SSH_COMMAND+x}" ]]; then
  if [[ -n "${GIT_SSH_COMMAND:-}" ]]; then
    export HUST_DEV_HUB_SAVED_GIT_SSH_COMMAND="$GIT_SSH_COMMAND"
  else
    export HUST_DEV_HUB_SAVED_GIT_SSH_COMMAND="__UNSET__"
  fi
fi

export GIT_SSH_COMMAND='env -u LD_LIBRARY_PATH -u PYTHONPATH ssh'

if [[ -z "${HUST_DEV_HUB_SAVED_PYTHONPATH+x}" ]]; then
  if [[ -n "${PYTHONPATH:-}" ]]; then
    export HUST_DEV_HUB_SAVED_PYTHONPATH="$PYTHONPATH"
  else
    export HUST_DEV_HUB_SAVED_PYTHONPATH="__UNSET__"
  fi
fi

_ascend_pyacl_path=""
for _candidate in \
  "${ASCEND_HOME_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/pyACL/python/site-packages" \
  "/usr/local/Ascend/ascend-toolkit/latest/pyACL/python/site-packages" \
  "/usr/local/Ascend/ascend-toolkit/latest/python/site-packages"; do
  if [[ -d "$_candidate" ]]; then
    _ascend_pyacl_path="$_candidate"
    break
  fi
done

if [[ -n "$_ascend_pyacl_path" ]]; then
  case ":${PYTHONPATH:-}:" in
    *":${_ascend_pyacl_path}:"*) ;;
    *) export PYTHONPATH="${_ascend_pyacl_path}${PYTHONPATH:+:$PYTHONPATH}" ;;
  esac
fi
unset _ascend_pyacl_path _candidate _hust_dev_hub_runtime_home
unset _hust_dev_hub_var
unset -f _hust_dev_hub_needs_user_cache_reset
unset -f _hust_dev_hub_resolve_user_home
unset -f _hust_dev_hub_save_var

if [[ -z "${HUST_DEV_HUB_SAVED_HF_ENDPOINT+x}" ]]; then
  if [[ -n "${HF_ENDPOINT:-}" ]]; then
    export HUST_DEV_HUB_SAVED_HF_ENDPOINT="$HF_ENDPOINT"
  else
    export HUST_DEV_HUB_SAVED_HF_ENDPOINT="__UNSET__"
  fi
fi

if [[ "${HUST_DEV_HUB_DISABLE_HF_MIRROR_AUTOSET:-0}" != "1" ]]; then
  if command -v curl >/dev/null 2>&1 \
    && curl -fsSIL --connect-timeout 2 --max-time 3 https://hf-mirror.com >/dev/null 2>&1; then
    export HF_ENDPOINT="https://hf-mirror.com"
  else
    unset HF_ENDPOINT
  fi
fi
EOF

  cat > "$deactivate_script" <<'EOF'
if [[ -n "${HUST_DEV_HUB_SAVED_LD_LIBRARY_PATH+x}" ]]; then
  if [[ "$HUST_DEV_HUB_SAVED_LD_LIBRARY_PATH" == "__UNSET__" ]]; then
    unset LD_LIBRARY_PATH
  else
    export LD_LIBRARY_PATH="$HUST_DEV_HUB_SAVED_LD_LIBRARY_PATH"
  fi
  unset HUST_DEV_HUB_SAVED_LD_LIBRARY_PATH
fi

if [[ -n "${HUST_DEV_HUB_SAVED_PATH+x}" ]]; then
  if [[ "$HUST_DEV_HUB_SAVED_PATH" == "__UNSET__" ]]; then
    unset PATH
  else
    export PATH="$HUST_DEV_HUB_SAVED_PATH"
  fi
  unset HUST_DEV_HUB_SAVED_PATH
fi

if [[ -n "${HUST_DEV_HUB_SAVED_GIT_SSH_COMMAND+x}" ]]; then
  if [[ "$HUST_DEV_HUB_SAVED_GIT_SSH_COMMAND" == "__UNSET__" ]]; then
    unset GIT_SSH_COMMAND
  else
    export GIT_SSH_COMMAND="$HUST_DEV_HUB_SAVED_GIT_SSH_COMMAND"
  fi
  unset HUST_DEV_HUB_SAVED_GIT_SSH_COMMAND
fi

if [[ -n "${HUST_DEV_HUB_SAVED_PYTHONPATH+x}" ]]; then
  if [[ "$HUST_DEV_HUB_SAVED_PYTHONPATH" == "__UNSET__" ]]; then
    unset PYTHONPATH
  else
    export PYTHONPATH="$HUST_DEV_HUB_SAVED_PYTHONPATH"
  fi
  unset HUST_DEV_HUB_SAVED_PYTHONPATH
fi

if [[ -n "${HUST_DEV_HUB_SAVED_HF_ENDPOINT+x}" ]]; then
  if [[ "$HUST_DEV_HUB_SAVED_HF_ENDPOINT" == "__UNSET__" ]]; then
    unset HF_ENDPOINT
  else
    export HF_ENDPOINT="$HUST_DEV_HUB_SAVED_HF_ENDPOINT"
  fi
  unset HUST_DEV_HUB_SAVED_HF_ENDPOINT
fi

for _hust_dev_hub_var in \
  HOME \
  XDG_CACHE_HOME \
  XDG_CONFIG_HOME \
  HF_HOME \
  HF_HUB_CACHE \
  HF_TOKEN_PATH \
  ASCEND_HOME_PATH \
  ASCEND_TOOLKIT_HOME \
  ASCEND_OPP_PATH \
  ASCEND_AICPU_PATH \
  TORCH_DEVICE_BACKEND_AUTOLOAD \
  HUST_ASCEND_RUNTIME_VERSION \
  HUST_ASCEND_HAS_STREAM_ATTR \
  HUST_ASCEND_OPP_OVERLAY_ROOT \
  HUST_ATB_SET_ENV; do
  _hust_dev_hub_saved_name="HUST_DEV_HUB_SAVED_${_hust_dev_hub_var}"
  if [[ -n "${!_hust_dev_hub_saved_name+x}" ]]; then
    if [[ "${!_hust_dev_hub_saved_name}" == "__UNSET__" ]]; then
      unset "$_hust_dev_hub_var"
    else
      printf -v "$_hust_dev_hub_var" '%s' "${!_hust_dev_hub_saved_name}"
      export "$_hust_dev_hub_var"
    fi
    unset "$_hust_dev_hub_saved_name"
  fi
done
unset _hust_dev_hub_var _hust_dev_hub_saved_name
EOF

  chmod 0644 "$activate_script" "$deactivate_script"
  log "Installed conda activate hooks for '$ENV_NAME' runtime libraries"
}

resolve_conda_sh_path() {
  local conda_base
  local conda_sh

  conda_base="${CONDA_BASE:-}"
  if [[ -z "$conda_base" ]]; then
    conda_base="$(run_conda_cmd info --base 2>/dev/null || true)"
  fi
  if [[ -z "$conda_base" ]]; then
    conda_base="$WORKSPACE_ROOT/miniconda3"
  fi
  if [[ ! -d "$conda_base" ]]; then
    conda_base="$HOME/miniconda3"
  fi

  conda_sh="$conda_base/etc/profile.d/conda.sh"
  if [[ -f "$conda_sh" ]]; then
    printf '%s\n' "$conda_sh"
    return 0
  fi

  return 1
}

configure_bashrc_conda_init() {
  local conda_sh
  local bashrc_file
  local tmp_file

  conda_sh="$(resolve_conda_sh_path || true)"
  if [[ -z "$conda_sh" || ! -f "$conda_sh" ]]; then
    log "Skip ~/.bashrc conda init setup because conda.sh was not found"
    return 0
  fi

  bashrc_file="$HOME/.bashrc"
  touch "$bashrc_file"
  tmp_file="$(mktemp)"

  awk -v begin="$BASHRC_CONDA_INIT_BEGIN" -v end="$BASHRC_CONDA_INIT_END" '
    $0 == begin {skip=1; next}
    $0 == end {skip=0; next}
    !skip {print}
  ' "$bashrc_file" > "$tmp_file"

  {
    cat "$tmp_file"
    printf '\n%s\n' "$BASHRC_CONDA_INIT_BEGIN"
    printf 'if [[ "$-" == *i* ]] && [[ -f "%s" ]]; then\n' "$conda_sh"
    printf '  source "%s"\n' "$conda_sh"
    printf 'fi\n'
    printf '%s\n' "$BASHRC_CONDA_INIT_END"
  } > "$bashrc_file"

  rm -f "$tmp_file"
  log "Updated ~/.bashrc to initialize conda command in new interactive shells"
  log "Current shell is unchanged. Open a new interactive shell or run: source $conda_sh"
}

configure_bashrc_auto_activate_env() {
  local conda_sh
  local bashrc_file
  local tmp_file

  configure_conda_env_library_hooks

  conda_sh="$(resolve_conda_sh_path || true)"

  if [[ -z "$conda_sh" || ! -f "$conda_sh" ]]; then
    log "Skip bashrc auto-activate setup because conda.sh was not found: $conda_sh"
    return 0
  fi

  bashrc_file="$HOME/.bashrc"
  touch "$bashrc_file"
  tmp_file="$(mktemp)"

  awk -v begin="$BASHRC_BEGIN" -v end="$BASHRC_END" '
    $0 == begin {skip=1; next}
    $0 == end {skip=0; next}
    !skip {print}
  ' "$bashrc_file" > "$tmp_file"

  {
    cat "$tmp_file"
    printf '\n%s\n' "$BASHRC_BEGIN"
    printf 'if [[ "$-" == *i* ]] && [[ -f "%s" ]]; then\n' "$conda_sh"
    printf '  source "%s"\n' "$conda_sh"
    printf '  conda activate "%s" >/dev/null 2>&1 || true\n' "$ENV_NAME"
    printf 'fi\n'
    printf '%s\n' "$BASHRC_END"
  } > "$bashrc_file"

  rm -f "$tmp_file"
  log "Updated ~/.bashrc to auto-activate conda env '$ENV_NAME' in interactive shells"
  log "Current shell is unchanged. Open a new interactive shell or run: conda deactivate && conda activate $ENV_NAME"
}

maybe_update_bashrc_auto_activate_env() {
  if (( UPDATE_BASHRC == 1 )); then
    configure_bashrc_auto_activate_env
    return 0
  fi

  log "Skip ~/.bashrc auto-activate update by default. Use --update-bashrc or menu option 7 when you need persistent auto-activation."
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

run_interactive_menu() {
  local choice=""

  cat <<EOF
=== vllm-hust-dev-hub quickstart ===
Hub root       : $HUB_ROOT
Workspace root : $WORKSPACE_ROOT
Conda env name : $ENV_NAME
Python version : $PYTHON_VERSION
===================================
1) 一键初始化（同步仓库 + 创建/修复环境 + 安装核心仓库）
2) 仅同步仓库
3) 仅创建/修复 conda 环境
4) 安装或更新本地仓库（核心）
5) 安装或更新本地仓库（核心 + 扩展）
6) 创建/启动官方 Ascend Docker instance（可交互录入 SSH 公钥）
7) 仅更新 ~/.bashrc 自动激活
8) 退出
EOF

  read -r -p "请选择 [1-8]: " choice
  case "$choice" in
    1)
      DO_CLONE=1
      DO_CONDA=1
      DO_INSTALL=1
      INSTALL_MODE="refresh"
      INSTALL_SCOPE="core"
      UPDATE_BASHRC=1
      MENU_CONFIRMED=1
      ;;
    2)
      DO_CLONE=1
      MENU_CONFIRMED=1
      ;;
    3)
      DO_CONDA=1
      MENU_CONFIRMED=1
      ;;
    4)
      DO_INSTALL=1
      INSTALL_MODE="refresh"
      INSTALL_SCOPE="core"
      MENU_CONFIRMED=1
      ;;
    5)
      DO_INSTALL=1
      INSTALL_MODE="refresh"
      INSTALL_SCOPE="full"
      MENU_CONFIRMED=1
      ;;
    6)
      local container_name
      container_name="$(prompt_for_ascend_container_name)"
      ensure_ascend_container_manager_source
      prompt_and_store_container_public_key
      if [[ -x "$SCRIPT_DIR/ascend-official-container.sh" ]]; then
        VLLM_ENGINE_CONTAINER_NAME="$container_name" \
          bash "$SCRIPT_DIR/ascend-official-container.sh" start
      else
        log "未找到容器脚本: $SCRIPT_DIR/ascend-official-container.sh"
        exit 2
      fi
      log "容器 '$container_name' 已启动或已复用。后续可执行: VLLM_ENGINE_CONTAINER_NAME='$container_name' bash scripts/ascend-official-container.sh shell"
      if [[ -f "$CONTAINER_EXTRA_AUTH_KEYS_FILE" ]]; then
        log "已配置额外容器 SSH 公钥来源: $CONTAINER_EXTRA_AUTH_KEYS_FILE"
      fi
      log "容器 SSH 默认端口: 2222"
      log "若公网 2222 不通，可在客户端 ~/.ssh/config 为容器 Host 配置: HostName 127.0.0.1 + Port 2222 + ProxyJump <已有宿主机 Host 条目>"
      exit 0
      ;;
    7)
      ensure_conda_available
      configure_bashrc_conda_init
      configure_bashrc_auto_activate_env
      log "已完成 ~/.bashrc 自动激活设置更新。"
      exit 0
      ;;
    8)
      log "已退出。"
      exit 0
      ;;
    *)
      log "无效选项: $choice"
      exit 2
      ;;
  esac
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --clone)
        DO_CLONE=1
        ;;
      --conda)
        DO_CONDA=1
        ;;
      --install)
        DO_INSTALL=1
        ;;
      --install-mode)
        INSTALL_MODE="$2"
        shift
        ;;
      --install-scope)
        INSTALL_SCOPE="$2"
        shift
        ;;
      --ascend-lightweight)
        ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE="0"
        ;;
      --ascend-custom-kernels)
        ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE="$2"
        shift
        ;;
      --all)
        DO_CLONE=1
        DO_CONDA=1
        DO_INSTALL=1
        INSTALL_SCOPE="core"
        ;;
      --env-name)
        ENV_NAME="$2"
        shift
        ;;
      --python)
        PYTHON_VERSION="$2"
        shift
        ;;
      --update-bashrc)
        UPDATE_BASHRC=1
        ;;
      --perf-timestamps)
        PERF_TIMESTAMPS=1
        ;;
      -y|--yes)
        AUTO_YES=1
        ;;
      -h|--help)
        print_help
        exit 0
        ;;
      *)
        echo "未知参数: $1" >&2
        print_help >&2
        exit 2
        ;;
    esac
    shift
  done

  if [[ "$INSTALL_SCOPE" != "core" && "$INSTALL_SCOPE" != "full" ]]; then
    echo "无效 --install-scope: $INSTALL_SCOPE (应为 core 或 full)" >&2
    exit 2
  fi

  if [[ "$INSTALL_MODE" != "install" && "$INSTALL_MODE" != "refresh" ]]; then
    echo "无效 --install-mode: $INSTALL_MODE (应为 install 或 refresh)" >&2
    exit 2
  fi

  if [[ -n "$ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE" && ! "$ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE" =~ ^[0-9]+$ ]]; then
    echo "无效 Ascend COMPILE_CUSTOM_KERNELS: $ASCEND_COMPILE_CUSTOM_KERNELS_OVERRIDE (应为非负整数)" >&2
    exit 2
  fi

  if [[ "$PERF_TIMESTAMPS" != "0" && "$PERF_TIMESTAMPS" != "1" ]]; then
    echo "无效性能时间戳开关: $PERF_TIMESTAMPS (应为 0 或 1)" >&2
    exit 2
  fi

  if [[ ! "$PERF_SUMMARY_LIMIT" =~ ^[0-9]+$ ]] || (( PERF_SUMMARY_LIMIT <= 0 )); then
    echo "无效性能汇总条数: $PERF_SUMMARY_LIMIT (应为正整数)" >&2
    exit 2
  fi
}

main() {
  init_quickstart_logging
  parse_args "$@"
  trap print_perf_summary_on_exit EXIT

  if (( DO_CLONE == 0 && DO_CONDA == 0 && DO_INSTALL == 0 )); then
    run_interactive_menu
  fi

  if (( DO_CLONE == 1 )); then
    if (( MENU_CONFIRMED == 1 )) || (( AUTO_YES == 1 )) || ask_yes_no "现在执行仓库同步步骤吗？"; then
      clone_repositories
    fi
  fi

  if (( DO_CONDA == 1 )); then
    if (( MENU_CONFIRMED == 1 )) || (( AUTO_YES == 1 )) || ask_yes_no "现在执行 conda 环境创建/修复吗？"; then
      create_or_update_conda_env
    fi
  fi

  if (( DO_INSTALL == 1 )) && (( DO_CONDA == 0 )); then
    if (( MENU_CONFIRMED == 1 )) || (( AUTO_YES == 1 )) || ask_yes_no "现在执行本地仓库 '$INSTALL_MODE' 安装步骤吗？"; then
      install_workspace_repos_into_env "$INSTALL_MODE" "$INSTALL_SCOPE" "without-runtime-reconcile"
      local install_rc=$?
      if [[ "$install_rc" -ne 0 ]]; then
        return "$install_rc"
      fi
      maybe_update_bashrc_auto_activate_env
    fi
  fi

  log "已完成所选步骤。"
  print_perf_summary
}

main "$@"
