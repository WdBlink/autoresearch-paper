# Fixed-Wing Visual Guidance — P1 acceptance

This fixture compiles the initial research goal from Codex task
`019fb6a0-a1cc-7422-ae35-8e9625de1c13` through the complete P1 workflow.

The proposal honestly records three facts from the source task:

1. the current Actor receives true `target_vector` state;
2. truth and FastSAM evaluators are not yet a fair isolated comparison;
3. no trained model, batch result, or SOTA result is assumed.

The semantic validator accepts the proposal as executable because its planned
evaluator has an exact interface, output bindings, and one mandatory build
experiment that gates all later work. The adversarial critique still requests
revision: the initial claim scope omitted FastSAM even though the source goal,
metric guardrail, evaluator, and detector-stress experiment required it. The
revision explicitly replaces that claim field before freeze.

## Frozen lineage

| Artifact | SHA-256 |
|---|---|
| Proposed IR | `9ff5318d04669ce47446d8a89ef4230210d824f386818c539804eda0c7322a3e` |
| Proposal record | `8a5fa5b469144d046b455513f8071212a7beadb3b6a97ef49f188d852e9f8824` |
| Critique record | `db22d86b71ae17d03b8bb842ee399599adab819c4911e1adf045be36e047fc71` |
| Frozen revised IR | `88096110be7a32b9f57d719442a50ebbba7e0358a7228a34a5e50c495850bcb5` |
| Revision record | `ffea10eb2dbf226267c41b212365b391b2394ab85e7ee82c5fd5a4535d696930` |
| Freeze receipt | `3581453633e5a6ba23bcbcbcae09131263fe5233a00f15452c344240123d4b32` |

The receipt scope is `ENGINEERING_ACCEPTANCE`. It proves P1 can produce and
replay a frozen Research IR; it does **not** authorize Worker dispatch, claim
that the planned evaluator exists, or claim scientific/SOTA success.

Replay without ambient project paths:

```bash
python3 ../../../mvp/research_compiler.py verify-freeze \
  --store acceptance-store \
  --receipt acceptance-store/receipts/sha256/3581453633e5a6ba23bcbcbcae09131263fe5233a00f15452c344240123d4b32.json
```

Add `--check-paths` on the source machine to revalidate the bound workspace,
code root, baseline sources, and evaluator working directory.
