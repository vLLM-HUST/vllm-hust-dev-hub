#!/usr/bin/env bash
# manage-container.sh — 容器内 vLLM-HUST 服务管理器
#
# 等价于 manage.sh 的"容器内直跑"版本：不依赖 docker / systemd，
# 直接 conda activate + source ascend env + exec vllm serve。
#
# 用法：
#   bash scripts/manage-container.sh <action> [flags]
#
# v0.2 覆盖的 action：start | stop | restart | status | health | logs |
#                     config | foreground | profile --kind {engine|torch|msprof}
#   计划内未做（v0.2）：benchmark (P2)

set -euo pipefail
IFS=$'\n\t'

VERSION="0.2.0"
SCRIPT_NAME="manage-container.sh"
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

# ===== 内置默认值 =====
DEFAULT_LOG_DIR="/tmp/vllm-hust-manager"
DEFAULT_CONDA_ENV="vllm-hust-dev"
DEFAULT_ASCEND_TOOLKIT="/usr/local/Ascend/ascend-toolkit/set_env.sh"
DEFAULT_ATB_SET_ENV="/usr/local/Ascend/nnal/atb/set_env.sh"
DEFAULT_MINICONDA="/root/miniconda3/etc/profile.d/conda.sh"
DEFAULT_MODEL_PATH="/root/.cache/huggingface/hub/Qwen2.5-0.5B-Instruct"
DEFAULT_SERVED_MODEL_NAME="qwen2.5-0.5b"
DEFAULT_HOST="0.0.0.0"
DEFAULT_PORT=8001
DEFAULT_TP_SIZE=1
DEFAULT_NPU_DEVICES="0"
DEFAULT_MAX_MODEL_LEN=4096
DEFAULT_MAX_NUM_BATCHED_TOKENS=4096
DEFAULT_MAX_NUM_SEQS=8
DEFAULT_GPU_MEM_UTIL="0.85"
DEFAULT_DTYPE="bfloat16"
DEFAULT_LOAD_FORMAT="auto"
DEFAULT_PREFIX_CACHING="1"
DEFAULT_REQUIRE_PREFIX_CACHING="0"
DEFAULT_CHUNKED_PREFILL="1"
DEFAULT_ENFORCE_EAGER="1"
DEFAULT_PLUGINS="ascend"
DEFAULT_AUTOSTART="1"
DEFAULT_PROFILE_KIND="engine"
DEFAULT_PROFILE_DURATION=30
DEFAULT_PROFILE_INTERVAL=2
# torch profiler (P4)
DEFAULT_PROFILE_TORCH_REQUESTS=8
DEFAULT_PROFILE_TORCH_WITH_STACK=1
DEFAULT_PROFILE_TORCH_KEEP=0
# msprof (P5)
DEFAULT_PROFILE_MSPROF_DURATION=30
DEFAULT_PROFILE_MSPROF_REQUESTS=30
DEFAULT_PROFILE_MSPROF_AIC_METRICS="ArithmeticUtilization|PipeUtilization|Memory|L2Cache"  # msprof 单值，但脚本会按 | 拆开重复 --aic-metrics=...
DEFAULT_PROFILE_MSPROF_TASK_MEMORY="off"
DEFAULT_PROFILE_MSPROF_SYS_PROFILING="off"
# 默认 msprof 二进制路径（按 cann-9.0.0 推断；找不到时 profile_msprof 会再探测）
DEFAULT_PROFILE_MSPROF_BIN="/usr/local/Ascend/cann-9.0.0/bin/msprof"
# benchmark
DEFAULT_BENCH_NUM_PROMPTS=200
DEFAULT_BENCH_CONCURRENCY=8
DEFAULT_BENCH_RATE="inf"
DEFAULT_BENCH_INPUT_LEN=128
DEFAULT_BENCH_OUTPUT_LEN=64
DEFAULT_BENCH_DATASET="random"
DEFAULT_BENCH_DATASET_PATH=""
DEFAULT_BENCH_BACKEND="vllm"

# traffic generator (P6: bench backend)
DEFAULT_TRAFFIC_BACKEND="urllib"
DEFAULT_TRAFFIC_INPUT_LEN=128
DEFAULT_TRAFFIC_DATASET="random"
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

# ===== 颜色 =====
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
  C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[0;33m'
  C_BLU=$'\033[0;34m'; C_DIM=$'\033[0;2m';  C_RST=$'\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_BLU=''; C_DIM=''; C_RST=''
fi

log_info()  { echo -e "${C_BLU}[$(date +%H:%M:%S)]${C_RST} $*" | tee -a "${MANAGER_LOG_FILE:-/dev/null}" >&2; }
log_ok()    { echo -e "${C_GRN}[$(date +%H:%M:%S)]${C_RST} $*" | tee -a "${MANAGER_LOG_FILE:-/dev/null}" >&2; }
log_warn()  { echo -e "${C_YEL}[$(date +%H:%M:%S)]${C_RST} $*" | tee -a "${MANAGER_LOG_FILE:-/dev/null}" >&2; }
log_err()   { echo -e "${C_RED}[$(date +%H:%M:%S)]${C_RST} $*" | tee -a "${MANAGER_LOG_FILE:-/dev/null}" >&2; }
log_dim()   { echo -e "${C_DIM}[$(date +%H:%M:%S)]${C_RST} $*" | tee -a "${MANAGER_LOG_FILE:-/dev/null}" >&2; }

# ===== 用法 =====
usage() {
  cat <<EOF
$SCRIPT_NAME v$VERSION — 容器内 vLLM-HUST 服务管理器

Usage: bash $SCRIPT_NAME <action> [flags]

Actions (v0.2):
  start         后台启动 vllm serve（写 pid/log，自动等 /health）
  stop          优雅停（SIGTERM 10s → SIGKILL）
  restart       stop + start
  status        进程 / 端口 / 模型 / NPU 摘要
  health        探活 /health
  logs          tail -f 日志
  config        打印最终生效配置
  foreground    前台启动（调试用）
  profile --kind engine   周期性抓 /metrics（Prometheus 快照）
  profile --kind torch    vllm 内置 PyTorch profiler（*.pt.trace.json.gz）
  profile --kind msprof   CANN msprof（kernel 级，PROF_*/ 目录，自动 TraceLoom 分析）
  benchmark      在线服务基准测试（vllm bench serve 封装）
  help          显示本帮助

Common flags:
  --profile <path>          profile 文件路径（覆盖 \$VLLM_ENGINE_ENV_FILE）
  --config KEY=VALUE        单点覆盖配置（可重复）
  --json                    status / health / config 输出 JSON
  --no-color                关闭颜色
  -h, --help                显示帮助

profile --kind torch/msprof 额外 flags:
  --label <text>            标签（输出目录名后缀）
  --requests N              期间发的 chat 请求数
  --duration <sec>          msprof 采集时长（默认 30s；torch 不需要）
  --interval <sec>          engine 抓取间隔
  --no-autostart            引擎没起时不要自动 start
  --keep-engine-running     torch：测完不自动恢复原 engine
  --with-stack / --no-stack torch：是否带 stack trace
  --aic-metrics <list>      msprof：--aic-metrics 参数
  --task-memory on|off      msprof：--task-memory 参数
  --sys-profiling on|off    msprof：--sys-profiling 参数
  --msprof-bin <path>       msprof 可执行文件路径

benchmark flags:
  --label <text>            标签（输出目录名后缀）
  --num-prompts N           请求数（默认 200）
  --concurrency C           最大并发数（默认 8）
  --rate R                  请求速率，inf=全速（默认 inf）
  --input-len N             prompt 输入长度（仅 random 数据集，默认 128）
  --output-len N            输出 token 数（默认 64）
  --dataset <d>             random|sonnet|sharegpt（默认 random）
  --dataset-path <p>        sonnet/sharegpt 数据集本地路径
  --backend <b>             vllm（默认 vllm）

Examples:
  VLLM_HUST_API_KEY=testkey123 \\
    bash $SCRIPT_NAME start --profile profiles/inplace-qwen2.5-0.5b-npu1.env

  bash $SCRIPT_NAME status --json
  bash $SCRIPT_NAME profile --kind engine --label smoke --duration 30
  bash $SCRIPT_NAME profile --kind torch  --label torch-smoke --requests 8
  bash $SCRIPT_NAME profile --kind msprof --label msprof-smoke --duration 30
  bash $SCRIPT_NAME benchmark --label bench-smoke --num-prompts 100 --concurrency 4
  bash $SCRIPT_NAME benchmark --label sharegpt-test --dataset sharegpt --dataset-path /data/sharegpt.jsonl --num-prompts 200 --rate 2
  bash $SCRIPT_NAME stop

EOF
}

# ===== 通用：.env 加载 =====
load_dotenv() {
  local f="$1" overwrite="${2:-false}"
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*export[[:space:]] ]] && line="${line#export }"
    local k="${line%%=*}"; k="${k// /}"
    [[ -z "$k" ]] && continue
    [[ "$overwrite" != "true" && -n "${!k:-}" ]] && continue
    [[ "$line" =~ ^[^=]+= ]] || continue
    export "$line" 2>/dev/null || true
  done < "$f"
}

# ===== CLI 解析 =====
parse_args() {
  ACTION=""
  PROFILE_FILE="${VLLM_ENGINE_ENV_FILE:-}"
  JSON_OUTPUT="false"
  CLI_OVERRIDES=()
  REST_ARGS=()
  HAS_HELP="false"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-color) NO_COLOR=1 ;;
      --json) JSON_OUTPUT="true" ;;
      --profile) PROFILE_FILE="$2"; shift ;;
      --config)
        [[ "$2" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || {
          log_err "bad --config '$2' (expect KEY=VALUE)"; exit 2; }
        CLI_OVERRIDES+=("${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"); shift ;;
      -h|--help) HAS_HELP="true"; REST_ARGS+=("$1") ;;
      start|stop|restart|status|health|logs|config|profile|benchmark|foreground|help)
        ACTION="$1" ;;
      *) REST_ARGS+=("$1") ;;
    esac
    shift
  done

  if [[ -z "$ACTION" ]]; then
    if [[ "$HAS_HELP" == "true" ]]; then
      usage; exit 0
    fi
    log_err "no action specified"
    usage >&2
    exit 1
  fi
}

