#!/usr/bin/env python3
"""Bounded host-private transport for the durable instance controller.

The default remains closed.  A trusted mode-0600 host configuration and matching
OS euid are required even for read-only authority access.  This entrypoint does
not dynamically import product backends, so a registered production instance is
reported unavailable until a trusted host service injects its qualified adapter.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instance_control.schema import ControlError, decode, require  # noqa: E402
from instance_control.transport import ControlTransport, PROTOCOL, validate_request  # noqa: E402


def parse_request(raw):
    require(len(raw) <= 4096, "request_too_large")
    return validate_request(decode(raw))


def dispatch_wire(value, configuration):
    """Return one redacted wire result without confusing rejection with outage."""
    authority = None
    try:
        if not configuration:
            if value["action"] == "inspect":
                return 0, {"protocol": PROTOCOL, "authorityAvailable": False,
                           "productionBackendQualified": False,
                           "operationsAccepting": False,
                           "instanceId": value["instance_id"],
                           "reason": "control_configuration_required"}, False
            raise ControlError("control_configuration_required")
        # CLI has no product registry by design. A host-private service embeds
        # ControlTransport and injects reviewed backend objects in trusted code.
        authority = ControlTransport.open(configuration)
        return 0, authority.dispatch(value), False
    except ControlError as exc:
        available = authority is not None
        return 2, {"protocol": PROTOCOL, "error": str(exc),
                   "authorityAvailable": available}, True
    except Exception:
        # Adapter exceptions may include host paths, command lines or secrets.
        # Never reflect them or a traceback across the wire boundary.
        return 2, {"protocol": PROTOCOL, "error": "transport_unavailable",
                   "authorityAvailable": authority is not None}, True


def main():
    try:
        value = parse_request(sys.stdin.buffer.read(4097))
        configuration = os.environ.get("VLLM_HUST_INSTANCE_CONTROL_CONFIG", "")
        exit_code, result, is_error = dispatch_wire(value, configuration)
    except ControlError as exc:
        exit_code = 2
        result = {"protocol": PROTOCOL, "error": str(exc),
                  "authorityAvailable": False, "operationsAccepting": False}
        is_error = True
    except Exception:
        exit_code = 2
        result = {"protocol": PROTOCOL, "error": "transport_unavailable",
                  "authorityAvailable": False, "operationsAccepting": False}
        is_error = True
    output = sys.stderr if is_error else sys.stdout
    print(json.dumps(result), file=output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
