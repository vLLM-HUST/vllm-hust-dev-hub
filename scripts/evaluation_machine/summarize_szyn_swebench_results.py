from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def verify_sha256_manifest(root: Path) -> None:
    manifest = root / "SHA256SUMS"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(maxsplit=1)
        relative = relative.removeprefix("*").removeprefix("./")
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"qualification artifact mismatch: {relative}")


def summarize(
    *,
    contract: dict[str, Any],
    tasks: list[dict[str, Any]],
    formal_results: Path,
    qualification_root: Path,
) -> dict[str, Any]:
    denominator = int(contract["declared_denominator"])
    qualification_id = str(contract["preserved_qualification_instance"])
    if len(tasks) != denominator:
        raise ValueError(f"expected {denominator} tasks, found {len(tasks)}")
    if str(tasks[0]["instance_id"]) != qualification_id:
        raise ValueError("preserved qualification is not task index 0")

    qualification_config = contract["preserved_qualification"]
    qualification_contract_path = qualification_root / "qualification-contract.json"
    manifest_path = qualification_root / "SHA256SUMS"
    if (
        sha256(qualification_contract_path)
        != qualification_config["qualification_contract_sha256"]
    ):
        raise ValueError("preserved qualification contract hash mismatch")
    if sha256(manifest_path) != qualification_config["sha256sums_sha256"]:
        raise ValueError("preserved qualification manifest hash mismatch")
    verify_sha256_manifest(qualification_root)
    qualification = load_json(qualification_contract_path)
    if qualification["status"] != "passed":
        raise ValueError("preserved qualification did not pass")
    if qualification["selection"]["instance_id"] != qualification_id:
        raise ValueError("preserved qualification instance mismatch")
    if qualification["asset_id"] != contract["asset_id"]:
        raise ValueError("preserved qualification asset mismatch")
    if (
        qualification["task_pool"]["source_parquet_sha256"]
        != contract["grader"]["dataset_parquet_sha256"]
    ):
        raise ValueError("preserved qualification dataset mismatch")
    if (
        qualification["task_pool"]["ordered_tasks_sha256"]
        != contract["task_pool"]["ordered_tasks_sha256"]
    ):
        raise ValueError("preserved qualification task order mismatch")
    if (
        qualification["task_pool"]["manifest_sha256"]
        != contract["task_pool"]["task_pool_manifest_sha256"]
    ):
        raise ValueError("preserved qualification task manifest mismatch")
    if qualification["model"]["revision"] != contract["model"]["revision"]:
        raise ValueError("preserved qualification model revision mismatch")
    if qualification["runtime"]["vllm_commit"] != contract["runtime"]["vllm_commit"]:
        raise ValueError("preserved qualification vLLM commit mismatch")
    if (
        qualification["runtime"]["vllm_ascend_commit"]
        != contract["runtime"]["vllm_ascend_commit"]
    ):
        raise ValueError("preserved qualification vLLM-Ascend commit mismatch")
    if int(qualification["result"]["attempted"]) != 1:
        raise ValueError("preserved qualification attempted count must be 1")
    if int(qualification["result"]["resolved"]) != 1:
        raise ValueError("preserved qualification resolved count must be 1")

    allowed = set(contract["scoring"]["terminal_states"])
    formal_ids = [str(task["instance_id"]) for task in tasks[1:]]
    counts: dict[str, int] = {}
    missing: list[str] = []
    invalid: dict[str, str] = {}
    for instance_id in formal_ids:
        terminal_path = formal_results / instance_id / "grader-terminal.json"
        if not terminal_path.is_file():
            missing.append(instance_id)
            continue
        terminal = load_json(terminal_path)
        if terminal.get("instance_id") != instance_id:
            invalid[instance_id] = "terminal instance mismatch"
            continue
        if terminal.get("execution_id") != contract["execution_id"]:
            invalid[instance_id] = "execution ID mismatch"
            continue
        status = str(terminal.get("status") or "missing")
        if status not in allowed:
            invalid[instance_id] = f"unknown terminal status: {status}"
            continue
        counts[status] = counts.get(status, 0) + 1

    formal_count = sum(counts.values())
    complete = formal_count == denominator - 1 and not missing and not invalid
    infrastructure_errors = counts.get("grader_error", 0)
    publishable = complete and infrastructure_errors == 0
    resolved = 1 + counts.get("resolved", 0)
    return {
        "schema_version": "szyn-swebench-verified-500-summary/v1",
        "execution_id": contract["execution_id"],
        "asset_id": contract["asset_id"],
        "declared_denominator": denominator,
        "preserved_qualification": {
            "instance_id": qualification_id,
            "resolved": 1,
            "evidence_path": qualification_config["evidence_path"],
        },
        "formal_expected": denominator - 1,
        "formal_terminal_count": formal_count,
        "formal_status_counts": dict(sorted(counts.items())),
        "missing_formal_instances": missing,
        "invalid_formal_instances": invalid,
        "resolved": resolved,
        "resolution_rate": resolved / denominator,
        "complete": complete,
        "publishable": publishable,
        "publication_blockers": {
            "missing": len(missing),
            "invalid": len(invalid),
            "grader_error": infrastructure_errors,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--task-pool", type=Path, required=True)
    parser.add_argument("--formal-results", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-publishable", action="store_true")
    args = parser.parse_args()

    contract = load_json(args.contract)
    if sha256(Path(__file__)) != contract["scoring"]["summary_script_sha256"]:
        raise ValueError("summary script hash mismatch")
    summary = summarize(
        contract=contract,
        tasks=[
            json.loads(line)
            for line in args.task_pool.read_text(encoding="utf-8").splitlines()
        ],
        formal_results=args.formal_results,
        qualification_root=args.qualification_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    if args.require_publishable and not summary["publishable"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
