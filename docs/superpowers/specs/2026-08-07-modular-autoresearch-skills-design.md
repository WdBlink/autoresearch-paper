# Modular Auto-Research Skills Design

**Date:** 2026-08-07

**Status:** Proposed for implementation

**Target release:** v0.21.0 modular preview

## 1. Context

The current `autoresearch-paper` skill has accumulated several different jobs:

- framing a research problem;
- adapting an arbitrary repository for autonomous experiments;
- defining or validating an evaluator;
- running a long-lived optimization loop;
- validating scientific evidence;
- writing, reviewing, formatting, and packaging a paper;
- operating host infrastructure such as watchdogs, lifecycle controls, and a dashboard.

These jobs have different objectives, failure modes, context needs, and appropriate human involvement. Keeping them in one entry point makes the skill expensive to load, encourages premature governance, and lets slow protocol machinery swallow the fast experimental loop.

The existing paper-production flow is a particularly poor place for research-stage controls. Once a project has a mature method, code, experiments, and evidence, paper production is a structured transformation task. It should run autonomously and repeatedly read the frozen research assets, complete presentation-level gaps, generate figures and tables, compile the manuscript, and review the result. It should not be forced through human approval gates intended for uncertain earlier research decisions.

This design replaces the all-in-one skill with a small suite of stage-specific skills connected by a thin router.

## 2. Source-Informed Principles

The design uses three source families without copying any one paper's taxonomy literally.

### 2.1 Deli paper production

The mature paper stage absorbs the proven production mechanisms:

1. literature and citation support;
2. paper structure and scientific narrative;
3. analysis of already-frozen results;
4. figures and tables;
5. iterative peer review, format review, and visual review.

These are internal capabilities of one autonomous paper skill, not five mandatory top-level workflow stages. Deli's workflow can reopen scientific search by adding experiments or changing a hypothesis, and its published guidance is oriented toward survey-style papers. Neither behavior is copied as a universal rule for original research papers. The new Paper skill keeps the production machinery while respecting a frozen evidence boundary.

### 2.2 XYZ bounded exploration

The experiment stage uses a versioned optimization contract and the repeated state transition:

`Research -> Development -> Review -> Record`

The contract bounds scope, permissions, evaluator, resources, authority, and stopping conditions. The optimizer cannot modify the evaluator or adoption gate inside the same decision path. Accepted and rejected attempts are both recorded.

This loop belongs entirely inside the experiment skill. It must not become a repository-wide controller or a sequence of separate governance skills.

### 2.3 Auto-research lifecycle roadmap

The broader lifecycle distinguishes research creation, writing, validation, and dissemination. The practical lesson is stage-dependent reliability: structured, tool-mediated production can be highly autonomous, while novel scientific judgment and evaluator design need their own stage-specific policies.

The first modular release covers discovery through paper production. Rebuttal and dissemination remain future extensions rather than empty taxonomy placeholders.

## 3. Goals

- Give each stage one clear optimization target.
- Load only the instructions and references required for the active stage.
- Preserve the fast experimental optimization loop.
- Make evaluator construction an explicit conditional detour rather than an assumed universal stage.
- Separate candidate optimization from final scientific validation.
- Make paper production fully autonomous once its input package is mature.
- Preserve the current Codex-hosted MVP runtime and its tests while moving its user-facing responsibility to the experiment stage.
- Keep existing installations usable through a documented compatibility window.
- Ensure one invocation loads only the current skill, the previous stage's compact artifact, and necessary project files.

## 4. Non-Goals

- Defining one global human-in-the-loop policy for the entire lifecycle.
- Requiring a human checkpoint before every stage or experiment iteration.
- Turning every artifact into a signed governance object.
- Building a new central scheduler, daemon, dashboard, or state machine.
- Claiming that every research project must follow a linear path.
- Implementing rebuttal, publication, publicity, or long-term research portfolio management in v0.21.0.
- Guaranteeing SOTA. The system optimizes toward a declared target and reports the actual result honestly.

## 5. Architecture: One Thin Router, Five Lifecycle Skills, One Conditional Capability

```text
Idea -> Discovery -> Repository Adapter -> Experiment -> Evidence -> Paper
                         ^       |
                         |       | evaluator partial or missing
                         |       v
                         +-- Evaluator Engineering
                              then reclassify and freeze the contract

Experiment <---------------- Evidence insufficient
Evidence or Experiment <- human confirmation <- Paper finds frame invalid

             Workflow = thin routing shell around these transitions
```

