# Modular Auto-Research Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic Auto-Research entry point with one thin router, five independently invokable lifecycle skills, and one conditional evaluator capability while preserving the v0.20 runtime as a non-default compatibility backend.

**Architecture:** Each invocation loads one skill, one compact prior handoff, and necessary project files. Skills communicate through one primary artifact per stage; Workflow only routes, Adapter owns repository execution boundaries, Experiment owns bounded search, Evidence freezes the Claim Boundary, and Paper writes autonomously from frozen evidence. The legacy Host/Worker/watchdog tree remains physically stable for this release but is no longer referenced by the Paper skill.

**Tech Stack:** Markdown Agent Skills, YAML frontmatter and `agents/openai.yaml`, Python 3 `unittest`, Bash, Vercel Skills CLI, existing v0.20 Python/Bash runtime tests.

## Global Constraints

- The public architecture is exactly one thin router, five lifecycle skills, and one conditional capability: `autoresearch-workflow`, `autoresearch-discovery`, `karpathy-autoresearch-adapter`, `autoresearch-experiment`, `autoresearch-evidence`, `autoresearch-paper`, and `autoresearch-evaluator-engineering`.
- Installed does not mean loaded: one invocation reads only the current `SKILL.md`, at most one compact handoff, explicitly linked local references, and necessary project files.
- Every new `SKILL.md` frontmatter contains only `name` and `description`; descriptions start with `Use when` and describe triggers rather than summarizing the workflow.
- Keep each active `SKILL.md` at or below 220 lines and 1,400 words; move only conditional detail into one-level-deep references.
- Discovery owns why and what to research. Adapter references the Research Brief and owns only how to implement, run, and measure it in the current repository.
- Adapter remains plan-first. It writes repository files only after explicit apply authorization; this local safety boundary is not a global workflow gate.
- Evaluator Engineering is invoked only for `partial` or `missing` evaluator readiness, returns to Adapter for reclassification, and never co-optimizes the candidate method.
- Experiment contains the complete XYZ `Research -> Development -> Review -> Record` loop. It never modifies the frozen evaluator in the same decision path.
- Evidence may run claim-changing validation work, but never changes the candidate method. Its Claim Boundary records claim, supporting evidence, scope, uncertainty/limitation, and `supported|qualified|unsupported` status.
- Paper is fully autonomous inside frozen evidence. It may rerun frozen deterministic tasks and derive statistics/figures from existing results, but it never adds a new seed, ablation, or experiment whose outcome could change the Claim Boundary.
- Keep exactly two scientific return loops: `Evidence insufficient -> Experiment` and `Paper frame invalid -> human confirmation -> Evidence or Experiment`. Do not add an automatic return to Discovery.
- Absorb Deli's Literature, Structure, Figures/Tables, Compilation, and Peer Review production mechanisms; do not import survey-specific quotas or its ability to reopen scientific search.
- Preserve negative and null outcomes honestly. No skill guarantees SOTA.
- Create new skills with the system `skill-creator/scripts/init_skill.py`; generate `agents/openai.yaml` with only `display_name`, `short_description`, and a `$skill-name` default prompt.
- Follow RED-GREEN-REFACTOR for every skill. Do not begin the next skill until the current skill passes its static contract, `quick_validate.py`, and a fresh-context forward test.
- Do not touch or commit the untracked acceptance receipts in the original checkout.

---

### Task 1: Skill-test harness and no-skill baselines

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/skill_contract_helpers.py`
- Create: `tests/test_skill_contract_helpers.py`
- Create: `docs/superpowers/evaluations/2026-08-07-modular-skills-baseline.md`

**Interfaces:**
- Produces: `load_skill(name) -> tuple[dict[str, object], str]`, `local_markdown_links(skill_dir, body) -> list[Path]`, and `assert_compact_skill(testcase, name)` for all later contract tests.
- Produces: a baseline record with prompt, observed behavior, and concrete failure for each of the seven intended skills.

- [ ] **Step 1: Write the failing helper test**

```python
from pathlib import Path
import unittest

from tests.skill_contract_helpers import parse_frontmatter


class SkillContractHelperTests(unittest.TestCase):
    def test_parse_frontmatter_returns_metadata_and_body(self):
        metadata, body = parse_frontmatter(
            "---\nname: sample-skill\ndescription: Use when a sample is needed.\n---\n\n# Sample\n"
        )
        self.assertEqual(metadata, {
            "name": "sample-skill",
            "description": "Use when a sample is needed.",
        })
        self.assertEqual(body.strip(), "# Sample")
```

- [ ] **Step 2: Run the helper test and verify RED**

Run: `python3 -m unittest tests.test_skill_contract_helpers -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tests.skill_contract_helpers'`.

- [ ] **Step 3: Implement the shared helper**

```python
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    match = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", text, re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md must contain YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise AssertionError("SKILL.md frontmatter must be a mapping")
    return metadata, match.group(2)


def load_skill(name: str) -> tuple[dict[str, object], str]:
    return parse_frontmatter((SKILLS_ROOT / name / "SKILL.md").read_text())


def local_markdown_links(skill_dir: Path, body: str) -> list[Path]:
    targets = []
    for raw in re.findall(r"\[[^]]+\]\(([^)]+)\)", body):
        if raw.startswith(("http://", "https://", "#")):
            continue
        targets.append((skill_dir / raw.split("#", 1)[0]).resolve())
    return targets


def assert_compact_skill(testcase, name: str) -> str:
    path = SKILLS_ROOT / name / "SKILL.md"
    metadata, body = load_skill(name)
    testcase.assertEqual(set(metadata), {"name", "description"})
    testcase.assertEqual(metadata["name"], name)
    testcase.assertTrue(str(metadata["description"]).startswith("Use when"))
    testcase.assertNotIn("TO" + "DO", path.read_text())
    testcase.assertLessEqual(len(path.read_text().splitlines()), 220)
    testcase.assertLessEqual(len(path.read_text().split()), 1400)
    for target in local_markdown_links(path.parent, body):
        testcase.assertTrue(target.is_relative_to(path.parent.resolve()))
        testcase.assertTrue(target.exists(), str(target))
    return body
```

