"""Derive an explicitly adjudicated result without changing pinned raw evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def checked(path: Path, expected_sha256: str) -> dict[str, Any]:
    if sha256(path) != expected_sha256:
        raise ValueError(f"artifact SHA256 mismatch: {path}")
    return load(path)


def adjudicate(
    *,
    contract: dict[str, Any],
    raw_summary_path: Path,
    manifest: dict[str, Any],
    formal_results: Path,
    control_results: Path,
) -> dict[str, Any]:
    if manifest.get("schema_version") != "szyn-candidate-timeout-adjudication/v1":
        raise ValueError("unsupported adjudication manifest")
    raw = checked(raw_summary_path, manifest["raw_summary_sha256"])
    counts = raw["formal_status_counts"]
    blockers = raw["publication_blockers"]
    entries = manifest.get("adjudications")
    if not isinstance(entries, list) or not entries:
        raise ValueError("at least one timeout adjudication is required")
    if (
        raw["execution_id"] != contract["execution_id"]
        or raw["declared_denominator"] != 500
        or raw["formal_terminal_count"] != 500
        or not raw["complete"]
        or raw["publishable"]
        or blockers["missing"]
        or blockers["invalid"]
        or blockers["grader_error"]
        or blockers["grader_timeout"] != len(entries)
        or counts.get("grader_timeout", 0) != len(entries)
        or counts.get("grader_error", 0)
        or sum(counts.values()) != 500
        or raw["resolution_rate"] != raw["resolved"] / 500
    ):
        raise ValueError("raw summary is not a complete timeout-only blocked run")

    seen: set[str] = set()
    timeout = int(contract["scoring"]["grader_timeout_seconds"])
    for entry in entries:
        instance_id = entry["instance_id"]
        if (
            not isinstance(instance_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*__[A-Za-z0-9_.-]+", instance_id)
            is None
            or instance_id in seen
            or entry.get("reason_code") != "candidate_infinite_loop_at_eof"
            or not isinstance(entry.get("causal_explanation"), str)
            or len(entry["causal_explanation"]) < 40
        ):
            raise ValueError("invalid or duplicate adjudication identity/reason")
        seen.add(instance_id)
        result = formal_results / instance_id
        control = control_results / instance_id
        current = checked(
            result / "grader-terminal.json", entry["current_terminal_sha256"]
        )
        first = checked(
            result / "infrastructure-retry-1/grader-attempt/grader-terminal.json",
            entry["first_terminal_sha256"],
        )
        baseline = checked(
            control / "grader-terminal.json", entry["control_terminal_sha256"]
        )
        control_collection = load(control / "collection-terminal.json")
        patch = result / "attempt-1/agent.patch"
        if sha256(patch) != entry["agent_patch_sha256"]:
            raise ValueError("candidate patch SHA256 mismatch")
        if sha256(result / "test-output.txt") != entry["current_test_output_sha256"]:
            raise ValueError("candidate test-output SHA256 mismatch")
        if sha256(control / "test-output.txt") != entry["control_test_output_sha256"]:
            raise ValueError("control test-output SHA256 mismatch")
        if any(
            terminal.get("instance_id") != instance_id
            or terminal.get("execution_id") != contract["execution_id"]
            for terminal in (current, first, baseline)
        ):
            raise ValueError("terminal identity mismatch")
        if (
            current["status"] != "grader_timeout"
            or first["status"] != "grader_timeout"
            or baseline["status"] != "unresolved"
            or current["grader_runtime_seconds"] < timeout
            or first["grader_runtime_seconds"] < timeout
            or baseline["grader_runtime_seconds"] >= timeout
            or current["image"] != first["image"]
            or current["image"] != baseline["image"]
            or current["execution_backend"] != first["execution_backend"]
            or current["execution_backend"] != baseline["execution_backend"]
            or current["patch_normalization"]["raw_patch_sha256"]
            != entry["agent_patch_sha256"]
            or first["patch_normalization"]["raw_patch_sha256"]
            != entry["agent_patch_sha256"]
            or control_collection.get("diagnostic_control")
            != "synthetic empty patch; not a model attempt or formal result"
            or (control / "attempt-1/agent.patch").read_bytes() != b""
        ):
            raise ValueError("timeout or empty-patch control evidence does not match")
        patch_text = patch.read_text(encoding="utf-8", errors="replace")
        if (
            "+                if self.current_char and (self.current_char.isalpha()"
            not in patch_text
            or "+                    while self.current_char and (self.current_char.isalnum()"
            not in patch_text
            or entry.get("eof_sentinel") != "EOF"
            or "tests/test_domain_cpp.py ."
            not in (result / "test-output.txt").read_text(
                encoding="utf-8", errors="replace"
            )
            or "tests/test_domain_cpp.py"
            not in (control / "test-output.txt").read_text(
                encoding="utf-8", errors="replace"
            )
        ):
            raise ValueError("candidate loop or test-progress witness is missing")

    effective = dict(counts)
    effective["grader_timeout"] -= len(entries)
    if effective["grader_timeout"] == 0:
        del effective["grader_timeout"]
    effective["unresolved"] = effective.get("unresolved", 0) + len(entries)
    if sum(effective.values()) != 500:
        raise ValueError("adjudicated denominator changed")
    return {
        "schema_version": "szyn-swebench-verified-500-adjudicated/v1",
        "execution_id": contract["execution_id"],
        "asset_id": raw["asset_id"],
        "declared_denominator": 500,
        "resolved": raw["resolved"],
        "resolution_rate": raw["resolved"] / 500,
        "raw_summary_sha256": manifest["raw_summary_sha256"],
        "raw_publishable": False,
        "adjudicated_publishable": True,
        "raw_status_counts": counts,
        "adjudicated_status_counts": dict(sorted(effective.items())),
        "adjudications": entries,
        "limitation": "Post-run causal adjudication; original grader terminals and pinned v3 summary remain unchanged.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--raw-summary", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--formal-results", type=Path, required=True)
    parser.add_argument("--control-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = adjudicate(
        contract=load(args.contract),
        raw_summary_path=args.raw_summary,
        manifest=load(args.manifest),
        formal_results=args.formal_results,
        control_results=args.control_results,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
