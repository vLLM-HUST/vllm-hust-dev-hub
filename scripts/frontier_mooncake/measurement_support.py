"""Fail-closed evidence gates and Mooncake-only measured counter receipts."""

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

FATAL = (
    "malloc():", "free():", "double free or corruption", "Fatal Python error:",
    "Segmentation fault", "corrupted double-linked list", "corrupted size",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualified_sources(root, receipts=None):
    """Verify both completed phase7 arms, their clean release and frozen sources."""
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("software_tests_passed") is not True:
        raise RuntimeError("Phase7 software qualification missing")
    hashes = {str(manifest_path): sha(manifest_path)}
    for relative, expected in manifest["sha256"].items():
        path = (root / relative).resolve()
        if sha(path) != expected:
            raise RuntimeError(f"Phase7 frozen source changed: {path}")
        hashes[str(path)] = expected
    receipts = receipts or {arm: root / "receipts" / f"{arm}-retrieval-r1" / "status.json" for arm in ("mooncake", "native")}
    if set(receipts) != {"mooncake", "native"}:
        raise ValueError("Both qualification receipt paths are required")
    for arm in ("mooncake", "native"):
        path = Path(receipts[arm]).resolve()
        if not path.is_relative_to((root / "receipts").resolve()):
            raise ValueError("Qualification receipt must belong to phase7")
        state = json.loads(path.read_text())
        release = state.get("release", {})
        if (state.get("passed") is not True or state.get("stage") != "completed"
                or release.get("exit") != 0 or release.get("owners") != []
                or (arm == "mooncake" and state.get("master_release_exit") != 0)):
            raise RuntimeError(f"Phase7 {arm} qualification/release incomplete")
        if (path.parent / "FAILED.txt").exists():
            raise RuntimeError(f"Phase7 {arm} has FAILED.txt")
        custody_path = path.parent / "custody.json"
        custody = json.loads(custody_path.read_text())
        plans = json.loads((root / "manager-plans.json").read_text())
        if custody.get("program") != arm or custody.get("serving_child", {}).get("argv") != plans[arm]:
            raise RuntimeError(f"Phase7 {arm} receipt custody does not match manager plan")
        retrieval_path = path.parent / "retrieval/summary.json"
        retrieval = json.loads(retrieval_path.read_text())
        if retrieval.get("passed") is not True or retrieval.get("completed_requests") != 26:
            raise RuntimeError(f"Phase7 {arm} full retrieval evidence missing")
        log = root / "receipts" / f"{arm}.log"
        if any(marker in log.read_text(errors="replace") for marker in FATAL):
            raise RuntimeError(f"Phase7 {arm} fatal shutdown log")
        for evidence in (path, log, custody_path, retrieval_path):
            hashes[str(evidence)] = sha(evidence)
    return hashes


def parse_npu_smi(text):
    """Parse exact HBM usage and per-NPU process rows; unknown formats fail."""
    if "HBM-Usage(MB)" not in text or "process" not in text.lower():
        raise RuntimeError("npu-smi output lacks HBM/process sections")
    devices, processes = {}, []
    current = None
    process_section = False
    for line in text.splitlines():
        if re.search(r"Process\s+(?:id|ID)", line):
            process_section = True
        cells = [value.strip() for value in line.strip().strip("|").split("|")]
        if process_section:
            if len(cells) >= 3 and re.fullmatch(r"\d+(?:\s+\d+)?", cells[0]) and cells[1].isdigit():
                device = int(cells[0].split()[0])
                if device in (0, 1):
                    processes.append(dict(device=device, pid=int(cells[1]), name=cells[2]))
            continue
        match = re.match(r"^\|\s*(\d+)\s+910B\S*\s*\|", line)
        if match:
            current = int(match.group(1))
            continue
        if current in (0, 1) and len(cells) >= 3:
            memory = re.search(r"(?:^|\s)(\d+)\s*/\s*(\d+)$", cells[-1])
            if memory:
                used, total = map(int, memory.groups())
                if current in devices or total <= 0 or used > total:
                    raise RuntimeError("Ambiguous/invalid npu-smi HBM record")
                devices[current] = dict(used_mb=used, total_mb=total)
                current = None
    if not process_section and "No running processes" not in text:
        raise RuntimeError("Cannot identify npu-smi process table")
    if set(devices) != {0, 1}:
        raise RuntimeError("Cannot identify exact HBM usage for both serving NPUs")
    return dict(devices=devices, processes=processes)


def memory_state():
    result = subprocess.run(["npu-smi", "info"], capture_output=True, text=True,
                            check=True, timeout=15)
    state = parse_npu_smi(result.stdout)
    state.update(observed_unix=time.time(), command=["npu-smi", "info"], raw=result.stdout)
    return state


def require_idle_memory():
    state = memory_state()
    if state["processes"] or any(row["used_mb"] > 4500 for row in state["devices"].values()):
        raise RuntimeError("NPU process/HBM gate failed: require no processes and <=4500 MB used on each of 0/1")
    return state


def check_release_addendum(path, receipts):
    record = json.loads(Path(path).read_text())
    if (record.get("passed") is not True or record.get("owned_processes") != []
            or record.get("npu_processes") != []):
        raise RuntimeError("Missing clean process/HBM release addendum")
    used = record.get("hbm_used_mb", {})
    if set(used) != {"0", "1"} or any(type(value) is not int or not 0 <= value <= 4500 for value in used.values()):
        raise RuntimeError("Release addendum HBM gate failed")
    expected = {arm: sha(Path(receipt)) for arm, receipt in receipts.items()}
    if record.get("qualification_receipt_sha256") != expected:
        raise RuntimeError("Release addendum does not bind both chosen qualification receipts")
    return record


def verify_qualification(root):
    manifest = json.loads((root / "manifest.json").read_text())
    qualified_sources(Path(manifest["qualification_root"]), manifest["qualification_receipts"])
    check_release_addendum(manifest["release_addendum"], manifest["qualification_receipts"])
    state = require_idle_memory()
    (root / "receipts/hbm-preflight.json").write_text(json.dumps(state, indent=2) + "\n")


def start_master(ctl):
    subprocess.run(ctl + ["start", "master"], check=True, timeout=20)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:33895/metrics", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise TimeoutError("Owned Mooncake master readiness deadline")


def process_table(proc=Path("/proc")):
    table = {}
    for entry in proc.glob("[0-9]*"):
        try:
            # comm may contain whitespace or ')'; fields after the last ')' are
            # state, ppid, pgrp, ... starttime (Linux proc_pid_stat).
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            table[int(entry.name)] = dict(pid=int(entry.name), ppid=int(fields[1]),
                                         pgid=int(fields[2]), start_ticks=int(fields[19]))
        except FileNotFoundError:
            continue
    return table


def owned_process_snapshot(pid, proc=Path("/proc")):
    table = process_table(proc)
    if pid not in table or table[pid]["pgid"] != pid or pid == os.getpgrp():
        raise RuntimeError("Owned server must have its own supervisor process group")
    ids = {pid} | {p for p, row in table.items() if row["pgid"] == pid}
    while True:
        expanded = ids | {p for p, row in table.items() if row["ppid"] in ids}
        if expanded == ids:
            break
        ids = expanded
    return dict(pgid=pid, processes=[table[p] for p in sorted(ids)])


def surviving_owned(snapshot, proc=Path("/proc")):
    if not snapshot:
        return []
    table = process_table(proc)
    known = {row["pid"]: row["start_ticks"] for row in snapshot["processes"]}
    return [row for pid, row in table.items()
            if row["pgid"] == snapshot["pgid"] or known.get(pid) == row["start_ticks"]]


def release_owned(root, ctl, program, started, master_started, state, owners):
    """Always attempt both owned stops; record errors instead of losing receipts."""
    errors = []
    exits = {}
    snapshot = state.get("owned_server_processes")
    if snapshot:
        # Refresh before supervisor stop, including all children and group
        # members before reparenting can hide ancestry.
        try:
            table = process_table()
            leader = snapshot["pgid"]
            previous = {row["pid"]: row["start_ticks"] for row in snapshot["processes"]}
            if leader in table and table[leader]["start_ticks"] == previous.get(leader):
                snapshot = owned_process_snapshot(leader)
        except Exception as exc:
            errors.append(f"Owned process snapshot failed: {exc}")
    for name, active in ((program, started), ("master", master_started)):
        if not active:
            continue
        try:
            stopped = subprocess.run(ctl + ["stop", name], capture_output=True,
                                     text=True, timeout=110)
            exits[name] = stopped.returncode
            if stopped.returncode:
                errors.append(f"{name} stop exit {stopped.returncode}")
        except Exception as exc:
            exits[name] = None
            errors.append(f"{name} stop: {type(exc).__name__}: {exc}")
    if snapshot:
        for sig, seconds in ((signal.SIGTERM, 15), (signal.SIGKILL, 10)):
            survivors_now = surviving_owned(snapshot)
            if not survivors_now:
                break
            original = {row["pid"]: row["start_ticks"] for row in snapshot["processes"]}
            group = snapshot["pgid"]
            verified = any(row["pgid"] == group and original.get(row["pid"]) == row["start_ticks"] for row in survivors_now)
            if group <= 1 or group == os.getpgrp() or not verified:
                errors.append("Refusing to signal a process group without a surviving owned identity")
                break
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
            except OSError as exc:
                errors.append(f"Owned process group signal failed: {exc}")
                break
            state.setdefault("owned_group_signals", []).append(dict(pgid=group, signal=int(sig)))
            limit = time.monotonic() + seconds
            while surviving_owned(snapshot) and time.monotonic() < limit:
                time.sleep(0.25)
    deadline = time.monotonic() + 30
    while (owners() or surviving_owned(snapshot)) and time.monotonic() < deadline:
        time.sleep(1)
    remaining = owners()
    survivors = surviving_owned(snapshot)
    state["owned_processes_after_stop"] = survivors
    if survivors:
        errors.append(f"Owned process group/descendants survived supervisor stop: {survivors}")
    if started or master_started:
        state["release"] = {"exit": exits.get(program), "owners": remaining, "owned_processes": survivors}
    if master_started:
        state["master_release_exit"] = exits.get("master")
    if remaining:
        errors.append(f"Participating device owners remain: {remaining}")
    for name in (program, "master"):
        path = root / "receipts" / f"{name}.log"
        if path.exists():
            text = path.read_text(errors="replace")
            errors.extend(f"{name}: {marker}" for marker in FATAL if marker in text)
    memory_deadline = time.monotonic() + 60
    while True:
        try:
            state["hbm_after_stop"] = memory_state()
            memory = state["hbm_after_stop"]
            if memory["processes"] or any(row["used_mb"] > 4500 for row in memory["devices"].values()):
                raise RuntimeError("HBM/processes have not returned to the idle threshold")
            break
        except Exception as exc:
            if time.monotonic() >= memory_deadline:
                errors.append(f"Post-release HBM/process gate: {exc}")
                break
            time.sleep(1)
    if errors:
        state.update(passed=False, stage="failed", shutdown_errors=errors)
    return errors


def transfer_receipt(before, after):
    """Expose actual counter series without equating absence to zero transfer."""
    from prometheus_client.parser import text_string_to_metric_families

    def counters(path):
        result = {}
        for family in text_string_to_metric_families(path.read_text()):
            if family.type != "counter" or "tiering" in family.name.lower():
                continue
            # These names indicate relevant instrumentation, not proof of a
            # particular transfer direction or backend. Preserve raw identities.
            if not any(word in family.name.lower() for word in
                       ("mooncake", "kv_transfer", "kv_connector", "offload")):
                continue
            for sample in family.samples:
                if sample.name.endswith("_created"):
                    continue
                key = (sample.name, tuple(sorted(sample.labels.items())))
                if key in result:
                    raise ValueError(f"Duplicate counter series: {key}")
                result[key] = float(sample.value)
        return result

    first, last = counters(before), counters(after)
    series = []
    for key in sorted(first.keys() | last.keys()):
        a, b = first.get(key), last.get(key)
        valid = a is not None and b is not None and math.isfinite(a) and math.isfinite(b) and b >= a
        series.append(dict(name=key[0], labels=dict(key[1]), before=a, after=b,
                           delta=b - a if valid else None,
                           status="observed" if valid else "missing-reset-or-nonfinite"))
    return dict(kind="observed-runtime-counters", source="vllm /metrics",
                status="available" if series else "unavailable",
                series=series, transfer_bytes=None, effectiveness=None,
                interpretation="No backend attribution or effectiveness inferred from generic counters; absent instrumentation is not zero transfer.")