# ===== 配置解析 =====
# 优先级：CLI --config > state.env（start 时落盘） > --profile > env > ./profiles/default.env > 内置默认
resolve_config() {
  # 0) Manager 级路径（先用默认值建 LOG_DIR，下面 state.env 路径依赖它）
  LOG_DIR="${VLLM_MANAGER_LOG_DIR:-$DEFAULT_LOG_DIR}"
  PID_FILE="${VLLM_MANAGER_PID_FILE:-$LOG_DIR/engine.pid}"
  LOG_FILE="${VLLM_MANAGER_LOG_FILE:-$LOG_DIR/engine.log}"
  MANAGER_LOG_FILE="$LOG_DIR/manager.log"
  STATE_FILE="${VLLM_MANAGER_STATE_FILE:-$LOG_DIR/state.env}"
  mkdir -p "$LOG_DIR"

  # 1) state.env（低优先级，仅 CLI --config 比它高）
  if [[ -f "$STATE_FILE" ]]; then
    load_dotenv "$STATE_FILE" true
  fi

  # 2) profile 加载（更低优先级；只有 state.env 没有时才用）
  if [[ -n "$PROFILE_FILE" ]]; then
    if [[ ! -f "$PROFILE_FILE" ]]; then
      log_err "profile file not found: $PROFILE_FILE"
      exit 1
    fi
    load_dotenv "$PROFILE_FILE" true
  fi

  # 3) CLI 覆盖（最高优先级；apply on top of state + profile + env）
  for kv in "${CLI_OVERRIDES[@]:-}"; do
    if [[ "$kv" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      export "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
    fi
  done

  # Manager 级（重读，因 CLI 可能覆盖）
  LOG_DIR="${VLLM_MANAGER_LOG_DIR:-$DEFAULT_LOG_DIR}"
  PID_FILE="${VLLM_MANAGER_PID_FILE:-$LOG_DIR/engine.pid}"
  LOG_FILE="${VLLM_MANAGER_LOG_FILE:-$LOG_DIR/engine.log}"
  MANAGER_LOG_FILE="$LOG_DIR/manager.log"
  STATE_FILE="${VLLM_MANAGER_STATE_FILE:-$LOG_DIR/state.env}"
  CONDA_ENV="${VLLM_MANAGER_CONDA_ENV:-$DEFAULT_CONDA_ENV}"
  ASCEND_TOOLKIT="${VLLM_MANAGER_ASCEND_TOOLKIT:-$DEFAULT_ASCEND_TOOLKIT}"
  ATB_SET_ENV="${VLLM_MANAGER_ATB_SET_ENV:-$DEFAULT_ATB_SET_ENV}"
  AUTOSTART="${VLLM_MANAGER_AUTOSTART:-$DEFAULT_AUTOSTART}"

  # Engine 级
  MODEL_PATH="${VLLM_ENGINE_MODEL_PATH:-$DEFAULT_MODEL_PATH}"
  SERVED_MODEL_NAME="${VLLM_ENGINE_SERVED_MODEL_NAME:-$DEFAULT_SERVED_MODEL_NAME}"
  HOST="${VLLM_ENGINE_HOST:-$DEFAULT_HOST}"
  PORT="${VLLM_ENGINE_PORT:-$DEFAULT_PORT}"
  TP_SIZE="${VLLM_ENGINE_TP_SIZE:-$DEFAULT_TP_SIZE}"
  NPU_DEVICES="${VLLM_ENGINE_NPU_DEVICES:-$DEFAULT_NPU_DEVICES}"
  MAX_MODEL_LEN="${VLLM_ENGINE_MAX_MODEL_LEN:-$DEFAULT_MAX_MODEL_LEN}"
  MAX_NUM_BATCHED_TOKENS="${VLLM_ENGINE_MAX_NUM_BATCHED_TOKENS:-$DEFAULT_MAX_NUM_BATCHED_TOKENS}"
  MAX_NUM_SEQS="${VLLM_ENGINE_MAX_NUM_SEQS:-$DEFAULT_MAX_NUM_SEQS}"
  GPU_MEM_UTIL="${VLLM_ENGINE_GPU_MEM_UTIL:-$DEFAULT_GPU_MEM_UTIL}"
  DTYPE="${VLLM_ENGINE_DTYPE:-$DEFAULT_DTYPE}"
  LOAD_FORMAT="${VLLM_ENGINE_LOAD_FORMAT:-$DEFAULT_LOAD_FORMAT}"
  PREFIX_CACHING="${VLLM_ENGINE_ENABLE_PREFIX_CACHING:-$DEFAULT_PREFIX_CACHING}"
  REQUIRE_PREFIX_CACHING="${VLLM_ENGINE_REQUIRE_PREFIX_CACHING:-$DEFAULT_REQUIRE_PREFIX_CACHING}"
  CHUNKED_PREFILL="${VLLM_ENGINE_ENABLE_CHUNKED_PREFILL:-$DEFAULT_CHUNKED_PREFILL}"
  ENFORCE_EAGER="${VLLM_ENGINE_ENFORCE_EAGER:-$DEFAULT_ENFORCE_EAGER}"
  PLUGINS="${VLLM_PLUGINS:-$DEFAULT_PLUGINS}"
  ENGINE_PYTHON="${VLLM_ENGINE_PYTHON:-}"
  COMPILATION_CONFIG="${VLLM_ENGINE_COMPILATION_CONFIG:-}"
  QUANTIZATION="${VLLM_ENGINE_QUANTIZATION:-}"
  API_KEY="${VLLM_HUST_API_KEY:-${VLLM_ENGINE_API_KEY:-}}"

  # Profile 级
  PROFILE_KIND="${VLLM_PROFILE_KIND:-$DEFAULT_PROFILE_KIND}"
  PROFILE_DURATION="${VLLM_PROFILE_DURATION_SEC:-$DEFAULT_PROFILE_DURATION}"
  PROFILE_INTERVAL="${VLLM_PROFILE_INTERVAL_SEC:-$DEFAULT_PROFILE_INTERVAL}"
  PROFILE_OUTPUT_DIR="${VLLM_PROFILE_OUTPUT_DIR:-$LOG_DIR/profile}"
  PROFILE_LABEL="${VLLM_PROFILE_LABEL:-manual-$(date +%Y%m%d-%H%M%S)}"

  # torch profiler (P4)
  PROFILE_TORCH_REQUESTS="${VLLM_PROFILE_TORCH_REQUESTS:-$DEFAULT_PROFILE_TORCH_REQUESTS}"
  PROFILE_TORCH_WITH_STACK="${VLLM_PROFILE_TORCH_WITH_STACK:-$DEFAULT_PROFILE_TORCH_WITH_STACK}"
  PROFILE_TORCH_KEEP="${VLLM_PROFILE_TORCH_KEEP:-$DEFAULT_PROFILE_TORCH_KEEP}"

  # msprof (P5)
  PROFILE_MSPROF_DURATION="${VLLM_PROFILE_MSPROF_DURATION_SEC:-$DEFAULT_PROFILE_MSPROF_DURATION}"
  PROFILE_MSPROF_REQUESTS="${VLLM_PROFILE_MSPROF_REQUESTS:-$DEFAULT_PROFILE_MSPROF_REQUESTS}"
  PROFILE_MSPROF_AIC_METRICS="${VLLM_PROFILE_MSPROF_AIC_METRICS:-$DEFAULT_PROFILE_MSPROF_AIC_METRICS}"
  PROFILE_MSPROF_TASK_MEMORY="${VLLM_PROFILE_MSPROF_TASK_MEMORY:-$DEFAULT_PROFILE_MSPROF_TASK_MEMORY}"
  PROFILE_MSPROF_SYS_PROFILING="${VLLM_PROFILE_MSPROF_SYS_PROFILING:-$DEFAULT_PROFILE_MSPROF_SYS_PROFILING}"
  PROFILE_MSPROF_BIN="${VLLM_PROFILE_MSPROF_BIN:-$DEFAULT_PROFILE_MSPROF_BIN}"

  # Benchmark 级
  BENCH_NUM_PROMPTS="${VLLM_BENCH_NUM_PROMPTS:-$DEFAULT_BENCH_NUM_PROMPTS}"
  BENCH_CONCURRENCY="${VLLM_BENCH_CONCURRENCY:-$DEFAULT_BENCH_CONCURRENCY}"
  BENCH_RATE="${VLLM_BENCH_RATE:-$DEFAULT_BENCH_RATE}"
  BENCH_INPUT_LEN="${VLLM_BENCH_INPUT_LEN:-$DEFAULT_BENCH_INPUT_LEN}"
  BENCH_OUTPUT_LEN="${VLLM_BENCH_OUTPUT_LEN:-$DEFAULT_BENCH_OUTPUT_LEN}"
  BENCH_DATASET="${VLLM_BENCH_DATASET:-$DEFAULT_BENCH_DATASET}"
  BENCH_DATASET_PATH="${VLLM_BENCH_DATASET_PATH:-$DEFAULT_BENCH_DATASET_PATH}"
  BENCH_BACKEND="${VLLM_BENCH_BACKEND:-$DEFAULT_BENCH_BACKEND}"

  # 校验
  [[ -z "$MODEL_PATH" ]] && { log_err "VLLM_ENGINE_MODEL_PATH is required"; exit 1; }
  [[ -z "$SERVED_MODEL_NAME" ]] && SERVED_MODEL_NAME="$(basename "$MODEL_PATH")"
  (( MAX_NUM_BATCHED_TOKENS < MAX_MODEL_LEN )) && MAX_NUM_BATCHED_TOKENS="$MAX_MODEL_LEN"
  for setting in PREFIX_CACHING REQUIRE_PREFIX_CACHING CHUNKED_PREFILL ENFORCE_EAGER; do
    value="${!setting}"
    [[ "$value" == "0" || "$value" == "1" ]] || {
      log_err "$setting must be 0 or 1 (got: $value)"
      exit 1
    }
  done
  if [[ "$REQUIRE_PREFIX_CACHING" == "1" && "$PREFIX_CACHING" != "1" ]]; then
    log_err "prefix caching is required; refusing configuration with VLLM_ENGINE_ENABLE_PREFIX_CACHING=$PREFIX_CACHING"
    exit 1
  fi

  mkdir -p "$LOG_DIR" "$PROFILE_OUTPUT_DIR"
}

# ===== 按需校验：只有真正把 API_KEY 用在外部 HTTP 调用的 action 才强制要求 =====
# 用法：require_api_key "<action name>"   — 失败时 exit 1
require_api_key() {
  if [[ -z "${API_KEY:-}" || "$API_KEY" == "EMPTY" ]]; then
    log_err "VLLM_HUST_API_KEY is required for $1 (non-EMPTY). Set in env or --config"
    exit 1
  fi
}

# ===== 落盘 state.env（让后续 status / health / stop 能复现 start 时的解析） =====
save_state() {
  # 不写 secret（API key、token、password 等）
  local key val
  : > "$STATE_FILE"
  {
    echo "# vllm-hust manager state — generated at $(date +%Y-%m-%dT%H:%M:%S%z)"
    echo "# Do not edit by hand. Secrets are intentionally omitted."
    for key in \
      VLLM_MANAGER_LOG_DIR VLLM_MANAGER_PID_FILE VLLM_MANAGER_LOG_FILE \
      VLLM_MANAGER_CONDA_ENV VLLM_MANAGER_ASCEND_TOOLKIT VLLM_MANAGER_ATB_SET_ENV \
      VLLM_MANAGER_AUTOSTART \
      VLLM_ENGINE_MODEL_PATH VLLM_ENGINE_SERVED_MODEL_NAME \
      VLLM_ENGINE_HOST VLLM_ENGINE_PORT VLLM_ENGINE_TP_SIZE VLLM_ENGINE_NPU_DEVICES \
      VLLM_ENGINE_MAX_MODEL_LEN VLLM_ENGINE_MAX_NUM_BATCHED_TOKENS VLLM_ENGINE_MAX_NUM_SEQS \
      VLLM_ENGINE_GPU_MEM_UTIL VLLM_ENGINE_DTYPE VLLM_ENGINE_LOAD_FORMAT \
      VLLM_ENGINE_ENABLE_PREFIX_CACHING VLLM_ENGINE_REQUIRE_PREFIX_CACHING VLLM_ENGINE_ENABLE_CHUNKED_PREFILL \
      VLLM_ENGINE_ENFORCE_EAGER VLLM_ENGINE_COMPILATION_CONFIG VLLM_ENGINE_QUANTIZATION \
      VLLM_ENGINE_PYTHON \
      VLLM_PLUGINS \
      ASCEND_RT_VISIBLE_DEVICES ASCEND_VISIBLE_DEVICES \
      COMPILE_CUSTOM_KERNELS TORCH_DEVICE_BACKEND_AUTOLOAD PYTORCH_NPU_ALLOC_CONF \
      HF_HUB_OFFLINE TRANSFORMERS_OFFLINE \
      VLLM_ASCEND_ENABLE_FLASHCOMM1 VLLM_ASCEND_ENABLE_FUSED_MC2 \
      VLLM_PROFILE_KIND VLLM_PROFILE_DURATION_SEC VLLM_PROFILE_INTERVAL_SEC \
      VLLM_PROFILE_OUTPUT_DIR VLLM_PROFILE_LABEL \
      VLLM_PROFILE_TORCH_REQUESTS VLLM_PROFILE_TORCH_WITH_STACK VLLM_PROFILE_TORCH_KEEP \
      VLLM_PROFILE_MSPROF_DURATION_SEC VLLM_PROFILE_MSPROF_REQUESTS \
      VLLM_PROFILE_MSPROF_AIC_METRICS VLLM_PROFILE_MSPROF_TASK_MEMORY \
      VLLM_PROFILE_MSPROF_SYS_PROFILING VLLM_PROFILE_MSPROF_BIN \
      VLLM_BENCH_NUM_PROMPTS VLLM_BENCH_CONCURRENCY VLLM_BENCH_RATE \
      VLLM_BENCH_INPUT_LEN VLLM_BENCH_OUTPUT_LEN VLLM_BENCH_DATASET \
      VLLM_BENCH_DATASET_PATH VLLM_BENCH_BACKEND; do
      val="${!key:-}"
      [[ -z "$val" ]] && continue
      # 防御：任何带 KEY/TOKEN/SECRET 字样的 key 一律不写
      case "$key" in
        *KEY*|*TOKEN*|*SECRET*) continue ;;
      esac
      printf '%s=%q\n' "$key" "$val"
    done
  } > "$STATE_FILE"
  log_dim "state saved: $STATE_FILE"
}

clear_state() {
  rm -f "$STATE_FILE" 2>/dev/null || true
}

# ===== 工具 =====
is_engine_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid; pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

wait_for_health() {
  local timeout="${1:-$HEALTH_TIMEOUT}" url="http://127.0.0.1:${PORT}/health"
  local dbg="${WAIT_FOR_HEALTH_DEBUG:-0}"
  # 注：在 Ascend conda env 下，/usr/bin/curl 会因为 LD_LIBRARY_PATH 冲突报
  # "symbol lookup error: libldap.so.2: undefined symbol: EVP_md2"。
  # 用 python urllib 走 stdlib 不依赖外部 .so。
  local probe
  probe=$(cat <<'PY'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as r:
        sys.stdout.write(str(r.status)); sys.exit(0)
except Exception as e:
    sys.stdout.write("000"); sys.exit(1)
PY
)
  for i in $(seq 1 "$timeout"); do
    local http_code=000
    if http_code=$("${ENGINE_PYTHON:-python3}" -c "$probe" "$url" 2>/dev/null); then
      :
    fi
    if [[ "$http_code" == "200" ]]; then
      log_ok "healthy after ${i}s (http=200)"
      return 0
    fi
    # 守护：engine pid 如果挂了立刻报错（避免 0s false-positive：端口被其它进程占用）
    if [[ -n "${WAIT_GUARD_PID:-}" ]] && ! kill -0 "$WAIT_GUARD_PID" 2>/dev/null; then
      log_err "engine pid $WAIT_GUARD_PID died during startup; check $LOG_FILE"
      return 2
    fi
    if (( i % 15 == 0 )) || (( i == timeout )) || [[ "$dbg" == "1" ]]; then
      log_dim "wait ${i}s: http=${http_code}"
    fi
    sleep 1
  done
  return 1
}

port_in_use() {
  local port="$1"
  # 优先 python 探测（conda env 里 ss/netstat 经常缺；python + socket 是 stdlib 必有）
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$port" <<'PY' >/dev/null 2>&1
import socket, sys
p = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", p))
    s.close()
    sys.exit(0)  # connected → port is in use
except Exception:
    sys.exit(1)  # can't connect → port is free
PY
    return $?  # 0 = in use, 1 = free
  fi
  # 兜底：ss / netstat
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN
  else
    netstat -ltn 2>/dev/null | grep -q ":$port " && return 0
  fi
  return 1
}

# 用 python urllib 走 POST /v1/chat/completions
# 入参：$1 = 次数, $2 = 单 prompt（短小固定），$3 = max_tokens
# stdout 打时间戳 + status；最终返回 0（不因个别失败而 abort）
drive_chat_requests() {
  local n="$1" prompt="$2" max_tokens="${3:-32}"
  local url="http://127.0.0.1:${PORT}/v1/chat/completions"
  # 注：不用 heredoc 拼 python（中文 prompt + bash 变量展开会乱码），
  # 直接走 sys.argv，避开 quoting hell。
  "${ENGINE_PYTHON:-python3}" - "$url" "$prompt" "$max_tokens" "$API_KEY" "$SERVED_MODEL_NAME" "$n" <<'PY'
import json, sys, urllib.request, urllib.error
url, prompt, max_tokens, api_key, model, n = sys.argv[1:7]
auth = "Bearer " + api_key
body = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": int(max_tokens),
    "temperature": 0.0,
    "stream": False,
}).encode()
ok = fail = 0
for i in range(int(n)):
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": auth,
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            if r.status == 200:
                ok += 1
            else:
                fail += 1
    except urllib.error.HTTPError:
        fail += 1
    except Exception:
        fail += 1
