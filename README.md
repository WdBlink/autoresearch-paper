<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="Autoresearch Paper" src=".github/logo-light.svg" width="440">
  </picture>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Version][version-shield]][repo-url]
[![Agent Skills][skills-shield]][skills-url]

</div>

Autoresearch is a modular, evidence-first lifecycle for turning an early idea
into a compiled scientific manuscript while keeping research, evaluation,
experimentation, evidence review, and writing in separate contexts.

## Status

- **Current version:** v0.21.0
- **Stability:** experimental
- **Architecture:** seven independently invokable Agent Skills
- **Compatibility:** the previous v0.20 runtime remains available only through
  an explicitly selected, deprecated compatibility entry point

The modular suite is now the default. A new project enters at the stage that
matches the artifact it already has; it does not need to start a supervisory
runtime or load the whole lifecycle.

## Architecture

The suite is **1 thin router + 5 lifecycle skills + 1 conditional capability**:

| Role | Skill | Owns |
| --- | --- | --- |
| Thin router | `autoresearch-workflow` | Select exactly one next skill from a compact handoff, then stop |
| Lifecycle | `autoresearch-discovery` | Turn an idea into a falsifiable Research Brief |
| Lifecycle | `karpathy-autoresearch-adapter` | Map a frozen brief and repository into an Experiment Contract |
| Conditional capability | `autoresearch-evaluator-engineering` | Build and validate a missing or partial evaluator, then return to Adapter |
| Lifecycle | `autoresearch-experiment` | Run the bounded Research → Development → Review → Record loop |
| Lifecycle | `autoresearch-evidence` | Validate the frozen candidate and freeze its Claim Boundary |
| Lifecycle | `autoresearch-paper` | Produce and compile the manuscript package without reopening research |

All seven can be installed together, but one invocation loads only the selected
skill, its focused references, one compact manifest or contract from the prior
stage, and the necessary linked project files. It does not preload a prior
package. The router never performs domain work.

```text
idea
  → Discovery → Research Brief
  → Adapter → Experiment Contract
       ↘ partial/missing evaluator → Evaluator Engineering → Adapter
  → Experiment → Candidate Package
  → Evidence → Validated Research Package + Claim Boundary
  → Paper → Manuscript Package
```

## Choose an entry point

Start with the narrowest skill that matches the artifact already in hand.

| What you have | Invoke | Expected next artifact |
| --- | --- | --- |
| You want the suite to decide | `autoresearch-workflow` | Four-field route handoff |
| An idea, constraints, or early literature | `autoresearch-discovery` | `research-brief.md` |
| A frozen Research Brief and a repository | `karpathy-autoresearch-adapter` | `autoresearch/experiment-contract.md` after explicit apply authorization |
| Adapter issued `autoresearch/evaluator_plan.md` for `partial` or `missing` readiness | `autoresearch-evaluator-engineering` | `autoresearch/evaluator-package/manifest.json`, followed by Adapter reclassification |
| An Adapter-issued frozen ready Experiment Contract | `autoresearch-experiment` | `autoresearch/candidate-package/manifest.json` |
| A bound `autoresearch/evidence-request.md` from Evidence | `autoresearch-experiment` | Resume against the linked frozen Experiment Contract; never expand its authority |
| A bound `autoresearch/evaluator-invalid-return.md` from Experiment | `karpathy-autoresearch-adapter` | Treat the stale contract as ineligible in memory, then return a replacement plan for explicit apply authorization |
| An accepted Candidate Package manifest and intended claims | `autoresearch-evidence` | `validated-research-package/manifest.json` with Claim Boundary |
| A valid frozen Validated Research Package manifest and venue constraints | `autoresearch-paper` | `manuscript-package/` |

Use `autoresearch-workflow` when the correct stage is unclear. It reads one
compact handoff, emits exactly one next-skill decision, and stops.

## Artifacts

Artifacts are the lifecycle boundary. Each producer owns its artifact's
semantics; downstream skills consume the frozen result rather than reconstructing
the prior stage's context.

