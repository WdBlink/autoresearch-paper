---
name: autoresearch-workflow
description: Use when routing an Auto-Research project from an explicit entry request or compact artifact handoff to exactly one next modular skill, terminal state, confirmation wait, or return loop without performing domain work.
---

# Core contract

Act only as a thin router. Accept either an explicit entry request or one
four-field compact handoff, select the first matching state in the canonical
route matrix, emit exactly one four-field handoff, and stop. Never inspect
repository internals, load another skill, create domain artifacts, or perform
research work.

# Input

The input handoff has `next_skill`, `reason`, `input_artifact`, and
`resume_artifact`. Its `reason` begins `status=<canonical-token>;`. For direct
entry, use only the artifacts, status, and human confirmation explicitly stated;
treat a referenced-but-missing required input as missing rather than inferring a
different lifecycle state.

Read [artifact handoffs](references/artifact-handoffs.md) to obtain the ordered
route matrix. Negative, refusal, confirmation, evaluator-return, and terminal
rows precede artifact-presence fallthrough. Select the first matching row.

# Routing

The only domain destinations are `autoresearch-discovery`,
`karpathy-autoresearch-adapter`, `autoresearch-evaluator-engineering`,
`autoresearch-experiment`, `autoresearch-evidence`, and `autoresearch-paper`.
Use literal `none` for a terminal outcome, confirmation-pending state, refused
package, or any other canonical no-route row. Do not route back to Discovery
after a Research Brief exists.

Evaluator construction is a conditional operational detour: Adapter sends a
`partial` or `missing` evaluator to Evaluator Engineering; an Evaluator Package
returns to Adapter. An evaluator integrity/readiness problem found by Experiment
also returns to Adapter. Neither path is a scientific return loop.

# Handoff

Emit only this YAML shape, preserving this field order and replacing the values
from the selected route-matrix row. The following terminal example demonstrates
that `next_skill: none` is representable without a fifth field:

```yaml
next_skill: none
reason: status=research-frame-invalid-confirmation-pending; Paper cannot route until a human selects the correction target.
input_artifact: validated-research-package/manifest.json
resume_artifact: none
```

# Stop

Always stop after routing. Return no explanation, plan, or execution output
beyond the compact YAML handoff.

# Boundaries

Do not perform discovery, evaluator engineering, adaptation, experimentation,
evidence review, or paper writing. The router represents state and selects; the
selected skill owns all domain procedure.
