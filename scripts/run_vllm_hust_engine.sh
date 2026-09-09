#!/usr/bin/env bash
# run_vllm_hust_engine.sh — Launch vLLM-HUST from the host into a Docker
# container with the repo's standard Ascend/runtime guardrails.
#
# This script intentionally runs from the host and uses `docker exec`.  Do not
# start the service by opening an interactive shell inside the container and
# running vLLM by hand; that path is too easy to get wrong.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

load_dotenv() {
  local env_file="$1"
  local overwrite="${2:-false}"
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    local key="${line%%=*}"
    key="${key// /}"
    [[ -z "$key" ]] && continue
    if [[ "$overwrite" == "true" ]]; then
      export "$line"
      continue
    fi
    if [[ "${!key+x}" != "x" ]]; then
      export "$line"
    fi
  done < "$env_file"
}

if [[ "${VLLM_ENGINE_LOAD_REPO_ENV:-true}" != "false" && "${VLLM_ENGINE_LOAD_REPO_ENV:-true}" != "0" ]]; then
  load_dotenv "$repo_root/.env"
fi
if [[ -n "${VLLM_ENGINE_ENV_FILE:-}" ]]; then
  load_dotenv "$VLLM_ENGINE_ENV_FILE" true
fi

# Validate the source/package identity before inspecting or recreating a
# container. This keeps a stale nested package receipt from turning a harmless
# configuration typo into a systemd restart loop and an avoidable outage.
python3 "$repo_root/scripts/validate_runtime_identity_contract.py"

container="${VLLM_ENGINE_CONTAINER_NAME:-${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-vllm-ascend-dev}}}"
container_image="${VLLM_ENGINE_IMAGE:-${IMAGE:-quay.io/ascend/vllm-ascend:v0.23.0-openeuler}}"
expected_image_id="${VLLM_ENGINE_EXPECTED_IMAGE_ID:-}"
auto_create_container="${VLLM_ENGINE_AUTO_CREATE_CONTAINER:-true}"
container_non_interactive="${VLLM_ENGINE_CONTAINER_NON_INTERACTIVE:-1}"
container_shm_size="${VLLM_ENGINE_CONTAINER_SHM_SIZE:-${SHM_SIZE:-16g}}"
container_ld_preload="${VLLM_ENGINE_CONTAINER_LD_PRELOAD:-}"
recreate_container="${VLLM_ENGINE_RECREATE_CONTAINER:-false}"
model_path="${VLLM_ENGINE_MODEL_PATH:-${MODEL_ID:-}}"
served_model_name="${VLLM_ENGINE_SERVED_MODEL_NAME:-${SERVED_MODEL_NAME:-}}"
host="${VLLM_ENGINE_HOST:-${HOST:-0.0.0.0}}"
port="${VLLM_ENGINE_PORT:-${PORT:-8000}}"
tp_size="${VLLM_ENGINE_TP_SIZE:-${TP_SIZE:-4}}"
max_model_len="${VLLM_ENGINE_MAX_MODEL_LEN:-${MAX_MODEL_LEN:-32768}}"
max_num_batched_tokens="${VLLM_ENGINE_MAX_NUM_BATCHED_TOKENS:-${MAX_NUM_BATCHED_TOKENS:-$max_model_len}}"
gpu_mem_util="${VLLM_ENGINE_GPU_MEM_UTIL:-${GPU_MEM_UTIL:-0.85}}"
max_num_seqs="${VLLM_ENGINE_MAX_NUM_SEQS:-${MAX_NUM_SEQS:-16}}"
dtype="${VLLM_ENGINE_DTYPE:-${DTYPE:-bfloat16}}"
kv_cache_dtype="${VLLM_ENGINE_KV_CACHE_DTYPE:-}"
kv_cache_memory_bytes="${VLLM_ENGINE_KV_CACHE_MEMORY_BYTES:-}"
load_format="${VLLM_ENGINE_LOAD_FORMAT:-${LOAD_FORMAT:-auto}}"
quantization="${VLLM_ENGINE_QUANTIZATION:-${QUANTIZATION:-}}"
compilation_config="${VLLM_ENGINE_COMPILATION_CONFIG:-}"
vllm_compat_version="${VLLM_ENGINE_VLLM_VERSION:-}"
cache_namespace="${VLLM_ENGINE_CACHE_NAMESPACE:-}"
if [[ -z "$cache_namespace" && -n "$expected_image_id" ]]; then
  cache_namespace="image-${expected_image_id#sha256:}"
  cache_namespace="${cache_namespace:0:22}"
elif [[ -z "$cache_namespace" && -n "$vllm_compat_version" ]]; then
  cache_namespace="vllm-${vllm_compat_version//[^a-zA-Z0-9_.-]/-}"
elif [[ -z "$cache_namespace" ]]; then
  cache_namespace="default"
