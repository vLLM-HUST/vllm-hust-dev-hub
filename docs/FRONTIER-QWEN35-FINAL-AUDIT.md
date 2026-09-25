# Qwen3.5-35B-A3B experiment and coverage audit

Audit date: 2026-09-26. This closes the current measured campaign and the per-component disposition audit. It does **not** claim that every catalog component has a performance curve: the requested exception for verified impediments applies to the unqualified entries in the [coverage report](FRONTIER-QWEN35-MOD-COVERAGE.md).

| Requirement | Inspected evidence and outcome |
| --- | --- |
| Assigned container, baseline model | Receipts and frozen model/runtime manifests identify Qwen3.5-35B-A3B, the assigned evaluation pod, SSH port 31769 and 910B2 devices. Final remote check reports no device owners. |
| Additional real concurrency curves | BidKV, known-output-budget DLA, and Pipeline Microbatch have C1/C2/C4/C8/C16 observations with matched Native controls. |
| Original workload and fair comparisons | Importers revalidated 900-second raw request windows, retrieval gates, prefix reuse, source/configuration identities and device release. Native/BidKV/DLA preserve the common TP2 runtime; Pipeline is matched to Native TP2×PP2 using all four chips. |
| Raw evidence equals publication | Rebuilt all 15 phase4 points, all six phase3 points, and all four phase2 Pipeline comparison points directly from retained raw records: all 25 exactly equal current website points. Phase3-to-phase2 curve compatibility and phase4 common controls passed. Earlier BidKV C4/C16 records remain historical evidence. |
| Actual MOD grouping | Published records use actual MOD identifiers, with no environment-based experiment group. Environment remains provenance. |
| No fabricated optimization benefit | BidKV did not exercise preemption; DLA executed known-budget checks without deferrals or preemption. Reports/popovers disclose these limits. Single observations do not establish stable speedup. |
| Every catalog record considered | 46 records comprise 13 infrastructure entries and 33 other records; all 33 have report rows. Paired connectors/descriptors are not counted as independent algorithms. Pinned witness files exist and recorded extension manifest hashes match source blobs. |
| Specific impediments for unqualified entries | Published coverage distinguishes actual Mooncake retrieval failures, vSpec draft download failure after a passing attribute ABI check, configuration guards, missing host contracts/device transport, and documentation/diagnostic-only packages. These are scoped to the pinned versions, not permanent impossibility claims. |
| Compatibility investigation | Mooncake was rebuilt from pinned source; actual transfers and Store operations passed. Three real model qualifications failed, including a larger Store and a tested tracker fix. Matched Native passed; no candidate performance points were fabricated. |
| Website publication | PRs 279–284 publish the measured results and disclosures. PR285 merged as `f6c86ed63cfb6a834794a880e7ca53b4ed2916b9`; Pages run 36173351160 succeeded. Live desktop English/mobile Chinese verified the coverage link, all 15 phase4 points, disclosures and exact downloads. |

PR285 initially had one download-event timeout. The exact mobile point passed independently; unchanged full CI passed on one controlled retry. The redundant slower local full run was stopped after CI and live validation passed; it is not reported as a completed local full test.

No unqualified component is assigned a synthetic curve, zero score or extrapolated speedup. Further curves require resolving the listed impediments and repeating model qualification before real measurement. Original failed receipts, pinned source hashes and archive digests remain in the coverage ledger and retained experiment artifacts.
