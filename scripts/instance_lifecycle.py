#!/usr/bin/env python3
"""Opt-in local lifecycle service; production profiles are never auto-enrolled."""

import argparse
from pathlib import Path
import signal
import threading

from instance_control.lifecycle import Lifecycle
from instance_control.lifecycle_backend import SimulationBackend
from instance_control.lifecycle_server import serve
from instance_control.schema import decode, fields, require
from instance_control.store import Store
from instance_control.transport import _private_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--simulation",
        action="store_true",
        help="enable only the durable CPU-free simulation adapter",
    )
    parser.add_argument(
        "--production-config", help="private default-off Docker/systemd allowlist"
    )
    args = parser.parse_args()
    path = Path(args.config)
    require(path.is_absolute() and path.resolve() == path, "invalid_config_path")
    config = decode(_private_file(path))
    fields(
        config,
        "schema enabled state_directory socket_path socket_gid administrator_uids profiles",
    )
    require(
        config["schema"] == "vllm-hust.lifecycle-host/v1"
        and type(config["enabled"]) is bool,
        "invalid_config",
    )
    require(
        isinstance(config["administrator_uids"], list)
        and config["administrator_uids"]
        and all(type(uid) is int and uid >= 0 for uid in config["administrator_uids"]),
        "invalid_config",
    )
    require(
        config["socket_gid"] is None
        or type(config["socket_gid"]) is int
        and config["socket_gid"] >= 0,
        "invalid_config",
    )
    store = Store(config["state_directory"], initialize=True)
    backends = {}
    if args.simulation:
        simulation_root = store.root / "simulation"
        simulation_store = Store(str(simulation_root), initialize=True)
        backends["simulation"] = SimulationBackend(simulation_store)
    if args.production_config:
        from instance_control.production_backend import ProductionBackend
        from instance_control.production_policy import ProductionPolicy

        backends["production"] = ProductionBackend(
            store, ProductionPolicy.load(args.production_config)
        )
    authority = Lifecycle(
        store,
        config["profiles"],
        backends,
        administrator_uids=config["administrator_uids"],
        enabled=config["enabled"],
    )
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    serve(config["socket_path"], authority, socket_gid=config["socket_gid"], stop=stop)


if __name__ == "__main__":
    main()