print(f"chat: ok={ok} fail={fail}")
sys.exit(0)
PY
}

# POST /start_profile 或 /stop_profile（vllm-hust profiler API）
# 入参：$1 = "start" | "stop"
# stdout 打 HTTP 状态码；返回 0=ok
profile_control() {
  local action="$1"
  local url="http://127.0.0.1:${PORT}/${action}_profile"
  # 注：和 drive_chat_requests 一样用 sys.argv 传参，避开 bash heredoc 的 quoting 问题
  "${ENGINE_PYTHON:-python3}" - "$url" "$action" "$API_KEY" <<'PY'
import sys, urllib.request, urllib.error
url, action, api_key = sys.argv[1:4]
try:
    req = urllib.request.Request(url, data=b"", method="POST", headers={
        "Authorization": "Bearer " + api_key,
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        print(f"{action}_profile: HTTP {r.status}")
        sys.exit(0)
except urllib.error.HTTPError as e:
    print(f"{action}_profile: HTTP {e.code} (body may explain)")
    sys.exit(0)  # 即使 404/409 也不 abort，让 caller 看日志
except Exception as e:
    print(f"{action}_profile: failed ({type(e).__name__}: {e})")
    sys.exit(1)
PY
}

# 探测 msprof 二进制：先用 VLLM_PROFILE_MSPROF_BIN/DEFAULT，再 fall back 到 find
msprof_bin_resolve() {
  if [[ -x "$PROFILE_MSPROF_BIN" ]]; then
    echo "$PROFILE_MSPROF_BIN"; return 0
  fi
  if command -v msprof >/dev/null 2>&1; then
    command -v msprof; return 0
  fi
  local found
  found="$(find /usr/local/Ascend -maxdepth 6 -name msprof -type f 2>/dev/null | head -1 || true)"
  if [[ -n "$found" && -x "$found" ]]; then
    echo "$found"; return 0
  fi
  return 1
}

# 把 VLLM_ARGS 数组拼成单字符串（msprof --application= 接受）
# 同时 export msprof 必需的 CANN profiling env（HCCL_OP_EXPANSION_MODE 等）
build_msprof_command() {
  local msprof_bin="$1" out_dir="$2" duration="$3"

  # aic-metrics 是单值，重复 --aic-metrics=... 才能多选（msprof 行为）
  # 用户传 'ArithmeticUtilization|PipeUtilization|Memory|L2Cache' 这种 | 分隔串
  local aic_metrics_esc="$PROFILE_MSPROF_AIC_METRICS"
  aic_metrics_esc="${aic_metrics_esc//,/ }"   # 兼容逗号分隔输入
  aic_metrics_esc="${aic_metrics_esc// /}"
  local aic_flags=""
  local m
  # 注：脚本顶 IFS=$'\n\t' 禁了按空格 word-split。临时 IFS=$' \n\t' 让 read 按空白拆。
  local -a m_arr
  IFS=$' \n\t' read -ra m_arr <<<"${aic_metrics_esc//|/ }"
  for m in "${m_arr[@]}"; do
    [[ -z "$m" ]] && continue
    aic_flags+="  --aic-metrics=$m \\"$'\n'
  done
  aic_flags="${aic_flags%$'\n'}"

  # 新版 msprof 不再支持 --application=...，改用 msprof [flags] <app> [app args]
  # 参考：https://www.hiascend.com/document/detail/zh/canncommercial/601/profiling/profiling_0003.html
  # 此处用 printf '%q ' 把 VLLM_ARGS 数组拼成引用安全的字符串追加到 msprof flags 后面
  local app_str
  printf -v app_str '%q ' "${VLLM_ARGS[@]}"
  app_str="${app_str% }"

  # msprof 脚本启动时 conda 和 ascend env 尚未激活，需在 exec 前 source
  cat <<EOF
# msprof-required env (CANN)
export HCCL_OP_EXPANSION_MODE="\${HCCL_OP_EXPANSION_MODE:-AIV}"
export PROFILING_MODE="\${PROFILING_MODE:-0}"
export MSPROF_HOST_PORT="\${MSPROF_HOST_PORT:-64451}"
export ASCEND_PROFILER_MODE=off

# 激活 conda 环境（确保 vllm-hust 能找到 cuda/torch 依赖）
source "$DEFAULT_MINICONDA" 2>/dev/null || true
conda activate "$CONDA_ENV" 2>/dev/null || true

# 激活 Ascend 环境
[[ -f "$DEFAULT_ASCEND_TOOLKIT" ]] && source "$DEFAULT_ASCEND_TOOLKIT" 2>/dev/null || true
[[ -f "$DEFAULT_ATB_SET_ENV" ]] && source "$DEFAULT_ATB_SET_ENV" 2>/dev/null || true

exec "$msprof_bin" \\
  --output="$out_dir" \\
  --duration=$duration \\
  --task-time=on \\
${aic_flags}
  --runtime-api=on \\
  --ascendcl=on \\
  --ge-api=off \\
  --task-memory=$PROFILE_MSPROF_TASK_MEMORY \\
  --sys-profiling=$PROFILE_MSPROF_SYS_PROFILING \\
  $app_str
EOF
}

activate_envs() {
  # Conda
  if [[ -z "${CONDA_PREFIX:-}" ]] || [[ "$CONDA_PREFIX" != *"$CONDA_ENV"* ]]; then
    if [[ -f "$DEFAULT_MINICONDA" ]]; then
      # shellcheck disable=SC1090
      source "$DEFAULT_MINICONDA"
      conda activate "$CONDA_ENV"
    else
      log_err "conda not found at $DEFAULT_MINICONDA; set VLLM_MANAGER_CONDA_ENV correctly"
      exit 1
    fi
  fi
  if [[ -n "$ENGINE_PYTHON" ]]; then
    [[ -x "$ENGINE_PYTHON" ]] || { log_err "VLLM_ENGINE_PYTHON not executable: $ENGINE_PYTHON"; exit 1; }
  else
    ENGINE_PYTHON="$(command -v python3)"
  fi
  # Ascend toolkit
  [[ -f "$ASCEND_TOOLKIT" ]] && source "$ASCEND_TOOLKIT"
  if [[ -f "$ATB_SET_ENV" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "$ATB_SET_ENV" --cxx_abi=1
    set -u
  fi
}

build_vllm_args() {
  local vllm_bin
  vllm_bin="$(command -v vllm-hust 2>/dev/null || command -v vllm 2>/dev/null || true)"
  [[ -z "$vllm_bin" ]] && { log_err "vllm/vllm-hust not on PATH (after conda activate)"; return 1; }
  VLLM_BIN="$vllm_bin"

  VLLM_ARGS=("${ENGINE_PYTHON:-python3}" -m vllm.entrypoints.cli.main serve "$MODEL_PATH"
    --served-model-name "$SERVED_MODEL_NAME"
    --host "$HOST" --port "$PORT"
    --tensor-parallel-size "$TP_SIZE"
    --max-model-len "$MAX_MODEL_LEN"
    --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS"
    --max-num-seqs "$MAX_NUM_SEQS"
    --gpu-memory-utilization "$GPU_MEM_UTIL"
    --dtype "$DTYPE" --load-format "$LOAD_FORMAT"
    --trust-remote-code
  )
  if [[ "$PREFIX_CACHING" == "1" ]]; then VLLM_ARGS+=(--enable-prefix-caching); else VLLM_ARGS+=(--no-enable-prefix-caching); fi
  if [[ "$CHUNKED_PREFILL" == "1" ]]; then VLLM_ARGS+=(--enable-chunked-prefill); else VLLM_ARGS+=(--no-enable-chunked-prefill); fi
  if [[ "$ENFORCE_EAGER" == "1" ]]; then VLLM_ARGS+=(--enforce-eager); fi
  if [[ -n "$QUANTIZATION" ]]; then VLLM_ARGS+=(--quantization "$QUANTIZATION"); fi
  if [[ -n "$COMPILATION_CONFIG" ]]; then VLLM_ARGS+=(--compilation-config "$COMPILATION_CONFIG"); fi

  # torch profiler (P4)：调用方（profile_torch）会先 export PROFILE_TORCH_ENABLED=1
  # 当 PROFILE_TORCH_DIR 非空时，注入 --profiler-config '{profiler:torch, torch_profiler_dir:...}'
  if [[ -n "${PROFILE_TORCH_DIR:-}" ]]; then
    local stack_flag="true"
    [[ "${PROFILE_TORCH_WITH_STACK:-1}" != "1" ]] && stack_flag="false"
    local prof_cfg
    prof_cfg=$(printf '{"profiler":"torch","torch_profiler_dir":"%s","torch_profiler_with_stack":%s}' \
      "$PROFILE_TORCH_DIR" "$stack_flag")
    VLLM_ARGS+=(--profiler-config "$prof_cfg")
  fi
}

export_engine_env() {
  # vLLM's native environment contract avoids publishing the credential in
  # process argv, manager logs, profiler application strings, or status output.
  export VLLM_API_KEY="$API_KEY"
  export VLLM_PLUGINS="$PLUGINS"
  export VLLM_TARGET_DEVICE=npu
  export ASCEND_RT_VISIBLE_DEVICES="$NPU_DEVICES"
  export ASCEND_VISIBLE_DEVICES="$NPU_DEVICES"
  export TORCH_DEVICE_BACKEND_AUTOLOAD="${TORCH_DEVICE_BACKEND_AUTOLOAD:-1}"
  export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}"
  export COMPILE_CUSTOM_KERNELS="${COMPILE_CUSTOM_KERNELS:-1}"
  export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
  export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
  export VLLM_ASCEND_ENABLE_FLASHCOMM1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-0}"
  export VLLM_ASCEND_ENABLE_FUSED_MC2="${VLLM_ASCEND_ENABLE_FUSED_MC2:-1}"
  export VLLM_LOGGING_LEVEL="${VLLM_LOGGING_LEVEL:-INFO}"

  # 注：vllm-hust 的 torch profiler 不是用 VLLM_TORCH_PROFILER_* env 开启，
  # 而是用 --profiler-config CLI arg + POST /start_profile / /stop_profile API。
  # 见 vllm/config/profiler.py 与 vllm/entrypoints/serve/profile/api_router.py
}

# ===== actions =====

cmd_start() {
  resolve_config
  require_api_key "start"
  if is_engine_running; then
    log_warn "engine already running (pid=$(cat "$PID_FILE"))"
    return 0
  fi
  if port_in_use "$PORT"; then
    log_err "port $PORT is in use (likely another vllm serve). Pick another via --config VLLM_ENGINE_PORT=<n> or stop the conflicting process."
    exit 1
  fi

  activate_envs
  build_vllm_args

  export_engine_env
  : > "$LOG_FILE"
  echo "[$(date +%H:%M:%S)] cmd: ${VLLM_ARGS[*]}" >> "$LOG_FILE"

  "${VLLM_ARGS[@]}" >> "$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"
  disown 2>/dev/null || true

  # 落盘 state.env（去掉 secret）让后续 status/health/stop 能复现这次配置
  save_state

  # 让 wait_for_health 守护 engine 进程
  WAIT_GUARD_PID="$pid"
  export WAIT_GUARD_PID

  log_info "started pid=$pid port=$PORT model=$SERVED_MODEL_NAME (waiting for /health)"
  if wait_for_health "$HEALTH_TIMEOUT"; then
    log_ok "engine ready: http://127.0.0.1:$PORT/v1 (served as: $SERVED_MODEL_NAME)"
  else
    log_warn "/health not reachable after ${HEALTH_TIMEOUT}s; check $LOG_FILE"
    return 1
  fi
}

cmd_stop() {
  resolve_config
  if ! is_engine_running; then
    log_dim "engine not running"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid; pid="$(cat "$PID_FILE")"
  log_info "stopping pid=$pid (SIGTERM)"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    log_warn "still alive, sending SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  clear_state
  # 顺手清掉 EngineCore 子进程（manage.sh 的 cleanup 套路）
  pkill -9 -f "VLLM::EngineCor|VLLM::Worker_TP" 2>/dev/null || true
  log_ok "stopped"
}

cmd_restart() {
  cmd_stop || true
  sleep 1
  cmd_start
}

cmd_status() {
  resolve_config
  local state="stopped" pid=0 health="unknown"
  is_engine_running && { state="running"; pid=$(cat "$PID_FILE"); }
  # 同 cmd_health：避开 Ascend env 下 curl 的 LD_LIBRARY_PATH 冲突
  # （curl 会在连接失败时也返回 0，导致误判 healthy）
  if command -v python3 >/dev/null 2>&1; then
    local code
    code=$(python3 - <<PY 2>/dev/null || echo 000
import sys, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:${PORT}/health", timeout=2) as r:
        print(r.status)
except Exception:
    print("000")
PY
)
    [[ "$code" == "200" ]] && health="healthy"
  fi

  if $JSON_OUTPUT; then
    cat <<JSON
{
  "state": "$state",
  "pid": $pid,
  "port": $PORT,
  "host": "$HOST",
  "npu_devices": "$NPU_DEVICES",
  "model_path": "$MODEL_PATH",
  "served_model_name": "$SERVED_MODEL_NAME",
  "tp_size": $TP_SIZE,
  "health": "$health",
  "log_dir": "$LOG_DIR",
  "log_file": "$LOG_FILE",
  "pid_file": "$PID_FILE"
}
JSON
  else
    echo -e "${C_BLU}=== vllm-hust engine status ===${C_RST}"
    if [[ "$state" == "running" ]]; then
      echo -e "  state:      ${C_GRN}running${C_RST} (pid $pid)"
    else
      echo -e "  state:      ${C_DIM}stopped${C_RST}"
    fi
    echo "  port:       $PORT"
    echo "  host:       $HOST"
    echo "  npu:        $NPU_DEVICES  (TP=$TP_SIZE)"
    echo "  model:      $MODEL_PATH"
    echo "  served_as:  $SERVED_MODEL_NAME"
    echo "  health:     $health"
    echo "  pid_file:   $PID_FILE"
    echo "  log_file:   $LOG_FILE"
  fi
}

cmd_health() {
  resolve_config
  local url="http://127.0.0.1:${PORT}/health"
  local code=000
  # 同 wait_for_health：避开 Ascend env 下 curl 的 LD_LIBRARY_PATH 冲突
  if command -v python3 >/dev/null 2>&1; then
    code=$(python3 - <<PY 2>/dev/null || echo 000
import sys, urllib.request
try:
    with urllib.request.urlopen("$url", timeout=5) as r:
        print(r.status)
except Exception:
    print("000")
PY
)
  fi
  if $JSON_OUTPUT; then
    cat <<JSON
{
  "url": "$url",
  "http_code": "$code",
  "ok": $([[ "$code" == "200" ]] && echo true || echo false)
}
JSON
  else
    if [[ "$code" == "200" ]]; then
      log_ok "health ok: $url"
    else
      log_err "health failed: $url (HTTP $code)"
      exit 1
    fi
  fi
}

cmd_logs() {
  resolve_config
  [[ -f "$LOG_FILE" ]] || { log_err "no log file: $LOG_FILE"; exit 1; }
  exec tail -F "$LOG_FILE"
}

cmd_config() {
  resolve_config
  if $JSON_OUTPUT; then
    cat <<JSON
{
  "log_dir": "$LOG_DIR",
  "pid_file": "$PID_FILE",
  "log_file": "$LOG_FILE",
  "manager_log": "$MANAGER_LOG_FILE",
  "conda_env": "$CONDA_ENV",
  "ascend_toolkit": "$ASCEND_TOOLKIT",
  "atb_set_env": "$ATB_SET_ENV",
  "model_path": "$MODEL_PATH",
  "served_model_name": "$SERVED_MODEL_NAME",
  "host": "$HOST",
  "port": $PORT,
  "tp_size": $TP_SIZE,
  "npu_devices": "$NPU_DEVICES",
  "max_model_len": $MAX_MODEL_LEN,
  "max_num_batched_tokens": $MAX_NUM_BATCHED_TOKENS,
  "max_num_seqs": $MAX_NUM_SEQS,
  "gpu_memory_utilization": $GPU_MEM_UTIL,
  "dtype": "$DTYPE",
  "load_format": "$LOAD_FORMAT",
  "prefix_caching": $([[ $PREFIX_CACHING == 1 ]] && echo true || echo false),
  "prefix_caching_required": $([[ $REQUIRE_PREFIX_CACHING == 1 ]] && echo true || echo false),
  "chunked_prefill": $([[ $CHUNKED_PREFILL == 1 ]] && echo true || echo false),
  "enforce_eager": $([[ $ENFORCE_EAGER == 1 ]] && echo true || echo false),
  "plugins": "$PLUGINS",
  "compilation_config": "${COMPILATION_CONFIG:-}",
  "quantization": "${QUANTIZATION:-}",
  "autostart": $([[ $AUTOSTART == 1 ]] && echo true || echo false),
  "bench_num_prompts": $BENCH_NUM_PROMPTS,
  "bench_concurrency": $BENCH_CONCURRENCY,
  "bench_rate": "$BENCH_RATE",
  "bench_input_len": $BENCH_INPUT_LEN,
  "bench_output_len": $BENCH_OUTPUT_LEN,
  "bench_dataset": "$BENCH_DATASET"
}
JSON
  else
    echo -e "${C_BLU}=== effective config ===${C_RST}"
    printf "  %-22s = %s\n" "log_dir"              "$LOG_DIR"
    printf "  %-22s = %s\n" "pid_file"             "$PID_FILE"
    printf "  %-22s = %s\n" "log_file"             "$LOG_FILE"
    printf "  %-22s = %s\n" "manager_log"          "$MANAGER_LOG_FILE"
    printf "  %-22s = %s\n" "conda_env"            "$CONDA_ENV"
    printf "  %-22s = %s\n" "ascend_toolkit"       "$ASCEND_TOOLKIT"
    printf "  %-22s = %s\n" "atb_set_env"          "$ATB_SET_ENV"
    printf "  %-22s = %s\n" "model_path"           "$MODEL_PATH"
    printf "  %-22s = %s\n" "served_model_name"    "$SERVED_MODEL_NAME"
    printf "  %-22s = %s:%s\n" "host:port"          "$HOST" "$PORT"
    printf "  %-22s = %s\n" "tp_size"              "$TP_SIZE"
    printf "  %-22s = %s\n" "npu_devices"          "$NPU_DEVICES"
    printf "  %-22s = %s\n" "max_model_len"        "$MAX_MODEL_LEN"
    printf "  %-22s = %s\n" "max_num_batched_tok"  "$MAX_NUM_BATCHED_TOKENS"
    printf "  %-22s = %s\n" "max_num_seqs"         "$MAX_NUM_SEQS"
    printf "  %-22s = %s\n" "gpu_mem_util"         "$GPU_MEM_UTIL"
    printf "  %-22s = %s\n" "dtype"                "$DTYPE"
    printf "  %-22s = %s\n" "prefix_caching"       "$PREFIX_CACHING"
    printf "  %-22s = %s\n" "prefix_cache_required" "$REQUIRE_PREFIX_CACHING"
    printf "  %-22s = %s\n" "chunked_prefill"      "$CHUNKED_PREFILL"
    printf "  %-22s = %s\n" "enforce_eager"        "$ENFORCE_EAGER"
    printf "  %-22s = %s\n" "plugins"              "$PLUGINS"
    printf "  %-22s = %s\n" "compilation_config"   "${COMPILATION_CONFIG:-<unset>}"
    printf "  %-22s = %s\n" "autostart"            "$AUTOSTART"
  fi
}

cmd_foreground() {
  resolve_config
  require_api_key "foreground"
  activate_envs
  build_vllm_args
  export_engine_env
  log_info "starting in foreground (Ctrl-C to stop)"
  exec "${VLLM_ARGS[@]}"
}

# ===== benchmark action（vllm bench serve 封装）=====
cmd_benchmark() {
  local label="" num_prompts="" concurrency="" rate="" input_len="" output_len=""
  local dataset="" dataset_path="" backend=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --label) label="$2"; shift ;;
      --num-prompts) num_prompts="$2"; shift ;;
      --concurrency) concurrency="$2"; shift ;;
      --rate) rate="$2"; shift ;;
      --input-len) input_len="$2"; shift ;;
      --output-len) output_len="$2"; shift ;;
      --dataset) dataset="$2"; shift ;;
      --dataset-path) dataset_path="$2"; shift ;;
      --backend) backend="$2"; shift ;;
      --json) ;;
      -h|--help)
        cat <<EOF
