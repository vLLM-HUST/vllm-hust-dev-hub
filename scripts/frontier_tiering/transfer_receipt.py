"""Record observed offload transfers without inferring a speedup from activity."""

import math
import re

NAMES = ("load_bytes", "store_bytes")


def snapshot(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(
            r"vllm:kv_offload_(load_bytes|store_bytes)_total(?:\{[^\n]*\})? ([^ ]+)",
            line,
        )
        if match:
            name, value = match.groups()
            value = float(value)
            if name in values or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid or ambiguous offload counter")
            values[name] = value
    if set(values) != set(NAMES):
        raise ValueError("Missing offload counters")
    return values


def receipt(before, after):
    a, b = snapshot(before), snapshot(after)
    delta = {name: b[name] - a[name] for name in NAMES}
    if any(value < 0 for value in delta.values()):
        raise ValueError("Offload counters reset during the window")
    return {
        **delta,
        "status": "restore-observed"
        if delta["load_bytes"] > 0
        else "store-only"
        if delta["store_bytes"] > 0
        else "not-exercised",
        "scope": "Actual NPU/CPU transfer bytes including drain; does not prove secondary-tier access or a performance improvement",
    }
