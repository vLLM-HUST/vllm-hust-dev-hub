#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"
CLONE_SCRIPT="$SCRIPT_DIR/clone-workspace-repos.sh"
MINICONDA_INSTALL_SCRIPT="$SCRIPT_DIR/install-miniconda.sh"
MANAGER_REPO="$HUB_ROOT/ascend-runtime-manager"
MANAGER_MANIFEST_DEFAULT="$MANAGER_REPO/manifests/euleros-910b.json"

ENV_NAME="vllm-hust-dev"
PYTHON_VERSION="3.10"
AUTO_YES=0
DO_CLONE=0
DO_CONDA=0
DO_INSTALL=0
INSTALL_MODE="install"
INSTALL_SCOPE="core"
MENU_CONFIRMED=0
BASHRC_BEGIN="# >>> vllm-hust-dev-hub auto-activate >>>"
BASHRC_END="# <<< vllm-hust-dev-hub auto-activate <<<"
CONDA_MAIN_CHANNEL="https://repo.anaconda.com/pkgs/main"
CONDA_R_CHANNEL="https://repo.anaconda.com/pkgs/r"
CONDA_ASCEND_CHANNEL="https://repo.huaweicloud.com/ascend/repos/conda/"
CONDA_FORGE_MIRROR_CHANNEL="https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/"
CONDA_FORGE_FALLBACK_CHANNEL="conda-forge"
TOS_MARKER_ROOT="$HOME/.config/vllm-hust-dev-hub"
CONDA_RUN_STREAM_FLAG=""

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
  --python VERSION         conda 环境 Python 版本 (默认: 3.10)。
  -y, --yes                非交互模式。
  -h, --help               显示本帮助。

未提供动作参数时，将进入交互式菜单。
EOF
}

log() {
  printf '[quickstart] %s\n' "$1"
}

