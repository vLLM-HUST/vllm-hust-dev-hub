#!/usr/bin/env bash

set -euo pipefail

INSTALL_PREFIX="${MINICONDA_PREFIX:-$HOME/miniconda3}"
AUTO_YES=0

print_help() {
  cat <<'EOF'
Usage: bash scripts/install-miniconda.sh [options]

Options:
  --prefix PATH  Installation directory (default: $HOME/miniconda3).
  -y, --yes      Non-interactive mode.
  -h, --help     Show this help message.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prefix)
        INSTALL_PREFIX="$2"
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

detect_platform() {
  local os_name
  local arch_name

  os_name="$(uname -s)"
  arch_name="$(uname -m)"

  case "$os_name" in
    Linux) os_name="Linux" ;;
    Darwin) os_name="MacOSX" ;;
    *)
      echo "Unsupported OS: $os_name" >&2
      return 1
      ;;
  esac

  case "$arch_name" in
    x86_64|amd64) arch_name="x86_64" ;;
    aarch64|arm64) arch_name="aarch64" ;;
    *)
      echo "Unsupported architecture: $arch_name" >&2
      return 1
      ;;
  esac

  printf '%s %s\n' "$os_name" "$arch_name"
}

download_installer() {
  local os_name="$1"
  local arch_name="$2"
  local installer_name
  local installer_url
  local installer_path

  installer_name="Miniconda3-latest-${os_name}-${arch_name}.sh"
  installer_url="https://repo.anaconda.com/miniconda/${installer_name}"
  installer_path="/tmp/${installer_name}"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$installer_url" -o "$installer_path"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$installer_path" "$installer_url"
  else
    echo "curl or wget is required to download Miniconda" >&2
    return 1
  fi

  printf '%s\n' "$installer_path"
}

main() {
  parse_args "$@"

  if [[ -x "$INSTALL_PREFIX/bin/conda" ]]; then
    echo "[install-miniconda] Miniconda already exists at $INSTALL_PREFIX"
    exit 0
  fi

  if ! ask_yes_no "Install Miniconda to $INSTALL_PREFIX?"; then
    echo "[install-miniconda] Installation cancelled"
    exit 1
  fi

  read -r os_name arch_name < <(detect_platform)
  installer_path="$(download_installer "$os_name" "$arch_name")"

  bash "$installer_path" -b -p "$INSTALL_PREFIX"
  rm -f "$installer_path"

  echo "[install-miniconda] Installed Miniconda to $INSTALL_PREFIX"
  echo "[install-miniconda] Activate later with: source $INSTALL_PREFIX/etc/profile.d/conda.sh && conda activate"
}

main "$@"