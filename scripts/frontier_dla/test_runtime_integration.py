"""Actual host allocator/API integration; run inside the assigned container.

These are CPU metadata tests, not inference performance or hardware qualification.
"""

from types import SimpleNamespace

import pytest
import torch

from vllm.config import SchedulerConfig
from vllm.sampling_params import SamplingParams
from vllm.v1.core.kv_cache_manager import KVCacheManager
from vllm.v1.core.sched.preemption import (
    PreemptionCandidate,
    PreemptionContext,
    PreemptionPolicyController,
)
from vllm.v1.kv_cache_interface import (
    FullAttentionSpec,
    KVCacheConfig,
    KVCacheGroupSpec,
    MambaSpec,
)
from vllm.v1.request import Request

from dla.preemption import DeclaredBudgetPreemptionPolicy


def manager(blocks, hybrid):
    groups = [
        KVCacheGroupSpec(
            ["attention"],
            FullAttentionSpec(
                block_size=16, num_kv_heads=1, head_size=2, dtype=torch.float16
            ),
        )
    ]
    if hybrid:
        groups.append(
            KVCacheGroupSpec(
                ["mamba"],
                MambaSpec(
                    block_size=16,
                    shapes=((64,),),
                    dtypes=(torch.float16,),
                    mamba_cache_mode="align",
                    num_speculative_blocks=2,
                ),
            )
        )
    return KVCacheManager(
        KVCacheConfig(num_blocks=blocks, kv_cache_tensors=[], kv_cache_groups=groups),
        max_model_len=1024,
        scheduler_block_size=16,
        hash_block_size=16,
        enable_caching=False,
    )


def request():
    return Request(
        request_id="budget-test",
        prompt_token_ids=[42] * 32,
        sampling_params=SamplingParams(max_tokens=160, ignore_eos=True),
        pooling_params=None,
        eos_token_id=0,
    )


@pytest.mark.parametrize("hybrid", [False, True])
def test_budget_capacity_changes_actual_allocator_admission(hybrid):
    native, candidate = manager(10, hybrid), manager(10, hybrid)
    assert native.allocate_slots(request(), 16, full_sequence_must_fit=True) is not None
    assert (
        candidate.allocate_slots(
            request(), 16, full_sequence_must_fit=True, reserve_output_budget=True
        )
        is None
    )
    assert candidate.output_budget_admission_stats == {
        "checks": 1,
        "extended_checks": 1,
        "deferred": 1,
        "passed": 0,
    }


@pytest.mark.parametrize("hybrid", [False, True])
def test_passing_budget_check_does_not_allocate_all_future_tokens(hybrid):
    cache = manager(32, hybrid)
    req = request()
    before = cache.block_pool.get_num_free_blocks()
    blocks = cache.allocate_slots(
        req, 16, full_sequence_must_fit=True, reserve_output_budget=True
    )
    assert blocks is not None
    assert sum(len(group) for group in blocks.get_block_ids()) < 12
    assert cache.output_budget_admission_stats["passed"] == 1
    cache.free(req)
    assert cache.block_pool.get_num_free_blocks() == before


def test_dla_runs_through_real_host_policy_controller():
    config = SimpleNamespace(
        additional_config={"dla_exact_output_budgets": True},
        scheduler_config=SimpleNamespace(
            preemption_policy=DeclaredBudgetPreemptionPolicy
        ),
    )
    controller = PreemptionPolicyController(config)
    context = PreemptionContext(
        candidates=(
            PreemptionCandidate("long", 0, 0, 32, 2, 34, 0, 160),
            PreemptionCandidate("near-finished", 0, 1, 32, 159, 191, 0, 160),
        ),
        scheduling_policy="fcfs",
        requesting_request_id="long",
        kv_cache_usage=0.95,
        now=2,
    )
    assert controller.select_victim(context) == "long"
    assert controller.stats.calls == controller.stats.selections == 1
    assert controller.stats.failures == 0


def test_scheduler_option_is_default_off_and_can_be_enabled():
    assert not SchedulerConfig(max_model_len=1024).scheduler_reserve_output_budget
    assert SchedulerConfig(
        max_model_len=1024, scheduler_reserve_output_budget=True
    ).scheduler_reserve_output_budget
