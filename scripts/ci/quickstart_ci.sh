#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"

RUNNER_FLAVOR="${RUNNER_FLAVOR:-unknown}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
INSTALL_SCOPE="${INSTALL_SCOPE:-full}"
RESULTS_ROOT="${RESULTS_ROOT:-$HUB_ROOT/.ci-results}"
GITHUB_TOKEN_FOR_CLONES="${CI_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}"
GITHUB_RUN_ID_SAFE="${GITHUB_RUN_ID:-local}"
GITHUB_RUN_ATTEMPT_SAFE="${GITHUB_RUN_ATTEMPT:-0}"
ENV_NAME_DEFAULT="vllm-hust-ci-${RUNNER_FLAVOR}-${GITHUB_RUN_ID_SAFE}-${GITHUB_RUN_ATTEMPT_SAFE}"
ENV_NAME="${ENV_NAME:-$ENV_NAME_DEFAULT}"

RESULTS_DIR="$RESULTS_ROOT/$ENV_NAME"
LOG_DIR="$RESULTS_DIR/logs"
JUNIT_DIR="$RESULTS_DIR/junit"
SUMMARY_FILE="$RESULTS_DIR/summary.md"
RESULTS_TSV="$RESULTS_DIR/results.tsv"

SCRIPT_EXIT_CODE=0
CLEANUP_DONE=0

mkdir -p "$LOG_DIR" "$JUNIT_DIR"
: > "$RESULTS_TSV"

slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

log() {
  printf '[quickstart-ci] %s\n' "$1"
}

append_result() {
  local name="$1"
  local status="$2"
  local log_file="$3"
  printf '%s\t%s\t%s\n' "$name" "$status" "$log_file" >> "$RESULTS_TSV"
}

resolve_conda_bin() {
  if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE:-}" ]]; then
    printf '%s\n' "$CONDA_EXE"
    return 0
  fi

  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return 0
  fi

  local candidate
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/miniforge3/bin/conda"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

conda_env_exists() {
  local conda_bin="$1"
  "$conda_bin" env list | awk '{print $1}' | grep -Fxq "$ENV_NAME"
}

cleanup_conda_env() {
  local cleanup_log="$LOG_DIR/cleanup-conda-env.log"
  local conda_bin=""

  if (( CLEANUP_DONE == 1 )); then
    return 0
  fi
  CLEANUP_DONE=1

  if ! conda_bin="$(resolve_conda_bin 2>/dev/null || true)"; then
    printf 'cleanup_status\tSKIPPED\tconda not found\n' >> "$RESULTS_TSV"
    return 0
  fi

  if ! conda_env_exists "$conda_bin"; then
    printf 'cleanup_status\tSKIPPED\tenv already absent\n' >> "$RESULTS_TSV"
    return 0
  fi

  if env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
    "$conda_bin" env remove -n "$ENV_NAME" -y >"$cleanup_log" 2>&1; then
    printf 'cleanup_status\tPASS\t%s\n' "$cleanup_log" >> "$RESULTS_TSV"
  else
    printf 'cleanup_status\tFAIL\t%s\n' "$cleanup_log" >> "$RESULTS_TSV"
  fi
}

write_summary() {
  {
    printf '# Quickstart CI Summary\n\n'
    printf -- '- Runner flavor: %s\n' "$RUNNER_FLAVOR"
    printf -- '- Conda env: %s\n' "$ENV_NAME"
    printf -- '- Python: %s\n' "$PYTHON_VERSION"
    printf -- '- Install scope: %s\n' "$INSTALL_SCOPE"
    printf -- '- Results dir: %s\n\n' "$RESULTS_DIR"
    printf '| Step | Status | Log |\n'
    printf '| --- | --- | --- |\n'

    while IFS=$'\t' read -r name status log_file; do
      if [[ -z "$name" ]]; then
        continue
      fi
      printf '| %s | %s | %s |\n' "$name" "$status" "$log_file"
    done < "$RESULTS_TSV"

    printf '\n'
    printf 'Overall exit code: %s\n' "$SCRIPT_EXIT_CODE"
  } > "$SUMMARY_FILE"

  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    cat "$SUMMARY_FILE" >> "$GITHUB_STEP_SUMMARY"
  fi
}

finalize() {
  cleanup_conda_env
  write_summary
}

handle_signal() {
  local signal_name="$1"
  log "Received ${signal_name}; stopping CI run and cleaning up '$ENV_NAME'"
  if (( SCRIPT_EXIT_CODE == 0 )); then
    SCRIPT_EXIT_CODE=130
  fi
  exit "$SCRIPT_EXIT_CODE"
}

trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM
trap finalize EXIT

prepare_clone_auth() {
  if [[ -z "$GITHUB_TOKEN_FOR_CLONES" ]]; then
    return 0
  fi

  git config --global url."https://x-access-token:${GITHUB_TOKEN_FOR_CLONES}@github.com/".insteadOf "https://github.com/"
  git config --global url."https://x-access-token:${GITHUB_TOKEN_FOR_CLONES}@github.com/".insteadOf "git@github.com:"
  export GIT_TERMINAL_PROMPT=0
}