fi
if [[ ! "$cache_namespace" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
  echo "ERROR: VLLM_ENGINE_CACHE_NAMESPACE contains unsafe characters: $cache_namespace" >&2
  exit 1
fi
vllm_bin="${VLLM_ENGINE_BIN:-vllm-hust}"
vllm_script="${VLLM_ENGINE_SCRIPT:-}"
conda_prefix="${VLLM_ENGINE_CONDA_PREFIX:-}"
conda_env="${VLLM_ENGINE_CONDA_ENV:-${CONDA_ENV:-}}"
engine_python="${VLLM_ENGINE_PYTHON:-}"
api_key="${VLLM_HUST_API_KEY:-${VLLM_ENGINE_API_KEY:-}}"
replace_existing="${VLLM_ENGINE_REPLACE_EXISTING:-true}"
enable_prefix_caching="${VLLM_ENGINE_ENABLE_PREFIX_CACHING:-1}"
require_prefix_caching="${VLLM_ENGINE_REQUIRE_PREFIX_CACHING:-0}"
enable_chunked_prefill="${VLLM_ENGINE_ENABLE_CHUNKED_PREFILL:-1}"
enforce_eager="${VLLM_ENGINE_ENFORCE_EAGER:-0}"
expert_parallel="${VLLM_ENGINE_ENABLE_EXPERT_PARALLEL:-0}"
legacy_ascend_env="${VLLM_ENGINE_ENABLE_LEGACY_ASCEND_ENV:-0}"
flashcomm1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-}"
fused_mc2="${VLLM_ASCEND_ENABLE_FUSED_MC2:-}"
if [[ "$legacy_ascend_env" != "0" && "$legacy_ascend_env" != "1" ]]; then
  echo "ERROR: VLLM_ENGINE_ENABLE_LEGACY_ASCEND_ENV must be 0 or 1." >&2
  exit 1
fi
for setting in enable_prefix_caching require_prefix_caching enable_chunked_prefill enforce_eager; do
  value="${!setting}"
  if [[ "$value" != "0" && "$value" != "1" ]]; then
    echo "ERROR: ${setting} must resolve to 0 or 1 (got: $value)." >&2
    exit 1
  fi
done
if [[ "$require_prefix_caching" == "1" && "$enable_prefix_caching" != "1" ]]; then
  echo "ERROR: prefix caching is required by VLLM_ENGINE_REQUIRE_PREFIX_CACHING=1; refusing to launch with VLLM_ENGINE_ENABLE_PREFIX_CACHING=$enable_prefix_caching." >&2
  exit 1
fi
optimization_repo_container="${VLLM_OPTIMIZATION_REPO_CONTAINER:-}"
optimization_src_subdir="${VLLM_OPTIMIZATION_SRC_SUBDIR:-src}"
optimization_plugin="${VLLM_OPTIMIZATION_PLUGIN:-}"
optimization_entrypoint_group="${VLLM_OPTIMIZATION_ENTRYPOINT_GROUP:-vllm.general_plugins}"
optimization_auto_install="${VLLM_OPTIMIZATION_AUTO_INSTALL:-true}"
optimization_entrypoint_probe="$(<"$repo_root/scripts/check_optimization_entrypoint.py")"
optimization_installer="$(<"$repo_root/scripts/prepare_optimization_plugin.py")"
optimization_env_prefix="${VLLM_OPTIMIZATION_ENV_PREFIX:-}"
plugins="${VLLM_PLUGINS:-}"
if [[ -z "$plugins" ]]; then
  # VLLM_PLUGINS filters entry-point names across both platform and general
  # plugin groups. Loading only `ascend` activates the NPU platform but drops
  # `ascend_model`, causing supported models such as DeepSeek-V4 to fall back
  # to an upstream CUDA implementation.
  plugins="ascend,ascend_kv_connector,ascend_model,ascend_model_loader,ascend_service_profiling"
elif [[ ",$plugins," != *",ascend,"* ]]; then
  plugins="ascend,${plugins}"
fi
if [[ -n "$optimization_plugin" ]]; then
  if [[ "$optimization_entrypoint_group" == "vllm.general_plugins" || "$optimization_entrypoint_group" == "vllm.platform_plugins" ]]; then
    if [[ ",$plugins," != *",$optimization_plugin,"* ]]; then
      plugins="${plugins},${optimization_plugin}"
    fi
  fi
fi
container_workspace_root="${CONTAINER_WORKSPACE_ROOT:-/workspace}"
engine_base_pythonpath="${VLLM_ENGINE_BASE_PYTHONPATH-/workspace/vllm-hust:/workspace/vllm-ascend-hust}"
pythonpath="${VLLM_ENGINE_PYTHONPATH:-}"
if [[ -z "$pythonpath" ]]; then
  pythonpath="$engine_base_pythonpath"
  if [[ -n "$optimization_repo_container" ]]; then
    opt_pythonpath="$optimization_repo_container"
    if [[ -n "$optimization_src_subdir" ]]; then
      opt_pythonpath="${optimization_repo_container%/}/${optimization_src_subdir}:$opt_pythonpath"
    fi
    if [[ -n "$pythonpath" ]]; then
      pythonpath="$opt_pythonpath:$pythonpath"
    else
      pythonpath="$opt_pythonpath"
    fi
  fi
fi
if [[ -n "$optimization_env_prefix" && -z "${VLLM_ENGINE_EXTRA_ENV_PREFIXES:-}" ]]; then
  export VLLM_ENGINE_EXTRA_ENV_PREFIXES="$optimization_env_prefix"
fi
target_device="${VLLM_TARGET_DEVICE:-npu}"
container_log_file="${VLLM_ENGINE_CONTAINER_LOG_FILE:-}"
simple_kv_offload="${VLLM_USE_SIMPLE_KV_OFFLOAD:-0}"

container_extra_env_exports() {
  python3 "$repo_root/scripts/container_env_exports.py"
}

extra_env_exports="$(container_extra_env_exports)"

if [[ -z "$api_key" || "$api_key" == "EMPTY" ]]; then
  echo "ERROR: vLLM-HUST must be started with a real API key." >&2
  echo "Set VLLM_HUST_API_KEY in .env; never use EMPTY." >&2
  exit 1
fi
if [[ -z "$model_path" ]]; then
  echo "ERROR: VLLM_ENGINE_MODEL_PATH or MODEL_ID must be set." >&2
  echo "Put model/topology choices in VLLM_ENGINE_ENV_FILE profiles or a local .env." >&2
  exit 1
fi
if [[ -z "$served_model_name" ]]; then
  served_model_name="$(basename "$model_path")"
fi

# DeepSeek-V4 DSpark and legacy MTP are different draft architectures.  A
# DSpark checkpoint carries multiple mtp.<stage> blocks plus dspark metadata;
# declaring it as method=mtp can appear to start but loads those weights into
# the wrong model.  Fail before reserving NPUs when a local checkpoint makes
# this mismatch observable.  DSpark-capable runtimes should use method=dspark.
if [[ -f "$model_path/config.json" && -n "${VLLM_ENGINE_EXTRA_ARGS_JSON:-}" ]]; then
  dspark_mtp_mismatch=$(python3 - "$model_path/config.json" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    model_config = json.load(handle)

try:
    extra_args = json.loads(os.environ.get("VLLM_ENGINE_EXTRA_ARGS_JSON", "[]"))
except json.JSONDecodeError:
    print("false")
    raise SystemExit

spec_config = None
for index, item in enumerate(extra_args[:-1]):
    if item == "--speculative-config":
        try:
            spec_config = json.loads(extra_args[index + 1])
        except (TypeError, json.JSONDecodeError):
            pass
        break

is_dspark = any(
    key in model_config
    for key in ("dspark_block_size", "dspark_target_layer_ids", "dspark_markov_rank")
)
print(str(is_dspark and isinstance(spec_config, dict) and spec_config.get("method") == "mtp").lower())
PY
  )
  if [[ "$dspark_mtp_mismatch" == "true" ]]; then
    echo "ERROR: the selected checkpoint contains DeepSeek-V4 DSpark metadata but" >&2
    echo "VLLM_ENGINE_EXTRA_ARGS_JSON requests legacy method=mtp." >&2
    echo "Use a DSpark-capable Ascend runtime with method=dspark, or remove the" >&2
    echo "speculative config and serve the target model without draft decoding." >&2
    exit 1
  fi
fi

# Respect an explicitly configured scheduler budget.  Large-context models often
# need max_model_len > max_num_batched_tokens to keep warmup/compile shapes bounded;
# the previous implicit promotion made that tuning impossible and could trigger
# Ascend dynamic-shape compilation failures at the full context length.
if ! [[ "$max_num_batched_tokens" =~ ^[0-9]+$ ]] || (( max_num_batched_tokens < 1 )); then
  echo "ERROR: VLLM_ENGINE_MAX_NUM_BATCHED_TOKENS must be a positive integer (got '$max_num_batched_tokens')." >&2
  exit 1
fi

npu_devices="${VLLM_ENGINE_NPU_DEVICES:-${ASCEND_RT_VISIBLE_DEVICES:-}}"
if [[ -z "$npu_devices" ]]; then
  echo "ERROR: VLLM_ENGINE_NPU_DEVICES or ASCEND_RT_VISIBLE_DEVICES must be set." >&2
  echo "Select devices through the deployment profile; the launcher does not choose physical NPUs." >&2
  exit 1
fi
runtime_visible_devices="${VLLM_ENGINE_RUNTIME_VISIBLE_DEVICES:-$npu_devices}"
host_visible_devices="${VLLM_ENGINE_HOST_VISIBLE_NPU_DEVICES:-$npu_devices}"

docker_cmd=(docker)
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found on PATH." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  if sudo -n docker info >/dev/null 2>&1; then
    docker_cmd=(sudo docker)
  else
    echo "ERROR: cannot access Docker socket; configure docker access or passwordless sudo." >&2
    exit 1
  fi
fi

if [[ -n "$expected_image_id" ]]; then
  configured_image_id="$("${docker_cmd[@]}" image inspect --format '{{.Id}}' "$container_image" 2>/dev/null || true)"
  [[ -n "$configured_image_id" ]] || {
    echo "ERROR: locked image is not available locally: $container_image" >&2
    exit 1
  }
  [[ "$configured_image_id" == "$expected_image_id" ]] || {
    echo "ERROR: image identity mismatch for $container_image" >&2
    echo "expected: $expected_image_id" >&2
    echo "actual:   $configured_image_id" >&2
    exit 1
  }
fi

container_is_running() {
  [[ "$("${docker_cmd[@]}" inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" == "true" ]]
}

ensure_container_ready() {
  if [[ "$recreate_container" == "true" || "$recreate_container" == "1" ]]; then
    if "${docker_cmd[@]}" inspect "$container" >/dev/null 2>&1; then
      echo "[vllm-hust] recreating container '$container' via dev-hub launcher policy."
      "${docker_cmd[@]}" rm -f "$container" >/dev/null
    fi
  fi

  if container_is_running; then
    return 0
  fi

  if [[ "$auto_create_container" != "true" && "$auto_create_container" != "1" ]]; then
    if "${docker_cmd[@]}" inspect "$container" >/dev/null 2>&1; then
      echo "ERROR: Docker container '$container' exists but is not running." >&2
    else
      echo "ERROR: Docker container '$container' not found." >&2
    fi
    echo "Set VLLM_ENGINE_AUTO_CREATE_CONTAINER=true or start the container first." >&2
    exit 1
  fi

  if [[ ! -x "$repo_root/scripts/ascend-official-container.sh" ]]; then
    echo "ERROR: container auto-bootstrap requires scripts/ascend-official-container.sh." >&2
    exit 1
  fi

  echo "[vllm-hust] container '$container' is absent or stopped; bootstrapping via dev-hub container manager."
  echo "[vllm-hust] image             = ${container_image:-auto-detect official Ascend image}"
  VLLM_ENGINE_CONTAINER_NAME="$container" \
  IMAGE="$container_image" \
  VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE="$container_non_interactive" \
  SHM_SIZE="$container_shm_size" \
  ASCEND_RT_VISIBLE_DEVICES="$host_visible_devices" \
  ASCEND_VISIBLE_DEVICES="$host_visible_devices" \
    "$repo_root/scripts/ascend-official-container.sh" start

  if ! container_is_running; then
    echo "ERROR: Docker container '$container' is still not running after bootstrap." >&2
    exit 1
  fi
}

ensure_container_ready

if [[ -n "$expected_image_id" ]]; then
  running_image_id="$("${docker_cmd[@]}" inspect --format '{{.Image}}' "$container")"
  [[ "$running_image_id" == "$expected_image_id" ]] || {
    echo "ERROR: container $container runs $running_image_id, expected $expected_image_id" >&2
    exit 1
  }
fi

echo "[vllm-hust] container        = $container"
echo "[vllm-hust] image            = ${container_image:-auto-detect official Ascend image}"
echo "[vllm-hust] container_shm    = $container_shm_size"
echo "[vllm-hust] model_path       = $model_path"
echo "[vllm-hust] served_model_name = $served_model_name"
echo "[vllm-hust] host:port         = $host:$port"
echo "[vllm-hust] tp_size           = $tp_size"
echo "[vllm-hust] npu_devices       = $npu_devices"
echo "[vllm-hust] runtime_devices   = $runtime_visible_devices"
echo "[vllm-hust] max_model_len     = $max_model_len"
echo "[vllm-hust] max_num_seqs      = $max_num_seqs"
echo "[vllm-hust] prefix_cache      = $enable_prefix_caching"
echo "[vllm-hust] prefix_required   = $require_prefix_caching"
echo "[vllm-hust] chunked_prefill   = $enable_chunked_prefill"
echo "[vllm-hust] graph_mode        = $([[ "$enforce_eager" == "1" ]] && echo "OFF (--enforce-eager)" || echo "ON")"
if [[ -n "$compilation_config" ]]; then
  echo "[vllm-hust] compilation_config = set"
fi
echo "[vllm-hust] plugins          = $plugins"
if [[ -n "$vllm_compat_version" ]]; then
  echo "[vllm-hust] vllm_compat      = $vllm_compat_version"
fi

if [[ "$replace_existing" == "true" ]]; then
cleanup_script='
port="$1"
all=""
for _ in 1 2 3; do
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
  if [ -z "$matches" ]; then
    continue
  fi
  all="$all $matches"
  kill $matches 2>/dev/null || true
  sleep 2
  kill -9 $matches 2>/dev/null || true
done
if [ -n "$all" ]; then
  echo "$all"
fi
'
  cleaned_pids=$("${docker_cmd[@]}" exec --env "VLLM_ENGINE_AGGRESSIVE_CLEANUP=${VLLM_ENGINE_AGGRESSIVE_CLEANUP:-0}" "$container" sh -c "$cleanup_script" sh "$port" 2>/dev/null || true)
  if [[ -n "$cleaned_pids" ]]; then
    echo "[vllm-hust] stopped existing vLLM process(es) on port $port: $cleaned_pids"
  fi
fi

inner_script=$(cat <<'BASH'
set -euo pipefail

__EXTRA_ENV_EXPORTS__

CONTAINER_LOG_FILE="__CONTAINER_LOG_FILE__"
if [[ -n "$CONTAINER_LOG_FILE" ]]; then
  mkdir -p "$(dirname "$CONTAINER_LOG_FILE")"
  exec > >(sed -E 's/sk-[A-Za-z0-9._-]+/<redacted>/g; s/(api-key[ =])[^ ]+/\1<redacted>/Ig; s/(Bearer )[A-Za-z0-9._~+\/-]+/\1<redacted>/g; s/([A-Za-z_]*(KEY|TOKEN|SECRET)[A-Za-z_]*=)[^ ]+/\1<redacted>/g' | tee -a "$CONTAINER_LOG_FILE") 2>&1
fi

CONDA_ENV="__CONDA_ENV__"
CONDA_PREFIX_OVERRIDE="__CONDA_PREFIX__"
ENGINE_PYTHON="__ENGINE_PYTHON__"
ENGINE_PYTHON_OVERRIDE="$ENGINE_PYTHON"
OPTIMIZATION_REPO="__OPTIMIZATION_REPO__"
OPTIMIZATION_PLUGIN="__OPTIMIZATION_PLUGIN__"
OPTIMIZATION_ENTRYPOINT_GROUP="__OPTIMIZATION_ENTRYPOINT_GROUP__"
OPTIMIZATION_AUTO_INSTALL="__OPTIMIZATION_AUTO_INSTALL__"
OPTIMIZATION_INSTALL_TARGET="__OPTIMIZATION_INSTALL_TARGET__"
OPTIMIZATION_INSTALL_DIR=""
cleanup_optimization_install() {
  if [[ -n "$OPTIMIZATION_INSTALL_DIR" ]]; then
    rm -rf -- "$OPTIMIZATION_INSTALL_DIR"
  fi
}
trap cleanup_optimization_install EXIT
if [[ -n "$CONDA_PREFIX_OVERRIDE" ]]; then
  export CONDA_PREFIX="$CONDA_PREFIX_OVERRIDE"
  export PATH="$CONDA_PREFIX/bin:$PATH"
  export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
elif [[ -n "$CONDA_ENV" && -f /root/miniconda3/etc/profile.d/conda.sh ]]; then
  source /root/miniconda3/etc/profile.d/conda.sh
  conda activate "$CONDA_ENV"
elif [[ -n "$CONDA_ENV" && -f /opt/conda/etc/profile.d/conda.sh ]]; then
  source /opt/conda/etc/profile.d/conda.sh
  conda activate "$CONDA_ENV"
elif [[ -n "${CONDA_PREFIX:-}" ]]; then
  echo "[container] conda already active: $CONDA_PREFIX"
else
  echo "[container] using the official image's native Python/CANN runtime"
fi
if [[ -n "$ENGINE_PYTHON" ]]; then
  if [[ ! -x "$ENGINE_PYTHON" ]]; then
    echo "ERROR: VLLM_ENGINE_PYTHON is not executable in the container: $ENGINE_PYTHON" >&2
    exit 1
  fi
else
  ENGINE_PYTHON="$(command -v python3)"
fi

optimization_plugin_installed() {
  "$ENGINE_PYTHON" - "$OPTIMIZATION_ENTRYPOINT_GROUP" "$OPTIMIZATION_PLUGIN" <<'PY'
__OPTIMIZATION_ENTRYPOINT_PROBE__
PY
}

if [[ -n "$OPTIMIZATION_REPO" || -n "$OPTIMIZATION_PLUGIN" ]]; then
  if [[ -z "$OPTIMIZATION_REPO" || -z "$OPTIMIZATION_PLUGIN" ]]; then
    echo "ERROR: VLLM_OPTIMIZATION_REPO_CONTAINER and VLLM_OPTIMIZATION_PLUGIN must be set together." >&2
    exit 1
  fi
  if [[ ! -d "$OPTIMIZATION_REPO" ]]; then
    echo "ERROR: optimization repository is not mounted in the container: $OPTIMIZATION_REPO" >&2
    exit 1
  fi
  OPTIMIZATION_INSTALL_DIR="$(
    "$ENGINE_PYTHON" - \
      --repo "$OPTIMIZATION_REPO" \
      --group "$OPTIMIZATION_ENTRYPOINT_GROUP" \
      --name "$OPTIMIZATION_PLUGIN" \
      --auto-install "$OPTIMIZATION_AUTO_INSTALL" \
      --target "$OPTIMIZATION_INSTALL_TARGET" <<'PY'
__OPTIMIZATION_INSTALLER__
PY
  )"
  if [[ -n "$OPTIMIZATION_INSTALL_DIR" ]]; then
    export PYTHONPATH="$OPTIMIZATION_INSTALL_DIR:${PYTHONPATH:-}"
    echo "[container] installed optimization plugin with $ENGINE_PYTHON into isolated target $OPTIMIZATION_INSTALL_DIR"
  fi
  if ! optimization_plugin_installed; then
    echo "ERROR: optimization installation did not register $OPTIMIZATION_ENTRYPOINT_GROUP:$OPTIMIZATION_PLUGIN" >&2
    exit 1
  fi
  echo "[container] verified optimization entry point: $OPTIMIZATION_ENTRYPOINT_GROUP:$OPTIMIZATION_PLUGIN"
fi

if [[ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]]; then
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
fi

if [[ -n "__CONTAINER_LD_PRELOAD__" ]]; then
  export LD_PRELOAD="__CONTAINER_LD_PRELOAD__"
fi

if [[ -n "${HUST_ATB_SET_ENV:-}" && -f "${HUST_ATB_SET_ENV}" ]]; then
  set +u
  source "${HUST_ATB_SET_ENV}" --cxx_abi=1
  set -u
elif [[ -f /usr/local/Ascend/nnal/atb/set_env.sh ]]; then
  set +u
  source /usr/local/Ascend/nnal/atb/set_env.sh --cxx_abi=1
  set -u
fi

export VLLM_TARGET_DEVICE="__TARGET_DEVICE__"
export ASCEND_RT_VISIBLE_DEVICES="__NPU_DEVICES__"
export ASCEND_VISIBLE_DEVICES="__NPU_DEVICES__"
export TORCH_DEVICE_BACKEND_AUTOLOAD="${TORCH_DEVICE_BACKEND_AUTOLOAD:-1}"
if [[ -n "${HCCL_OP_EXPANSION_MODE:-}" ]]; then
  export HCCL_OP_EXPANSION_MODE
fi
export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}"
export VLLM_PLUGINS="${VLLM_PLUGINS:-__PLUGINS__}"
unset VLLM_ASCEND_ENABLE_FLASHCOMM1 VLLM_ASCEND_ENABLE_FUSED_MC2
if [[ "__ENABLE_LEGACY_ASCEND_ENV__" == "1" ]]; then
  [[ -n "__FLASHCOMM1__" ]] && export VLLM_ASCEND_ENABLE_FLASHCOMM1="__FLASHCOMM1__"
  [[ -n "__FUSED_MC2__" ]] && export VLLM_ASCEND_ENABLE_FUSED_MC2="__FUSED_MC2__"