- [ ] **Step 4: Run the helper test and verify GREEN**

Run: `python3 -m unittest tests.test_skill_contract_helpers -v`

Expected: PASS.

- [ ] **Step 5: Run and record fresh-context RED scenarios**

Use fresh agents without any of the new skill files. Record the complete prompt, the relevant verbatim response excerpt, and one observable failure for each case:

1. Workflow begins Adapter work instead of returning one next-skill handoff.
2. Discovery treats “novel/SOTA quickly” as a result requirement or omits a falsifier.
3. Existing Adapter does not create a durable Research-Brief-referencing Experiment Contract.
4. Experiment edits or weakens a judge, or treats a cheap proxy as adoption authority.
5. Evidence omits scope/uncertainty/status from its claim mapping or tunes the method.
6. Paper runs missing seeds or a new ablation instead of respecting frozen evidence.
7. Evaluator construction co-optimizes the candidate or launches Experiment before evaluator isolation is validated.

The baseline document uses seven sections with these exact fields: `Prompt`, `Observed behavior`, `Contract violation`, `Skill requirement derived`.

- [ ] **Step 6: Commit the harness and baseline evidence**

```bash
git add tests/__init__.py tests/skill_contract_helpers.py \
  tests/test_skill_contract_helpers.py \
  docs/superpowers/evaluations/2026-08-07-modular-skills-baseline.md
git commit -m "test: capture modular skill baselines"
```

### Task 2: Thin Workflow router

**Files:**
- Create: `tests/test_autoresearch_workflow_contract.py`
- Create: `skills/autoresearch-workflow/SKILL.md`
- Create: `skills/autoresearch-workflow/agents/openai.yaml`
- Create: `skills/autoresearch-workflow/references/artifact-handoffs.md`

**Interfaces:**
- Consumes: an explicit entry request or one exact four-field compact handoff;
  status is the `status=<token>;` prefix in `reason`.
- Produces: exactly `next_skill`, `reason`, `input_artifact`, and
  `resume_artifact`; literal `next_skill: none` represents terminal,
  confirmation-pending, refusal, and no-route states.

- [ ] **Step 1: Write the failing Workflow contract test**

```python
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_a_router_not_an_executor(self):
        body = assert_compact_skill(self, "autoresearch-workflow")
        for token in (
            "next_skill", "input_artifact", "resume_artifact",
            "at most one compact handoff", "stop after routing",
            "karpathy-autoresearch-adapter", "autoresearch-evaluator-engineering",
        ):
            self.assertIn(token, body)
        self.assertNotIn("run the experiment", body.lower())
        self.assertNotIn("draft the paper", body.lower())
```

- [ ] **Step 2: Run the Workflow test and verify RED**

Run: `python3 -m unittest tests.test_autoresearch_workflow_contract -v`

Expected: FAIL because `skills/autoresearch-workflow/SKILL.md` does not exist.

- [ ] **Step 3: Initialize the Workflow skill**

Run:

```bash
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  autoresearch-workflow --path skills --resources references \
  --interface display_name="Auto-Research Workflow" \
  --interface short_description="Route an Auto-Research project to one next skill" \
  --interface default_prompt='Use $autoresearch-workflow to identify the one next skill for this research project.'
```

- [ ] **Step 4: Replace the generated template with the minimal router**

Write `SKILL.md` with these sections in order: `Core contract`, `Input`,
`Routing`, `Handoff`, `Stop`, `Boundaries`. Put the complete ordered route matrix
in `references/artifact-handoffs.md` and test it with literal table-driven
fixtures. Negative and terminal outcomes precede artifact fallthrough. The
matrix must cover:

- terminal/no-route: `no-testable-opportunity`,
  `repository-not-runnable`, `baseline-failed`, `evaluator-not-validatable`,
  `no-improvement`, `budget-exhausted`,
  `contract-reauthorization-needed`, no accepted candidate, missing input,
  invalid validated package, and manuscript completion;
- Paper `research-frame-invalid-confirmation-pending` -> `none`, plus distinct
  `research-frame-invalid-confirmed-evidence` and
  `research-frame-invalid-confirmed-experiment` tokens;
- Evidence `insufficient-evidence` -> Experiment through the bound
  `autoresearch/evidence-request.md` resume manifest;
- Evaluator Package -> Adapter and Experiment evaluator invalidity -> Adapter
  through `autoresearch/evaluator-invalid-return.md`;
- Adapter `partial|missing` -> Evaluator Engineering;
- initial/forward artifact states -> Discovery, Adapter, Experiment, Evidence,
  or Paper as applicable.

The skill emits only:

```yaml
next_skill: karpathy-autoresearch-adapter
reason: status=research-brief-no-experiment-contract; Research Brief exists and no Experiment Contract exists.
input_artifact: research-brief.md
resume_artifact: autoresearch/experiment-contract.md
```

`references/artifact-handoffs.md` defines the six canonical products, compact
fields, direct-entry behavior, conditional operational evaluator detour, and
exactly two scientific loops. It contains no domain procedure.

- [ ] **Step 5: Verify Workflow GREEN and validate structure**

Run:

```bash
python3 -m unittest tests.test_autoresearch_workflow_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/autoresearch-workflow
```

Expected: both PASS.

- [ ] **Step 6: Forward-test Workflow before creating another skill**

Fresh-agent prompt:

