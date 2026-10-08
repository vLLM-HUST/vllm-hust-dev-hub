"""Common native/BidKV V1 SD-layout Mamba kernel ABI adapter.

Core 752a3a5 adds DS-layout metadata and V2 index mapping; Ascend 9bf964c
implements the V1 SD kernel. Reject unsupported modes rather than dropping them.
"""

from vllm_ascend.worker.worker import NPUWorker


class V1SDKernel:
    def __init__(self, kernel):
        self.kernel = kernel

    def __getitem__(self, grid):
        def launch(*args, **kwargs):
            if len(args) != 18:
                raise RuntimeError(
                    "Expected pinned core Mamba ABI with18 positional arguments"
                )
            if args[16] is not None or kwargs.get("CONV_STATE_DIM_FIRST", True):
                raise RuntimeError("Mamba ABI bridge supports only V1 SD layout")
            if kwargs.get("HAS_IDX_MAPPING", False) or kwargs.get(
                "PRECOMPUTED_NEW_COMPUTED", False
            ):
                raise RuntimeError("Mamba V2 semantics are unsupported by this bridge")
            kwargs = dict(kwargs)
            for name in (
                "CONV_STATE_DIM_FIRST",
                "HAS_IDX_MAPPING",
                "PRECOMPUTED_NEW_COMPUTED",
            ):
                kwargs.pop(name, None)
            return self.kernel[grid](*args[:13], args[15], args[17], **kwargs)

        return launch


class Worker(NPUWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from vllm.model_executor.layers.mamba.mamba_utils import is_conv_state_dim_first
        from vllm.v1.worker import mamba_utils
        from vllm_ascend.ops.triton.mamba.postprocess import (
            postprocess_mamba_fused_kernel,
        )

        if is_conv_state_dim_first():
            raise RuntimeError("This qualified bridge requires SD conv state layout")
        mamba_utils.postprocess_mamba_fused_kernel = V1SDKernel(
            postprocess_mamba_fused_kernel
        )
