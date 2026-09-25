#!/bin/bash
set -eo pipefail
cd /home/coder/frontier-mods-qwen35-20260925/phase2
source /usr/local/Ascend/cann/set_env.sh
source /usr/local/Ascend/nnal/atb/set_env.sh
set -u
export PATH="/home/coder/frontier-mods-qwen35-20260925/.venv/bin:$PATH"
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3
export OMP_NUM_THREADS=1
export TASK_QUEUE_ENABLE=1
export VLLM_VERSION=0.25.1
export PYTHONPATH="/home/coder/frontier-mods-qwen35-20260925/phase2:/home/coder/frontier-mods-qwen35-20260925/phase2/core:/home/coder/frontier-mods-qwen35-20260925/phase2/ascend-wheel:/home/coder/frontier-mods-qwen35-20260925/phase2/plugin/src:/home/coder/frontier-mods-qwen35-20260925:${PYTHONPATH:-}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
unset FRONTIER_PP_CALIBRATION_DIR
exec /home/coder/frontier-mods-qwen35-20260925/.venv/bin/vllm serve /home/coder/frontier-mods-qwen35-20260925/model --host 127.0.0.1 --port 33782 --served-model-name frontier-qwen35-pp2 --tensor-parallel-size 2 --pipeline-parallel-size 2 --distributed-executor-backend mp --worker-cls pipeline_worker.Worker --dtype bfloat16 --kv-cache-dtype auto --max-model-len 262144 --max-num-seqs 16 --max-num-batched-tokens 4096 --gpu-memory-utilization 0.95 --seed 17 --enable-prefix-caching --mamba-cache-mode align --enable-prompt-tokens-details --async-scheduling --shutdown-timeout 60 --additional-config '{"enable_cpu_binding":false}' --limit-mm-per-prompt '{"image":0,"video":0}' --compilation-config '{"cudagraph_mode": "FULL_AND_PIECEWISE", "cudagraph_capture_sizes": [3, 6, 12, 24, 48], "max_cudagraph_capture_size": 48}' --speculative-config '{"method": "mtp", "num_speculative_tokens": 2}' --generation-config vllm --override-generation-config '{"temperature": 0.0, "top_p": 1.0, "top_k": -1, "presence_penalty": 0.0}' --default-chat-template-kwargs '{"enable_thinking":true}' --kv-cache-memory-bytes 26038239232 --batch-admission-policy vllm_hust_pipeline_microbatch.policy.PipelineMicrobatchPolicy --batch-admission-policy-config '{"mode":"calibrated","model_ids":["/home/coder/frontier-mods-qwen35-20260925/model"],"pipeline_parallel_size":2,"tensor_parallel_size":2,"microbatch_count":2,"cost_models":[{"pp_rank":0,"layer_num":20,"p0":0,"p1":2.337736504957753,"p2":0,"p3":0.0013904910859525073,"p4":0,"p5":41.526477773684775},{"pp_rank":0,"layer_num":20,"p0":0,"p1":2.3378393230092156,"p2":0,"p3":0.0013986642534462414,"p4":0,"p5":41.495214833677984},{"pp_rank":1,"layer_num":20,"p0":0,"p1":2.1554347273584242,"p2":0,"p3":0.001427110719812561,"p4":0,"p5":42.069390809437735},{"pp_rank":1,"layer_num":20,"p0":0,"p1":2.179656307253565,"p2":0,"p3":0.0014240655999693246,"p4":0,"p5":42.03938134034371}]}'
