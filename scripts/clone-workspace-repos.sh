#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_BASE_DIR="$(cd -- "$ROOT_DIR/.." && pwd)"
CLONE_JOBS="${CLONE_JOBS:-4}"
AUTO_YES=0

if ! command -v git >/dev/null 2>&1; then
  echo "git is required but was not found in PATH" >&2
  exit 1
fi

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

queue_clone() {
  local relative_path="$1"
  local repo_url="$2"
  local destination
  destination="$(clone_destination "$relative_path")"

  mkdir -p "$(dirname -- "$destination")"
  echo "[clone] $relative_path <- $repo_url"
  git clone "$repo_url" "$destination"
}

maybe_pull_updates() {
  local relative_path="$1"
  local destination
  local branch_name
  local upstream_ref
  local counts
  local ahead_count
  local behind_count

  destination="$(clone_destination "$relative_path")"

  if [[ ! -d "$destination/.git" ]]; then
    echo "[skip] $relative_path already exists and is not a git repository"
    return 0
  fi

  branch_name="$(git -C "$destination" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ -z "$branch_name" || "$branch_name" == "HEAD" ]]; then
    echo "[skip] $relative_path has no active local branch"
    return 0
  fi

  upstream_ref="$(git -C "$destination" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [[ -z "$upstream_ref" ]]; then
    echo "[skip] $relative_path has no upstream tracking branch"
    return 0
  fi

  git -C "$destination" fetch --quiet --prune
  counts="$(git -C "$destination" rev-list --left-right --count "$branch_name...$upstream_ref")"
  ahead_count="${counts%%$'\t'*}"
  behind_count="${counts##*$'\t'}"

  if [[ "$behind_count" == "0" ]]; then
    echo "[up-to-date] $relative_path"
    return 0
  fi

  if ask_yes_no "Remote updates found for $relative_path (behind=$behind_count, ahead=$ahead_count). Pull with --ff-only?"; then
    echo "[pull] $relative_path"
    git -C "$destination" pull --ff-only
  else
    echo "[skip] $relative_path remote updates not pulled"
  fi
}

# Use SSH URLs to avoid HTTPS connectivity issues.
# Keep upstream comparison repos under reference-repos/ rather than as top-level siblings.
REPOS=(
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

running_jobs=0
failures=0
pending_clones=()

for entry in "${REPOS[@]}"; do
  relative_path="${entry%%|*}"
  repo_url="${entry#*|}"
  destination="$(clone_destination "$relative_path")"

  if [[ -e "$destination" ]]; then
    maybe_pull_updates "$relative_path"
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