#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"
CLONE_SCRIPT="$SCRIPT_DIR/clone-workspace-repos.sh"
MINICONDA_INSTALL_SCRIPT="$SCRIPT_DIR/install-miniconda.sh"
MANAGER_REPO="$WORKSPACE_ROOT/ascend-runtime-manager"
MANAGER_MANIFEST_DEFAULT="$MANAGER_REPO/manifests/euleros-910b.json"

ENV_NAME="vllm-hust-dev"
PYTHON_VERSION="3.11"
AUTO_YES=0
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
QUICKSTART_SETUPTOOLS_VERSION="77.0.3"
TOS_MARKER_ROOT="$HOME/.config/vllm-hust-dev-hub"
CONDA_RUN_STREAM_FLAG=""
CONTAINER_EXTRA_AUTH_KEYS_FILE="$WORKSPACE_ROOT/.ssh/vllm-ascend-extra-authorized_keys"
PIP_DEFAULTS_INITIALIZED=0
PIP_SELECTED_INDEX_URL=""
PIP_SELECTED_EXTRA_INDEX_URL=""
PIP_INSTALL_RETRIES=""
PIP_INSTALL_TIMEOUT=""
PIP_INSTALL_RESUME_RETRIES=""
PIP_SUPPORTS_RESUME_RETRIES="unknown"
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
  --all                    执行 clone + conda + install(core)。
  --env-name NAME          conda 环境名 (默认: vllm-hust-dev)。
  --python VERSION         conda 环境 Python 版本 (默认: 3.11)。
  --update-bashrc          更新 ~/.bashrc，在新交互 shell 自动激活 conda 环境。
  -y, --yes                非交互模式；容器公钥可通过 VLLM_HUST_CONTAINER_PUBKEY 传入。
  -h, --help               显示本帮助。

未提供动作参数时，将进入交互式菜单。
交互菜单的选项 6 会创建或复用官方 Ascend Docker instance，并在检测到宿主机公钥材料时自动配置容器 SSH。
EOF
}

