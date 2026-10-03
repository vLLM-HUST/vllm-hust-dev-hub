# SZYN SWE-bench Qwen3.5 execution evidence

This directory contains evidence produced under
`config/szyn-swebench-qwen35-execution-v1.json` for the 500-task SZYN
SWE-bench evaluation tracked by issue #87.

## Qualification

`qualification/scikit-learn__scikit-learn-10844` is the clean end-to-end
qualification for the resumable collector and official grader:

- collection status: `collected_ungraded`
- official grader status: `resolved`
- patch applied: yes
- FAIL_TO_PASS: 1/1
- PASS_TO_PASS: 16/16
- official image: `sweb.eval.x86_64.scikit-learn_1776_scikit-learn-10844`
- image digest: `sha256:2cb7669b05e488e4cf5ab5905ccd225c71fb2804cdb4072bb3fa0704e0816e76`
- execution backend: `fex-2609.1`
- official image setup commit: `974b94e4ebe0d8a319a2a4d71f18d0b4ff0e8a09`
- frozen base commit: `97523985b39ecde369d83352d7c3baf403b60a22`
- grading wall time: 122.095 seconds (25.917 seconds inside the official runner)

The first grading launch used an invalid long-form FEXServer option. Its
terminal record and logs are preserved unchanged under `grader-attempt-1`.
No tests ran in that attempt. `grader-attempt-2` preserves a successful but
superseded run that reset the official setup commit before evaluation. The
current root terminal preserves that setup commit, verifies that its parent is
the frozen base commit, and records a clean image worktree before applying the
same collected patch.

`SHA256SUMS` covers every raw artifact in the qualification directory. The
full 499-task continuation is intentionally not summarized as complete until
all remaining tasks have terminal collection and official grading records.