fi
export VLLM_ASCEND_TORCH_PREFLIGHT="${VLLM_ASCEND_TORCH_PREFLIGHT:-0}"
export COMPILE_CUSTOM_KERNELS="${COMPILE_CUSTOM_KERNELS:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
requested_pythonpath="__PYTHONPATH__"
inherited_pythonpath="${PYTHONPATH:-}"
if [[ "${VLLM_ENGINE_INHERIT_PYTHONPATH:-0}" == "1" ]]; then
  export PYTHONPATH="$requested_pythonpath${inherited_pythonpath:+:$inherited_pythonpath}"
else
  # Ascend's set_env.sh contributes required CANN Python directories, but some
  # images also inject an old vLLM/vllm-ascend checkout. Preserve runtime-only
  # entries while rejecting any undeclared engine/plugin source tree.
  export PYTHONPATH="$("$ENGINE_PYTHON" - "$requested_pythonpath" "$inherited_pythonpath" <<'PY'
import pathlib
import sys

requested, inherited = sys.argv[1:3]
entries: list[str] = []


def append(entry: str, *, reject_engine_sources: bool) -> None:
    if not entry or entry in entries:
        return
    path = pathlib.Path(entry)
    if reject_engine_sources and any(
        (path / package / "__init__.py").is_file()
        for package in ("vllm", "vllm_ascend")
    ):
        return
    entries.append(entry)