The architecture contains one thin router:

1. `autoresearch-workflow`

five research-lifecycle skills:

2. `autoresearch-discovery`
3. `karpathy-autoresearch-adapter`
4. `autoresearch-experiment`
5. `autoresearch-evidence`
6. `autoresearch-paper`

and one conditional capability skill:

7. `autoresearch-evaluator-engineering`

All seven skills may be installed and independently invoked, but they are never loaded together as one execution context. Each invocation loads only:

1. the current skill;
2. the previous stage's compact artifact;
3. the necessary project files.

A project may enter at any stage when it already possesses the required input artifact.

| Skill | One core question | Unique product |
|---|---|---|
| Workflow | Where should the project go now? | Next skill plus artifact references |
| Discovery | What problem is worth researching? | Research Brief |
| Adapter | Can this problem be implemented, run, and measured reliably in this repository? | Experiment Contract |
| Experiment | What candidate is better inside the frozen contract? | Candidate Package with Experiment Ledger |
| Evidence | Which claims actually hold? | Validated Research Package with Claim Boundary |
| Paper | How should the frozen claims be expressed faithfully and clearly? | Manuscript Package |
| Evaluator Engineering | How can a missing measurement capability be built and checked? | Reproducible Evaluator Package |

The governing principle is:

> First decide what to research, then decide whether it can be measured. Search only inside a frozen experimental frame. Validate independently after leaving the search loop. Write only from frozen evidence.

## 6. Skill Contracts

### 6.1 `autoresearch-workflow`: thin router

**Purpose:** Determine the current stage from one compact handoff or an explicit entry request, select the appropriate domain skill, and preserve links to outputs.

**Inputs:** A user goal plus at most one compact handoff manifest containing status and artifact references. Workflow may check the existence of referenced paths, but it does not read the complete domain artifacts to make the route decision.

**Unique product:** A route decision: the next skill to invoke plus compact references to existing artifacts. If persistence is useful, record exactly this decision in `workflow-state.md`.

**Stop condition:** Exactly one domain skill is selected, or one concrete missing input prevents routing. Workflow stops immediately after handing control over; it never executes the selected domain work in its own context.

**Must do:**

- accept entry at any stage;
- check only the receiving skill's published input contract;
- support only the explicit return edges defined in Section 12;
- leave autonomy and human participation to each domain stage.

**Must not do:**

- duplicate domain instructions;
- maintain a second experiment state machine;
- introduce a universal approval gate;
- inspect multiple complete stage artifacts when a compact status and references are sufficient;
- preload another domain skill, the whole suite, or all project artifacts;
- own watchdog, scheduler, or dashboard behavior.

### 6.2 `autoresearch-discovery`: decide what is worth testing

**Purpose:** Convert an idea or broad problem into a falsifiable, literature-aware research opportunity.

**Inputs:** Idea, problem statement, optional repository, constraints, and target venue or audience when known.

**Unique product:** `research-brief.md` with the problem, prior art, gap, candidate hypotheses, falsifiers, plausible baselines, evaluation needs, risks, and recommended next step.

**Stop condition:** At least one testable research direction is supported by evidence and has a credible path to evaluation, or the skill records `no-testable-opportunity`. “No worthwhile direction yet” is a valid honest outcome.

**Must not do:**

- adapt the repository for autonomous execution;
- run an open-ended optimization campaign;
- manufacture a novelty or SOTA claim;
- draft the final paper.

Human participation for discovery is intentionally stage-local and remains to be designed from real use. This release does not impose a global checkpoint.

### 6.3 `karpathy-autoresearch-adapter`: establish the execution boundary

**Purpose:** Translate a frozen Research Brief into a bounded, repeatable Experiment Contract for the current repository.

**Inputs:** Repository, `research-brief.md` or an equivalent frozen research definition, resource constraints, and any known evaluation command.

**Unique product:** `autoresearch/experiment-contract.md`. It links the repository-local protocol assets required to execute it: editable scope, setup and baseline commands, target metric, resource budget, experiment instructions, baseline evidence, and evaluator readiness classification.

**Stop condition:** A fresh agent can execute the baseline and knows exactly what it may edit, how results are measured, and when to stop; or the skill stops with `repository-not-runnable`, `baseline-failed`, `partial`, or `missing`.