| Producer | Canonical product | Consumer |
| --- | --- | --- |
| Discovery | `research-brief.md` | Adapter |
| Adapter | `autoresearch/experiment-contract.md` | Experiment |
| Evaluator Engineering | `autoresearch/evaluator-package/` | Adapter for reclassification |
| Experiment | `autoresearch/candidate-package/` | Evidence, only when it contains an accepted candidate |
| Evidence | `validated-research-package/`, including `claim-boundary.md` | Paper |
| Paper | `manuscript-package/` | User or a future dissemination capability |

The Paper product includes editable manuscript sources, bibliography,
figures/tables, traceability and review records, venue support files, a package
manifest, and a compiled submission artifact. It does not submit anything to an
external venue.

Package directories expose one compact entry point: Evaluator Engineering hands
Adapter `autoresearch/evaluator-package/manifest.json`, accepted Experiment
hands Evidence `autoresearch/candidate-package/manifest.json`, and Evidence
hands Paper `validated-research-package/manifest.json`. Each consumer opens only
the linked files needed for its current task.

## Install

List the repository's discoverable skills before selecting one:

```bash
npx skills add WdBlink/autoresearch-paper --list
```

Install one explicit entry point—for example, Paper:

```bash
npx skills add WdBlink/autoresearch-paper --skill autoresearch-paper -g --copy
```

Or intentionally install the complete seven-skill suite:

```bash
npx skills add WdBlink/autoresearch-paper --all -g --copy
```

`--all` installs all seven skills for availability; a run still loads only one
skill at a time. Omit `-g` for a project-local installation. New modular Paper
users do not run `scripts/setup.sh`; that script belongs to the compatibility
backend.

## Examples

Route from the current project state:

```text
Use autoresearch-workflow. I have research-brief.md but no Experiment Contract.
```

Start with an early question:

```text
Use autoresearch-discovery to frame a falsifiable Research Brief for reducing
tail latency in an existing inference service. The deployment constraints and
initial sources are attached.
```

Adapt a repository after the brief is frozen:

```text
Use karpathy-autoresearch-adapter with research-brief.md and this repository.
Inspect first and return the plan without changing files.
```

Enter directly at Paper when research has already been validated:

```text
Use autoresearch-paper with validated-research-package/manifest.json. Target the supplied
conference format and compile the final manuscript package.
```

Paper works autonomously inside the frozen Claim Boundary. It may verify
citations and derive reproducible presentation artifacts from existing data,
but it will not run claim-changing experiments.

## Stage boundaries

- **Discovery owns the question.** It does not inspect implementation details,
  choose an evaluator, adapt a repository, or run experiments.
- **Adapter owns execution design and all evaluator-readiness classification.**
  `ready` requires fixed inputs/splits, candidate-edit isolation,
  known-outcome/discrimination checks, and adequate repeatability—not merely a
  deterministic command. Adapter requires explicit authorization before
  persisting the approved plan or final ready Experiment Contract and never
  emits a partial contract. It accepts a bound evaluator-invalid return,
  treats its durable manifest as plan-only invalidation evidence without
  changing the worktree, and requires a new explicit apply authorization before
  persisting a revised adaptation plan and replacement artifact. The stale
  contract is never edited or reused in place.
- **Evaluator Engineering owns measurement construction.** It consumes only
  Adapter's `autoresearch/evaluator_plan.md` plus necessary linked project files.
  The plan carries frozen evaluation requirements and permitted design latitude
  plus the Research Brief identity/hash/reference, so Evaluator Engineering
  never loads the Brief. It changes only evaluator assets and returns its
  compact manifest to Adapter.
- **Experiment owns candidate search.** It accepts exactly one compact handoff:
  an Adapter-issued frozen contract for a new run, or a bound
  `autoresearch/evidence-request.md` for a resume. A resume opens the exact
  linked contract and cannot expand its authority. Every attempt is recorded;
  evaluator integrity/readiness failures return only to Adapter in
  `autoresearch/evaluator-invalid-return.md`.