for entry in requested.split(":"):
    append(entry, reject_engine_sources=False)
for entry in inherited.split(":"):
    append(entry, reject_engine_sources=True)
print(":".join(entries))
PY
)"
fi
if [[ -n "__VLLM_VERSION__" ]]; then
  export VLLM_VERSION="__VLLM_VERSION__"
fi

repair_editable_imports() {
  local workspace_root="$1"
  local site_roots
  local root
  local finder_file

  if [[ -z "$workspace_root" ]]; then
    workspace_root="/workspace"
  fi
  site_roots="$("$ENGINE_PYTHON" - <<'PY'
import site
for path in site.getsitepackages():
    if "site-packages" in path:
        print(path)
PY
)"

  for root in $site_roots; do
    for finder_file in "$root"/__editable___vllm*_finder.py; do
      [[ -f "$finder_file" ]] || continue
      "$ENGINE_PYTHON" - "$finder_file" "$workspace_root" <<'PY'
import pathlib
import sys

finder_file = pathlib.Path(sys.argv[1])
workspace_root = sys.argv[2].rstrip("/")
text = finder_file.read_text()
text = text.replace(
    "/vllm-workspace/vllm/vllm", f"{workspace_root}/vllm-hust/vllm"
)
text = text.replace(
    "/vllm-workspace/vllm-ascend/vllm_ascend",
    f"{workspace_root}/vllm-ascend-hust/vllm_ascend",
)
finder_file.write_text(text)
PY
    done
  done
}

