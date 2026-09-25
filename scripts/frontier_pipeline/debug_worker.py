"""Diagnostic-only PP inputs/samples; never use for performance windows."""

import json
from pathlib import Path

from pipeline_worker import Worker as BaseWorker


class Worker(BaseWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._audit_step = 0
        self._audit_batch = None

    def _audit(self, kind, values):
        if self._audit_batch is None or self._audit_step > 32:
            return
        root = Path(
            "/home/coder/frontier-mods-qwen35-20260925/phase2/debug-pipeline-r3"
        )
        root.mkdir(exist_ok=True)
        with (root / f"rank-{self.rank}.jsonl").open("a") as stream:
            stream.write(
                json.dumps(dict(step=self._audit_step, kind=kind, **values)) + "\n"
            )

    def init_device(self):
        super().init_device()
        runner = self.model_runner
        forward = runner._model_forward
        sample = runner._sample

        def traced_forward(num_tokens, input_ids, positions, *args, **kwargs):
            if self._audit_batch is not None and self._audit_step <= 32:
                n = runner.input_batch.num_reqs
                self._audit(
                    "forward",
                    dict(
                        input_ids=input_ids[:16].tolist(),
                        positions=positions[..., :16].tolist(),
                        request_ids=runner.input_batch.req_ids,
                        computed=runner.input_batch.num_computed_tokens_cpu[
                            :n
                        ].tolist(),
                        accepted=runner.num_accepted_tokens.gpu[:n].tolist(),
                        scheduled=self._audit_batch.num_scheduled_tokens,
                        drafts=self._audit_batch.scheduled_spec_decode_tokens,
                    ),
                )
            return forward(num_tokens, input_ids, positions, *args, **kwargs)

        def traced_sample(logits, metadata):
            output = sample(logits, metadata)
            self._audit(
                "sample",
                dict(
                    tokens=output.sampled_token_ids.tolist(),
                    target_argmax=logits.argmax(-1).tolist(),
                ),
            )
            return output

        runner._model_forward = traced_forward
        runner._sample = traced_sample

    def execute_model(self, scheduler_output):
        self._audit_step += 1
        self._audit_batch = scheduler_output
        return super().execute_model(scheduler_output)
