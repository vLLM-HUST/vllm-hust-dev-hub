#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_BASE_DIR="$(cd -- "$ROOT_DIR/.." && pwd)"
CLONE_JOBS="${CLONE_JOBS:-4}"
AUTO_YES=0
TEMP_GIT_SSH_CONFIG=""

cleanup_temp_git_ssh_config() {
  if [[ -n "$TEMP_GIT_SSH_CONFIG" && -f "$TEMP_GIT_SSH_CONFIG" ]]; then
    rm -f "$TEMP_GIT_SSH_CONFIG"
  fi
}

build_git_ssh_command() {
  local ssh_binary
  local workspace_ssh_dir="$TARGET_BASE_DIR/.ssh"
  local known_hosts_file="$HOME/.ssh/known_hosts"
  local identity_file=""
  local -a ssh_command

  ssh_binary="$(command -v ssh)"
  ssh_command=(
    env -u LD_LIBRARY_PATH "$ssh_binary"
    -o StrictHostKeyChecking=accept-new
    -o "UserKnownHostsFile=$known_hosts_file"
  )

  if [[ -d "$workspace_ssh_dir" ]]; then
    identity_file="$(find "$workspace_ssh_dir" -maxdepth 1 -type f -name 'id_*' ! -name '*.pub' | sort | head -n 1 || true)"
  fi

  if [[ -n "$identity_file" ]]; then
    ssh_command+=( -i "$identity_file" -o IdentitiesOnly=yes )
  elif [[ -f "$workspace_ssh_dir/config" ]]; then
    TEMP_GIT_SSH_CONFIG="$(mktemp)"
    sed -E "s#(/home/[^/]+/\.ssh/)#$workspace_ssh_dir/#g" "$workspace_ssh_dir/config" > "$TEMP_GIT_SSH_CONFIG"
    chmod 600 "$TEMP_GIT_SSH_CONFIG"
    ssh_command+=( -F "$TEMP_GIT_SSH_CONFIG" )
  fi

  printf '%q ' "${ssh_command[@]}"
}

configure_git_ssh_defaults() {
  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  touch "$HOME/.ssh/known_hosts"
  chmod 600 "$HOME/.ssh/known_hosts"
  export GIT_SSH_COMMAND="$(build_git_ssh_command)"
}

if ! command -v git >/dev/null 2>&1; then
  echo "git is required but was not found in PATH" >&2
  exit 1
fi

run_git() {
  env -u LD_LIBRARY_PATH git "$@"
}

