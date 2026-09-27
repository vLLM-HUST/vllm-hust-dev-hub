"""Read actual preemption and declared-budget admission counter deltas."""

import re

POLICIES = {
    "bidkv": "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy",
    "dla": "dla.preemption.DeclaredBudgetPreemptionPolicy",
}
EVENTS = {"calls", "selections", "abstentions", "failures", "invalid_selections"}
ADMISSION = {"checks", "extended_checks", "deferred", "passed"}


def snapshot(path, program):
    values, admission, enabled = {}, {}, None
    policy = POLICIES[program]
    for line in path.read_text().splitlines():
        if line.startswith("vllm:preemption_policy_events{"):
            if f'policy="{policy}"' not in line:
                raise ValueError("Unexpected preemption policy")
            event = re.search(r'event="([^"]+)"', line).group(1)
            if event in values:
                raise ValueError("Multiple engines are unsupported")
            values[event] = float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:preemption_policy_enabled{"):
            if f'policy="{policy}"' not in line or enabled is not None:
                raise ValueError("Unexpected/multiple policy identities")
            enabled = float(line.rsplit(" ", 1)[1]) == 1
        elif line.startswith("vllm:output_budget_admission_events{"):
            event = re.search(r'event="([^"]+)"', line).group(1)
            if event in admission:
                raise ValueError("Multiple admission engines are unsupported")
            admission[event] = float(line.rsplit(" ", 1)[1])
    if set(values) != EVENTS or enabled is None or set(admission) != ADMISSION:
        raise ValueError("Incomplete runtime counters")
    return values, admission, enabled


def delta(before, after):
    result = {k: after[k] - before[k] for k in before}
    if any(v < 0 for v in result.values()):
        raise ValueError("Counter reset")
    return result


def receipt(before, after, *, program):
    a, aa, ena = snapshot(before, program)
    b, ba, enb = snapshot(after, program)
    counts, budget = delta(a, b), delta(aa, ba)
    if not ena or not enb or counts["failures"] or counts["invalid_selections"]:
        raise ValueError("Preemption policy disabled or failed")
    if program == "dla" and not (
        budget["extended_checks"] > 0 and budget["passed"] > 0
    ):
        raise ValueError("DLA output-budget admission was not exercised")
    if program == "bidkv" and any(budget.values()):
        raise ValueError("BidKV must not enable output-budget admission")
    return dict(
        policy=POLICIES[program],
        enabled=True,
        status="exercised"
        if counts["selections"] > 0 or budget["deferred"] > 0
        else "not-exercised",
        admission_check_executed=budget["extended_checks"] > 0,
        admission_deferral_observed=budget["deferred"] > 0,
        preemption_status="exercised" if counts["selections"] > 0 else "not-exercised",
        preemption=counts,
        admission=budget,
        admission_status="exercised"
        if budget["extended_checks"] > 0
        else "not-exercised",
        scope="Real counter deltas including drain. Capacity checks alone do not establish a changed scheduling decision; observed deferrals/selections do not establish a speedup",
    )
