"""Require actual batch admissions and completions with no fallback failures."""

import re

POLICY = "vllm_hust_pipeline_microbatch.policy.PipelineMicrobatchPolicy"
EVENTS = {
    "calls",
    "admissions",
    "abstentions",
    "completions",
    "aborts",
    "failures",
    "invalid_admissions",
    "builtin_fallbacks",
}


def snapshot(path):
    values, enabled = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("vllm:batch_admission_policy_events{"):
            if f'policy="{POLICY}"' not in line:
                raise ValueError("Unexpected policy identity")
            event = re.search(r'event="([^"]+)"', line).group(1)
            if event in values:
                raise ValueError("Multiple engines require explicit aggregation")
            values[event] = float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:batch_admission_policy_enabled{"):
            if f'policy="{POLICY}"' not in line or enabled is not None:
                raise ValueError("Unexpected/multiple policy identities")
            enabled = float(line.rsplit(" ", 1)[1]) == 1
    if set(values) != EVENTS or enabled is None:
        raise ValueError("Incomplete policy metrics")
    return values, enabled


def receipt(before, after):
    a, enabled_a = snapshot(before)
    b, enabled_b = snapshot(after)
    delta = {key: b[key] - a[key] for key in EVENTS}
    if not enabled_a or not enabled_b or any(v < 0 for v in delta.values()):
        raise ValueError("Disabled policy or counter reset")
    if any(
        delta[k]
        for k in ("aborts", "failures", "invalid_admissions", "builtin_fallbacks")
    ):
        raise ValueError("Policy aborted, failed, or fell back")
    if not all(delta[k] > 0 for k in ("calls", "admissions", "completions")):
        raise ValueError("Policy lifecycle not exercised")
    return dict(
        enabled=True,
        policy=POLICY,
        status="exercised",
        **delta,
        scope="Actual admissions/completions during measured window and drain; performance delta requires matched native control",
    )