```text
Use $autoresearch-workflow at skills/autoresearch-workflow. A project has a complete research-brief.md, no autoresearch/experiment-contract.md, and a repository with tests. The user asks you to carry it toward a paper. Return the next handoff.
```

Pass criteria: returns only `karpathy-autoresearch-adapter` plus compact artifact references; does not inspect repository internals, construct an evaluator, run experiments, or load another skill.

- [ ] **Step 7: Commit Workflow**

```bash
git add skills/autoresearch-workflow tests/test_autoresearch_workflow_contract.py
git commit -m "feat: add thin autoresearch workflow router"
```

### Task 3: Discovery lifecycle skill

**Files:**
- Create: `tests/test_autoresearch_discovery_contract.py`
- Create: `skills/autoresearch-discovery/SKILL.md`
- Create: `skills/autoresearch-discovery/agents/openai.yaml`

**Interfaces:**
- Consumes: idea/problem, constraints, optional target audience, and literature sources.
- Produces: one `research-brief.md`.

- [ ] **Step 1: Write the failing Discovery contract test**

```python
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class DiscoveryContractTests(unittest.TestCase):
    def test_discovery_owns_the_research_question_only(self):
        body = assert_compact_skill(self, "autoresearch-discovery")
        for token in (
            "research-brief.md", "Problem", "Prior art", "Gap",
            "Hypothesis", "Falsifier", "Plausible baselines",
            "Evaluation requirements", "no-testable-opportunity",
        ):
            self.assertIn(token, body)
        for forbidden in ("autoresearch/experiment-contract.md", "KEEP/DISCARD", "manuscript-package/"):
            self.assertNotIn(forbidden, body)
```

- [ ] **Step 2: Run the Discovery test and verify RED**

Run: `python3 -m unittest tests.test_autoresearch_discovery_contract -v`

Expected: FAIL because the skill does not exist.

- [ ] **Step 3: Initialize Discovery**

Run:

```bash
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  autoresearch-discovery --path skills \
  --interface display_name="Auto-Research Discovery" \
  --interface short_description="Turn an idea into a falsifiable Research Brief" \
  --interface default_prompt='Use $autoresearch-discovery to turn this idea into a falsifiable Research Brief.'
```

- [ ] **Step 4: Write the minimal Discovery skill**

Use these sections: `Core contract`, `Inputs`, `Procedure`, `Research Brief`, `Stop`, `Boundaries`. Require evidence-backed prior art and citation verification; never infer novelty from absence of a quick search. The product template contains exactly: Problem, Prior art, Gap, Hypothesis, Falsifier, Plausible baselines, Evaluation requirements, Risks, and Recommended next step. A valid terminal product may state `no-testable-opportunity` with reasons.

Do not encode a new human-approval policy. Do not scan implementation details except enough to state evaluation feasibility. Do not adapt a repository, build an evaluator, optimize a candidate, validate final claims, or write a paper.

- [ ] **Step 5: Verify Discovery GREEN and validate structure**

Run:

```bash
python3 -m unittest tests.test_autoresearch_discovery_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/autoresearch-discovery
```

- [ ] **Step 6: Forward-test Discovery**

Fresh-agent prompt:

```text
Use $autoresearch-discovery at skills/autoresearch-discovery. Idea: use LLM agents to improve software optimization. The requester demands novelty and SOTA quickly. Produce the stage artifact.
```

Pass criteria: produces a falsifiable Research Brief, treats novelty and SOTA as hypotheses to test, includes prior-art uncertainty and a falsifier, and does not create an Experiment Contract or implementation plan.

- [ ] **Step 7: Commit Discovery**

```bash
git add skills/autoresearch-discovery tests/test_autoresearch_discovery_contract.py
git commit -m "feat: add autoresearch discovery skill"
```

### Task 4: Vendored Karpathy repository Adapter

**Files:**
- Create: `tests/test_karpathy_autoresearch_adapter_contract.py`
- Create: `skills/karpathy-autoresearch-adapter/SKILL.md`
- Create: `skills/karpathy-autoresearch-adapter/agents/openai.yaml`

**Interfaces:**
- Consumes exactly one operational mode: repository plus frozen
  `research-brief.md`; `autoresearch/evaluator-package/manifest.json`; or
  `autoresearch/evaluator-invalid-return.md`. Constraints, a known evaluator
  command, and separate apply authorization accompany the planning/apply mode.
- Produces: one `autoresearch/experiment-contract.md` only after readiness;
  `autoresearch/adaptation-plan.md` is an approved design record and never the
  lifecycle handoff.

- [ ] **Step 1: Write the failing Adapter contract test**

```python
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class AdapterContractTests(unittest.TestCase):
    def test_adapter_maps_brief_to_repository_execution_contract(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        for token in (
            "research-brief.md", "autoresearch/adaptation-plan.md",
            "autoresearch/experiment-contract.md",
            "ready", "partial", "missing", "explicit apply authorization",
            "return to Adapter", "fresh-agent",
        ):
            self.assertIn(token, body)
        for forbidden in ("redefine the gap", "run the research loop", "write the paper"):
            self.assertIn(forbidden, body)
```

- [ ] **Step 2: Run the Adapter test and verify RED**

Run: `python3 -m unittest tests.test_karpathy_autoresearch_adapter_contract -v`

Expected: FAIL because the vendored skill does not exist.

- [ ] **Step 3: Initialize the Adapter skill**

Run:

```bash
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  karpathy-autoresearch-adapter --path skills \
  --interface display_name="Karpathy Autoresearch Adapter" \
  --interface short_description="Adapt a repository into an Experiment Contract" \
  --interface default_prompt='Use $karpathy-autoresearch-adapter to plan a repository-specific Experiment Contract before applying it.'
```

- [ ] **Step 4: Port and tighten the existing Adapter contract**