benchmark — 在线服务基准测试（vllm bench serve 封装）

Flags:
  --label <text>          标签，纳入产物目录名（默认 manual-<ts>）
  --num-prompts N         请求数（默认 200）
  --concurrency C         最大并发数（默认 8）
  --rate R                请求速率，inf=全速（默认 inf）
  --input-len N           prompt 输入长度（仅 random 数据集，默认 128）
  --output-len N          输出 token 数（默认 64）
  --dataset <d>           random|sonnet|sharegpt（默认 random）
  --dataset-path <p>      sonnet/sharegpt 数据集本地路径（必须）
  --backend <b>           vllm（默认 vllm）

Examples:
  $SCRIPT_NAME benchmark
  $SCRIPT_NAME benchmark --label my-test --num-prompts 500 --concurrency 16 --rate inf
  $SCRIPT_NAME benchmark --label sharegpt --dataset sharegpt --dataset-path /data/sharegpt.jsonl
EOF
        return 0 ;;
      *) log_err "unknown benchmark flag: $1"; exit 1 ;;
    esac
    shift
  done

  resolve_config
  [[ -n "$label"       ]] || label="$PROFILE_LABEL"
  [[ -n "$num_prompts" ]] || num_prompts="$BENCH_NUM_PROMPTS"
  [[ -n "$concurrency" ]] || concurrency="$BENCH_CONCURRENCY"
  [[ -n "$rate"        ]] || rate="$BENCH_RATE"
  [[ -n "$input_len"   ]] || input_len="$BENCH_INPUT_LEN"
  [[ -n "$output_len"  ]] || output_len="$BENCH_OUTPUT_LEN"
  [[ -n "$dataset"     ]] || dataset="$BENCH_DATASET"
  [[ -n "$dataset_path" ]] || dataset_path="$BENCH_DATASET_PATH"
  [[ -n "$backend"     ]] || backend="$BENCH_BACKEND"

  require_api_key "benchmark"
  activate_envs

  # 确保 engine 在运行
  if ! is_engine_running; then
    if [[ "$AUTOSTART" != "1" ]]; then
      log_err "engine not running; start it first or set VLLM_MANAGER_AUTOSTART=1"
      exit 1
    fi
    log_info "engine not running; autostarting..."
    cmd_start
  fi

  local ts; ts="$(date +%Y%m%d-%H%M%S)"
  local out_dir="$PROFILE_OUTPUT_DIR/benchmark/${label}-${ts}"
  mkdir -p "$out_dir"

  # 数据集校验：sonnet/sharegpt 必须传 --dataset-path
  if [[ "$dataset" != "random" && -z "$dataset_path" ]]; then
    log_err "--dataset $dataset requires --dataset-path <path>"
    exit 1
  fi

  echo
  echo -e "${C_BLU}=== benchmark ===${C_RST}"
  echo "  label:         $label"
  echo "  num_prompts:   $num_prompts"
  echo "  concurrency:   $concurrency"
  echo "  rate:          $rate"
  echo "  dataset:       $dataset"
  echo "  input_len:     $input_len"
  echo "  output_len:    $output_len"
  echo "  output:        $out_dir"
  echo

  local bench_args=(
    vllm bench serve
    --backend "$backend"
    --model "$SERVED_MODEL_NAME"
    --served-model-name "$SERVED_MODEL_NAME"
    --tokenizer "$MODEL_PATH"
    --tokenizer-mode auto
    --host 127.0.0.1 --port "$PORT"
    --header "Authorization=Bearer $API_KEY"
    --dataset-name "$dataset"
    --num-prompts "$num_prompts"
    --max-concurrency "$concurrency"
    --request-rate "$rate"
    --save-result --result-dir "$out_dir"
    --result-filename bench.json
    --label "${label}-bench"
    --seed 0
  )

  if [[ "$dataset" == "random" ]]; then
    bench_args+=(--random-input-len "$input_len" --random-output-len "$output_len")
  else
    bench_args+=(--dataset-path "$dataset_path")
  fi

  local bench_log="$out_dir/bench.log"
  log_info "starting benchmark (this may take a while)..."
  env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    "${bench_args[@]}" > "$bench_log" 2>&1

  # 生成摘要
  local summary="$out_dir/summary.txt"
  {
    echo "=== benchmark summary ($label @ $ts) ==="
    echo "num_prompts:   $num_prompts"
    echo "concurrency:   $concurrency"
    echo "rate:          $rate"
    echo "dataset:       $dataset"
    echo "input_len:     $input_len"
    echo "output_len:    $output_len"
    echo "output_dir:    $out_dir"
    echo
    echo "--- bench result ---"
    if [[ -f "$out_dir/bench.json" ]]; then
      python3 -c "
import json
d = json.load(open('$out_dir/bench.json'))
for k in ['num_prompts','completed','failed','duration',
          'request_throughput','output_throughput','total_token_throughput',
          'mean_ttft_ms','p99_ttft_ms','mean_tpot_ms','p99_tpot_ms',
          'mean_itl_ms','p99_itl_ms','max_concurrency','max_concurrent_requests',
          'total_input_tokens','total_output_tokens']:
    v = d.get(k, '?')
    print(f'  {k:30s} = {v}')
"
    else
      echo "  (bench.json not found; check $bench_log)"
    fi
    echo
    echo "--- bench log tail ---"
    tail -20 "$bench_log" 2>/dev/null
  } > "$summary"

  # 也输出到终端
  log_ok "benchmark complete"
  if [[ -f "$out_dir/bench.json" ]]; then
    python3 -c "
