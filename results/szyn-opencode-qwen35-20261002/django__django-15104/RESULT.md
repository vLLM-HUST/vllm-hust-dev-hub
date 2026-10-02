# China Mobile Suzhou OpenCode SWE-bench Qualification

This is a single-case qualification result, not an aggregate score for all 500 tasks.

## Identity

- Asset: `SZYN-OPENCODE-SWEBENCH-VERIFIED-500`
- Attribution: China Mobile Suzhou / Suzhou Yunneng
- Case: `django__django-15104`
- Base commit: `a7e7043c8746933dafce652507d3b821801cdc7d`
- Collector: OpenCode 1.18.19 (`2b72179c663cadcb54f54d9f19221b3fb3d11fb6`)
- Model: Qwen3.5-35B-A3B, BF16, TP2, thinking disabled
- Runtime: vLLM `0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665`; vLLM-Ascend `1cdb8c4db6e50f36f1fb3283b3e3dd618f6821e8`

## Result

- Attempted: 1
- Resolved: 1
- FAIL_TO_PASS: 1/1 passed
- Full `migrations.test_autodetector` module: 139/139 passed
- Agent patch versus gold source result: exact
- Wall time: 161.091 seconds
- Model requests: 26 successful, 0 failed
- Tokens: 649,311 prompt; 3,809 generated
- MTP: 2,630 draft tokens; 2,491 accepted
- APC: 544,768 cache-hit tokens out of 649,311 queried tokens

The agent changed one source line. Hidden tests and the gold patch were withheld until the agent had exited. The hidden evaluation ran in a fresh checkout with only the agent's source change applied.

## Scope

This run qualifies the dataset and collector path on the named configuration. It must not be presented as a 500-task resolution rate or as a point on the 900-second SWE prefix-throughput curves.