repair_editable_imports "__CONTAINER_WORKSPACE_ROOT__"

if [[ "${VLLM_ENGINE_DISCOVER_TORCH_LIBS:-0}" == "1" ]]; then
  torch_lib="$("$ENGINE_PYTHON" -c 'import os, torch; print(os.path.join(os.path.dirname(torch.__file__), "lib"))' 2>/dev/null || true)"
  torch_npu_lib="$("$ENGINE_PYTHON" -c 'import os, torch_npu; print(os.path.join(os.path.dirname(torch_npu.__file__), "lib"))' 2>/dev/null || true)"
  if [[ -n "$torch_lib" || -n "$torch_npu_lib" ]]; then
    export LD_LIBRARY_PATH="${torch_lib:-}:${torch_npu_lib:-}:${LD_LIBRARY_PATH:-}"
  fi
fi

if [[ "${VLLM_ASCEND_TORCH_PREFLIGHT:-0}" == "1" ]]; then
  "$ENGINE_PYTHON" - <<'PY'
import torch
import torch_npu  # noqa: F401

print("[container] torch:", torch.__file__)
print("[container] torch_npu:", torch_npu.__file__)
print("[container] torch.npu.is_available:", torch.npu.is_available())
torch.npu.set_device("npu:0")
probe = torch.zeros(1, device="npu:0")
print("[container] torch_npu_preflight: ok shape=%s device=%s" % (tuple(probe.shape), probe.device))
PY
fi

