"""Common PP worker with opt-in, calibration-only NPU event receipts."""

import json
import os
from pathlib import Path

from frontier_worker import Worker as QualifiedWorker


class Worker(QualifiedWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._profile_dir = os.environ.get("FRONTIER_PP_CALIBRATION_DIR")
        self._prompt_lengths = {}
        self._profile_step = 0
        self._step_record = None

    def _record_call(self, kind, function, *args):
        if not self._profile_dir or not self._step_record:
            return function(*args)
        import torch
        from vllm.distributed import get_pp_group, get_tp_group

        start = torch.npu.Event(enable_timing=True)
        end = torch.npu.Event(enable_timing=True)
        start.record()
        output = function(*args)
        end.record()
        end.synchronize()
        record = {
            **self._step_record,
            "kind": kind,
            "elapsed_ms": start.elapsed_time(end),
            "pp_rank": get_pp_group().rank_in_group,
            "tp_rank": get_tp_group().rank_in_group,
            "scope": "Observed rank interval including communication and host gaps; calibration only, not a benchmark score",
        }
        path = Path(self._profile_dir) / f"rank-{self.rank}.jsonl"
        with path.open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        return output

    def execute_model(self, scheduler_output):
        if not self._profile_dir:
            return super().execute_model(scheduler_output)
        self._profile_step += 1
        for req_id in scheduler_output.finished_req_ids:
            self._prompt_lengths.pop(req_id, None)
        computed, generated = {}, {}
        for request in scheduler_output.scheduled_new_reqs:
            self._prompt_lengths[request.req_id] = len(request.prompt_token_ids)
            computed[request.req_id] = request.num_computed_tokens
            generated[request.req_id] = 0
        cached = scheduler_output.scheduled_cached_reqs
        computed.update(zip(cached.req_ids, cached.num_computed_tokens))
        generated.update(zip(cached.req_ids, cached.num_output_tokens))
        ids = tuple(scheduler_output.num_scheduled_tokens)
        self._step_record = None
        if ids:
            self._step_record = {
                "step": self._profile_step,
                "request_num": len(ids),
                "aggregated_ctx_length": sum(
                    self._prompt_lengths[r] + generated[r] for r in ids
                ),
                "scheduled_tokens": scheduler_output.total_num_scheduled_tokens,
                "decode_only": all(computed[r] >= self._prompt_lengths[r] for r in ids),
            }
        return self._record_call("execute", super().execute_model, scheduler_output)

    def sample_tokens(self, grammar_output):
        return self._record_call("sample", super().sample_tokens, grammar_output)