**Evaluator readiness:**

- `ready`: route directly to Experiment;
- `partial`: route to Evaluator Engineering, then return to Adapter for reclassification;
- `missing`: route to Evaluator Engineering, then return to Adapter for reclassification.

**Must not do:**

- redefine the research gap, contribution, or hypothesis owned by the Research Brief;
- copy the Research Brief into a second independently editable source of research truth;
- optimize the candidate method;
- declare the evaluator scientifically valid merely because it runs;
- absorb the subsequent experiment loop;
- write the paper.

The Experiment Contract references the Research Brief and owns only how the research is implemented, run, and measured in this repository. The implementation should preserve the existing Karpathy adapter's plan-first contract rather than invent a competing generic adapter.

### 6.4 `autoresearch-evaluator-engineering`: conditional evaluator construction

**Purpose:** Create or repair a trustworthy evaluator when the adapter cannot certify one as ready.

**Inputs:** Experiment Contract, Research Brief, available datasets or fixtures, and known sources of measurement error.

**Unique product:** `autoresearch/evaluator-package/`, containing the versioned evaluator, fixtures, validation report, metric definition, isolation rules, and known limitations.

**Stop condition:** The evaluator is executable, discriminative, repeatable enough for the stated budget, and isolated from candidate edits; or the skill records `evaluator-not-validatable` and stops without opening Experiment.

**Must not do:**

- optimize the research method against an evaluator it is still changing;
- hide weak evaluator validity behind procedural approval;
- become mandatory when a suitable evaluator already exists;
- claim external scientific transfer from a private development benchmark.

Human participation for evaluator engineering is stage-local and intentionally undecided in this release.
After a successful evaluator build, control returns to Adapter so the repository-specific Experiment Contract can bind and freeze the evaluator before Experiment starts.

### 6.5 `autoresearch-experiment`: search for the best supported candidate

**Purpose:** Run bounded experimental optimization against a frozen evaluator.

**Inputs:** Experiment Contract, evaluator package or a `ready` evaluator declaration, resource budget, and stop/re-authorization conditions.

**Unique product:** `autoresearch/candidate-package/`, containing `experiment-ledger.jsonl`, reproducible candidate artifacts, accepted-candidate summary, complete logs for accepted and rejected attempts, and an honest outcome classification.

**Internal loop:**

1. **Research:** inspect current evidence and propose the next bounded intervention;
2. **Development:** implement only within the editable scope;
3. **Review:** run the isolated evaluator and apply the declared acceptance rule;
4. **Record:** persist result, provenance, decision, and next-state information.

**Stop condition:** The declared budget, success threshold, or stopping rule is reached with a reproducible best candidate and a complete ledger. `no-improvement`, `budget-exhausted`, and `contract-reauthorization-needed` are valid outcomes.

**Must not do:**

- modify the evaluator in the same optimization path;
- use a cheap screening metric as final scientific proof;
- turn each iteration into a human approval ceremony;
- write or cosmetically optimize the paper;
- claim SOTA without final evidence against the relevant external baselines.

The current P1-P6 Codex-hosted runtime becomes an implementation option for this skill, not the definition of the entire research lifecycle.

### 6.6 `autoresearch-evidence`: freeze and validate the scientific claim

**Purpose:** Turn an accepted experimental candidate into a paper-ready, independently inspectable evidence package.

**Inputs:** Frozen candidate, experiment ledger, evaluator contract, relevant baselines, and claim scope.

**Unique product:** `validated-research-package/`, containing a manifest, frozen code and configuration references, final result tables, repeated runs or uncertainty estimates where applicable, ablations, error analysis, provenance, limitations, and a Claim Boundary.

The Claim Boundary is a semantic artifact, not a new authority service. For every candidate claim it records:

```text
Claim
-> supporting evidence
-> applicable scope
-> uncertainty / limitation
-> supported / qualified / unsupported
```

**Stop condition:** Every intended headline claim is supported, qualified, or explicitly rejected by reproducible evidence; or Evidence records `insufficient-evidence` and routes to Experiment.

**Allowed work:** Repeat frozen evaluations, run predefined ablations, fill missing seeds, compare declared baselines, and produce analysis needed to interpret results.

**Must not do:**

