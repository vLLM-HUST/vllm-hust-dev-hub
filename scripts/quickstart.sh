#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"
CLONE_SCRIPT="$SCRIPT_DIR/clone-workspace-repos.sh"

ENV_NAME="vllm-hust-dev"
PYTHON_VERSION="3.10"
AUTO_YES=0
DO_CLONE=0
DO_CONDA=0

print_help() {
  cat <<'EOF'
Usage: bash scripts/quickstart.sh [options]

Options:
  --clone                  Clone workspace repositories.
  --conda                  Create or update conda environment.
  --all                    Run clone + conda steps.
  --env-name NAME          Conda environment name (default: vllm-hust-dev).
  --python VERSION         Python version for conda env (default: 3.10).
  -y, --yes                Non-interactive mode.
  -h, --help               Show this help message.

If no action flags are provided, an interactive menu is shown.
EOF
}

log() {
  printf '[quickstart] %s\n' "$1"
}

find_conda_bin() {
  if command -v conda >/dev/null 2>&1; then
    command -v conda
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

ensure_conda_available() {
  local conda_bin
  if conda_bin="$(find_conda_bin)"; then
    local conda_root
    conda_root="$(cd -- "$(dirname -- "$conda_bin")/.." && pwd)"
    # shellcheck disable=SC1091
    source "$conda_root/etc/profile.d/conda.sh"
    return 0
  fi

  cat <<'EOF' >&2
[quickstart] conda was not found.
Install Miniconda/Anaconda first, then re-run this script.
EOF
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
  conda env list | awk '{print $1}' | grep -Fxq "$ENV_NAME"
}

create_or_update_conda_env() {
  ensure_conda_available

  if conda_env_exists; then
    log "Conda env '$ENV_NAME' already exists. Updating core tools..."
  else
    log "Creating conda env '$ENV_NAME' (python=$PYTHON_VERSION)..."
    conda create -y -n "$ENV_NAME" "python=$PYTHON_VERSION" pip
  fi

  log "Installing baseline tools into '$ENV_NAME'..."
  conda run -n "$ENV_NAME" python -m pip install --upgrade pip setuptools wheel
  conda run -n "$ENV_NAME" python -m pip install pytest pre-commit

  local benchmark_repo="$WORKSPACE_ROOT/vllm-hust-benchmark"
  if [[ -f "$benchmark_repo/pyproject.toml" ]]; then
    log "Installing vllm-hust-benchmark (editable) into '$ENV_NAME'..."
    conda run -n "$ENV_NAME" python -m pip install -e "$benchmark_repo"
  fi

  log "Conda env ready: $ENV_NAME"
  log "Activate with: conda activate $ENV_NAME"
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
  cat <<EOF
=== vllm-hust-dev-hub quickstart ===
Hub root       : $HUB_ROOT
Workspace root : $WORKSPACE_ROOT
Conda env name : $ENV_NAME
Python version : $PYTHON_VERSION
===================================
1) Clone workspace repositories
2) Create or update conda environment
3) Clone + conda environment
4) Exit
EOF

  local choice=""
  read -r -p "Select an option [1-4]: " choice
  case "$choice" in
    1)
      DO_CLONE=1
      ;;
    2)
      DO_CONDA=1
      ;;
    3)
      DO_CLONE=1
      DO_CONDA=1
      ;;
    4)
      log "Exit."
      exit 0
      ;;
    *)
      log "Invalid option: $choice"
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
      --all)
        DO_CLONE=1
        DO_CONDA=1
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
        echo "Unknown argument: $1" >&2
        print_help >&2
        exit 2
        ;;
    esac
    shift
  done
}

main() {
  parse_args "$@"

  if (( DO_CLONE == 0 && DO_CONDA == 0 )); then
    run_interactive_menu
  fi

  if (( DO_CLONE == 1 )); then
    if (( AUTO_YES == 1 )) || ask_yes_no "Run repository clone step now?"; then
      clone_repositories
    fi
  fi

  if (( DO_CONDA == 1 )); then
    if (( AUTO_YES == 1 )) || ask_yes_no "Run conda environment setup now?"; then
      create_or_update_conda_env
    fi
  fi

  log "All selected steps finished."
}

main "$@"