import json
d = json.load(open('$out_dir/bench.json'))
def fmt(v): return f'{v:>8.2f}' if isinstance(v, (int, float)) else f'{str(v):>8}'
print(f'  throughput:  {fmt(d.get(\"request_throughput\",\"?\"))} req/s  |  {fmt(d.get(\"output_throughput\",\"?\"))} tok/s')
print(f'  ttft:        {fmt(d.get(\"mean_ttft_ms\",\"?\"))} ms (p99: {fmt(d.get(\"p99_ttft_ms\",\"?\"))} ms)')
print(f'  tpot:        {fmt(d.get(\"mean_tpot_ms\",\"?\"))} ms (p99: {fmt(d.get(\"p99_tpot_ms\",\"?\"))} ms)')
print(f'  itl:         {fmt(d.get(\"mean_itl_ms\",\"?\"))} ms (p99: {fmt(d.get(\"p99_itl_ms\",\"?\"))} ms)')
print(f'  completed:   {d.get(\"completed\",\"?\")} / {d.get(\"num_prompts\",\"?\")}  fail: {d.get(\"failed\",\"?\")}')
"
  fi
  log_ok "summary: $summary"
  log_ok "output:  $out_dir"
}

# ===== profile (v0.2: --kind {engine|torch|msprof}) =====
cmd_profile() {
  local kind="" label="" duration="" interval="" requests="" no_autostart="false"
  local with_stack="" keep_engine="" aic_metrics="" task_memory="" sys_profiling="" msprof_bin=""
  local traffic_requests="" traffic_concurrency="" traffic_rate="" traffic_prompt="" traffic_max_tokens=""
  local traffic_backend="" traffic_input_len="" traffic_dataset="" traffic_dataset_path=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --kind) kind="$2"; shift ;;
      --label) label="$2"; shift ;;
      --duration) duration="$2"; shift ;;
      --interval) interval="$2"; shift ;;
      --requests) requests="$2"; shift ;;
      --no-autostart) no_autostart="true" ;;
      --keep-engine-running) keep_engine="1" ;;
      --with-stack)    with_stack="1" ;;
      --no-stack)      with_stack="0" ;;
      --aic-metrics)   aic_metrics="$2"; shift ;;
      --task-memory)   task_memory="$2"; shift ;;
      --sys-profiling) sys_profiling="$2"; shift ;;
      --msprof-bin)    msprof_bin="$2"; shift ;;
      --traffic-requests)    traffic_requests="$2"; shift ;;
      --traffic-concurrency) traffic_concurrency="$2"; shift ;;
      --traffic-rate)        traffic_rate="$2"; shift ;;
      --traffic-prompt)      traffic_prompt="$2"; shift ;;
      --traffic-max-tokens)  traffic_max_tokens="$2"; shift ;;
      --traffic-backend)     traffic_backend="$2"; shift ;;
      --traffic-input-len)   traffic_input_len="$2"; shift ;;
      --traffic-dataset)     traffic_dataset="$2"; shift ;;
      --traffic-dataset-path) traffic_dataset_path="$2"; shift ;;
      --json) ;;  # 暂未用
      -h|--help)
        cat <<EOF
profile --kind {engine|torch|msprof} [flags]
  --kind <k>            engine | torch | msprof
  --label <text>        标签，纳入产物目录名
  --duration <sec>      engine 抓取时长 / msprof 采集时长
  --interval <sec>      engine 抓取间隔
  --requests N          torch/msprof 期间发的 chat 请求数
  --no-autostart        引擎没起时不要自动 start
  --keep-engine-running torch：测完不自动恢复原 engine（默认会）
  --with-stack          torch：dump 带 stack（默认）
  --no-stack            torch：dump 不带 stack
  --aic-metrics <list>  msprof：--aic-metrics 参数
  --task-memory on|off  msprof：--task-memory 参数
  --sys-profiling on|off msprof：--sys-profiling 参数
  --msprof-bin <path>   msprof 可执行文件路径

Traffic generator (profile --kind engine 自动发请求让 metrics 有意义):
  --traffic-requests N       期间发 N 个 chat 请求（0 = 不发，默认 0）
  --traffic-concurrency C    并发数（默认 4）
  --traffic-rate R           节流到 R req/s（0 = 全速，默认 0）
  --traffic-prompt "text"    请求内容（默认中文 prompt，仅 urllib 后端）
  --traffic-max-tokens N     每请求最大 token（默认 64）
  --traffic-backend <b>      urllib | bench（默认 urllib）
  --traffic-input-len N      prompt 输入长度（仅 bench+random，默认 128）
  --traffic-dataset <d>      random | sonnet | sharegpt（仅 bench，默认 random）
  --traffic-dataset-path <p>  sonnet/sharegpt 数据集本地文件路径（默认空；
                              不传时自动 fallback 到 random 并打印 warning）
EOF
        return 0 ;;
      *) log_err "unknown profile flag: $1"; exit 1 ;;
    esac
    shift
  done

  resolve_config
  [[ -n "$kind"      ]] || kind="$PROFILE_KIND"
  [[ -n "$duration"  ]] || duration="$PROFILE_DURATION"
  [[ -n "$interval"  ]] || interval="$PROFILE_INTERVAL"
  [[ -n "$label"     ]] || label="$PROFILE_LABEL"
  [[ -n "$requests"  ]] || requests="$DEFAULT_PROFILE_TORCH_REQUESTS"
  [[ -n "$with_stack" ]] && PROFILE_TORCH_WITH_STACK="$with_stack"
  [[ -n "$keep_engine" ]] && PROFILE_TORCH_KEEP="$keep_engine"
  [[ -n "$aic_metrics"  ]] && PROFILE_MSPROF_AIC_METRICS="$aic_metrics"
  [[ -n "$task_memory"  ]] && PROFILE_MSPROF_TASK_MEMORY="$task_memory"
  [[ -n "$sys_profiling" ]] && PROFILE_MSPROF_SYS_PROFILING="$sys_profiling"
  [[ -n "$msprof_bin"   ]] && PROFILE_MSPROF_BIN="$msprof_bin"

  case "$kind" in
    engine)
      if ! is_engine_running; then
        if [[ "$no_autostart" == "true" || "$AUTOSTART" != "1" ]]; then
          log_err "engine not running; start it first (run '$SCRIPT_NAME start') or remove --no-autostart"
          exit 1
        fi
        log_info "engine not running; autostarting..."
        cmd_start
      fi
      profile_engine "$label" "$duration" "$interval" \
        "${traffic_requests:-0}" \
        "${traffic_concurrency:-4}" \
        "${traffic_rate:-0}" \
        "${traffic_prompt:-你好，请用 30 个字以内介绍华为昇腾 910B。}" \
        "${traffic_max_tokens:-64}" \
        "${traffic_backend:-$DEFAULT_TRAFFIC_BACKEND}" \
        "${traffic_input_len:-$DEFAULT_TRAFFIC_INPUT_LEN}" \
        "${traffic_dataset:-$DEFAULT_TRAFFIC_DATASET}" \
        "${traffic_dataset_path:-}"
      ;;
    torch)   profile_torch   "$label" "$requests" "$no_autostart" ;;
    msprof)  profile_msprof  "$label" "$duration" "$requests" "$no_autostart" ;;
    *)
      log_err "unknown --kind '$kind' (engine|torch|msprof)"
      exit 1 ;;
  esac
}