- change the candidate method to chase a better result;
- silently redefine the evaluator or claim;
- become a heavyweight claim-governance bureaucracy;
- require a human approval merely because the stage exists;
- draft the complete manuscript.

If validation exposes insufficient evidence or a method problem, route back to Experiment. A rejected premise is recorded honestly; this release does not automatically open a new Discovery loop.

### 6.7 `autoresearch-paper`: autonomous manuscript production

**Purpose:** Turn mature research assets into a submission-ready paper package.

**Inputs:** `validated-research-package/`, repository and experiment assets, target venue or format, and optional author constraints.

**Unique product:** `manuscript-package/`, containing manuscript source, compiled paper, figures, tables, bibliography, review reports, and submission checklist.

**Stop condition:** All manuscript release checks pass and `submission-package-ready` is recorded; or a missing frozen asset is identified; or `research-frame-invalid` pauses for human confirmation before any upstream route.

**Internal loop:**

1. inventory and freeze source assets;
2. research literature needed for positioning and citation verification;
3. design the paper structure and contribution narrative inside the Claim Boundary;
4. write the complete manuscript grounded in available evidence;
5. generate or repair figures and tables;
6. run scientific, citation, format, and visual reviews;
7. route each review finding to the relevant internal subtask;
8. compile and repeat until all release checks pass or a typed upstream gap is found.

**Autonomy:** This stage is fully autonomous. It does not stop for routine outline, draft, figure, formatting, or reviewer approval once the user has asked it to produce the paper.

**Allowed completion work:** Re-run frozen deterministic tasks, compute additional statistics from existing data, fill table cells from existing results, and generate presentation artifacts from the frozen method, evaluator, and evidence.

**Must not do:**

- alter the research method or evaluator;
- start an open-ended SOTA search;
- add a new seed, ablation, or experiment whose outcome could change the Claim Boundary;
- strengthen a claim beyond the status, scope, or uncertainty frozen by Evidence;
- invent missing results, citations, or novelty;
- import host watchdog and lifecycle machinery into the writing instructions;
- turn internal review into a global human gate.

If a presentation gap can be filled from frozen tasks or existing data, Paper completes it autonomously. If a new seed, ablation, or experiment could change a claim, Paper does not run it. If Paper discovers that the research frame itself is invalid, it pauses for human confirmation before routing to Evidence or Experiment; it does not disguise renewed scientific search as writing.

## 7. Stage-Specific Autonomy

Autonomy is a property of each stage, not the workflow as a whole.

| Stage | v0.21.0 autonomy decision |
|---|---|
| Workflow | Automatically routes; owns no scientific approval |
| Discovery | Local policy deliberately left open for later design |
| Adapter | Plan-first and bounded by repository safety; local policy may evolve |
| Evaluator Engineering | Local policy deliberately left open for later design |
| Experiment | Iterations run without per-cycle approval inside the active contract; exceptions follow the contract |
| Evidence | Performs frozen validation autonomously; scientific scope changes route upstream |
| Paper | Fully autonomous inside frozen evidence; only an invalid research frame triggers human confirmation before upstream routing |

This table is not a universal human-gate policy. It records only what is already justified by the stage's work.

## 8. Minimal Artifact Protocol

The skills communicate through ordinary files and links rather than a large central schema.

| Producer | Required handoff | Consumer |
|---|---|---|
| Discovery | `research-brief.md` | Adapter or user |
| Adapter | `autoresearch/experiment-contract.md` | Evaluator Engineering or Experiment |
| Evaluator Engineering | `autoresearch/evaluator-package/` | Experiment |
| Experiment | `autoresearch/candidate-package/` | Evidence |
| Evidence | `validated-research-package/manifest.json`, result assets, `claim-boundary.md` | Paper |
| Paper | `manuscript-package/` | User or future dissemination skill |
| Workflow | `workflow-state.md` containing links only | Any next stage |

Each producer owns its artifact semantics. The workflow skill checks presence and declared status but does not reinterpret scientific content.

Typed upstream requests use a short common shape:

```yaml
target_stage: evidence | experiment | evaluator-engineering
reason: concise scientific or operational gap
required_artifact: exact missing or invalid asset
resume_when: observable completion condition
```

This is routing metadata, not an approval permit.

## 9. Platform Versus Domain Boundary

The following are platform capabilities and must not be copied into every domain skill:

- worker transport and host/worker process separation;
- heartbeat, watchdog, and recovery;
- lifecycle authentication and pause/resume/stop;
- scheduler or automation registration;
- dashboards and status projection;
- sandbox and secret handling.

A domain skill may state the capability it needs, such as a durable runner, but should reference a platform adapter only when that runtime is actually selected. The user-facing research workflow remains valid when run interactively without the legacy host stack.

## 10. Repository Layout

The v0.21.0 layout performs the semantic and context split first:

```text
skills/
  autoresearch-workflow/
    SKILL.md
    references/artifact-handoffs.md
  autoresearch-discovery/
    SKILL.md
  karpathy-autoresearch-adapter/
    SKILL.md
  autoresearch-evaluator-engineering/
    SKILL.md
  autoresearch-experiment/
    SKILL.md
    references/bounded-experiment-loop.md
  autoresearch-evidence/
    SKILL.md
  autoresearch-paper/
    SKILL.md
    references/paper/
    compat/SKILL.v0.20.md
    mvp/                 # unchanged compatibility payload
    mvp0/                # unchanged compatibility payload
    examples/mvp0/       # unchanged compatibility payload
    references/          # legacy harness references plus paper/
    scripts/             # unchanged compatibility tooling
    tests/               # compatibility regression suite
    dashboard/           # unchanged compatibility payload
tests/
  test_modular_skill_contracts.py
scripts/
  test.sh
```

Only the active skill's `SKILL.md` and explicitly linked references are loaded. Core entry points should remain compact and use progressive disclosure for detailed checklists or templates.
Each modular skill also carries generated `agents/openai.yaml` UI metadata; the repeated metadata path is omitted from the tree above. Skill folders do not carry per-skill README, changelog, or installation guides.

The old 895-line prompt is preserved as `compat/SKILL.v0.20.md`; it is not named `SKILL.md` and therefore is not discoverable as another active skill. The existing runtime tree remains physically in place for this release because its standalone-copy behavior, setup script, tests, references, and dashboard are tightly path-coupled. It is a deprecated compatibility backend, not the semantic implementation of the new Experiment or Evidence skills.

The runtime files remain in place, but the compatibility tests are not literally unchanged: every assertion that previously treated the root `SKILL.md` as the v0.20 Host/runtime contract is redirected to `compat/SKILL.v0.20.md`. New tests own the root Paper contract. Runtime behavior assertions remain intact.

This apparent colocation does not consume model context: the new Paper entry point references only `references/paper/`. None of the new domain skills references the legacy prompt or compatibility runtime by default. A later release may move the entire compatibility tree atomically to `compat/autoresearch-paper-v0.20/`; it must not split the coupled runtime piecemeal.

## 11. Migration Strategy

### 11.1 Compatibility

- Keep `autoresearch-paper` as the public name for the new paper-only skill.
- Keep `autoresearch-paper-mvp0` as a deprecated compatibility entry point during one release; do not present it as the new modular Experiment skill.
- Preserve existing runtime behavior and the full baseline test suite before deleting any legacy alias.
- Publish all modular skills from the same repository and install them independently or as a suite.

The nested MVP0 entry point is not one of the seven modular skills and is not promised as a standard Skills CLI discovery result. It remains installable only through the explicitly named compatibility installer in this release. Its invalid/unintended nested discovery behavior must not be used to satisfy modular suite tests.

### 11.2 Existing Karpathy adapter

The repository will include a canonical copy of the existing `karpathy-autoresearch-adapter` contract, with provenance noted in its README/reference material. Its approved plan becomes a durable `autoresearch/adaptation-plan.md`, and its applied output includes the referenced `experiment-contract.md`. The suite must not silently mutate the user's separately installed copy.

The current compatibility installer does not provide safe backup-and-replace semantics. Any new repository-owned installer must fail on a conflicting real directory or create an explicit backup before replacement. The primary multi-skill installation path uses the standard Skills CLI with explicit `--skill` selection (or an intentional `--all`); the repository does not reimplement a generic multi-agent installer.

### 11.3 Documentation

The README starts with the modular lifecycle and stage-entry examples. Installation examples select named skills so a multi-skill repository is never ambiguous. Legacy host/runtime registration moves to a compatibility section. The changelog explains renamed responsibilities, artifact handoffs, and the deprecated MVP0 entry point.

## 12. Error and Return Routing

Each stage either produces its success artifact, returns a typed upstream request, or reports an honest terminal outcome.

