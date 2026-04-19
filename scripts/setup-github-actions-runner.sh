#!/usr/bin/env bash

set -euo pipefail

RUNNER_VERSION="${RUNNER_VERSION:-2.333.1}"
RUNNER_URL="${GITHUB_RUNNER_URL:-}"
RUNNER_TOKEN="${GITHUB_RUNNER_TOKEN:-}"
RUNNER_NAME="${GITHUB_RUNNER_NAME:-$(hostname -s 2>/dev/null || hostname)}"
RUNNER_GROUP="${GITHUB_RUNNER_GROUP:-Default}"
RUNNER_LABELS="${GITHUB_RUNNER_LABELS:-}"
RUNNER_WORKDIR="${GITHUB_RUNNER_WORKDIR:-_work}"
RUNNER_DIR="${GITHUB_RUNNER_DIR:-$HOME/.local/share/github-actions-runner}"
SERVICE_NAME="${GITHUB_RUNNER_SERVICE_NAME:-github-actions-runner}"
DISABLE_UPDATE="${GITHUB_RUNNER_DISABLE_UPDATE:-0}"
PRESERVE_PROXY_ENV="${GITHUB_RUNNER_PRESERVE_PROXY:-0}"
AUTO_YES=0
REPLACE_EXISTING=1
COMMAND="install"

print_help() {
  cat <<'EOF'
Usage: bash scripts/setup-github-actions-runner.sh <command> [options]

Commands:
  install    Download, configure, and start the runner as a user service.
  start      Start the configured user service.
  stop       Stop the configured user service.
  restart    Restart the configured user service.
  status     Show runner service status.
  remove     Remove the runner service; pass a fresh remove token to unregister.
  help       Show this help message.

Options:
  --url URL              GitHub org or repo URL, for example https://github.com/intellistream.
  --token TOKEN          Temporary registration token for install, or remove token for remove.
  --name NAME            Runner name (default: current hostname).
  --group NAME           Runner group name (default: Default).
  --labels CSV           Extra runner labels, comma-separated.
  --runner-dir PATH      Install directory (default: $HOME/.local/share/github-actions-runner).
  --workdir PATH         Runner work directory relative to runner dir (default: _work).
  --service-name NAME    User systemd service name (default: github-actions-runner).
  --version VERSION      Runner version to download (default: 2.333.1).
  --replace              Replace an existing runner config with the same name (default).
  --no-replace           Refuse to overwrite an existing runner config.
  --disable-update       Pass --disableupdate to config.sh.
  -y, --yes              Non-interactive mode.
  -h, --help             Show this help message.

Environment variables:
  GITHUB_RUNNER_URL
  GITHUB_RUNNER_TOKEN
  GITHUB_RUNNER_NAME
  GITHUB_RUNNER_GROUP
  GITHUB_RUNNER_LABELS
  GITHUB_RUNNER_DIR
  GITHUB_RUNNER_WORKDIR
  GITHUB_RUNNER_SERVICE_NAME
  GITHUB_RUNNER_DISABLE_UPDATE
  GITHUB_RUNNER_PRESERVE_PROXY

Examples:
  export GITHUB_RUNNER_URL=https://github.com/intellistream
  export GITHUB_RUNNER_TOKEN=<temporary-registration-token>
  bash scripts/setup-github-actions-runner.sh install --labels train8,ascend

  bash scripts/setup-github-actions-runner.sh status

  export GITHUB_RUNNER_TOKEN=<temporary-remove-token>
  bash scripts/setup-github-actions-runner.sh remove
EOF
}

log() {
  printf '[github-runner] %s\n' "$1"
}

fail() {
  printf '[github-runner] %s\n' "$1" >&2
  exit 1
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
      *) echo 'Please answer y or n.' ;;
    esac
  done
}

parse_args() {
  if [[ $# -gt 0 && "$1" != -* ]]; then
    COMMAND="$1"
    shift
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --url)
        RUNNER_URL="$2"
        shift
        ;;
      --token)
        RUNNER_TOKEN="$2"
        shift
        ;;
      --name)
        RUNNER_NAME="$2"
        shift
        ;;
      --group)
        RUNNER_GROUP="$2"
        shift
        ;;
      --labels)
        RUNNER_LABELS="$2"
        shift
        ;;
      --runner-dir)
        RUNNER_DIR="$2"
        shift
        ;;
      --workdir)
        RUNNER_WORKDIR="$2"
        shift
        ;;
      --service-name)
        SERVICE_NAME="$2"
        shift
        ;;
      --version)
        RUNNER_VERSION="$2"
        shift
        ;;
      --replace)
        REPLACE_EXISTING=1
        ;;
      --no-replace)
        REPLACE_EXISTING=0
        ;;
      --disable-update)
        DISABLE_UPDATE=1
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