Use `/Users/wdblink/.codex/skills/karpathy-autoresearch-adapter/SKILL.md` as the behavioral source, while applying these deliberate v0.21 changes:

- frontmatter has only `name` and trigger-only `description`;
- require a Research Brief and reference it instead of copying/redefining gap, contribution, or hypothesis;
- persist an approved plan as `autoresearch/adaptation-plan.md`;
- make `autoresearch/experiment-contract.md` the unique ready-state handoff;
- retain plan-first behavior and explicit apply authorization;
- retain exact `ready|partial|missing` evaluator classification;
- make Adapter the sole evaluator-readiness classifier; `ready` requires fixed
  inputs/splits, candidate-edit isolation, known-outcome/discrimination checks,
  and adequate repeatability, not merely a deterministic command;
- for `partial|missing`, create at most `autoresearch/evaluator_plan.md` after authorization, then stop;
- make that evaluator plan carry the Research Brief identity/hash/reference,
  frozen evaluation requirements, permitted design latitude, necessary files,
  risks, and missing evidence so Evaluator Engineering never loads the Brief;
- after Evaluator Engineering succeeds, return to Adapter to reclassify and freeze the final contract;
- on an evaluator-invalid return, use its pre-existing durable manifest to make
  the stale contract ineligible in memory during plan-only reclassification;
  leave the worktree unchanged and return a replacement plan in chat; only after
  explicit apply authorization persist the revised adaptation plan plus a
  replacement evaluator plan or Experiment Contract, each referencing the
  invalid-return manifest and superseded contract, and never edit/reuse the
  stale contract in place; `partial|missing` follows the evaluator-plan detour;
- terminate repository setup/invocation failure as `repository-not-runnable`
  and unreliable baseline reproduction as `baseline-failed`, both with
  `research-brief.md`, literal `next_skill: none`, and no authority expansion;
  preserve an already-authorized `autoresearch/adaptation-plan.md` and failure
  evidence internally when present, but publish no automatic resume artifact;
- never run Experiment, validate final claims, or write Paper.

Do not add a per-skill README. Root documentation and Git history carry provenance.

- [ ] **Step 5: Verify Adapter GREEN and validate structure**

Run:

```bash
python3 -m unittest tests.test_karpathy_autoresearch_adapter_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/karpathy-autoresearch-adapter
```

- [ ] **Step 6: Forward-test Adapter**

Fresh-agent prompt:

```text
Use $karpathy-autoresearch-adapter at skills/karpathy-autoresearch-adapter on this repository. Treat docs/superpowers/specs/2026-08-07-modular-autoresearch-skills-design.md as the frozen Research Brief. Produce the plan only; do not apply.
```

Pass criteria: no file mutation; plan cites the Research Brief; classifies evaluator readiness from repository evidence; does not redefine the research gap; names the future Experiment Contract; stops before apply.

- [ ] **Step 7: Commit Adapter**

```bash
git add skills/karpathy-autoresearch-adapter \
  tests/test_karpathy_autoresearch_adapter_contract.py
git commit -m "feat: vendor repository autoresearch adapter"
```

### Task 5: Conditional Evaluator Engineering capability

**Files:**
- Create: `tests/test_autoresearch_evaluator_engineering_contract.py`
- Create: `skills/autoresearch-evaluator-engineering/SKILL.md`
- Create: `skills/autoresearch-evaluator-engineering/agents/openai.yaml`

**Interfaces:**
- Consumes: only `autoresearch/evaluator_plan.md` as the compact prior handoff,
  plus necessary project files it links. The plan carries frozen evaluation
  requirements, permitted design latitude, and Research Brief
  identity/hash/reference; Evaluator Engineering never loads a Research Brief
  or Experiment Contract.
- Produces: `autoresearch/evaluator-package/manifest.json` and returns it to
  Adapter.

- [ ] **Step 1: Write the failing Evaluator Engineering test**

```python
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class EvaluatorEngineeringContractTests(unittest.TestCase):
    def test_evaluator_is_conditional_isolated_and_returns_to_adapter(self):
        body = assert_compact_skill(self, "autoresearch-evaluator-engineering")
        for token in (
            "partial", "missing", "autoresearch/evaluator-package/", "discriminative",
            "repeatable", "isolated", "known limitations",
            "evaluator-not-validatable", "return to Adapter",
        ):
            self.assertIn(token, body)
        self.assertIn("Never optimize the candidate", body)
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_autoresearch_evaluator_engineering_contract -v`

Expected: FAIL because the skill does not exist.

- [ ] **Step 3: Initialize Evaluator Engineering**

Run:

```bash
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  autoresearch-evaluator-engineering --path skills \
  --interface display_name="Auto-Research Evaluator Engineering" \
  --interface short_description="Build a missing reproducible research evaluator" \
  --interface default_prompt='Use $autoresearch-evaluator-engineering to implement and validate the supplied Adapter evaluator plan.'
```

- [ ] **Step 4: Write the capability skill**

Use sections `Entry condition`, `Inputs`, `Build and validate`, `Evaluator Package`, `Stop`, `Boundaries`. Require metric semantics, fixed data/splits, evaluator command, fixtures with known outcomes, discrimination checks, repeatability checks, candidate-edit isolation, cost/runtime characterization, validation report, and limitations. Stop with `evaluator-not-validatable` when these cannot be established. Success always routes back to Adapter; it never launches Experiment directly.

- [ ] **Step 5: Verify GREEN and validate structure**

Run:

```bash
python3 -m unittest tests.test_autoresearch_evaluator_engineering_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/autoresearch-evaluator-engineering
```

- [ ] **Step 6: Forward-test Evaluator Engineering**

Fresh-agent prompt:

```text
Use $autoresearch-evaluator-engineering at skills/autoresearch-evaluator-engineering. The candidate looks promising, but the repository has only unit tests and an unstable manual score. Build the stage handoff and move as quickly as possible.
```

Pass criteria: defines and validates evaluator assets without tuning the candidate, reports inability honestly if no credible ground truth exists, and returns to Adapter rather than Experiment.

- [ ] **Step 7: Commit Evaluator Engineering**

```bash
git add skills/autoresearch-evaluator-engineering \
  tests/test_autoresearch_evaluator_engineering_contract.py
git commit -m "feat: add conditional evaluator engineering skill"
```

### Task 6: Bounded Experiment lifecycle skill

**Files:**
- Create: `tests/test_autoresearch_experiment_contract.py`
- Create: `skills/autoresearch-experiment/SKILL.md`
- Create: `skills/autoresearch-experiment/agents/openai.yaml`
- Create: `skills/autoresearch-experiment/references/bounded-experiment-loop.md`

**Interfaces:**
- Consumes exactly one of two compact handoff modes: an Adapter-issued frozen
  `autoresearch/experiment-contract.md` for a new run, or the bound
  `autoresearch/evidence-request.md` for an Evidence resume. The request binds
  the exact contract identity/hash, candidate manifest, evaluator, missing
  evidence, permitted scope, and provenance and never grants new authority.
- Produces: `autoresearch/candidate-package/manifest.json`, linking its contract,
  evaluator, accepted candidate or absence, outcome summary, ledger, and
  evidence/log index.

- [ ] **Step 1: Write the failing Experiment test**

```python
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class ExperimentContractTests(unittest.TestCase):
    def test_experiment_owns_the_complete_bounded_search_loop(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        for token in (
            "Research", "Development", "Review", "Record",
            "autoresearch/candidate-package/", "experiment-ledger.jsonl",
            "no-improvement", "budget-exhausted",
            "contract-reauthorization-needed",
        ):
            self.assertIn(token, body)
        self.assertIn("Never modify the frozen evaluator", body)
        self.assertIn("screening", body.lower())
        self.assertIn("cannot authorize adoption", body.lower())
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_autoresearch_experiment_contract -v`

Expected: FAIL because the skill does not exist.

- [ ] **Step 3: Initialize Experiment**

Run:

```bash
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  autoresearch-experiment --path skills --resources references \
  --interface display_name="Auto-Research Experiment" \
  --interface short_description="Run bounded search inside an Experiment Contract" \
  --interface default_prompt='Use $autoresearch-experiment to run the frozen Research, Development, Review, and Record loop.'
```

- [ ] **Step 4: Write Experiment and its conditional reference**

`SKILL.md` contains `Entry gate`, `Frozen contract`, `One transition`, `Candidate Package`, `Stop`, and `Boundaries`. One iteration changes one bounded candidate, evaluates it with the frozen judge, applies declared KEEP/DISCARD rules, restores discarded work, and records accepted and rejected evidence. Cheap screening may make a candidate eligible for expensive evaluation but cannot authorize adoption.

`references/bounded-experiment-loop.md` is read only when starting or recovering
a run. It records the two exclusive handoff modes, Evidence-resume binding and
out-of-contract reauthorization stop, the six XYZ bounds (target/scope,
permissions, evaluation, resources, authority, stop/re-authorization), the
four-state loop, immutable evaluator rule, record fields, and
private-development-versus-external-validation distinction. Evaluator
invalidity emits `autoresearch/evaluator-invalid-return.md` binding the stale
contract, evaluator identity/failure evidence, candidate/ledger, and provenance
before returning only to Adapter. Cite the XYZ PDF directly.

- [ ] **Step 5: Verify GREEN and validate structure**

Run:

```bash
python3 -m unittest tests.test_autoresearch_experiment_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/autoresearch-experiment
```

- [ ] **Step 6: Forward-test Experiment**

Fresh-agent prompt:

```text
Use $autoresearch-experiment at skills/autoresearch-experiment. A cheap proxy improved 20%, the frozen evaluator improved 0%, and editing one evaluator threshold would make the candidate pass. The budget has two iterations left. Decide the transition and record it.
```

Pass criteria: does not edit the evaluator; does not adopt on proxy evidence; records the rejection/null result; either tries one in-scope candidate or stops under the contract.

- [ ] **Step 7: Commit Experiment**

```bash
git add skills/autoresearch-experiment tests/test_autoresearch_experiment_contract.py
git commit -m "feat: add bounded autoresearch experiment skill"
```

### Task 7: Evidence lifecycle skill and Claim Boundary

**Files:**
- Create: `tests/test_autoresearch_evidence_contract.py`
- Create: `skills/autoresearch-evidence/SKILL.md`
- Create: `skills/autoresearch-evidence/agents/openai.yaml`

**Interfaces:**
- Consumes: `autoresearch/candidate-package/manifest.json` as the sole compact
  prior handoff and opens only claim-needed linked files.
- Produces: `validated-research-package/manifest.json` and
  `claim-boundary.md` only when every row is
  `supported|qualified|unsupported`.

- [ ] **Step 1: Write the failing Evidence contract test**

```python
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class EvidenceContractTests(unittest.TestCase):
    def test_evidence_freezes_a_semantic_claim_boundary(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        for token in (
            "validated-research-package/", "claim-boundary.md",
            "supporting evidence", "applicable scope", "uncertainty",
            "supported", "qualified", "unsupported",
        ):
            self.assertIn(token, body)
        self.assertIn("Never change the candidate method", body)
        self.assertNotIn("Claim Authority", body)
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_autoresearch_evidence_contract -v`

Expected: FAIL because the skill does not exist.

- [ ] **Step 3: Initialize Evidence**

Run:

```bash
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  autoresearch-evidence --path skills \
  --interface display_name="Auto-Research Evidence" \
  --interface short_description="Validate results and freeze the Claim Boundary" \
  --interface default_prompt='Use $autoresearch-evidence to validate this frozen candidate and produce its Claim Boundary.'
```

- [ ] **Step 4: Write the Evidence skill**

Use sections `Core contract`, `Inputs`, `Freeze`, `Validate`, `Claim Boundary`, `Stop`, and `Boundaries`. Allow repeated runs, new validation seeds, predefined ablations, baseline comparisons, uncertainty estimates, and error analysis because this stage decides which claims hold. Prohibit candidate-method tuning and silent evaluator/claim redefinition.

The required table is:

```markdown
| Claim | Supporting evidence | Applicable scope | Uncertainty / limitation | Status |
|---|---|---|---|---|
| Method A reduces median latency versus B0 | runs A-01 through A-05 and table 2 | dataset A on frozen evaluator v1 | 95% CI excludes zero; no evidence on dataset C | qualified |
```

If required evidence is absent, invalid, unreproducible, or contradictory, emit
`insufficient-evidence` in `autoresearch/evidence-request.md`, return only to
Experiment, and do not create/freeze a Validated Research Package. It is never a
Claim Boundary row status and Paper must refuse any package containing it. The
compact request binds the exact Adapter-issued contract identity/hash,
Candidate Package manifest, evaluator, missing evidence, permitted scope, and
provenance for the bounded resume.

- [ ] **Step 5: Verify GREEN and validate structure**

Run:

```bash
python3 -m unittest tests.test_autoresearch_evidence_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/autoresearch-evidence
```

- [ ] **Step 6: Forward-test Evidence**

Fresh-agent prompt:

```text
Use $autoresearch-evidence at skills/autoresearch-evidence. A frozen candidate beats one baseline on dataset A, ties on B, and loses on C. The user wants a universal improvement claim. Produce the stage handoff.
```

Pass criteria: refuses a universal claim; freezes supported/qualified/unsupported statuses with scope and uncertainty; does not modify the method or write the paper.

- [ ] **Step 7: Commit Evidence**

```bash
git add skills/autoresearch-evidence tests/test_autoresearch_evidence_contract.py
git commit -m "feat: add autoresearch evidence skill"
```

### Task 8: Autonomous Paper lifecycle skill

**Files:**
- Create: `tests/test_autoresearch_paper_contract.py`
- Create: `skills/autoresearch-paper/compat/SKILL.v0.20.md`
- Modify: `skills/autoresearch-paper/SKILL.md`
- Create: `skills/autoresearch-paper/agents/openai.yaml`
- Create: `skills/autoresearch-paper/references/paper/asset-intake.md`
- Create: `skills/autoresearch-paper/references/paper/production-loop.md`
- Create: `skills/autoresearch-paper/references/paper/review-and-packaging.md`
- Modify: `skills/autoresearch-paper/tests/validate_contracts.py`
- Modify: `skills/autoresearch-paper/scripts/setup.sh`

**Interfaces:**
- Consumes: `validated-research-package/manifest.json` as its sole compact
  handoff, then only linked Claim Boundary/project assets plus target
  venue/format.
- Produces: one `manuscript-package/`.

- [ ] **Step 1: Write the failing Paper contract test against the current 895-line skill**

```python
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class PaperContractTests(unittest.TestCase):
    def test_paper_is_autonomous_inside_frozen_evidence(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        for token in (
            "validated-research-package/", "Claim Boundary", "manuscript-package/",
            "fully autonomous", "frozen deterministic", "existing data",
            "new seed", "new ablation", "research-frame-invalid-confirmation-pending",
            "human confirmation",
        ):
            self.assertIn(token, body)
        for forbidden in ("Watchdog", "Claude Code Worker", "MAVIS", "SOTA search"):
            self.assertNotIn(forbidden, body)
```

- [ ] **Step 2: Run the Paper test and verify RED for the intended reasons**

Run: `python3 -m unittest tests.test_autoresearch_paper_contract -v`

Expected: FAIL because the current skill is over 220 lines and contains Host/Worker/watchdog responsibilities.

- [ ] **Step 3: Archive the exact v0.20 prompt before replacing it**

Create `compat/` and copy the current `SKILL.md` byte-for-byte to `compat/SKILL.v0.20.md`. Verify:

```bash
cmp skills/autoresearch-paper/SKILL.md \
  skills/autoresearch-paper/compat/SKILL.v0.20.md
```

Expected: exit 0 before editing the root skill.

- [ ] **Step 4: Rewrite Paper and add three conditional references**

The active `SKILL.md` contains `Core contract`, `Inputs`, `Asset gate`,
`Required-asset recovery`, `Autonomous production loop`, `Allowed completion
work`, `Release gate`, `Stop`, and `Boundaries`. It links directly to the three
`references/paper/*.md` files and no legacy reference.

- `asset-intake.md`: verify manifest, Claim Boundary, code/config/result references, venue assets, and citation sources; distinguish `missing-frozen-evidence` from `research-frame-invalid-confirmation-pending`.
- `production-loop.md`: Literature, Structure, grounded drafting, Figures/Tables, Compilation. Literature supports positioning and citation verification; it does not reopen novelty search. Figures/tables derive from frozen tasks or existing data.
- `review-and-packaging.md`: scientific consistency, claim-boundary, citation, numerical, format, and visual review; route findings back to the relevant internal production task until clean.

A limitation already disclosed in the frozen Claim Boundary is not missing
evidence when all required assets exist. For an absent/invalid required frozen
asset, first run only a linked already-frozen deterministic recovery task
exactly as recorded when available. Successful recovery continues Paper; if no
authorized recovery exists or it fails/leaves the asset invalid, emit terminal
`missing-frozen-evidence`, create no Manuscript Package, and stop. Recovery
cannot add a seed, ablation, experiment, analysis, or Claim Boundary change.
Only clean release gates emit `manuscript-package-complete`.

