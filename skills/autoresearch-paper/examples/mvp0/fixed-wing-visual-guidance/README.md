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
| Proposal record | `bc50735ef26d787baebfe0f0538e3181ff0e7d273fddbf7de427b21284e23255` |
| Critique record | `a2e907a5c7ebb4b876166d7b0f9dfd17ffb6d8215fe5fdf0183866a371b2fdb6` |
| Frozen revised IR | `88096110be7a32b9f57d719442a50ebbba7e0358a7228a34a5e50c495850bcb5` |
| Revision record | `c742e5971b7f729ed0cd1ad3d616c25ad77d70156b91346d94bb7972f00c152f` |
| Freeze receipt | `520661ab70a879d1f1be88c0140de523ea8a29290c45b81baee12804e590c9be` |

The receipt scope is `ENGINEERING_ACCEPTANCE`. It proves P1 can produce and
replay a frozen Research IR; it does **not** authorize Worker dispatch, claim
that the planned evaluator exists, or claim scientific/SOTA success.

Replay without ambient project paths:

```bash
python3 ../../../mvp/research_compiler.py verify-freeze \
  --store acceptance-store \
  --receipt acceptance-store/receipts/sha256/520661ab70a879d1f1be88c0140de523ea8a29290c45b81baee12804e590c9be.json
```

Add `--check-paths` on the source machine to revalidate the bound workspace,
code root, baseline sources, and evaluator working directory.