require_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || fail "Missing required command: $command_name"
}

detect_runner_arch() {
  case "$(uname -m)" in
    x86_64|amd64)
      printf 'x64\n'
      ;;
    aarch64|arm64)
      printf 'arm64\n'
      ;;
    armv7l|armv6l)
      printf 'arm\n'
      ;;
    *)
      fail "Unsupported architecture: $(uname -m)"
      ;;
  esac
}

archive_name() {
  local arch="$1"
  printf 'actions-runner-linux-%s-%s.tar.gz\n' "$arch" "$RUNNER_VERSION"
}

download_url() {
  local arch="$1"
  printf 'https://github.com/actions/runner/releases/download/v%s/actions-runner-linux-%s-%s.tar.gz\n' "$RUNNER_VERSION" "$arch" "$RUNNER_VERSION"
}

service_unit_path() {
  printf '%s/.config/systemd/user/%s.service\n' "$HOME" "$SERVICE_NAME"
}

runner_pid_file() {
  printf '%s/.runner.pid\n' "$RUNNER_DIR"
}

runner_log_file() {
  printf '%s/.runner.log\n' "$RUNNER_DIR"
}

ensure_runner_layout() {
  mkdir -p "$RUNNER_DIR"

  if [[ -x "$RUNNER_DIR/config.sh" && -x "$RUNNER_DIR/run.sh" ]]; then
    return 0
  fi

  if [[ -n "$(find "$RUNNER_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]]; then
    fail "Runner directory is not empty and does not look like a runner install: $RUNNER_DIR"
  fi

  local arch archive url archive_path
  arch="$(detect_runner_arch)"
  archive="$(archive_name "$arch")"
  url="$(download_url "$arch")"
  archive_path="$RUNNER_DIR/$archive"

  require_command tar
  if command -v curl >/dev/null 2>&1; then
    log "Downloading runner $RUNNER_VERSION for linux-$arch"
    curl -fsSL "$url" -o "$archive_path"
  elif command -v wget >/dev/null 2>&1; then
    log "Downloading runner $RUNNER_VERSION for linux-$arch"
    wget -qO "$archive_path" "$url"
  else
    fail 'curl or wget is required to download the GitHub Actions runner'
  fi

  tar -xzf "$archive_path" -C "$RUNNER_DIR"
  rm -f "$archive_path"
  printf '%s\n' "$RUNNER_VERSION" > "$RUNNER_DIR/.dev-hub-runner-version"
}

require_install_inputs() {
  [[ -n "$RUNNER_URL" ]] || fail 'Runner URL is required. Pass --url or set GITHUB_RUNNER_URL.'
  [[ -n "$RUNNER_TOKEN" ]] || fail 'Runner token is required. Pass --token or set GITHUB_RUNNER_TOKEN.'
}

configure_runner() {
  local -a config_args
  config_args=(
    ./config.sh
    --unattended
    --url "$RUNNER_URL"
    --token "$RUNNER_TOKEN"
    --name "$RUNNER_NAME"
    --runnergroup "$RUNNER_GROUP"
    --work "$RUNNER_WORKDIR"
  )

  if [[ -n "$RUNNER_LABELS" ]]; then
    config_args+=(--labels "$RUNNER_LABELS")
  fi
  if (( DISABLE_UPDATE == 1 )); then
    config_args+=(--disableupdate)
  fi
  if (( REPLACE_EXISTING == 1 )); then
    config_args+=(--replace)
  fi

  if [[ -f "$RUNNER_DIR/.runner" ]] && (( REPLACE_EXISTING == 0 )); then
    fail "Runner is already configured at $RUNNER_DIR. Use --replace to overwrite the registration."
  fi

  (
    cd "$RUNNER_DIR"
    "${config_args[@]}"
  )
}

has_systemd_user() {
  command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1
}

write_service_unit() {
  local unit_path
  local exec_start=''
  unit_path="$(service_unit_path)"
  mkdir -p "$(dirname -- "$unit_path")"

  if (( PRESERVE_PROXY_ENV == 0 )); then
    exec_start="/usr/bin/env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u no_proxy -u NO_PROXY $RUNNER_DIR/run.sh"
  else
    exec_start="$RUNNER_DIR/run.sh"
  fi

  cat > "$unit_path" <<EOF
[Unit]
Description=GitHub Actions Runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$RUNNER_DIR
ExecStart=$exec_start
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=300
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
}