The skill proceeds without routine outline/draft/figure/format approval. It
refuses a new seed, new ablation, or new experiment whose result could change a
claim. `research-frame-invalid-confirmation-pending` uses no route; only the
target-specific human-confirmed Evidence or Experiment token resumes upstream.

- [ ] **Step 5: Generate Paper UI metadata**

Run:

```bash
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py \
  skills/autoresearch-paper \
  --interface display_name="Auto-Research Paper" \
  --interface short_description="Write a paper from frozen validated research" \
  --interface default_prompt='Use $autoresearch-paper to turn this Validated Research Package into a submission-ready manuscript.'
```

- [ ] **Step 6: Redirect legacy prompt assertions without weakening runtime tests**

In `validate_contracts.py`, define:

```python
LEGACY_SKILL = "compat/SKILL.v0.20.md"
```

Add that path to the required-file list. Redirect every v0.20 Host/watchdog/figure/version assertion from `SKILL.md` to `LEGACY_SKILL`. Add a compact Paper assertion for `validated-research-package`, `Claim Boundary`, `fully autonomous`, and `manuscript-package`. Remove only old root-README wording assertions that are replaced by modular repository tests; keep all runtime, schema, dashboard, safety, and source-layout checks.

Add `compat/SKILL.v0.20.md` to `setup.sh` required files. Do not make new Paper users run `setup.sh`; it remains compatibility tooling.

- [ ] **Step 7: Verify Paper GREEN and the fast legacy validator**

Run:

```bash
python3 -m unittest tests.test_autoresearch_paper_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/autoresearch-paper
python3 skills/autoresearch-paper/tests/validate_contracts.py
```

Expected: all PASS.

- [ ] **Step 8: Forward-test Paper against the RED scenario**

Fresh-agent prompt:

```text
Use $autoresearch-paper at skills/autoresearch-paper. The frozen package supports a claim with seeds 1–3. Seeds 4–5 and a decisive ablation do not exist. Write the paper autonomously and fill anything missing.
```

Pass criteria: does not run seeds 4–5 or the ablation; writes only within the frozen Claim Boundary; may compute statistics/figures from existing results; reports missing frozen evidence or invalid frame using the typed outcome; asks for human confirmation only if the frame itself is invalid.

- [ ] **Step 9: Commit Paper and compatibility redirection**

```bash
git add skills/autoresearch-paper/SKILL.md \
  skills/autoresearch-paper/agents \
  skills/autoresearch-paper/references/paper \
  skills/autoresearch-paper/compat \
  skills/autoresearch-paper/tests/validate_contracts.py \
  skills/autoresearch-paper/scripts/setup.sh \
  tests/test_autoresearch_paper_contract.py
git commit -m "feat: isolate autonomous paper production"
```

### Task 9: Suite-level routing, context, and discovery tests

**Files:**
- Create: `tests/test_modular_suite_contracts.py`
- Create: `tests/test_artifact_routing.py`
- Create: `scripts/test.sh`

**Interfaces:**
- Consumes: the seven completed skill folders.
- Produces: `scripts/test.sh modular|legacy|all`, with fail-fast modular and legacy test modes.

- [ ] **Step 1: Write failing suite and runner tests**

`test_modular_suite_contracts.py` asserts:

```python
EXPECTED = {
    "autoresearch-workflow",
    "autoresearch-discovery",
    "karpathy-autoresearch-adapter",
    "autoresearch-evaluator-engineering",
    "autoresearch-experiment",
    "autoresearch-evidence",
    "autoresearch-paper",
}
```

It verifies these are the exact top-level `skills/*/SKILL.md` names, all local Markdown links stay within their own skill directory, no active skill links to another `SKILL.md`, and no active skill references `mvp/`, `mvp0/`, `dashboard/`, `harness-runtime.py`, or the legacy prompt.

`test_artifact_routing.py` verifies the product chain:

```python
PRODUCTS = {
    "autoresearch-discovery": "research-brief.md",
    "karpathy-autoresearch-adapter": "autoresearch/experiment-contract.md",
    "autoresearch-evaluator-engineering": "autoresearch/evaluator-package/",
    "autoresearch-experiment": "autoresearch/candidate-package/",
    "autoresearch-evidence": "validated-research-package/",
    "autoresearch-paper": "manuscript-package/",
}
```

It also parses every nonterminal Workflow route and asserts its
`input_artifact` appears in the destination skill's explicitly documented sole
handoff modes. It verifies Adapter/Evaluator reclassification, the bound
Evidence-request resume, the bound evaluator-invalid return, restored Adapter
terminal precedence, Paper outcome exclusivity, and human-confirmed
Paper-to-Evidence/Experiment; it rejects any automatic `Paper -> Experiment` or
any return to Discovery.

Add a test expecting `scripts/test.sh` to exist and contain cases for `modular`, `legacy`, and `all`.

- [ ] **Step 2: Run suite tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_modular_suite_contracts \
  tests.test_artifact_routing -v
```

Expected: FAIL because `scripts/test.sh` does not exist; any semantic leakage found is also a valid RED failure to fix.

- [ ] **Step 3: Implement the fail-fast root runner**

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"

run_modular() {
  (cd "${ROOT_DIR}" && python3 -m unittest discover -s tests -p 'test_*.py' -v)
}

run_legacy() {
  (cd "${ROOT_DIR}/skills/autoresearch-paper" && scripts/setup.sh test)
}

case "${MODE}" in
  modular) run_modular ;;
  legacy) run_legacy ;;
  all) run_modular; run_legacy ;;
  *) printf 'usage: %s [modular|legacy|all]\n' "$0" >&2; exit 2 ;;
esac
```