export HOME="${VLLM_ENGINE_CONTAINER_HOME:-/tmp/vllm-hust-home}"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export VLLM_CACHE_ROOT="$HOME/.cache/vllm/__CACHE_NAMESPACE__"
export VLLM_CONFIG_ROOT="$HOME/.config/vllm"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$VLLM_CACHE_ROOT" "$VLLM_CONFIG_ROOT"
echo "[container] compile cache namespace: __CACHE_NAMESPACE__"

VLLM_BIN="__VLLM_BIN__"
VLLM_SCRIPT="__VLLM_SCRIPT__"
if [[ -n "$VLLM_SCRIPT" ]]; then
  if [[ -x "$VLLM_BIN" ]]; then
    :
  elif command -v "$VLLM_BIN" >/dev/null 2>&1; then
    VLLM_BIN="$(command -v "$VLLM_BIN")"
  fi
  if [[ ! -x "$VLLM_BIN" ]]; then
    echo "ERROR: VLLM_ENGINE_BIN is not executable in the container: $VLLM_BIN" >&2
    exit 1
  fi
  if [[ ! -f "$VLLM_SCRIPT" ]]; then
    echo "ERROR: VLLM_ENGINE_SCRIPT does not exist in the container: $VLLM_SCRIPT" >&2
    exit 1
  fi
  echo "[container] using vLLM launcher: $VLLM_BIN $VLLM_SCRIPT"
elif [[ -n "$ENGINE_PYTHON_OVERRIDE" ]]; then
  VLLM_BIN="$(dirname "$ENGINE_PYTHON")/vllm"
  if [[ ! -f "$VLLM_BIN" ]]; then
    echo "ERROR: expected vLLM script next to VLLM_ENGINE_PYTHON, but not found: $VLLM_BIN" >&2
    exit 1
  fi
  echo "[container] using vLLM binary: $VLLM_BIN"
else
  if command -v "$VLLM_BIN" >/dev/null 2>&1; then
    VLLM_BIN="$(command -v "$VLLM_BIN")"
  else
    VLLM_BIN="$(command -v vllm-hust 2>/dev/null || command -v vllm 2>/dev/null || true)"
  fi
  if [[ -z "$VLLM_BIN" ]]; then
    echo "ERROR: neither requested vLLM binary nor vllm-hust/vllm found in container PATH" >&2
    exit 1
  fi
  echo "[container] using vLLM binary: $VLLM_BIN"
fi
echo "[container] python: $ENGINE_PYTHON"
"$ENGINE_PYTHON" - <<'PY'
import importlib
import importlib.metadata
import json
import os
import pathlib

pythonpath = [
    pathlib.Path(entry).resolve()
    for entry in os.environ.get("PYTHONPATH", "").split(":")
    if entry
]
try:
    installed_contract = json.loads(
        os.environ.get("VLLM_ENGINE_INSTALLED_MODULES_JSON", "{}")
    )
except json.JSONDecodeError as exc:
    raise SystemExit(
        f"ERROR: invalid VLLM_ENGINE_INSTALLED_MODULES_JSON: {exc}"
    ) from exc
if not isinstance(installed_contract, dict):
    raise SystemExit("ERROR: VLLM_ENGINE_INSTALLED_MODULES_JSON must be an object")

