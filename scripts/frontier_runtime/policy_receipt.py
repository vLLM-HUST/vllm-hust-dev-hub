"""Read actual policy counter deltas; installation alone is not effectiveness."""

import argparse
import json
import re
from pathlib import Path

POLICY = "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy"
EVENTS = {"calls", "selections", "abstentions", "failures", "invalid_selections"}


def snapshot(path):
    events, enabled = {}, None
    preemptions = None
    for line in path.read_text().splitlines():
        if line.startswith("vllm:preemption_policy_events{"):
            if f'policy="{POLICY}"' not in line:
                raise ValueError("Unexpected policy identity")
            event = re.search(r'event="([^"]+)"', line).group(1)
            if event in events:
                raise ValueError("Multiple engines require explicit aggregation")
            events[event] = float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:preemption_policy_enabled{"):
            if f'policy="{POLICY}"' not in line or enabled is not None:
                raise ValueError("Unexpected/multiple policy identities")
            enabled = float(line.rsplit(" ", 1)[1]) == 1
        elif line.startswith("vllm:num_preemptions_total{"):
            if preemptions is not None:
                raise ValueError("Multiple engines require explicit aggregation")
            preemptions = float(line.rsplit(" ", 1)[1])
    if set(events) != EVENTS or enabled is None or preemptions is None:
        raise ValueError("Incomplete policy metrics")
    return events, enabled, preemptions


def receipt(before, after):
    old, was_enabled, old_preemptions = snapshot(before)
    new, is_enabled, new_preemptions = snapshot(after)
    values = {key: new[key] - old[key] for key in EVENTS}
    if not was_enabled or not is_enabled or any(v < 0 for v in values.values()):
        raise ValueError("Policy disabled or counter reset")
    if values["failures"] or values["invalid_selections"]:
        raise ValueError("Policy failed or returned invalid selections")
    return {
        "enabled": True,
        "policy": POLICY,
        **values,
        "preemptions": new_preemptions - old_preemptions,
        "status": "not-exercised" if values["calls"] == 0 else "called",
        "scope": "Counter deltas covering measured window and in-flight drain; calls alone do not establish optimization benefit",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    a = p.parse_args()
    for cell in ("c4", "c16"):
        result = receipt(a.run / f"{cell}-before.prom", a.run / f"{cell}-after.prom")
        with (a.run / f"{cell}-policy-effectiveness.json").open("x") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
        print(cell, result)