- Discovery may return `no-testable-opportunity`.
- Adapter may return `repository-not-runnable`, `baseline-failed`, or evaluator `partial/missing`.
- Evaluator Engineering may return `evaluator-not-validatable`.
- Experiment may return `no-improvement`, `budget-exhausted`, or `contract-reauthorization-needed`.
- Evidence may return `claim-narrowed`, `claim-rejected`, or `insufficient-evidence`; insufficient evidence routes to Experiment.
- Paper may return `missing-frozen-evidence`, `research-frame-invalid`, or `submission-package-ready`. `research-frame-invalid` requires human confirmation before routing to Evidence or Experiment.

“No improvement” and “claim rejected” are scientifically valid outcomes, not system failures.

The release keeps only two scientific return loops:

```text
Evidence insufficient -> Experiment
Paper finds research frame invalid -> human confirmation -> Evidence or Experiment
```

## 13. Test Strategy

### 13.1 Structural contract tests

- every skill has valid frontmatter and a unique name;
- every referenced local file exists;
- each required input, output, success condition, and forbidden responsibility is present;
- the workflow contains the conditional evaluator route and stage return edges;
- the Paper skill explicitly declares full autonomy and forbids method/evaluator changes;
- the Experiment skill contains the four-state XYZ loop and evaluator-isolation rule;
- no domain skill imports the whole suite or platform instructions by default.

### 13.2 Artifact handoff tests

Use small fixtures to verify routing for:

- idea-only entry;
- repository with evaluator ready;
- repository with evaluator partial;
- accepted candidate needing final evidence;
- mature validated package and Claim Boundary entering Paper directly;
- Paper filling a bounded presentation gap from frozen work or existing data;
- Paper refusing a new seed, ablation, or experiment that could change a claim;
- Paper pausing for human confirmation when the research frame is invalid.

### 13.3 Installer tests

- list all independently discoverable skills through the standard Skills CLI;
- install one explicitly selected skill;
- install the complete suite only through an intentional `--all` selection;
- preserve the deprecated MVP0 alias through the separate compatibility installer, not modular CLI discovery;
- make any repository-owned compatibility installer fail or back up conflicting destinations rather than overwriting silently;
- verify Claude Code and Codex discovery paths when both are requested.

### 13.4 Regression tests

- run the existing 330-test MVP/runtime suite from its unchanged compatibility location;
- keep contract, lifecycle, security, fault-soak, and dashboard tests passing;
- run documentation link and path checks;
- run a clean paper-stage fixture that never invokes the experiment optimizer.

## 14. Rollout

1. Add the modular entry points and handoff contracts.
2. Preserve the current MVP runtime as a compatibility backend without loading or relabeling it as a modular lifecycle stage.
3. Archive the old prompt and replace the monolithic Paper entry point with the autonomous paper-only flow.
4. Add suite and per-skill installation.
5. Update README, changelog, and migration notes.
6. Run structural, handoff, installer, and legacy regression tests.
7. Mark the MVP0 alias deprecated but do not remove it in this release.

## 15. Acceptance Criteria

The modular preview is complete when:

- the thin router, all five lifecycle skills, and the conditional evaluator capability are independently invokable;
- an invocation loads only its current skill, previous compact handoff, and necessary project files;
- the workflow routes by existing artifacts without imposing a global gate;
- Paper can start directly from a mature validated package, stay inside its Claim Boundary, and complete autonomously;
- Experiment owns the bounded `Research -> Development -> Review -> Record` loop;
- evaluator engineering is invoked only for `partial` or `missing` readiness;
- Evidence produces a compact validated research package without becoming a governance subsystem;
- current MVP/runtime behavior remains covered and passing;
- all skill references and installers work from a clean checkout;
- README and changelog describe the new lifecycle and compatibility behavior;
- no unrelated user files or experimental receipts are included in the branch.

## 16. Primary References

- XYZ Lab, *Bounded-Exploration AI4AI for System Optimization*: <https://xyz-lab.ai/blogs/ai4ai-at-scale/assets/bounded-exploration-ai4ai-system-optimization.pdf>
- Deli, *Paper Writing*: <https://victorchen96.github.io/auto_research/skill/paper-writing.html>
- *AI for Auto-Research: Roadmap & User Guide*: <https://arxiv.org/html/2605.18661>
