#!/usr/bin/env python3
"""Private production executor, not a product API or general command runner."""

import argparse
import sys

from instance_control.production_backend import ProductionBackend, ProductionExecutor
from instance_control.production_policy import ProductionPolicy
from instance_control.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--guard-fd", required=True, type=int)
    args = parser.parse_args()
    try:
        nonce = sys.stdin.buffer.read(129)
        if not 32 <= len(nonce) <= 128:
            return 2
        backend = ProductionBackend(
            Store(args.state), ProductionPolicy.load(args.policy)
        )
        ProductionExecutor(backend).execute(nonce.decode("ascii"), args.guard_fd)
        return 0
    except Exception:
        # No raw subprocess output, exception repr or credential may leave here.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