background_runner_is_alive() {
  local pid_file pid
  pid_file="$(runner_pid_file)"
  [[ -f "$pid_file" ]] || return 1
  pid="$(cat "$pid_file")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

start_background_runner() {
  local pid_file log_file
  local -a runner_cmd
  pid_file="$(runner_pid_file)"
  log_file="$(runner_log_file)"

  if background_runner_is_alive; then
    log "Runner is already running in background with pid $(cat "$pid_file")"
    return 0
  fi

  mkdir -p "$RUNNER_DIR"
  if (( PRESERVE_PROXY_ENV == 1 )); then
    runner_cmd=(./run.sh)
  else
    runner_cmd=(env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u no_proxy -u NO_PROXY ./run.sh)
  fi

  (
    cd "$RUNNER_DIR"
    nohup "${runner_cmd[@]}" >> "$log_file" 2>&1 < /dev/null &
    echo $! > "$pid_file"
  )
  log "Started runner in background mode; log file: $log_file"
}

stop_background_runner() {
  local pid_file pid
  pid_file="$(runner_pid_file)"

  if ! background_runner_is_alive; then
    rm -f "$pid_file"
    log 'Runner background process is not running.'
    return 0
  fi

  pid="$(cat "$pid_file")"
  kill "$pid" >/dev/null 2>&1 || true
  rm -f "$pid_file"
  log "Stopped runner background process $pid"
}

status_background_runner() {
  local pid_file log_file
  pid_file="$(runner_pid_file)"
  log_file="$(runner_log_file)"

  if background_runner_is_alive; then
    log "Runner is running in background with pid $(cat "$pid_file")"
    if [[ -f "$log_file" ]]; then
      echo '--- recent runner log ---'
      tail -n 20 "$log_file"
    fi
    return 0
  fi

  log 'Runner background process is not running.'
  return 1
}

show_linger_hint() {
  if ! command -v loginctl >/dev/null 2>&1; then
    return 0
  fi

  local linger_state
  linger_state="$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || true)"
  if [[ "$linger_state" != "yes" ]]; then
    log 'Runner service is installed as a user service.'
    log "If you want it to survive logout, enable linger once with: sudo loginctl enable-linger $USER"
  fi
}

install_service() {
  if ! has_systemd_user; then
    log 'systemd --user is not available in this session; using background mode.'
    start_background_runner
    return 0
  fi

  write_service_unit
  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE_NAME.service"
  show_linger_hint
}

service_control() {
  local action="$1"

  if ! has_systemd_user; then
    case "$action" in
      start)
        start_background_runner
        ;;
      stop)
        stop_background_runner
        ;;
      restart)
        stop_background_runner
        start_background_runner
        ;;
      status)
        status_background_runner
        ;;
      *)
        fail "Unsupported background action: $action"
        ;;
    esac
    return 0
  fi

  case "$action" in
    start|stop|restart)
      systemctl --user "$action" "$SERVICE_NAME.service"
      ;;
    status)
      systemctl --user --no-pager --full status "$SERVICE_NAME.service"
      ;;
    *)
      fail "Unsupported service action: $action"
      ;;
  esac
}

print_workflow_hint() {
  local arch_label
  local extra_labels=""
  arch_label="$(detect_runner_arch)"

  log 'Add the following runs-on block to workflows that should target this runner:'
  if [[ -n "$RUNNER_LABELS" ]]; then
    extra_labels=", ${RUNNER_LABELS//,/\, }"
    printf 'runs-on: [self-hosted, Linux, %s%s]\n' "$arch_label" "$extra_labels"
  else
    printf 'runs-on: [self-hosted, Linux, %s]\n' "$arch_label"
  fi
}

remove_runner() {
  local unit_path
  unit_path="$(service_unit_path)"

  if has_systemd_user; then
    systemctl --user disable --now "$SERVICE_NAME.service" >/dev/null 2>&1 || true
  else
    stop_background_runner
  fi

  rm -f "$unit_path"
  if has_systemd_user; then
    systemctl --user daemon-reload
  fi

  if [[ -x "$RUNNER_DIR/config.sh" && -f "$RUNNER_DIR/.runner" ]]; then
    [[ -n "$RUNNER_TOKEN" ]] || fail 'A fresh remove token is required to unregister the runner. Pass --token or set GITHUB_RUNNER_TOKEN.'
    (
      cd "$RUNNER_DIR"
      ./config.sh remove --token "$RUNNER_TOKEN"
    )
  fi

  if [[ -d "$RUNNER_DIR" ]]; then
    if ask_yes_no "Delete local runner files under $RUNNER_DIR?"; then
      rm -rf "$RUNNER_DIR"
      log "Deleted $RUNNER_DIR"
    fi
  fi
}

install_runner() {
  require_install_inputs
  ensure_runner_layout
  configure_runner
  install_service
  print_workflow_hint
}

main() {
  parse_args "$@"

  case "$COMMAND" in
    install)
      install_runner
      ;;
    start|stop|restart|status)
      service_control "$COMMAND"
      ;;
    remove)
      remove_runner
      ;;
    help)
      print_help
      ;;
    *)
      fail "Unknown command: $COMMAND"
      ;;
  esac
}

main "$@"