- **Evidence owns scientific validation.** It opens claim-needed files from the
  Candidate Package manifest, freezes only `supported|qualified|unsupported`
  rows, and never tunes the method. `insufficient-evidence` produces an upstream
  request to Experiment, not a Validated Research Package. The request binds
  the exact contract, candidate, evaluator, missing evidence, permitted scope,
  and provenance needed for a safe resume.
- **Paper owns presentation.** It enters through the Validated Research Package
  manifest, refuses any package containing `insufficient-evidence`, and remains
  autonomous for a valid frozen package without altering research authority.
  A disclosed limitation is not missing evidence when every required frozen
  asset is present. For an absent/invalid required asset, Paper first attempts
  only an already-frozen deterministic recovery task exactly as recorded, when
  one exists. Only unavailable or failed recovery that leaves the asset
  absent/invalid is terminal; it cannot coexist with
  `manuscript-package-complete` or authorize new research.

Honest return paths are part of the architecture: `insufficient-evidence`
returns to Experiment; a partial or missing evaluator detours through Evaluator
Engineering and back to Adapter; `research-frame-invalid` waits for human
confirmation as `research-frame-invalid-confirmation-pending` before a
target-specific Evidence or Experiment route. `no-testable-opportunity`,
`evaluator-not-validatable`, `no-improvement`, `budget-exhausted`, and
`contract-reauthorization-needed`, `repository-not-runnable`, and
`baseline-failed` are terminal/no-route outcomes. Workflow uses
literal `next_skill: none` for them and for confirmation-pending states; none is
permission to weaken the scientific contract.

## Compatibility backend

The **v0.20 compatibility backend** preserves the former Codex Host,
Claude Code/MiniMax worker, Research IR, receipt ledger, evidence gate,
recompile loop, watchdog, dashboard, and optional MAVIS compatibility behavior.
It is deprecated, non-default, and not the semantic implementation of the new
Experiment, Evidence, or Paper skills.

The nested `autoresearch-paper-mvp0` entry point is not one of the seven modular
skills and is not part of standard modular discovery. Install it only when an
existing v0.20 workflow specifically depends on it:

```bash
skills/autoresearch-paper/scripts/install-mvp0.sh
```

This compatibility installer synchronizes files into its fixed shared install
location and creates runtime links. It does not promise backup-and-replace
semantics for pre-existing content. Review the script and preserve anything
important before choosing this deprecated path.

MAVIS remains optional and is used only by explicitly selected compatibility
fixtures. The modular lifecycle does not require MAVIS, the legacy watchdog, or
the legacy supervisory controller.

## Tests

Run the modular contract and documentation suite from the repository root:

```bash
scripts/test.sh modular
```

Run the v0.20 compatibility regression suite separately:

```bash
cd skills/autoresearch-paper
scripts/setup.sh test
```

Run both only when a change intentionally spans the modular suite and the
compatibility backend:

```bash
scripts/test.sh all
```

## Contributing

Keep every skill focused on its unique product and stop condition. Do not make a
domain skill preload the suite, duplicate the platform runtime, or reinterpret a
previous stage's scientific artifact. Add or update modular contract tests for
stage changes, and run the compatibility suite when touching retained v0.20
files.

Issues and pull requests are welcome. Describe the stage boundary being changed,
the artifact contract affected, and the evidence used to verify the change.

## Citation

If this suite contributed to a research artifact, cite the release as:

```bibtex
@software{autoresearch_paper,
  title   = {Autoresearch: A Modular Evidence-First Research Lifecycle},
  author  = {WdBlink},
  year    = {2026},
  url     = {https://github.com/WdBlink/autoresearch-paper},
  version = {0.21.0}
}
```

## License

MIT

[license-shield]: https://img.shields.io/github/license/WdBlink/autoresearch-paper.svg
[license-url]: https://github.com/WdBlink/autoresearch-paper/blob/main/LICENSE
[version-shield]: https://img.shields.io/badge/version-0.21.0-CC785C
[repo-url]: https://github.com/WdBlink/autoresearch-paper
[skills-shield]: https://img.shields.io/badge/Agent%20Skills-compatible-2f6f8f
[skills-url]: https://skills.sh/
