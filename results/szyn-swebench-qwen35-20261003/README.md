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
- grading wall time: 931.810 seconds

The first grading launch used an invalid long-form FEXServer option. Its
terminal record and logs are preserved unchanged under `grader-attempt-1`.
No tests ran in that attempt. The successful retry uses the same collected
patch, dataset snapshot, official image digest, and evaluation script.

`SHA256SUMS` covers every raw artifact in the qualification directory. The
full 499-task continuation is intentionally not summarized as complete until
all remaining tasks have terminal collection and official grading records.
