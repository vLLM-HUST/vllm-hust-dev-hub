#!/usr/bin/env python3
"""Read-only production preflight/dry-run; never initializes state or mints a lease."""

import argparse

from instance_control.production_driver import make_driver
from instance_control.production_policy import ProductionPolicy
from instance_control.schema import canonical
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--desired", choices=["running", "stopped"])
    parser.add_argument(
        "--capture-configuration",
        action="store_true",
        help="emit a candidate digest only; never qualifies or changes a target",
    )
    args = parser.parse_args()
    try:
        policy = ProductionPolicy.load(args.policy)
        target = policy.target(args.instance_id)
        policy.verify_host(target)
        observation = make_driver(target, capture=args.capture_configuration).inspect(
            time.monotonic() + target["timeout_seconds"]
        )
        print(
            canonical(
                {
                    "ok": True,
                    "mutations_enabled": policy.enabled,
                    "effect_performed": False,
                    "binding": policy.binding(args.instance_id),
                    "observation": observation,
                    "desired": args.desired,
                    "requires_approval": True,
                    "capture_only": args.capture_configuration,
                }
            )
        )
        return 0
    except Exception:
        print(
            canonical(
                {
                    "ok": False,
                    "error": "production_preflight_failed",
                    "effect_performed": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