# v1: 周期性抓 /metrics；可选在期间发 chat 请求让 metrics 有意义
# 用法：profile_engine <label> <duration> <interval> [traffic-requests] [traffic-concurrency] [traffic-rate] [traffic-prompt] [traffic-max-tokens] [traffic-backend] [traffic-input-len] [traffic-dataset] [traffic-dataset-path]
profile_engine() {
  local label="$1" duration="$2" interval="$3"
  local traffic_requests="${4:-0}"
  local traffic_concurrency="${5:-4}"
  local traffic_rate="${6:-0}"
  local traffic_prompt="${7:-你好，请用 30 个字以内介绍华为昇腾 910B。}"
  local traffic_max_tokens="${8:-64}"
  local traffic_backend="${9:-$DEFAULT_TRAFFIC_BACKEND}"
  local traffic_input_len="${10:-$DEFAULT_TRAFFIC_INPUT_LEN}"
  local traffic_dataset="${11:-$DEFAULT_TRAFFIC_DATASET}"
  local traffic_dataset_path="${12:-}"
  # traffic generator 会真发 chat 请求；只要开了 --traffic-requests N (N>0) 就强制要 API_KEY
  if (( traffic_requests > 0 )); then
    require_api_key "profile --kind engine --traffic-requests"
  fi
  # idle 警告
  if (( traffic_requests <= 0 )); then
    log_warn "no traffic configured — metrics will reflect idle engine."
    log_warn "  Add --traffic-requests 30 to capture load-time metrics."
  fi
  # --traffic-prompt + bench 组合：prompt 被忽略
  if (( traffic_requests > 0 )) && [[ "$traffic_backend" == "bench" ]] && [[ -n "$traffic_prompt" && "$traffic_prompt" != "你好，请用 30 个字以内介绍华为昇腾 910B。" ]]; then
    log_warn "--traffic-prompt is ignored when --traffic-backend bench (bench uses dataset prompts)"
  fi
  local ts; ts="$(date +%Y%m%d-%H%M%S)"
  local out_dir="$PROFILE_OUTPUT_DIR/engine/${label}-${ts}"
  mkdir -p "$out_dir"

  local url="http://127.0.0.1:${PORT}/metrics"
  local chat_url="http://127.0.0.1:${PORT}/v1/chat/completions"
  local end_time=$(( $(date +%s) + duration ))
  local snap_idx=0
  local failed=0

  echo
  echo -e "${C_BLU}=== profile --kind engine ===${C_RST}"
  echo "  label:             $label"
  echo "  duration:          ${duration}s"
  echo "  interval:          ${interval}s"
  echo "  url:               $url"
  echo "  output:            $out_dir"
  if (( traffic_requests > 0 )); then
    echo "  traffic_requests:  $traffic_requests"
    echo "  traffic_backend:   $traffic_backend"
    echo "  traffic_concur:    $traffic_concurrency"
    echo "  traffic_rate:      ${traffic_rate} req/s (0 = full speed)"
    echo "  traffic_max_tok:   $traffic_max_tokens"
    if [[ "$traffic_backend" == "bench" ]]; then
      echo "  traffic_input_len: $traffic_input_len"
      echo "  traffic_dataset:   $traffic_dataset"
    else
      echo "  traffic_prompt:    $traffic_prompt"
    fi
  fi
  echo

  # rate 节流理论时长（rate>0 时），用于 traffic wait timeout 估算
  # rate=2 req/s, requests=15 → (15-1)/2 = 7s
  if (( $(echo "$traffic_rate" | awk '{print ($1 > 0)?1:0}') == 1 )); then
    rate_dur_s=$(awk -v r="$traffic_requests" -v rate="$traffic_rate" 'BEGIN{print int((r-1)/rate + 0.999)}')
  else
    rate_dur_s=0
  fi

  # 同 wait_for_health：避免 Ascend env 下 curl 的 LD_LIBRARY_PATH 冲突
  local probe
  probe=$(cat <<'PY'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=5) as r:
        sys.stdout.buffer.write(r.read())
        sys.exit(0)
except Exception:
    sys.exit(1)
PY
)

  # 启动 traffic generator（bench 或 urllib 后端，跑在后台）
  local traffic_pid=""
  local traffic_log="$out_dir/traffic.log"
  local bench_json="$out_dir/bench.json"
  local bench_log="$out_dir/bench.log"
  local bench_started="false"

  # ---- P6: bench 后端 ----
  if (( traffic_requests > 0 )) && [[ "$traffic_backend" == "bench" ]]; then
    # bench 需要本地 model 文件来加载 tokenizer（random/sonnet/sharegpt 都需要）
    # 如果模型文件不在磁盘上（如被清理或只在 engine 内存中），自动降级到 urllib
    if [[ ! -d "$MODEL_PATH" ]]; then
      log_warn "model path not found on disk ($MODEL_PATH)"
      log_warn "bench backend requires local tokenizer; falling back to urllib"
      traffic_backend="urllib"
    else
      # P7: sonnet/sharegpt 必须传 --dataset-path，否则 vllm bench serve 会 raise
      #   "dataset_path must be provided"。不传则 fallback 到 random。
      if [[ "$traffic_dataset" != "random" && -z "$traffic_dataset_path" ]]; then
        log_warn "--traffic-dataset=$traffic_dataset requires --traffic-dataset-path <file>"
        log_warn "no dataset path given; falling back to --traffic-dataset=random"
        traffic_dataset="random"
      fi
      # bench 需要 conda env 里的 vllm CLI
      activate_envs
      local bench_rate="inf"
      if (( $(echo "$traffic_rate" | awk '{print ($1 > 0)?1:0}') == 1 )); then
        bench_rate="$traffic_rate"
      fi
      local bench_args=(
        vllm bench serve
        --backend vllm
        --model "$SERVED_MODEL_NAME"
        --served-model-name "$SERVED_MODEL_NAME"
        --tokenizer "$MODEL_PATH"
        --tokenizer-mode auto
        --host 127.0.0.1 --port "$PORT"
        --header "Authorization=Bearer $API_KEY"
        --dataset-name "$traffic_dataset"
        --num-prompts "$traffic_requests"
        --max-concurrency "$traffic_concurrency"
        --request-rate "$bench_rate"
        --save-result --result-dir "$out_dir"
        --result-filename bench.json
        --label "${label}-bench"
        --ready-check-timeout-sec 30
        --seed 0
      )
      if [[ "$traffic_dataset" == "random" ]]; then
        bench_args+=(--random-input-len "$traffic_input_len" --random-output-len "$traffic_max_tokens")
      else
        bench_args+=(--dataset-path "$traffic_dataset_path")
      fi
      log_info "starting vllm bench serve (requests=$traffic_requests, concurrency=$traffic_concurrency, dataset=$traffic_dataset)"
      # env 显式注入 offline 模式，避免 activate_envs 的 source 脚本覆盖
      env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "${bench_args[@]}" > "$bench_log" 2>&1 &
      traffic_pid=$!
      bench_started="true"
      log_info "bench traffic started: pid=$traffic_pid"
      # bench 先启 → sleep 2 → 让第一个请求打过去再开始抓 metrics
      sleep 2
    fi
  fi

  # ---- urllib 后端（现有逻辑）----
  # - 期间并发发 chat 请求
  # - 写 out_dir/traffic.log 记录每次请求的 status / latency / tok 数
  if (( traffic_requests > 0 )) && [[ "$bench_started" != "true" ]]; then
    local traffic_script
    traffic_script=$(cat <<'PY'
# vllm-hust 上有时 handler 会"半挂"：vllm 端日志显示 200 OK 但 client 端 r.read() 阻塞。
# 修法：Connection: close + 30s timeout + 进程级 wall-clock deadline（不再 join 卡住的 thread）。
import sys, json, time, threading, urllib.request, urllib.error
url, api_key, model, n_reqs, concurrency, rate, prompt, max_tokens, log_path = sys.argv[1:10]
n_reqs = int(n_reqs)
concurrency = int(concurrency)
rate = float(rate)
max_tokens = int(max_tokens)

auth = "Bearer " + api_key
body = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": max_tokens,
    "temperature": 0.0,
    "stream": False,
}).encode()

# 进程级 deadline：rate 节流理论时长 + 30s 余量
rate_dur = (n_reqs - 1) / rate if rate > 0 else 0.0
deadline = time.time() + max(rate_dur + 30.0, 60.0)
print(f"traffic: deadline in {deadline - time.time():.1f}s (rate_dur={rate_dur:.1f}s)", flush=True)

results = []  # list of (status, latency, in_tok, out_tok)
results_lock = threading.Lock()
start_time = time.time()

# 渐进写 log：每完成一个请求就 append 一行（不依赖最终 join 成功）
log_fh = open(log_path, "w", buffering=1)  # line-buffered
def log_line(s):
    log_fh.write(s + "\n")

def one_req(i):
    t0 = time.time()
    status = -1; in_tok = 0; out_tok = 0; latency = 0.0
    try:
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": auth,
            "Connection": "close",   # 关键：避免 vllm-hust 偶发的 keep-alive 挂死
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            latency = time.time() - t0
            status = r.status
            try:
                data = json.loads(r.read())
                in_tok = data.get("usage", {}).get("prompt_tokens", 0)
                out_tok = data.get("usage", {}).get("completion_tokens", 0)
            except Exception:
                in_tok = out_tok = 0
    except urllib.error.HTTPError as e:
        latency = time.time() - t0
        status = e.code
        in_tok = out_tok = 0
    except Exception as e:
        latency = time.time() - t0
        status = -1
        in_tok = out_tok = 0
    with results_lock:
        results.append((status, latency, in_tok, out_tok))
        log_line(f"[{i:03d}] status={status} latency={latency*1000:.1f}ms in_tok={in_tok} out_tok={out_tok}")

# 节流：start_time + i/rate 时刻发第 i 个
sem = threading.Semaphore(concurrency)
threads = []
for i in range(n_reqs):
    if rate > 0:
        target = start_time + i / rate
        delay = target - time.time()
        if delay > 0:
            time.sleep(delay)
    sem.acquire()
    t = threading.Thread(target=one_req, args=(i,), daemon=True)
    t.start()
    threads.append(t)
    # 如果已经超时就不再启动新 thread
    if time.time() > deadline:
        print(f"traffic: deadline hit before starting all threads (i={i+1}/{n_reqs})", flush=True)
        break

# 等所有 thread 完成，但带总 deadline（不再无限 join）
remaining = deadline - time.time()
for t in threads:
    t.join(timeout=max(0.1, remaining))
    remaining = deadline - time.time()
    if remaining <= 0:
        print("traffic: deadline hit during join; some requests may be incomplete", flush=True)
        break

elapsed = time.time() - start_time
ok = sum(1 for s, *_ in results if s == 200)
fail = len(results) - ok
total_in = sum(r[2] for r in results)
total_out = sum(r[3] for r in results)
latencies = sorted(r[1] for r in results if r[0] == 200)
def pct(p):
    if not latencies: return 0
    k = max(0, min(len(latencies) - 1, int(p * (len(latencies) - 1))))
    return latencies[k]

# 在 per-request 行前面插入统计 header（保持先 header 后 per-req 的顺序）
header = (
    f"requests:     {n_reqs}\n"
    f"completed:    {len(results)}\n"
    f"ok:           {ok}\n"
    f"fail:         {fail}\n"
    f"elapsed:      {elapsed:.2f}s\n"
    f"throughput:   {len(results)/elapsed:.2f} req/s (over completed)\n"
    f"in_tokens:    {total_in}\n"
    f"out_tokens:   {total_out}\n"
    f"in_tps:       {total_in/elapsed:.2f} tok/s\n"
    f"out_tps:      {total_out/elapsed:.2f} tok/s\n"
    f"latency_p50:  {pct(0.50)*1000:.1f} ms\n"
    f"latency_p90:  {pct(0.90)*1000:.1f} ms\n"
    f"latency_p99:  {pct(0.99)*1000:.1f} ms\n"
    f"\n--- per-request ---\n"
)
# 把 header 插到 log_path 顶部（per-req 行已经写完了）
log_fh.close()
with open(log_path, "r+") as f:
    body = f.read()
    f.seek(0)
    f.write(header + body)
    f.truncate()

