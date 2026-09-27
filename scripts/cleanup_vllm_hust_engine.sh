#!/usr/bin/env bash
# Stop vLLM serve processes inside the configured engine container.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

load_dotenv() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    local key="${line%%=*}"
    key="${key// /}"
    [[ -z "$key" || -n "${!key:-}" ]] && continue
    export "$line"
  done < "$env_file"
}

load_dotenv "$repo_root/.env"

if [[ -z "${VLLM_ENGINE_CONTAINER_NAME:-${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-}}}" || -z "${VLLM_ENGINE_PORT:-${PORT:-}}" ]]; then
  echo "ERROR: cleanup requires a container name (VLLM_ENGINE_CONTAINER_NAME; legacy fallbacks: VLLM_ENGINE_CONTAINER or DOCKER_CONTAINER) and a port (VLLM_ENGINE_PORT or PORT), either in .env or the caller environment." >&2
  exit 2
fi

container="${VLLM_ENGINE_CONTAINER_NAME:-${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-}}}"
port="${VLLM_ENGINE_PORT:-${PORT:-}}"
docker_bin="${DOCKER_BIN:-docker}"
docker_cmd=("$docker_bin")
if [[ -n "${VLLM_ENGINE_DOCKER_SUDO:-sudo}" ]]; then
  docker_cmd=("${VLLM_ENGINE_DOCKER_SUDO:-sudo}" "$docker_bin")
fi

if ! "${docker_cmd[@]}" info >/dev/null 2>&1; then
  echo "ERROR: cleanup cannot contact the configured Docker daemon." >&2
  exit 1
fi
if ! running=$("${docker_cmd[@]}" inspect -f '{{.State.Running}}' "$container" 2>/dev/null); then
  exit 0
fi
[[ "$running" == "true" ]] || exit 0

term_attempts="${VLLM_ENGINE_CLEANUP_TERM_ATTEMPTS:-10}"
kill_attempts="${VLLM_ENGINE_CLEANUP_KILL_ATTEMPTS:-10}"
poll_interval="${VLLM_ENGINE_CLEANUP_POLL_INTERVAL:-0.5}"
for value in "$term_attempts" "$kill_attempts"; do
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: cleanup attempt counts must be positive integers." >&2
    exit 2
  fi
done
if [[ ! "$poll_interval" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]]; then
  echo "ERROR: VLLM_ENGINE_CLEANUP_POLL_INTERVAL must be a non-negative number." >&2
  exit 2
fi

cleanup_script='
port="$1"
term_attempts="$2"
kill_attempts="$3"
poll_interval="$4"

collect_matches() {
  matches="$(ps -eo pid=,args= | awk -v port="$port" '"'"'
    /vllm/ && / serve / {
      if ($0 ~ ("--port " port) || $0 ~ ("--port=" port)) {
        print $1
      }
    }
  '"'"' | tr "\n" " ")"
  launchers="$(
    ps -eo pid=,args= | while read -r launcher_pid launcher_args; do
      case "$launcher_args" in
        bash\ /tmp/vllm-hust-engine.*.sh*)
          launcher_script=${launcher_args#bash }
          launcher_script=${launcher_script%% *}
          if [ -r "$launcher_script" ] && grep -Fq -- "--port \"$port\"" "$launcher_script"; then
            printf "%s " "$launcher_pid"
          fi
          ;;
      esac
    done
  )"
  matches="$matches $launchers"
  if [ "${VLLM_ENGINE_AGGRESSIVE_CLEANUP:-0}" = "1" ] || [ "${VLLM_ENGINE_AGGRESSIVE_CLEANUP:-false}" = "true" ]; then
    orphans="$(ps -eo pid=,args= | awk '"'"'
      /VLLM::EngineCor|VLLM::Worker_TP|multiprocessing\.resource_tracker|multiprocessing\.spawn|\[python3\]/ {
        print $1
      }
    '"'"' | tr "\n" " ")"
    matches="$matches $orphans"
  fi
  printf "%s\n" $matches 2>/dev/null | awk '"'"'/^[0-9]+$/ { print }'"'"' | sort -un | tr "\n" " "
}

wait_for_exit() {
  attempts="$1"
  while [ "$attempts" -gt 0 ]; do
    remaining="$(collect_matches)"
    [ -z "$remaining" ] && return 0
    sleep "$poll_interval"
    attempts=$((attempts - 1))
  done
  [ -z "$(collect_matches)" ]
}

initial="$(collect_matches)"
[ -n "$initial" ] || exit 0

kill -TERM $initial 2>/dev/null || true
if ! wait_for_exit "$term_attempts"; then
  survivors="$(collect_matches)"
  kill -KILL $survivors 2>/dev/null || true
  if ! wait_for_exit "$kill_attempts"; then
    echo "ERROR: vLLM process(es) remain after SIGKILL: $(collect_matches)" >&2
    exit 1
  fi
fi
echo "$initial"
'

if ! cleaned_pids=$("${docker_cmd[@]}" exec \
  --env "VLLM_ENGINE_AGGRESSIVE_CLEANUP=${VLLM_ENGINE_AGGRESSIVE_CLEANUP:-0}" \
  "$container" sh -c "$cleanup_script" sh "$port" "$term_attempts" \
  "$kill_attempts" "$poll_interval"); then
  echo "ERROR: container vLLM cleanup failed for '$container' on port $port." >&2
  exit 1
fi
if [[ -n "$cleaned_pids" ]]; then
  echo "[vllm-hust] stopped container vLLM process(es) on port $port: $cleaned_pids"
fi