log() {
  printf '[quickstart] %s\n' "$1"
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

run_conda_cmd() {
  # Keep conda operations isolated from external PYTHONPATH overrides.
  local conda_runner=(conda)

  if [[ -n "$CONDA_BIN" ]]; then
    conda_runner=("$CONDA_BIN")
  fi

  (unset PYTHONPATH; "${conda_runner[@]}" "$@")
}

get_conda_env_prefix() {
  local env_name="$1"

  run_conda_cmd env list | awk -v target_env="$env_name" '$1 == target_env { print $NF; exit }'
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
  local wrapped_cmd=("$@")

  detect_conda_run_stream_flag
  env_prefix="$(get_conda_env_prefix "$env_name")"
  if [[ -n "$env_prefix" && -d "$env_prefix/lib" ]]; then
    wrapped_cmd=(env "LD_LIBRARY_PATH=$env_prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$@")
  fi

  if [[ -n "$CONDA_RUN_STREAM_FLAG" ]]; then
    run_conda_cmd run "$CONDA_RUN_STREAM_FLAG" -n "$env_name" "${wrapped_cmd[@]}"
  else
    run_conda_cmd run -n "$env_name" "${wrapped_cmd[@]}"
  fi
}

run_with_heartbeat() {
  local description="$1"
  shift
  local pid
  local heartbeat_pid

  "$@" &
  pid=$!

  (
    while kill -0 "$pid" >/dev/null 2>&1; do
      sleep 30
      if kill -0 "$pid" >/dev/null 2>&1; then
        log "Still running: $description"
      fi
    done
  ) &
  heartbeat_pid=$!

  wait "$pid"
  local exit_code=$?
  kill "$heartbeat_pid" >/dev/null 2>&1 || true
  wait "$heartbeat_pid" >/dev/null 2>&1 || true
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

default_ascend_compile_custom_kernels() {
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

ensure_ascend_build_python_packages() {
  local repo_path="$1"
  local compile_custom_kernels="$2"
  local pybind11_spec
  local triton_ascend_spec

  ensure_pip_package_in_env "$ENV_NAME" "setuptools-scm>=8"
  ensure_pip_package_in_env "$ENV_NAME" "decorator"
  ensure_pip_package_in_env "$ENV_NAME" "scipy"

  triton_ascend_spec="$(read_build_requirement_spec_from_pyproject "$repo_path" "triton-ascend" || true)"
  ensure_pip_package_in_env "$ENV_NAME" "${triton_ascend_spec:-triton-ascend}"

  if [[ "$compile_custom_kernels" == "0" ]]; then
    return 0
  fi

  pybind11_spec="$(read_build_requirement_spec_from_pyproject "$repo_path" "pybind11" || true)"
  ensure_pip_package_in_env "$ENV_NAME" "${pybind11_spec:-pybind11}"
}

ensure_ascend_catlass_submodule_ready() {
  local repo_path="$1"
  local submodule_relative_path="csrc/third_party/catlass"
  local submodule_path="$repo_path/$submodule_relative_path"

  if [[ -e "$submodule_path/CMakeLists.txt" || -e "$submodule_path/README.md" ]]; then
    return 0
  fi

  if [[ ! -d "$repo_path/.git" && ! -f "$repo_path/.git" ]]; then
    log "Warning: skipping $submodule_relative_path initialization because '$repo_path' has no git metadata"
    return 0
  fi

  log "Initializing Ascend submodule: $submodule_relative_path"
  run_system_command_with_sanitized_ld_library_path \
    git -C "$repo_path" submodule update --init --recursive "$submodule_relative_path"
}

validate_ascend_custom_op_in_env() {
  local env_name="$1"

  run_conda_env_cmd "$env_name" env TORCH_DEVICE_BACKEND_AUTOLOAD=0 python - <<'PY'
import torch  # noqa: F401
from vllm_ascend.utils import enable_custom_op

raise SystemExit(0 if enable_custom_op() else 1)
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

  ensure_ascend_build_python_packages "$repo_path" "$compile_custom_kernels"

  if [[ "$compile_custom_kernels" != "0" ]]; then
    ensure_ascend_catlass_submodule_ready "$repo_path"
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

  run_with_heartbeat \
    "installing editable package from $repo_path" \
    run_pip_install_in_env "$ENV_NAME" \
      "COMPILE_CUSTOM_KERNELS=$compile_custom_kernels" \
      "TORCH_DEVICE_BACKEND_AUTOLOAD=0" \
      "LD_LIBRARY_PATH=$build_ld_library_path" \
      -- "${pip_args[@]}"

  if [[ "$compile_custom_kernels" == "0" ]]; then
    return 0
  fi

  if validate_ascend_custom_op_in_env "$ENV_NAME"; then
    log "Verified Ascend custom op import in '$ENV_NAME'"
    return 0
  fi

  log "Ascend custom op validation failed; attempting RUNPATH repair"
  if repair_ascend_custom_op_runpath_in_env "$ENV_NAME" && validate_ascend_custom_op_in_env "$ENV_NAME"; then
    log "Verified Ascend custom op import in '$ENV_NAME' after RUNPATH repair"
    return 0
  fi

  log "Warning: Ascend custom op validation is still failing in '$ENV_NAME'"
  return 12
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

ensure_pip_install_defaults() {
  if (( PIP_DEFAULTS_INITIALIZED == 1 )); then
    return 0
  fi

  PIP_SELECTED_INDEX_URL="$(select_pip_index_url || true)"
  PIP_SELECTED_EXTRA_INDEX_URL="$(get_first_nonempty_env PIP_EXTRA_INDEX_URL HUST_DEV_HUB_PIP_EXTRA_INDEX_URL HUST_ASCEND_MANAGER_PIP_EXTRA_INDEX_URL || true)"
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
  if [[ ! -f "$CLONE_SCRIPT" ]]; then
    log "clone script not found: $CLONE_SCRIPT"
    return 2
  fi
  log "Cloning workspace repositories..."
  if (( AUTO_YES == 1 )); then
    bash "$CLONE_SCRIPT" --yes
    return 0
  fi
  bash "$CLONE_SCRIPT"
}

conda_env_exists() {
  run_conda_cmd env list | awk '{print $1}' | grep -Fxq "$ENV_NAME"
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
  ensure_conda_available

  if conda_env_exists; then
    log "Conda env '$ENV_NAME' already exists. Updating core tools..."
  else
    accept_conda_tos_if_needed
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
  report_vllm_cli_status "$ENV_NAME" || true

  configure_bashrc_conda_init
  maybe_update_bashrc_auto_activate_env

  log "Conda env ready: $ENV_NAME"
  log "Activate with: conda activate $ENV_NAME"
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
    /setup[[:space:]]*\(/ { in_setup=1 }
    in_setup && /^[[:space:]]*name[[:space:]]*=/ {
      line = $0
      sub(/^[[:space:]]*name[[:space:]]*=[[:space:]]*["\047]/, "", line)
      sub(/["\047][[:space:]]*,?[[:space:]]*$/, "", line)
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

  if ! has_vllm_cli_in_env "$env_name"; then
    log "Warning: 'vllm' command is unavailable in conda env '$env_name'"
    return 1
  fi

  if run_conda_env_cmd "$env_name" env TORCH_DEVICE_BACKEND_AUTOLOAD=0 vllm --help >/dev/null 2>&1; then
    log "Verified: 'vllm' command is available in conda env '$env_name'"
    return 0
  fi

  log "Warning: 'vllm' command exists in '$env_name' but runtime validation failed (for example missing backend/runtime libs)."
  return 1
}
ensure_pip_package_in_env() {
  local env_name="$1"
  local package_spec="$2"
  local package_name="${package_spec%%[<>=!~; ]*}"

  if is_package_installed_in_env "$env_name" "$package_name"; then
    return 0
  fi

  log "Installing missing build dependency '$package_spec' into '$env_name'"
  run_with_heartbeat \
    "installing $package_spec into $env_name" \
    run_pip_install_in_env "$env_name" -- "$package_spec"
}

repo_requires_ascend_runtime() {
  local repo_path="$1"

  [[ "$repo_path" == "$WORKSPACE_ROOT/vllm-ascend-hust" ]]
}

repo_prefers_no_build_isolation() {
  local repo_path="$1"

  [[ "$repo_path" == "$MANAGER_REPO" || "$repo_path" == "$WORKSPACE_ROOT/vllm-hust-benchmark" ]]
}

install_editable_repo_into_env() {
  local repo_path="$1"
  local reconcile_mode="${2:-without-runtime-reconcile}"
  local pip_args=(-v -e "$repo_path")
  local compile_custom_kernels

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

    if install_ascend_repo_into_env "$repo_path" "$compile_custom_kernels"; then
      return 0
    fi

    if [[ "$compile_custom_kernels" != "0" ]] && ! ascend_compile_custom_kernels_configured_explicitly; then
      log "Ascend custom-kernel install failed in auto mode; falling back to lightweight plugin mode"
      install_ascend_repo_into_env "$repo_path" "0"
      return $?
    fi

    return 12
  fi

  if repo_prefers_no_build_isolation "$repo_path"; then
    pip_args=(--no-build-isolation "${pip_args[@]}")
  fi

  log "Installing editable package from: $repo_path"
  run_with_heartbeat \
    "installing editable package from $repo_path" \
    run_pip_install_in_env "$ENV_NAME" -- "${pip_args[@]}"
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

  log "Reconciling Ascend Python stack via hust-ascend-manager (user-space only; no system changes)"
  run_with_heartbeat \
    "reconciling Ascend Python stack via hust-ascend-manager" \
    run_conda_env_cmd "$ENV_NAME" python -m hust_ascend_manager.cli "${manager_args[@]}"
}

install_workspace_repos_into_env() {
  local install_mode="${1:-$INSTALL_MODE}"
  local install_scope="${2:-$INSTALL_SCOPE}"
  local reconcile_mode="${3:-without-runtime-reconcile}"

  if ! ensure_conda_available "no-bootstrap"; then
    log "Install-only flow requires an existing conda setup. Run quickstart with --conda (or --all) first."
    return 2
  fi

  if ! conda_env_exists; then
    log "Conda env '$ENV_NAME' does not exist yet. Create it first with --conda."
    return 2
  fi

  configure_conda_env_library_hooks

  if [[ "$install_mode" != "install" && "$install_mode" != "refresh" ]]; then
    echo "Invalid install mode: $install_mode" >&2
    return 2
  fi

  if [[ "$install_scope" != "core" && "$install_scope" != "full" ]]; then
    echo "Invalid install scope: $install_scope" >&2
    return 2
  fi

  local installed_any=0
  local installed_list=()
  local skipped_list=()
  local repo_entries=()
  mapfile -t repo_entries < <(build_installable_repo_entries "$install_scope")

  if (( ${#repo_entries[@]} == 0 )); then
    log "No installable local repositories found (pyproject.toml missing or project name unavailable)."
    return 0
  fi

  local entry
  local manager_entry=""
  local non_manager_entries=()
  local repo_path
  local project_name
  for entry in "${repo_entries[@]}"; do
    repo_path="${entry%%|*}"
    project_name="${entry#*|}"
    if [[ "$project_name" == "hust-ascend-manager" ]]; then
      manager_entry="$entry"
    else
      non_manager_entries+=("$entry")
    fi
  done

  if [[ -n "$manager_entry" ]]; then
    repo_path="${manager_entry%%|*}"
    project_name="${manager_entry#*|}"

    if [[ "$install_mode" == "install" ]] && is_package_installed_in_env "$ENV_NAME" "$project_name"; then
      log "Skipping already installed package '$project_name' from: $repo_path"
      skipped_list+=("$repo_path ($project_name)")
    else
      install_editable_repo_into_env "$repo_path" "$reconcile_mode"
      installed_any=1
      installed_list+=("$repo_path ($project_name)")
    fi
  fi

  if [[ "$reconcile_mode" == "with-runtime-reconcile" ]]; then
    reconcile_ascend_runtime_with_manager
  else
    log "Skipping Ascend Python stack reconciliation for install-only flow. Use --conda to refresh the user-space environment."
  fi

  for entry in "${non_manager_entries[@]}"; do
    repo_path="${entry%%|*}"
    project_name="${entry#*|}"

    if [[ "$install_mode" == "install" ]] && is_package_installed_in_env "$ENV_NAME" "$project_name"; then
      log "Skipping already installed package '$project_name' from: $repo_path"
      skipped_list+=("$repo_path ($project_name)")
      continue
    fi

    if ! install_editable_repo_into_env "$repo_path" "$reconcile_mode"; then
      skipped_list+=("$repo_path ($project_name)")
      continue
    fi
    installed_any=1
    installed_list+=("$repo_path ($project_name)")
  done

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

  if [[ "$install_mode" == "install" && ${#skipped_list[@]} -gt 0 ]]; then
    local skipped_item
    log "Skipped already installed repositories:"
    for skipped_item in "${skipped_list[@]}"; do
      log "  - $skipped_item"
    done
  fi

  if [[ -d "$WORKSPACE_ROOT/vllm-ascend-hust" && ! -f "$WORKSPACE_ROOT/vllm-ascend-hust/pyproject.toml" ]]; then
    log "Warning: vllm-ascend-hust exists but has no pyproject.toml, skipped install"
  fi

  report_vllm_cli_status "$ENV_NAME" || true
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
  ASCEND_HOME_PATH \
  ASCEND_OPP_PATH \
  ASCEND_AICPU_PATH \
  TORCH_DEVICE_BACKEND_AUTOLOAD \
  HUST_ASCEND_RUNTIME_VERSION \
  HUST_ASCEND_HAS_STREAM_ATTR \
  HUST_ASCEND_OPP_OVERLAY_ROOT \
  HUST_ATB_SET_ENV; do
  _hust_dev_hub_save_var "$_hust_dev_hub_var"
done

if [[ "${HUST_DEV_HUB_ENABLE_MANAGER_ENV_HOOK:-0}" == "1" ]] \
  && command -v hust-ascend-manager >/dev/null 2>&1; then
  _hust_dev_hub_manager_env="$(hust-ascend-manager env --shell 2>/dev/null || true)"
  if [[ -n "$_hust_dev_hub_manager_env" ]]; then
    _hust_dev_hub_manager_env_filtered="$(printf '%s\n' "$_hust_dev_hub_manager_env" | \
      grep -E '^[[:space:]]*export[[:space:]]+(ASCEND_HOME_PATH|ASCEND_OPP_PATH|ASCEND_AICPU_PATH|TORCH_DEVICE_BACKEND_AUTOLOAD|HUST_ASCEND_RUNTIME_VERSION|HUST_ASCEND_HAS_STREAM_ATTR|HUST_ASCEND_OPP_OVERLAY_ROOT|HUST_ATB_SET_ENV|LD_LIBRARY_PATH|PYTHONPATH)=' || true)"
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
unset _ascend_pyacl_path _candidate
unset _hust_dev_hub_var
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
  ASCEND_HOME_PATH \
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
      prompt_and_store_container_public_key
      if [[ -x "$SCRIPT_DIR/ascend-official-container.sh" ]]; then
        bash "$SCRIPT_DIR/ascend-official-container.sh" start
      else
        log "未找到容器脚本: $SCRIPT_DIR/ascend-official-container.sh"
        exit 2
      fi
      log "容器已启动或已复用。可执行: bash scripts/ascend-official-container.sh shell"
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
}

main() {
  parse_args "$@"

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
      maybe_update_bashrc_auto_activate_env
    fi
  fi

  log "已完成所选步骤。"
}

main "$@"