print(f"traffic: ok={ok} fail={fail} completed={len(results)}/{n_reqs} elapsed={elapsed:.2f}s tps={len(results)/elapsed:.2f} out_tps={total_out/elapsed:.2f}", flush=True)
PY
)
    "${ENGINE_PYTHON:-python3}" -c "$traffic_script" \
      "$chat_url" "$API_KEY" "$SERVED_MODEL_NAME" \
      "$traffic_requests" "$traffic_concurrency" "$traffic_rate" \
      "$traffic_prompt" "$traffic_max_tokens" "$traffic_log" > "$out_dir/traffic.stdout" 2>&1 &
    traffic_pid=$!
    log_info "traffic generator started: pid=$traffic_pid, requests=$traffic_requests, concurrency=$traffic_concurrency"
  fi

  while [[ $(date +%s) -lt $end_time ]]; do
    snap_idx=$((snap_idx + 1))
    local snap_file="$out_dir/$(printf '%04d' "$snap_idx")-$(date +%H%M%S).prom"
    if "${ENGINE_PYTHON:-python3}" -c "$probe" "$url" > "$snap_file" 2>/dev/null; then
      printf "  [%s] snap %04d  %s  (%d bytes)\n" \
        "$(date +%H:%M:%S)" "$snap_idx" "$(basename "$snap_file")" \
        "$(wc -c < "$snap_file")"
    else
      failed=$((failed + 1))
      printf "  [%s] snap %04d  FAILED\n" "$(date +%H:%M:%S)" "$snap_idx"
    fi

    # 采集 npu-smi 指标（温度、功耗、利用率、HBM）
    local npu_csv="$out_dir/npu-smi.csv"
    if [[ ! -f "$npu_csv" ]]; then
      echo "timestamp,temp_c,power_w,util_pct,hbm_gb" > "$npu_csv"
    fi
    if command -v npu-smi >/dev/null 2>&1; then
      local npu_line
      npu_line=$(python3 -c "
import subprocess, sys, re
dev = '${NPU_DEVICES:-0}'
try:
    def get_val(cmd, patterns):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        for pat in patterns:
            for l in r.stdout.split('\n'):
                m = re.search(pat, l)
                if m: return m.group(1)
        return 'N/A'

    t = get_val(['npu-smi','info','-t','temp','-i',dev], [r'Temperature\s*:\s*(\d+)', r'Temperature\s*\(C\)\s*:\s*(\d+)'])
    p = get_val(['npu-smi','info','-t','power','-i',dev], [r'Power\s*\(W\)\s*:\s*([\d.]+)'])
    u = get_val(['npu-smi','info','-t','usages','-i',dev], [r'Aicore Usage.*:\s*(\d+)', r'Utilization.*:\s*(\d+)'])
    r2 = subprocess.run(['npu-smi','info','-t','usages','-i',dev], capture_output=True, text=True, timeout=3)
    hbm_cap = hbm_pct = 0
    for l in r2.stdout.split('\n'):
        if 'HBM Capacity' in l:   hbm_cap = float(re.search(r'(\d+)', l.split(':')[-1]).group(1))
        if 'HBM Usage Rate' in l: hbm_pct = float(re.search(r'(\d+)', l.split(':')[-1]).group(1))
    h = round(hbm_cap * hbm_pct / 100, 1) if hbm_cap > 0 else 'N/A'
    print(f'{t},{p},{u},{h}')
except Exception as e:
    print(f'N/A,N/A,N/A,N/A')
    sys.stderr.write(f'npu-smi err: {e}\\n')
" 2>/dev/null || echo "N/A,N/A,N/A,N/A")
      echo "$(date +%Y%m%d-%H%M%S),$npu_line" >> "$npu_csv"
    fi

    sleep "$interval"
  done

  # 等 traffic 结束（如果还在跑）；用 timeout 包一层兜底
  if [[ -n "$traffic_pid" ]]; then
    log_info "waiting for traffic generator to finish (pid=$traffic_pid)..."
    # python 端有 wall-clock deadline（~rate_dur + 30s + 60s min），这里 timeout 留余量
    # rate=0 全速时按 90s 兜底
    local wait_s=120
    if (( rate_dur_s > 0 )); then
      wait_s=$(( rate_dur_s + 90 ))
    fi
    # 不能用 `timeout N bash -c "wait $pid"` — 子 shell 没有 child job，wait 立即返回 0
    # 改用 kill -0 轮询（不阻塞、设上限）
    local waited=0
    while (( waited < wait_s )); do
      if ! kill -0 "$traffic_pid" 2>/dev/null; then
        log_ok "traffic generator done after ${waited}s"
        break
      fi
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$traffic_pid" 2>/dev/null; then
      log_warn "traffic generator still running after ${wait_s}s; force-killing pid=$traffic_pid"
      kill -9 "$traffic_pid" 2>/dev/null || true
    fi
    if [[ "$bench_started" == "true" ]] && [[ -f "$bench_log" ]]; then
      tail -5 "$bench_log"
    elif [[ -f "$out_dir/traffic.stdout" ]]; then
      tail -3 "$out_dir/traffic.stdout"
    fi
  fi

  # 抓 final snapshot（traffic 跑完后状态更准确反映"实际"metrics）
  snap_idx=$((snap_idx + 1))
  local final_file="$out_dir/$(printf '%04d' "$snap_idx")-$(date +%H%M%S)-final.prom"
  if "${ENGINE_PYTHON:-python3}" -c "$probe" "$url" > "$final_file" 2>/dev/null; then
    log_ok "final snapshot: $final_file"
  fi

  # 写 summary
  local last_snap; last_snap="$(ls -1 "$out_dir"/*.prom 2>/dev/null | tail -1 || true)"
  local first_snap; first_snap="$(ls -1 "$out_dir"/*.prom 2>/dev/null | head -1 || true)"
  local summary="$out_dir/summary.txt"
  {
    echo "=== engine profile summary ($label @ $ts) ==="
    echo "duration:    ${duration}s"
    echo "interval:    ${interval}s"
    echo "samples:     $snap_idx (failed: $failed)"
    echo "output_dir:  $out_dir"
    if (( traffic_requests > 0 )); then
      echo "backend:     $traffic_backend"
    fi
    # bench result
    if (( traffic_requests > 0 )) && [[ "$bench_started" == "true" ]] && [[ -f "$bench_json" ]]; then
      echo
      echo "--- bench result ---"
      python3 -c "
import json, sys
d = json.load(open('$bench_json'))
print(f\"dataset:              {d.get('backend','?')}\")
print(f\"num_prompts:          {d.get('num_prompts','?')}\")
print(f\"completed:            {d.get('completed','?')}  fail: {d.get('failed','?')}\")
print(f\"duration:             {d.get('duration',0):.2f}s\")
print(f\"request_throughput:   {d.get('request_throughput',0):.2f} req/s\")
print(f\"output_throughput:    {d.get('output_throughput',0):.2f} tok/s\")
print(f\"total_token_throughput: {d.get('total_token_throughput',0):.2f} tok/s\")
print(f\"total_input_tokens:   {d.get('total_input_tokens','?')}\")
print(f\"total_output_tokens:  {d.get('total_output_tokens','?')}\")
print(f\"mean_ttft_ms:         {d.get('mean_ttft_ms',0):.1f}  p99_ttft_ms: {d.get('p99_ttft_ms',0):.1f}\")
print(f\"mean_tpot_ms:         {d.get('mean_tpot_ms',0):.1f}  p99_tpot_ms: {d.get('p99_tpot_ms',0):.1f}\")
print(f\"mean_itl_ms:          {d.get('mean_itl_ms',0):.1f}  p99_itl_ms: {d.get('p99_itl_ms',0):.1f}\")
print(f\"max_concurrency:      {d.get('max_concurrency','?')}  peak: {d.get('max_concurrent_requests','?')}\")
" 2>/dev/null || echo "(failed to parse $bench_json)"
    elif (( traffic_requests > 0 )) && [[ -f "$traffic_log" ]]; then
      echo
      echo "--- traffic ---"
      cat "$traffic_log"
    fi
    # metrics delta: first snap vs final snap
    if [[ -n "$first_snap" && -n "$last_snap" && "$first_snap" != "$last_snap" ]]; then
      echo
      echo "--- metrics delta (snap 1 → final) ---"
      python3 -c "
import re, sys
def parse(fn):
    d = {}
    for line in open(fn):
        m = re.match(r'^(vllm:\S+)(\{[^}]*\})?\s+(\S+)', line)
        if not m: continue
        name, labels, val = m.group(1), m.group(2) or '', m.group(3)
        key = name + labels
        try: d[key] = float(val)
        except: pass
    return d
f, l = parse('$first_snap'), parse('$last_snap')
keys = [
    'vllm:prompt_tokens_total{engine=\"0\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:generation_tokens_total{engine=\"0\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:request_success_total{engine=\"0\",finished_reason=\"stop\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:request_success_total{engine=\"0\",finished_reason=\"length\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:request_success_total{engine=\"0\",finished_reason=\"error\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:kv_cache_usage_perc{engine=\"0\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:num_requests_running{engine=\"0\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:e2e_request_latency_seconds_count{engine=\"0\",model_name=\"qwen2.5-0.5b\"}',
    'vllm:e2e_request_latency_seconds_sum{engine=\"0\",model_name=\"qwen2.5-0.5b\"}',
]
short = {
    'vllm:prompt_tokens_total': 'prompt_tokens_total',
    'vllm:generation_tokens_total': 'generation_tokens_total',
    'vllm:request_success_total{engine=\"0\",finished_reason=\"stop': 'request_success{stop}',
    'vllm:request_success_total{engine=\"0\",finished_reason=\"length': 'request_success{length}',
    'vllm:request_success_total{engine=\"0\",finished_reason=\"error': 'request_success{error}',
    'vllm:kv_cache_usage_perc': 'kv_cache_usage_perc',
    'vllm:num_requests_running': 'num_requests_running',
    'vllm:e2e_request_latency_seconds_count': 'e2e_latency_count',
    'vllm:e2e_request_latency_seconds_sum': 'e2e_latency_sum',
}
for k in keys:
    v1 = f.get(k, 0)
    v2 = l.get(k, 0)
    diff = v2 - v1
    # find short name
    sn = k.split('{')[0]
    for prefix, name in short.items():
        if k.startswith(prefix):
            sn = name
            break
    if abs(diff) < 0.01 and 'kv_cache' not in sn and 'running' not in sn:
        print(f'  {sn:30s} {v1:.0f} → {v2:.0f}  (+0)')
    elif 'kv_cache' in sn or 'running' in sn:
        print(f'  {sn:30s} {v1:.4f} → {v2:.4f}')
    else:
        print(f'  {sn:30s} {v1:.0f} → {v2:.0f}  (+{diff:.0f})')
" 2>/dev/null || echo "(failed to compute metrics delta)"
    fi
    if [[ -n "$last_snap" ]]; then
      echo "last_snap:   $last_snap"
      echo
      echo "--- last snapshot: key vllm:* metrics ---"
      # vllm: 指标可能带 {labels}，所以用 [:{ ] 匹配 metric name 后的边界
      grep -E "^vllm:(num_requests_(running|waiting|swapped)|kv_cache_usage_perc|prefix_cache_(queries|hits)_total|request_success_total|prompt_tokens_total|generation_tokens_total|e2e_request_latency_seconds_(sum|count)|time_per_output_token_seconds_(sum|count)|gpu_cache_usage_perc|engine_uptime_seconds|model_forward_total_time_seconds)([{ ])" "$last_snap" 2>/dev/null | head -40
    fi
    echo
    echo "--- engine log tail (last 40 lines) ---"
    tail -40 "$LOG_FILE" 2>/dev/null
  } > "$summary"
  echo
  log_ok "done. summary: $summary"
  log_ok "snapshots:  $out_dir"
}

# ===== P4: profile --kind torch（vllm 内置 PyTorch profiler） =====
# 关键约束（vllm-hust）：
# - torch profiler 通过 --profiler-config '{profiler:torch, torch_profiler_dir:...}' CLI arg 注入
# - 运行时通过 POST /start_profile 启动，POST /stop_profile 触发 dump
# - 必须在 start vllm 之前设好 --profiler-config
# - 我们用 PROFILE_TORCH_DIR 这个临时 env 通知 build_vllm_args 注入 profiler-config
# 流程：
# 1) backup state.env
# 2) stop 现有 engine
# 3) export PROFILE_TORCH_DIR, cmd_start（vllm 启动时就带 --profiler-config）
# 4) POST /start_profile
# 5) 驱动 N 条请求
# 6) POST /stop_profile（vllm dump *.pt.trace.json.gz 到 torch_profiler_dir）
# 7) stop engine
# 8) 恢复 state.env + （默认）cmd_start 恢复原 engine
profile_torch() {
  local label="$1" requests="$2" no_autostart="$3"
  require_api_key "profile --kind torch"
  local ts; ts="$(date +%Y%m%d-%H%M%S)"
  local out_dir="$PROFILE_OUTPUT_DIR/torch/${label}-${ts}"
  mkdir -p "$out_dir"

  local was_running="false"
  is_engine_running && was_running="true"

  local state_bak="$LOG_DIR/state.env.torch-bak"
  if [[ -f "$STATE_FILE" ]]; then
    cp -f "$STATE_FILE" "$state_bak"
    log_dim "state backed up: $state_bak"
  else
    rm -f "$state_bak"
  fi

  # 关键 env 覆盖备份：CLI --config 不写进 state.env，所以单独存。
  # 这样测完 cmd_start 恢复原 engine 时，能用 profile-torch 跑时实际用的 NPU，
  # 而不是 fallback 到 profile 文件里的默认值。
  local cfg_bak="$LOG_DIR/state.env.torch-cfg-bak"
  {
    for k in VLLM_ENGINE_NPU_DEVICES ASCEND_RT_VISIBLE_DEVICES ASCEND_VISIBLE_DEVICES \
             VLLM_ENGINE_PORT VLLM_ENGINE_GPU_MEM_UTIL VLLM_ENGINE_MAX_MODEL_LEN \
             VLLM_ENGINE_TP_SIZE VLLM_ENGINE_MAX_NUM_SEQS; do
      v="${!k:-}"
      [[ -n "$v" ]] && printf '%s=%q\n' "$k" "$v"
    done
  } > "$cfg_bak"
  log_dim "cfg backed up: $cfg_bak"

  echo
  echo -e "${C_BLU}=== profile --kind torch ===${C_RST}"
  echo "  label:         $label"
  echo "  requests:      $requests"
  echo "  with_stack:    $PROFILE_TORCH_WITH_STACK"
  echo "  keep_engine:   $PROFILE_TORCH_KEEP"
  echo "  was_running:   $was_running"
  echo "  output:        $out_dir"
  echo

  if [[ "$no_autostart" == "true" && "$was_running" != "true" ]]; then
    log_err "engine not running and --no-autostart set; start it manually first"
    rm -f "$state_bak"
    exit 1
  fi

  # 1) stop 现有 engine（如果有）
  if [[ "$was_running" == "true" ]]; then
    log_info "stopping current engine to inject --profiler-config..."
    cmd_stop || true
    sleep 1
  fi

  # 2) 告诉 build_vllm_args 注入 --profiler-config
  export PROFILE_TORCH_DIR="$out_dir"
  export PROFILE_TORCH_WITH_STACK="$PROFILE_TORCH_WITH_STACK"
  export VLLM_PROFILE_TORCH_KEEP="$PROFILE_TORCH_KEEP"

  # 3) start engine（带 --profiler-config）
  log_info "starting engine with --profiler-config torch_profiler_dir=$out_dir"
  cmd_start || {
    log_err "engine start failed; check $LOG_FILE"
    unset PROFILE_TORCH_DIR PROFILE_TORCH_WITH_STACK
    rm -f "$state_bak"
    exit 1
  }

  # 4) POST /start_profile
  log_info "POST /start_profile ..."
  profile_control start || log_warn "start_profile failed; trace may still be captured if profiler config injected correctly"

  # 5) 驱动请求
  log_info "driving $requests chat requests under torch profiler..."
  drive_chat_requests "$requests" "用一句话介绍华为昇腾 910B。" 32

  # 6) POST /stop_profile（vllm dump）
  log_info "POST /stop_profile ..."
  # 注：profile_control 内部 python urlopen 已经 120s；不要包 timeout（bash function timeout 找不到）
  if ! profile_control stop; then
    log_warn "stop_profile failed; traces may still be on disk"
  fi

  log_info "sleeping 5s for vllm to flush dumps..."
  sleep 5

  # 7) stop engine、清理 profile env
  unset PROFILE_TORCH_DIR PROFILE_TORCH_WITH_STACK
  log_info "stopping profile-mode engine..."
  cmd_stop || true
  sleep 1

  # 8) 恢复原 state
  if [[ -f "$state_bak" ]]; then
    cp -f "$state_bak" "$STATE_FILE"
    log_dim "state restored from $state_bak"
  fi
  rm -f "$state_bak"

  # 9) 归档 + summary
  local traces; traces="$(ls -1 "$out_dir"/*.pt.trace.json.gz 2>/dev/null || true)"
  local trace_count=0
  [[ -n "$traces" ]] && trace_count=$(echo "$traces" | wc -l)
  local last_trace=""
  [[ -n "$traces" ]] && last_trace="$(echo "$traces" | tail -1)"

  local summary="$out_dir/summary.txt"
  {
    echo "=== torch profile summary ($label @ $ts) ==="
    echo "requests:      $requests"
    echo "with_stack:    $PROFILE_TORCH_WITH_STACK"
    echo "output_dir:    $out_dir"
    echo "trace_count:   $trace_count"
    if [[ -n "$last_trace" ]]; then
      echo "last_trace:    $last_trace"
      echo "last_size:     $(wc -c < "$last_trace") bytes"
    fi
    echo
    echo "--- trace files ---"
    if [[ -n "$traces" ]]; then
      ls -la "$out_dir"/*.pt.trace.json.gz
    else
      echo "(no *.pt.trace.json.gz found)"
    fi
    echo
    echo "--- engine log tail (profiler / start_profile / stop_profile / Saved) ---"
    grep -E "Saved profiling|start_profile|stop_profile|profiler|Profil" "$LOG_FILE" 2>/dev/null | tail -30
    echo
    echo "View: open chrome and visit chrome://tracing, then load any *.pt.trace.json.gz"
  } > "$summary"

  echo
  if [[ $trace_count -gt 0 ]]; then
    log_ok "done. $trace_count trace(s) dumped."
  else
    log_warn "done but no *.pt.trace.json.gz found. Possible causes:"
    log_warn "  - /start_profile or /stop_profile failed (check summary tail)"
    log_warn "  - vllm engine crashed mid-profile (check $LOG_FILE)"
    log_warn "  - profiler_config injection rejected (vllm 0.23.x ProfilerConfig should accept 'torch_profiler_dir')"
  fi
  log_ok "summary:     $summary"
  log_ok "output_dir:  $out_dir"

  # 10) 恢复原 engine（用 cfg_bak 把 CLI 覆盖重新注入到 cmd_start 的子 shell）
  if [[ "$was_running" == "true" && "$PROFILE_TORCH_KEEP" != "1" ]]; then
    log_info "restoring original engine (with cfg from profile-torch run)..."
    if [[ -f "$cfg_bak" ]]; then
      # 归档一份 cfg_bak 到 out_dir，方便事后看测前 env
      cp -f "$cfg_bak" "$out_dir/cfg.env" 2>/dev/null || true
      set -a
      # shellcheck disable=SC1090
      source "$cfg_bak"
      set +a
    fi
    cmd_start
  fi
  rm -f "$cfg_bak"
}

# ===== P5: profile --kind msprof（CANN kernel 级 profiler） =====
# 关键约束：msprof 独占 NPU，与已存在的 vllm 冲突（drvErr=87），因此
# - 检测到 engine 在跑就 abort，让用户先 stop
# - msprof 作为 vllm serve 的父进程（--application=）启动
# - 等 msprof --duration 到点自动结束 vllm
# - 之后 msprof --export=on 导出 timeline / kernel csv
profile_msprof() {
  local label="$1" duration="$2" requests="$3" no_autostart="$4"
  require_api_key "profile --kind msprof"
  local ts; ts="$(date +%Y%m%d-%H%M%S)"
  local out_dir="$PROFILE_OUTPUT_DIR/msprof/${label}-${ts}"
  local msprof_log="$LOG_DIR/msprof-${label}-${ts}.log"
  local msprof_pid_file="$LOG_DIR/msprof.pid"
  mkdir -p "$out_dir"

  echo
  echo -e "${C_BLU}=== profile --kind msprof ===${C_RST}"
  echo "  label:         $label"
  echo "  duration:      ${duration}s"
  echo "  requests:      $requests"
  echo "  aic_metrics:   $PROFILE_MSPROF_AIC_METRICS"
  echo "  task_memory:   $PROFILE_MSPROF_TASK_MEMORY"
  echo "  sys_profiling: $PROFILE_MSPROF_SYS_PROFILING"
  echo "  output:        $out_dir"
  echo

  if is_engine_running; then
    log_err "engine is running; msprof requires exclusive NPU. Run '$SCRIPT_NAME stop' first."
    exit 1
  fi

  if [[ "$no_autostart" == "true" ]]; then
    log_err "--no-autostart not supported for --kind msprof (msprof must start vllm itself)"
    exit 1
  fi

  # 注：port 8000 经常被外部 orphan uvicorn 占用，wait_for_health 会拿到 false-positive
  # 的 200 OK。msprof 下无法 bind 8000 也会让 vllm 启动失败但 msprof 看起来已起来。
  # 检测端口冲突并显式 abort，让用户换一个端口。
  if port_in_use "$PORT"; then
    log_err "port $PORT is in use (likely orphan vllm/uvicorn). msprof requires exclusive port. Use --config VLLM_ENGINE_PORT=<free-port>"
    exit 1
  fi

  local msprof_bin
  if ! msprof_bin="$(msprof_bin_resolve)"; then
    log_err "msprof not found. Set --msprof-bin or VLLM_PROFILE_MSPROF_BIN. Tried: $PROFILE_MSPROF_BIN"
    exit 1
  fi
  log_dim "msprof: $msprof_bin"

  activate_envs
  build_vllm_args
  export_engine_env

  # 拼出 msprof 启动脚本（写到临时文件，no_autostart 同理；这里是为了日志清晰）
  local msprof_script; msprof_script="$(mktemp "$LOG_DIR/.msprof.XXXX.sh")"
  build_msprof_command "$msprof_bin" "$out_dir" "$duration" > "$msprof_script"
  chmod +x "$msprof_script"
  log_dim "msprof script: $msprof_script"
  log_dim "msprof script content:"
  sed 's/^/    /' "$msprof_script" | head -15
  # 临时保留脚本方便诊断（profile_msprof 末尾不删）

  # 启动 msprof 包住 vllm serve
  # 注意：必须用 setsid 完全脱离终端，否则非交互 bash 的 job control
  # 会在后台进程尝试读取 tty 时将其挂起（SIGTTIN）。
  setsid bash "$msprof_script" < /dev/null >> "$msprof_log" 2>&1 &
  local msprof_pid=$!
  echo "$msprof_pid" > "$msprof_pid_file"
  disown 2>/dev/null || true
  log_info "msprof started pid=$msprof_pid (logging to $msprof_log)"

  # 等就绪：复用 wait_for_health
  log_info "waiting for engine under msprof to become healthy (timeout ${HEALTH_TIMEOUT}s)..."
  if ! wait_for_health "$HEALTH_TIMEOUT"; then
    log_err "engine under msprof did not become healthy in ${HEALTH_TIMEOUT}s; check $msprof_log"
    kill -TERM "$msprof_pid" 2>/dev/null || true
    pkill -9 -f "VLLM::EngineCore" 2>/dev/null || true
    rm -f "$msprof_pid_file"
    exit 1
  fi

  # 驱动请求
  log_info "driving $requests chat requests under msprof..."
  drive_chat_requests "$requests" "用中文写 30 字短文：介绍华为昇腾 910B。" 48

  # 等 msprof 到点自动结束
  log_info "waiting ${duration}s for msprof to auto-finish (and vllm to exit)..."
  sleep "$duration"
  # 多给几秒让 msprof 收尾
  sleep 5
  # 兜底：msprof 还活着就强杀（避免 hang）
  if kill -0 "$msprof_pid" 2>/dev/null; then
    log_warn "msprof still alive after ${duration}s; sending SIGTERM"
    kill -TERM "$msprof_pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "$msprof_pid" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$msprof_pid" 2>/dev/null || true
  fi
  pkill -9 -f "VLLM::EngineCore" 2>/dev/null || true
  rm -f "$msprof_pid_file"
  # 不删 msprof_script（保留供事后诊断 msprof 命令行）
  rm -f "$PID_FILE" 2>/dev/null || true
  clear_state 2>/dev/null || true

  # export：binary → csv / json
  log_info "exporting msprof data..."
  local export_log="$out_dir/export.log"
  if "$msprof_bin" --export=on --output="$out_dir" >> "$export_log" 2>&1; then
    log_ok "msprof export ok"
  else
    log_warn "msprof export failed (rc=$?); see $export_log"
  fi

  # 归档
  local prof_dir
  prof_dir="$(find "$out_dir" -maxdepth 2 -type d -name 'PROF_*' | head -1 || true)"
  local summary="$out_dir/summary.txt"
  {
    echo "=== msprof summary ($label @ $ts) ==="
    echo "duration:      ${duration}s"
    echo "requests:      $requests"
    echo "output_dir:    $out_dir"
    if [[ -n "$prof_dir" ]]; then
      echo "prof_dir:      $prof_dir"
    fi
    echo
    echo "--- top-level ---"
    ls -la "$out_dir"
    echo
    if [[ -n "$prof_dir" ]]; then
      echo "--- PROF dir top-level ---"
      ls -la "$prof_dir" 2>/dev/null | head -20
      echo
      echo "--- exported artifacts (csv/json) ---"
      find "$prof_dir" -maxdepth 3 -type f \( -name "*.csv" -o -name "*.json" -o -name "*.db" \) 2>/dev/null | head -30
    fi
    echo
    echo "View: open MindStudio Insight, import PROF_* dir as project."
  } > "$summary"

  # 自动调用 TraceLoom 分析（如果可用）
  local prof_dir_for_tl
  prof_dir_for_tl="$(find "$out_dir" -maxdepth 2 -type d -name 'PROF_*' | head -1 || true)"
  if [[ -n "$prof_dir_for_tl" ]] && command -v traceloom >/dev/null 2>&1; then
    local traceloom_out="$out_dir/traceloom"
    log_info "running TraceLoom analysis on $prof_dir_for_tl ..."
    mkdir -p "$traceloom_out"
    if traceloom analysis "$prof_dir_for_tl" --out-dir "$traceloom_out" >> "$out_dir/traceloom.log" 2>&1; then
      log_ok "TraceLoom analysis complete: $traceloom_out/summary.md"
    else
      log_warn "TraceLoom analysis failed (rc=$?); see $out_dir/traceloom.log"
    fi
  elif [[ -n "$prof_dir_for_tl" ]]; then
    log_dim "traceloom not on PATH; skip post-msprof analysis (install: pip install traceloom)"
  fi

  echo
  log_ok "done. summary: $summary"
  log_ok "output_dir:  $out_dir"
}

# ===== 入口 =====
main() {
  parse_args "$@"
  case "$ACTION" in
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    status)     cmd_status ;;
    health)     cmd_health ;;
    logs)       cmd_logs ;;
    config)     cmd_config ;;
    foreground) cmd_foreground ;;
    profile)    cmd_profile "${REST_ARGS[@]}" ;;
    benchmark)  cmd_benchmark "${REST_ARGS[@]}" ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
