# Sage Mate inference runtime handoff

This handoff covers the managed vLLM-HUST inference runtime only. It does not
transfer ownership of Workstation instance management, approval workflows, or
the statecentric native-engine research deployment.

## Source of truth

- `config/vllm-ascend-production-lock.json` pins the exact core/plugin commits,
  immutable wheel hashes, base image digest, dependency set and image tag.
- `vllm-ascend-hust/.github/vllm-main-verified.commit` must equal the locked
  core commit.
- The Sage Mate parent repository pins core, plugin and dev-hub as gitlinks.
- Machine-local `.env` selects a built image by tag and immutable image ID; it
  is configuration, never a source of package identity.

Do not infer production identity from the base-image release name. Confirm the
installed package versions, OCI labels and runtime receipt independently.

## Safe promotion sequence

1. Confirm every target checkout is clean and each locked SHA is reachable from
   its canonical `origin/main`.
2. Build wheels from merged main SHAs and verify their hashes against the lock.
   Never publish a wheel produced from a PR head as a main artifact.
3. Run `scripts/build_locked_vllm_ascend_image.sh`; it rejects dirty checkouts,
   mismatched verified-core declarations and artifact hash drift.
4. Preserve the active image ID, container command, receipt and NPU process map
   as the rollback point.
5. Switch only through the managed `sage-mate-vllm-engine.service`. The Sage
   deployment owns physical NPU0-3; NPU4-7 and statecentric are out of scope.
6. Require graph-mode cold start, health, models, normal and streaming chat,
   stateful Responses, function/custom tools, concurrency, cancellation and a
   second cold restart before declaring production healthy.
7. Test grammar custom tools at the server default temperature and confirm both
   public custom-tool SSE event names and exact grammar acceptance.

## Failure and rollback

Stop promotion on any identity, import, ABI, graph, NPU, response-protocol or
custom-grammar failure. Restore the recorded image ID and matching machine-local
identity values, then restart through the same managed service. Do not mutate a
running container, start an unmanaged duplicate, change topology, enable eager
mode, or occupy a different NPU set as an implicit fallback.

Detailed historical rollback artifacts remain in
`docs/sage-mate-production-runtime.md`; routine cleanup must not delete them.

## Minimum handoff evidence

Record exact core/plugin/dev-hub/Sage SHAs, wheel hashes, image ID and creation
time, installed package versions/import origins, model and TP size, physical NPU
IDs, graph mode, health/model responses, custom grammar/SSE results, Codex
`apply_patch` acceptance, cold-restart result, public Sage chat result, relevant
logs and the retained rollback image. Never include API keys or private model
paths in a public receipt.