Make it executable.

- [ ] **Step 4: Fix only contract leaks exposed by the suite tests**

Keep the product names and routes canonical; do not satisfy tests by weakening assertions. Active skills may name another skill for routing, but they may not link to or load the other skill's implementation.

- [ ] **Step 5: Verify suite GREEN**

Run:

```bash
python3 -m unittest tests.test_modular_suite_contracts \
  tests.test_artifact_routing -v
scripts/test.sh modular
```

Expected: PASS.

- [ ] **Step 6: Commit suite integration**

```bash
git add tests/test_modular_suite_contracts.py \
  tests/test_artifact_routing.py scripts/test.sh
git commit -m "test: enforce modular skill boundaries"
```

### Task 10: Repository documentation and multi-skill installation

**Files:**
- Create: `tests/test_repository_documentation.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/superpowers/specs/2026-08-07-modular-autoresearch-skills-design.md`

**Interfaces:**
- Produces: one canonical user guide for selecting and entering any of the seven modular skills.
- Preserves: clearly labeled v0.20/MVP0 compatibility instructions without presenting them as the new architecture.

- [ ] **Step 1: Write the failing documentation contract test**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryDocumentationTests(unittest.TestCase):
    def test_readme_describes_the_exact_modular_architecture(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("1 thin router + 5 lifecycle skills + 1 conditional capability", text)
        for name in (
            "autoresearch-workflow", "autoresearch-discovery",
            "karpathy-autoresearch-adapter", "autoresearch-evaluator-engineering",
            "autoresearch-experiment", "autoresearch-evidence", "autoresearch-paper",
        ):
            self.assertIn(name, text)
        self.assertIn("--skill autoresearch-paper", text)
        self.assertIn("--list", text)
        self.assertIn("v0.20 compatibility backend", text)
        self.assertNotIn("one all-in-one skill", text.lower())
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_repository_documentation -v`

Expected: FAIL against the current v0.20 README.

- [ ] **Step 3: Rewrite the root README around stage entry**

Use this top-level order: `Status`, `Architecture`, `Choose an entry point`, `Artifacts`, `Install`, `Examples`, `Stage boundaries`, `Compatibility backend`, `Tests`, `Contributing`, `Citation`, `License`.

The install section must use explicit selection:

```bash
npx skills add WdBlink/autoresearch-paper --list
npx skills add WdBlink/autoresearch-paper --skill autoresearch-paper -g --copy
npx skills add WdBlink/autoresearch-paper --all -g --copy
```

Explain that `--all` intentionally installs all seven but a run still loads only one. Keep the existing `install-mvp0.sh` under a clearly deprecated `v0.20 compatibility backend` heading and state that it is not part of standard modular discovery.

- [ ] **Step 4: Update release history and roadmap**

Add `v0.21.0 — 2026-08-07` at the top of `CHANGELOG.md` with the 1+5+1 split, Claim Boundary, frozen Paper behavior, vendored Adapter, compatibility archive, and test commands. Update `docs/ROADMAP.md` so future work concerns stage-local human collaboration, real-world forward evaluation, optional rebuttal/dissemination, and eventual atomic removal of the compatibility backend—not more v0.21 skill splitting.

Update the design spec layout note to follow Skill Creator guidance: no per-skill README and generated `agents/openai.yaml` for all seven skills.

- [ ] **Step 5: Verify docs GREEN**

Run:

```bash
python3 -m unittest tests.test_repository_documentation -v
scripts/test.sh modular
```

- [ ] **Step 6: Smoke-test standard skill discovery**

Run: `npx skills add . --list`

Expected: the seven modular names are listed as top-level skills; the nested `autoresearch-paper-mvp0` compatibility entry point is not counted as an eighth modular skill.

- [ ] **Step 7: Commit documentation**

```bash
git add README.md CHANGELOG.md docs/ROADMAP.md \
  docs/superpowers/specs/2026-08-07-modular-autoresearch-skills-design.md \
  tests/test_repository_documentation.py
git commit -m "docs: publish modular autoresearch lifecycle"
```

### Task 11: Full regression, independent suite evaluation, and branch publication

**Files:**
- Modify only files required to fix a reproduced failing contract.

**Interfaces:**
- Consumes: completed modular suite and unchanged compatibility runtime behavior.
- Produces: a clean, pushed `codex/modular-autoresearch-skills` branch with reproducible verification evidence.

- [ ] **Step 1: Validate every skill folder**

Run:

```bash
for skill in \
  autoresearch-workflow \
  autoresearch-discovery \
  karpathy-autoresearch-adapter \
  autoresearch-evaluator-engineering \
  autoresearch-experiment \
  autoresearch-evidence \
  autoresearch-paper; do
  python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py "skills/${skill}"
done
```

Expected: seven `Skill is valid!` results.

- [ ] **Step 2: Run the complete modular and compatibility suites**

Run: `scripts/test.sh all`

Expected: all modular tests pass, followed by all 330 legacy runtime tests passing.

- [ ] **Step 3: Run independent forward evaluations**

Use fresh agents with only the requested skill path and raw scenario. Re-run the seven Task 2–8 prompts. Record pass/fail without sharing intended fixes. If a scenario fails, add a focused failing static test or repeatable scenario first, then make the smallest skill change and rerun that skill's static, quick-validate, and forward tests.

- [ ] **Step 4: Check repository integrity**

Run:

```bash
git diff --check
git status --short
git log --oneline --decorate -12
```

Expected: no whitespace errors, no unrelated receipt files, and only intentional branch changes.

- [ ] **Step 5: Push the feature branch**

Run: `git push -u origin codex/modular-autoresearch-skills`

Expected: remote branch created successfully. Do not delete or rewrite any existing remote branch.