run_step() {
  local name="$1"
  shift
  local slug
  local log_file

  slug="$(slugify "$name")"
  log_file="$LOG_DIR/$slug.log"

  log "Running: $name"
  if "$@" >"$log_file" 2>&1; then
    append_result "$name" "PASS" "$log_file"
    return 0
  fi

  append_result "$name" "FAIL" "$log_file"
  return 1
}

skip_step() {
  local name="$1"
  local reason="$2"
  append_result "$name" "SKIPPED" "$reason"
}

run_pytest_step() {
  local name="$1"
  local repo_dir="$2"
  local junit_name="$3"
  shift 3
  local conda_bin="$1"
  shift

  local junit_file="$JUNIT_DIR/$junit_name"
  run_step "$name" env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
    "$conda_bin" run -n "$ENV_NAME" python -m pytest -q --junitxml "$junit_file" "$@"
}

install_smoke_test_dependencies() {
  local conda_bin="$1"

  run_step \
    "install smoke test deps" \
    env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" TORCH_DEVICE_BACKEND_AUTOLOAD=0 \
    "$conda_bin" run -n "$ENV_NAME" python -m pip install -e "$WORKSPACE_ROOT/vllm-hust[ci-smoke]" --no-build-isolation
}

plugin_installed() {
  local conda_bin="$1"
  env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
    "$conda_bin" run -n "$ENV_NAME" python - <<'PY'
from importlib.metadata import PackageNotFoundError, version

try:
    version("vllm-ascend-hust")
except PackageNotFoundError:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

main() {
  local conda_bin=""
  local bootstrap_ok=0

  prepare_clone_auth

  if ! run_step \
    "quickstart bootstrap" \
    env HUST_DEV_HUB_SKIP_ASCEND_SYSTEM_APPLY=1 bash "$HUB_ROOT/scripts/quickstart.sh" --clone --conda --install --install-scope "$INSTALL_SCOPE" --env-name "$ENV_NAME" --python "$PYTHON_VERSION" -y; then
    SCRIPT_EXIT_CODE=1
  else
    bootstrap_ok=1
  fi

  if (( bootstrap_ok == 0 )); then
    skip_step "python smoke" "quickstart bootstrap failed"
    skip_step "vllm help" "quickstart bootstrap failed"
    skip_step "runtime check" "quickstart bootstrap failed"
    skip_step "ascend-runtime-manager tests" "quickstart bootstrap failed"
    skip_step "vllm-hust-benchmark tests" "quickstart bootstrap failed"
    skip_step "vllm-hust smoke tests" "quickstart bootstrap failed"
    skip_step "runtime check require plugin" "quickstart bootstrap failed"
    return 0
  fi

  conda_bin="$(resolve_conda_bin)"

  if ! run_step \
    "python smoke" \
    env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
    "$conda_bin" run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)'; then
    SCRIPT_EXIT_CODE=1
  fi

  if ! run_step \
    "vllm help" \
    env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
    "$conda_bin" run -n "$ENV_NAME" bash -lc 'if command -v vllm-hust >/dev/null 2>&1; then TORCH_DEVICE_BACKEND_AUTOLOAD=0 vllm-hust --help; else TORCH_DEVICE_BACKEND_AUTOLOAD=0 vllm --help; fi'; then
    SCRIPT_EXIT_CODE=1
  fi

  if ! run_step \
    "runtime check" \
    env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
    "$conda_bin" run -n "$ENV_NAME" python -m hust_ascend_manager.cli runtime check --repo "$WORKSPACE_ROOT/vllm-hust"; then
    SCRIPT_EXIT_CODE=1
  fi

  if ! run_pytest_step \
    "ascend-runtime-manager tests" \
    "$WORKSPACE_ROOT/ascend-runtime-manager" \
    "ascend-runtime-manager.xml" \
    "$conda_bin" \
    "$WORKSPACE_ROOT/ascend-runtime-manager/tests"; then
    SCRIPT_EXIT_CODE=1
  fi

  if ! install_smoke_test_dependencies "$conda_bin"; then
    SCRIPT_EXIT_CODE=1
  fi

  if ! run_pytest_step \
    "vllm-hust-benchmark tests" \
    "$WORKSPACE_ROOT/vllm-hust-benchmark" \
    "vllm-hust-benchmark.xml" \
    "$conda_bin" \
    "$WORKSPACE_ROOT/vllm-hust-benchmark/tests"; then
    SCRIPT_EXIT_CODE=1
  fi

  if ! run_step \
    "vllm-hust smoke tests" \
    env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" TORCH_DEVICE_BACKEND_AUTOLOAD=0 \
    "$conda_bin" run -n "$ENV_NAME" python -m pytest -q --junitxml "$JUNIT_DIR/vllm-hust-smoke.xml" "$WORKSPACE_ROOT/vllm-hust/tests/test_vllm_port.py"; then
    SCRIPT_EXIT_CODE=1
  fi

  if plugin_installed "$conda_bin"; then
    if ! run_step \
      "runtime check require plugin" \
      env HOME="$HOME" XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}" XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
      "$conda_bin" run -n "$ENV_NAME" python -m hust_ascend_manager.cli runtime check --repo "$WORKSPACE_ROOT/vllm-hust" --require-plugin; then
      SCRIPT_EXIT_CODE=1
    fi
  else
    skip_step "runtime check require plugin" "vllm-ascend-hust not installed on this runner"
  fi
}

main
exit "$SCRIPT_EXIT_CODE"