for module_name in ("vllm", "vllm_ascend"):
    expected_root = next(
        (
            root
            for root in pythonpath
            if (root / module_name / "__init__.py").is_file()
        ),
        None,
    )
    module = importlib.import_module(module_name)
    origin = pathlib.Path(module.__file__).resolve()
    if expected_root is not None:
        if not origin.is_relative_to(expected_root):
            raise SystemExit(
                f"ERROR: {module_name} imported from {origin}, expected {expected_root}"
            )
        print(f"[container] {module_name}: {origin} (declared source)")
        continue

    contract = installed_contract.get(module_name)
    if not isinstance(contract, dict):
        raise SystemExit(
            f"ERROR: {module_name} has no declared source root in PYTHONPATH "
            "and no installed-distribution contract"
        )
    distribution_name = contract.get("distribution")
    expected_version = contract.get("version")
    if not isinstance(distribution_name, str) or not distribution_name:
        raise SystemExit(
            f"ERROR: installed contract for {module_name} needs distribution"
        )
    if not isinstance(expected_version, str) or not expected_version:
        raise SystemExit(
            f"ERROR: installed contract for {module_name} needs exact version"
        )
    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise SystemExit(
            f"ERROR: installed distribution {distribution_name} for {module_name} not found"
        ) from exc
    actual_version = distribution.version
    if actual_version != expected_version:
        raise SystemExit(
            f"ERROR: installed distribution {distribution_name} version "
            f"{actual_version}, expected {expected_version}"
        )
    distribution_root = pathlib.Path(distribution.locate_file("")).resolve()
    try:
        relative_origin = origin.relative_to(distribution_root)
    except ValueError as exc:
        raise SystemExit(
            f"ERROR: {module_name} imported from {origin}, outside installed "
            f"distribution root {distribution_root}"
        ) from exc
    distribution_files = {
        pathlib.PurePosixPath(str(item)) for item in (distribution.files or ())
    }
    if pathlib.PurePosixPath(relative_origin.as_posix()) not in distribution_files:
        raise SystemExit(
            f"ERROR: {module_name} origin {relative_origin} is not owned by "
            f"installed distribution {distribution_name}"
        )
    print(
        f"[container] {module_name}: {origin} "
        f"(installed {distribution_name}=={actual_version})"
    )
PY
# The contract belongs to the launcher preflight, not to vLLM itself. Avoid
# leaking launcher-only variables into vLLM's environment validator.
unset VLLM_ENGINE_INSTALLED_MODULES_JSON

if [[ -n "$VLLM_SCRIPT" ]]; then
  args=("$VLLM_BIN" "$VLLM_SCRIPT")
elif [[ -n "$ENGINE_PYTHON_OVERRIDE" ]]; then
  args=("$ENGINE_PYTHON" "$VLLM_BIN")
else
  args=("$VLLM_BIN")
fi
args+=(
  serve "__MODEL_PATH__"
  --served-model-name "__SERVED_MODEL_NAME__"
  --host "__HOST__"
  --port "__PORT__"
  --tensor-parallel-size "__TP_SIZE__"
  --max-model-len "__MAX_MODEL_LEN__"
  --max-num-batched-tokens "__MAX_NUM_BATCHED_TOKENS__"
  --gpu-memory-utilization "__GPU_MEM_UTIL__"
  --dtype "__DTYPE__"
  --load-format "__LOAD_FORMAT__"
  --trust-remote-code
  --max-num-seqs "__MAX_NUM_SEQS__"
)

[[ -n "__KV_CACHE_DTYPE__" ]] && args+=(--kv-cache-dtype "__KV_CACHE_DTYPE__")
[[ -n "__KV_CACHE_MEMORY_BYTES__" ]] && args+=(--kv-cache-memory-bytes "__KV_CACHE_MEMORY_BYTES__")

if [[ "__ENABLE_PREFIX_CACHING__" == "1" ]]; then
  args+=(--enable-prefix-caching)
else
  args+=(--no-enable-prefix-caching)
fi
if [[ "__ENABLE_CHUNKED_PREFILL__" == "1" ]]; then
  args+=(--enable-chunked-prefill)
else
  args+=(--no-enable-chunked-prefill)
fi
[[ "__ENFORCE_EAGER__" == "1" ]] && args+=(--enforce-eager)
[[ "__EXPERT_PARALLEL__" == "1" ]] && args+=(--enable-expert-parallel)
[[ -n "__QUANTIZATION__" ]] && args+=(--quantization "__QUANTIZATION__")
[[ -n "${VLLM_ENGINE_COMPILATION_CONFIG:-}" ]] && args+=(--compilation-config "$VLLM_ENGINE_COMPILATION_CONFIG")
if [[ -n "${VLLM_ENGINE_EXTRA_ARGS_JSON:-}" ]]; then
  mapfile -t extra_args < <("$ENGINE_PYTHON" -S - <<'PY'
import json
import os
import sys

raw = os.environ.get("VLLM_ENGINE_EXTRA_ARGS_JSON", "")
try:
    args = json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"invalid VLLM_ENGINE_EXTRA_ARGS_JSON: {exc}") from exc
if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
    raise SystemExit("VLLM_ENGINE_EXTRA_ARGS_JSON must be a JSON list of strings")
for item in args:
    print(item)
PY
  )
  args+=("${extra_args[@]}")
fi

engine_pid=""
forward_engine_signal() {
  local signal="$1"
  if [[ -n "$engine_pid" ]]; then
    kill "-$signal" -- "-$engine_pid" 2>/dev/null || true
  fi
}
trap 'forward_engine_signal TERM' TERM
trap 'forward_engine_signal INT' INT

setsid "${args[@]}" &
engine_pid=$!
set +e
wait "$engine_pid"
engine_rc=$?
set -e
if [[ "$engine_rc" -ne 0 ]]; then
  kill -TERM -- "-$engine_pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$engine_pid" 2>/dev/null || true
fi
exit "$engine_rc"
BASH
)

replace() {
  local needle="$1"
  local value="$2"
  inner_script="${inner_script//"$needle"/"$value"}"
}