if [[ ! "$CLONE_JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "CLONE_JOBS must be a positive integer" >&2
  exit 1
fi

print_help() {
  cat <<'EOF'
Usage: bash scripts/clone-workspace-repos.sh [options]

Options:
  -y, --yes   Auto-approve prompts for cloning reference repos and pulling updates.
  -h, --help  Show this help message.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
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

is_reference_repo() {
  [[ "$1" == reference-repos/* ]]
}

clone_destination() {
  printf '%s\n' "$TARGET_BASE_DIR/$1"
}

github_repo_path_from_url() {
  local repo_url="$1"

  if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]%.git}"
    return 0
  fi

  if [[ "$repo_url" =~ ^https://github\.com/(.+)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]%.git}"
    return 0
  fi

  return 1
}

https_url_from_ssh_url() {
  local repo_url="$1"

  if [[ "$repo_url" =~ ^git@github\.com:(.+)$ ]]; then
    printf 'https://github.com/%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi

  return 1
}

maybe_sync_origin_remote_to_ssh() {
  local destination="$1"
  local desired_repo_url="$2"
  local current_repo_url
  local current_repo_path
  local desired_repo_path

  current_repo_url="$(run_git -C "$destination" remote get-url origin 2>/dev/null || true)"
  if [[ -z "$current_repo_url" || "$current_repo_url" == "$desired_repo_url" ]]; then
    return 0
  fi

  current_repo_path="$(github_repo_path_from_url "$current_repo_url" 2>/dev/null || true)"
  desired_repo_path="$(github_repo_path_from_url "$desired_repo_url" 2>/dev/null || true)"
  if [[ -z "$current_repo_path" || -z "$desired_repo_path" || "$current_repo_path" != "$desired_repo_path" ]]; then
    return 0
  fi

  # Keep the existing protocol for established clones to avoid breaking hosts
  # that only have HTTPS auth configured.
  return 0
}

queue_clone() {
  local relative_path="$1"
  local repo_url="$2"
  local destination
  local https_url
  destination="$(clone_destination "$relative_path")"

  if [[ ! -d "$(dirname -- "$destination")" ]]; then
    mkdir -p "$(dirname -- "$destination")"
  fi
  echo "[clone] $relative_path <- $repo_url"
  if run_git clone "$repo_url" "$destination"; then
    return 0
  fi

  if https_url="$(https_url_from_ssh_url "$repo_url")"; then
    echo "[clone] $relative_path SSH clone failed; retrying via $https_url"
    run_git clone "$https_url" "$destination"
  fi
}

maybe_pull_updates() {
  local relative_path="$1"
  local repo_url="$2"
  local destination
  local branch_name
  local upstream_ref
  local upstream_remote
  local upstream_branch
  local current_repo_url
  local https_url
  local counts
  local ahead_count
  local behind_count

  destination="$(clone_destination "$relative_path")"

  if [[ ! -d "$destination/.git" ]]; then
    echo "[skip] $relative_path already exists and is not a git repository"
    return 0
  fi

  maybe_sync_origin_remote_to_ssh "$destination" "$repo_url"

  branch_name="$(run_git -C "$destination" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ -z "$branch_name" || "$branch_name" == "HEAD" ]]; then
    echo "[skip] $relative_path has no active local branch"
    return 0
  fi

  upstream_ref="$(run_git -C "$destination" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [[ -z "$upstream_ref" ]]; then
    echo "[skip] $relative_path has no upstream tracking branch"
    return 0
  fi
  upstream_remote="${upstream_ref%%/*}"
  upstream_branch="${upstream_ref#*/}"

  if ! run_git -C "$destination" fetch --quiet --prune; then
    current_repo_url="$(run_git -C "$destination" remote get-url origin 2>/dev/null || true)"
    https_url="$(https_url_from_ssh_url "$current_repo_url" 2>/dev/null || true)"
    if [[ -z "$https_url" ]]; then
      https_url="$(https_url_from_ssh_url "$repo_url" 2>/dev/null || true)"
    fi

    if [[ -n "$https_url" ]]; then
      echo "[fetch] $relative_path SSH fetch failed; retrying via $https_url"
      run_git -C "$destination" remote set-url origin "$https_url"
      if ! run_git -C "$destination" fetch --quiet --prune; then
        echo "[skip] $relative_path fetch failed after HTTPS fallback"
        return 0
      fi
    else
      echo "[skip] $relative_path fetch failed and no HTTPS fallback is available"
      return 0
    fi
  fi

  counts="$(run_git -C "$destination" rev-list --left-right --count "$branch_name...$upstream_ref")"
  ahead_count="${counts%%$'\t'*}"
  behind_count="${counts##*$'\t'}"

  if [[ "$behind_count" == "0" ]]; then
    echo "[up-to-date] $relative_path"
    return 0
  fi

  if ask_yes_no "Remote updates found for $relative_path (behind=$behind_count, ahead=$ahead_count). Pull with --ff-only?"; then
    echo "[pull] $relative_path"
    if ! run_git -C "$destination" pull --ff-only "$upstream_remote" "$upstream_branch"; then
      echo "[skip] $relative_path pull failed; leaving local branch unchanged"
    fi
  else
    echo "[skip] $relative_path remote updates not pulled"
  fi
}

# Prefer SSH URLs for fresh clones, with HTTPS fallback when SSH auth is unavailable.
# Keep upstream comparison repos under reference-repos/ rather than as top-level siblings.
REPOS=(
  "ascend-runtime-manager|git@github.com:intellistream/ascend-runtime-manager.git"
  "vllm-hust|git@github.com:intellistream/vllm-hust.git"
  "vllm-hust-workstation|git@github.com:intellistream/vllm-hust-workstation.git"
  "vllm-hust-website|git@github.com:intellistream/vllm-hust-website.git"
  "vllm-hust-docs|git@github.com:intellistream/vllm-hust-docs.git"
  "vllm-ascend-hust|git@github.com:intellistream/vllm-ascend-hust.git"
  "reference-repos/vllm|git@github.com:vllm-project/vllm.git"
  "reference-repos/sglang|git@github.com:sgl-project/sglang.git"
  "reference-repos/vllm-ascend|git@github.com:vllm-project/vllm-ascend.git"
  "EvoScientist|git@github.com:intellistream/EvoScientist.git"
  "vllm-hust-benchmark|git@github.com:intellistream/vllm-hust-benchmark.git"
)

parse_args "$@"
trap cleanup_temp_git_ssh_config EXIT
configure_git_ssh_defaults

running_jobs=0
failures=0
pending_clones=()

for entry in "${REPOS[@]}"; do
  relative_path="${entry%%|*}"
  repo_url="${entry#*|}"
  destination="$(clone_destination "$relative_path")"

  if [[ -e "$destination" ]]; then
    maybe_pull_updates "$relative_path" "$repo_url"
    continue
  fi

  if is_reference_repo "$relative_path"; then
    if ! ask_yes_no "Clone upstream reference repo $relative_path?"; then
      echo "[skip] $relative_path reference clone declined"
      continue
    fi
  fi

  pending_clones+=("$entry")
done

for entry in "${pending_clones[@]}"; do
  relative_path="${entry%%|*}"
  repo_url="${entry#*|}"

  queue_clone "$relative_path" "$repo_url" &
  running_jobs=$((running_jobs + 1))

  if (( running_jobs >= CLONE_JOBS )); then
    if ! wait -n; then
      failures=$((failures + 1))
    fi
    running_jobs=$((running_jobs - 1))
  fi
done

while (( running_jobs > 0 )); do
  if ! wait -n; then
    failures=$((failures + 1))
  fi
  running_jobs=$((running_jobs - 1))
done

if (( failures > 0 )); then
  echo "Completed with $failures failed clone job(s)" >&2
  exit 1
fi

echo "All repository clone jobs finished successfully"