run_conda_cmd() {
  # Keep conda operations isolated from external PYTHONPATH overrides.
  (unset PYTHONPATH; conda "$@")
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

  detect_conda_run_stream_flag
  if [[ -n "$CONDA_RUN_STREAM_FLAG" ]]; then
    run_conda_cmd run "$CONDA_RUN_STREAM_FLAG" -n "$env_name" "$@"
  else
    run_conda_cmd run -n "$env_name" "$@"
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

find_conda_bin() {
  if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
    printf '%s\n' "$CONDA_EXE"
    return 0
  fi

  local resolved_path
  if resolved_path="$(type -P conda 2>/dev/null)" && [[ -n "$resolved_path" ]]; then
    printf '%s\n' "$resolved_path"
    return 0
  fi

  local candidates=(
    "$HOME/miniconda3/bin/conda"
    "$HOME/anaconda3/bin/conda"
    "$HOME/miniforge3/bin/conda"
    "$HOME/mambaforge/bin/conda"
  )

  local path
  for path in "${candidates[@]}"; do
    if [[ -x "$path" ]]; then
      printf '%s\n' "$path"
      return 0
    fi
  done

  return 1
}

source_conda_sh_if_present() {
  local conda_base="$1"
  local conda_sh="$conda_base/etc/profile.d/conda.sh"

  if [[ -f "$conda_sh" ]]; then
    # shellcheck disable=SC1091
    source "$conda_sh"
  fi
}

get_conda_base() {
  local conda_bin="$1"

  if command -v conda >/dev/null 2>&1; then
    run_conda_cmd info --base 2>/dev/null || true
    return 0
  fi

  "$conda_bin" info --base 2>/dev/null || true
}

ensure_conda_available() {
  local conda_bin
  if conda_bin="$(find_conda_bin)"; then
    local conda_root
    conda_root="$(get_conda_base "$conda_bin")"
    if [[ -z "$conda_root" ]]; then
      conda_root="$(cd -- "$(dirname -- "$conda_bin")/.." && pwd)"
    fi
    source_conda_sh_if_present "$conda_root"
    return 0
  fi

  log "conda was not found."
  if [[ ! -f "$MINICONDA_INSTALL_SCRIPT" ]]; then
    echo "[quickstart] Miniconda installer script not found: $MINICONDA_INSTALL_SCRIPT" >&2
    return 1
  fi

  if (( AUTO_YES == 1 )) || ask_yes_no "Download and install Miniconda automatically now?"; then
    if (( AUTO_YES == 1 )); then
      bash "$MINICONDA_INSTALL_SCRIPT" --yes
    else
      bash "$MINICONDA_INSTALL_SCRIPT"
    fi

    if conda_bin="$(find_conda_bin)"; then
      local conda_root
      conda_root="$(get_conda_base "$conda_bin")"
      if [[ -z "$conda_root" ]]; then
        conda_root="$(cd -- "$(dirname -- "$conda_bin")/.." && pwd)"
      fi
      source_conda_sh_if_present "$conda_root"
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
    run_conda_env_cmd "$ENV_NAME" python -m pip install --upgrade pip setuptools wheel
  run_with_heartbeat \
    "installing pytest and pre-commit into $ENV_NAME" \
    run_conda_env_cmd "$ENV_NAME" python -m pip install pytest pre-commit

  install_workspace_repos_into_env "refresh" "$INSTALL_SCOPE" "with-runtime-reconcile"

  if run_conda_cmd run -n "$ENV_NAME" vllm --help >/dev/null 2>&1; then
    log "Verified: 'vllm' command is available in conda env '$ENV_NAME'"
  else
    log "Warning: 'vllm' command is still unavailable in conda env '$ENV_NAME'"
  fi

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

repo_requires_ascend_runtime() {
  local repo_path="$1"

  [[ "$repo_path" == "$WORKSPACE_ROOT/vllm-ascend-hust" ]]
}

install_editable_repo_into_env() {
  local repo_path="$1"
  local reconcile_mode="${2:-without-runtime-reconcile}"
  local pip_args=(-v -e "$repo_path")

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

    # vllm-ascend documents editable installs with --no-build-isolation to
    # avoid torch/torch-npu resolver conflicts in the temporary build env.
    pip_args=(-v --no-build-isolation -e "$repo_path")
  fi

  log "Installing editable package from: $repo_path"
  run_with_heartbeat \
    "installing editable package from $repo_path" \
    run_conda_env_cmd "$ENV_NAME" python -m pip install "${pip_args[@]}"
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
        run_conda_env_cmd "$ENV_NAME" python -m pip install -v -e "$MANAGER_REPO"
    else
      log "Warning: hust-ascend-manager is not installed and local repo is unavailable; skipping Ascend runtime reconciliation"
      return 0
    fi
  fi

  local manager_args=(setup --install-python-stack)
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

  ensure_conda_available

  if ! conda_env_exists; then
    log "Conda env '$ENV_NAME' does not exist yet. Create it first with --conda."
    return 2
  fi

  configure_bashrc_auto_activate_env

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

  if run_conda_env_cmd "$ENV_NAME" vllm --help >/dev/null 2>&1; then
    log "Verified: 'vllm' command is available in conda env '$ENV_NAME'"
  else
    log "Warning: 'vllm' command is still unavailable in conda env '$ENV_NAME'"
  fi
}

configure_bashrc_auto_activate_env() {
  local conda_base
  local conda_sh
  local bashrc_file
  local tmp_file

  conda_base="$(run_conda_cmd info --base 2>/dev/null || true)"
  if [[ -z "$conda_base" ]]; then
    conda_base="$HOME/miniconda3"
  fi
  conda_sh="$conda_base/etc/profile.d/conda.sh"

  if [[ ! -f "$conda_sh" ]]; then
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
  log "Current shell is unchanged. Open a new interactive shell or run: conda activate $ENV_NAME"
}

ask_yes_no() {
  local prompt="$1"
  local answer=""
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
4) 安装缺失本地仓库（核心）
5) 安装缺失本地仓库（核心 + 扩展）
6) 刷新重装本地仓库（核心）
7) 刷新重装本地仓库（核心 + 扩展）
8) 仅更新 ~/.bashrc 自动激活
9) 退出
EOF

  read -r -p "请选择 [1-9]: " choice
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
      INSTALL_MODE="install"
      INSTALL_SCOPE="core"
      MENU_CONFIRMED=1
      ;;
    5)
      DO_INSTALL=1
      INSTALL_MODE="install"
      INSTALL_SCOPE="full"
      MENU_CONFIRMED=1
      ;;
    6)
      DO_INSTALL=1
      INSTALL_MODE="refresh"
      INSTALL_SCOPE="core"
      MENU_CONFIRMED=1
      ;;
    7)
      DO_INSTALL=1
      INSTALL_MODE="refresh"
      INSTALL_SCOPE="full"
      MENU_CONFIRMED=1
      ;;
    8)
      ensure_conda_available
      configure_bashrc_auto_activate_env
      log "已完成 ~/.bashrc 自动激活设置更新。"
      exit 0
      ;;
    9)
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
    fi
  fi

  log "已完成所选步骤。"
}

main "$@"