replace "__CONDA_ENV__" "$conda_env"
replace "__CONDA_PREFIX__" "$conda_prefix"
replace "__ENGINE_PYTHON__" "$engine_python"
replace "__OPTIMIZATION_REPO__" "$optimization_repo_container"
replace "__OPTIMIZATION_PLUGIN__" "$optimization_plugin"
replace "__OPTIMIZATION_ENTRYPOINT_GROUP__" "$optimization_entrypoint_group"
replace "__OPTIMIZATION_AUTO_INSTALL__" "$optimization_auto_install"
replace "__OPTIMIZATION_ENTRYPOINT_PROBE__" "$optimization_entrypoint_probe"
replace "__OPTIMIZATION_INSTALLER__" "$optimization_installer"
replace "__EXTRA_ENV_EXPORTS__" "$extra_env_exports"
replace "__CONTAINER_LOG_FILE__" "$container_log_file"
replace "__CONTAINER_LD_PRELOAD__" "$container_ld_preload"
replace "__TARGET_DEVICE__" "$target_device"
replace "__NPU_DEVICES__" "$runtime_visible_devices"
replace "__PLUGINS__" "$plugins"
replace "__ENABLE_LEGACY_ASCEND_ENV__" "$legacy_ascend_env"
replace "__FLASHCOMM1__" "$flashcomm1"
replace "__FUSED_MC2__" "$fused_mc2"
replace "__PYTHONPATH__" "$pythonpath"
replace "__CONTAINER_WORKSPACE_ROOT__" "$container_workspace_root"
replace "__VLLM_VERSION__" "$vllm_compat_version"
replace "__CACHE_NAMESPACE__" "$cache_namespace"
replace "__VLLM_BIN__" "$vllm_bin"
replace "__VLLM_SCRIPT__" "$vllm_script"
replace "__MODEL_PATH__" "$model_path"
replace "__SERVED_MODEL_NAME__" "$served_model_name"
replace "__HOST__" "$host"
replace "__PORT__" "$port"
replace "__TP_SIZE__" "$tp_size"
replace "__MAX_MODEL_LEN__" "$max_model_len"
replace "__MAX_NUM_BATCHED_TOKENS__" "$max_num_batched_tokens"
replace "__GPU_MEM_UTIL__" "$gpu_mem_util"
replace "__DTYPE__" "$dtype"
replace "__KV_CACHE_DTYPE__" "$kv_cache_dtype"
replace "__KV_CACHE_MEMORY_BYTES__" "$kv_cache_memory_bytes"
replace "__LOAD_FORMAT__" "$load_format"
replace "__MAX_NUM_SEQS__" "$max_num_seqs"
replace "__ENABLE_PREFIX_CACHING__" "$enable_prefix_caching"
replace "__ENABLE_CHUNKED_PREFILL__" "$enable_chunked_prefill"
replace "__ENFORCE_EAGER__" "$enforce_eager"
replace "__EXPERT_PARALLEL__" "$expert_parallel"
replace "__QUANTIZATION__" "$quantization"

tmp_host_script="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/vllm-hust-engine.XXXXXX.sh")"
launch_id="$(basename "$tmp_host_script" .sh)"
optimization_install_target="/tmp/${launch_id}.optimization"
optimization_source_snapshot="/tmp/.${launch_id}.optimization.source"
replace "__OPTIMIZATION_INSTALL_TARGET__" "$optimization_install_target"
container_script=""
cleanup_container_launch() {
  [[ -n "$container_script" ]] || return 0
  "${docker_cmd[@]}" exec "$container" sh -c '
script="$1"
target="$2"
snapshot="$3"
port="$4"
self=$$
case "$script" in /tmp/vllm-hust-engine.*.sh) ;; *) exit 64 ;; esac
case "$target" in /tmp/vllm-hust-engine.*.optimization) ;; *) exit 64 ;; esac
case "$snapshot" in /tmp/.vllm-hust-engine.*.optimization.source) ;; *) exit 64 ;; esac

pids="$(ps -eo pid=,args= | awk -v self="$self" -v script="$script" -v target="$target" -v port="$port" '\''
  $1 != self && (index($0, script) || index($0, target) ||
    ($0 ~ /vllm/ && $0 ~ / serve / &&
      ($0 ~ ("--port " port) || $0 ~ ("--port=" port)))) { print $1 }
'\'')"
for _ in 1 2 3 4 5; do
  descendants=""
  for parent in $pids; do
    children="$(ps -eo pid=,ppid= | awk -v parent="$parent" '\''$2 == parent { print $1 }'\'')"
    descendants="$descendants $children"
  done
  pids="$pids $descendants"
done
if [ -n "$pids" ]; then
  kill $pids 2>/dev/null || true
  sleep 1
  kill -9 $pids 2>/dev/null || true
fi
rm -rf -- "$script" "$target" "$snapshot"
' sh "$container_script" "$optimization_install_target" \
    "$optimization_source_snapshot" "$port" >/dev/null 2>&1 || true
}
cleanup() {
  rm -f "$tmp_host_script"
  cleanup_container_launch
}
trap cleanup EXIT

printf '#!/usr/bin/env bash\n%s\n' "$inner_script" > "$tmp_host_script"
chmod +x "$tmp_host_script"

container_script="/tmp/$(basename "$tmp_host_script")"
"${docker_cmd[@]}" cp "$tmp_host_script" "$container:$container_script"

# vLLM natively supports VLLM_API_KEY. Keep the credential out of the generated
# script and process argv: passing only the variable name asks Docker to copy the
# value from this launcher's environment without exposing it in `ps` or status.
export VLLM_API_KEY="$api_key"
set +e
"${docker_cmd[@]}" exec \
  --env VLLM_API_KEY \
  --env "VLLM_TARGET_DEVICE=$target_device" \
  --env "ASCEND_RT_VISIBLE_DEVICES=$runtime_visible_devices" \
  --env "ASCEND_VISIBLE_DEVICES=$runtime_visible_devices" \
  --env "VLLM_ENGINE_COMPILATION_CONFIG=$compilation_config" \
  --env "VLLM_ENGINE_EXTRA_ARGS_JSON=${VLLM_ENGINE_EXTRA_ARGS_JSON:-}" \
  --env "VLLM_USE_SIMPLE_KV_OFFLOAD=$simple_kv_offload" \
  "$container" bash "$container_script"
engine_rc=$?
set -e

exit "$engine_rc"
