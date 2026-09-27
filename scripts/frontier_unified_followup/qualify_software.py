"""Verify generated plans and imports before admitting the follow-up supervisor."""

from __future__ import annotations

import json

from contract import ARMS, BASE, digest, verify


def main() -> None:
    root = BASE / "phase10-followup-r1"
    verify(root)
    plans = json.loads((root / "manager-plans.json").read_text())
    expected = {
        "bidkv": "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy",
        "dla": "dla.preemption.DeclaredBudgetPreemptionPolicy",
    }
    for arm in ARMS:
        command = plans[arm]
        assert command[command.index("--preemption-policy") + 1] == expected[arm]
        assert "--enforce-eager" not in command
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for relative, expected_hash in manifest["sha256"].items():
        if digest(root / relative) != expected_hash:
            raise RuntimeError(f"Generated file changed: {relative}")
    manifest["software_tests_passed"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"passed": True, "arms": list(ARMS)}))


if __name__ == "__main__":
    main()
