# Auto-Research Radar Implementation Plan

> **For agentic workers:** implement with test-first changes and verify each
> boundary before continuing. Do not edit the immutable v0.21 design or plan.

**Date:** 2026-08-12

**Target release:** v0.22.0

**Goal:** Add an asynchronous Research Radar capability without turning source
monitoring into a lifecycle stage or reopening a frozen scientific contract.

**Architecture:** The suite becomes 1 thin router + 5 lifecycle skills + 2
conditional capabilities. Adapter freezes a Research Watch Profile; Radar
publishes a verified Research Signal Package through a stable manifest;
Experiment alone decides adoption under its frozen contract. Source Cursor,
Signal Decision Ledger, and Experiment Adoption Ledger remain separate.

**Tech stack:** Markdown Agent Skills, YAML UI metadata, Python 3.11, pinned CCL
Chromium reader, PyYAML, and Cryptography runtime dependencies, SQLite read-only snapshots,
JSON/JSONL manifests, a POSIX shell wrapper, Python `unittest`, Vercel Skills
CLI.

## Global constraints

- The eight standard skills are `autoresearch-workflow`,
  `autoresearch-discovery`, `karpathy-autoresearch-adapter`,
  `autoresearch-evaluator-engineering`, `autoresearch-radar`,
  `autoresearch-experiment`, `autoresearch-evidence`, and
  `autoresearch-paper`.
- Radar is a conditional sidecar, never a sixth lifecycle stage.
- Adapter is the only writer of
  `autoresearch/research-watch-profile.yaml`, and only after explicit apply
  authorization.
- Radar publishes immutable runs and atomically updates
  `autoresearch/research-radar/manifest.json` only after validation.
- An RSS summary is a lead; every forwarded scientific signal requires the
  applicable primary source and explicit verification status.
- Radar owns Source Cursor and Signal Decision Ledger. Experiment owns the
  Adoption Ledger. Radar cannot mark a signal adopted.
- A Radar success or failure creates no scientific route. The scientific
  return loops remain exactly Evidence to Experiment and confirmed Paper frame
  invalidity to Evidence or Experiment.
- A successful cycle with zero forwarded signals still commits complete
  decisions and advances source state. Stale or unverified synchronization,
  validation failure, or pre-replace commit failure advances nothing. A
  commit-indeterminate result requires inspection before retry.
- Keep v0.20 compatibility files operational and separately tested, but exclude
  their entry point from default discovery.

---

## Task 1: Freeze the contracts in tests

**Files:**

- Create `tests/test_autoresearch_radar_contract.py`
- Create `tests/test_folo_source_adapter.py`
- Modify lifecycle, routing, installation, and documentation contract tests

### Steps

1. Add a failing static contract for the Radar sole handoff, state ownership,
   primary-source rule, package fields, atomic commit order, and boundaries.
2. Add deterministic source-adapter fixtures for candidate extraction, stable
   identity, refresh-receipt freshness, decision completeness, deferred retry,
   idempotent replay, compare-and-swap, and failed atomic replacement.
3. Update suite enumeration to require exactly eight top-level `SKILL.md`
   manifests recursively.
4. Add failing integration assertions for Adapter policy ownership, Experiment
   adoption, Evidence multiplicity audit, Paper citation verification, and
   Workflow's operational Radar route.
5. Run the focused tests and preserve the expected failures before production
   implementation.

**Verification:**

```bash
python3 -m unittest \
  tests.test_autoresearch_radar_contract \
  tests.test_folo_source_adapter \
  tests.test_modular_suite_contracts \
  tests.test_artifact_routing -v
```

---

## Task 2: Create the Radar skill

**Files:**

- Create `skills/autoresearch-radar/SKILL.md`
- Create `skills/autoresearch-radar/agents/openai.yaml`
- Create `skills/autoresearch-radar/references/folo-local-source.md`
- Create `skills/autoresearch-radar/references/research-signal-package.md`

### Steps

1. Initialize `autoresearch-radar` with the system skill creator so its
   frontmatter and generated UI metadata follow the repository contract.
2. Define one input only: an Adapter-issued
   `autoresearch/research-watch-profile.yaml` for a scheduled or explicit scan.
3. Define the cycle as authorize, refresh, snapshot, extract, classify, verify,
   decide, validate, commit, and stop.
4. Document Source Cursor and Signal Decision Ledger ownership, and explicitly
   deny adoption authority.
5. Specify immutable run artifacts plus the stable manifest pointer and all
   failure-before-state-advance cases.
6. Keep source-specific mechanics in the FOLO reference and package schema in
   the signal-package reference so the active skill remains compact.

**Verification:**

```bash
python3 -m unittest tests.test_autoresearch_radar_contract -v
python3 /Users/wdblink/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/autoresearch-radar
```

---

## Task 3: Implement the deterministic FOLO source adapter

**Files:**

- Create `skills/autoresearch-radar/scripts/folo_source.py`
- Create `skills/autoresearch-radar/scripts/folo-source`
- Add only runtime dependency metadata that the source adapter genuinely needs

### Steps

1. Validate a fresh, externally authenticated official-UI synchronization
   Ed25519-signed receipt bound to the Watch Profile, expected source instance,
   exact cache-snapshot hash, and exact reconstructed-database hash.
2. Open a disposable cache snapshot through immutable/query-only SQLite,
   validate integrity and required tables, and read subscribed feeds only.
3. Emit canonical candidates in deterministic order with stable identity and a
   digest over canonical candidate bytes.
4. Separate candidate extraction from record commit. Bind production commit to
   one extraction manifest and deterministically re-extract from its database;
   require exactly one valid decision per candidate and strict profile,
   evidence, and primary-source receipts for every forwarded decision.
5. Store processed and deferred state independently; surface deferred items at
   or after their retry time.
6. Commit candidates, decisions, database snapshot, authority artifacts,
   evidence and primary-source objects, vendored profile/public key/refresh
   receipt, immutable state, and run manifest before atomically replacing one stable pointer as
   the sole commit root. Enforce a sibling lock, compare-and-swap against the
   input-root digest, directory synchronization, idempotent replay, conflict
   rejection, and a distinct commit-indeterminate result.
7. Never read-write the live FOLO cache and never advance before replacement on
   stale sync, invalid cache, incomplete decisions, schema/hash failure, or
   atomic replace failure. If replacement may have happened, report
   commit-indeterminate instead of claiming no advancement.

**Verification:**

```bash
python3 -m unittest tests.test_folo_source_adapter -v
```

---

## Task 4: Integrate stage ownership

**Files:**

- Modify `skills/autoresearch-workflow/`
- Modify `skills/karpathy-autoresearch-adapter/`
- Modify `skills/autoresearch-experiment/`
- Modify `skills/autoresearch-evidence/`
- Modify `skills/autoresearch-paper/`

### Steps

1. Let Workflow route only an explicit `research-radar-refresh-requested` to
   Radar. Treat Radar completion and failure as operational statuses with
   `next_skill: none`; preserve the two scientific loops.
2. Let Adapter define the external-research policy and freeze the Watch Profile
   only during its existing authorized apply phase. Adapter never runs Radar.
3. Let Experiment open the stable Radar manifest as an optional linked runtime
   input, never as one of its two compact handoffs. Admit only verified,
   minimum-evidence, contract-fit signals within the declared proposal budget.
4. Record every considered signal and resulting candidate in Experiment's
   Adoption Ledger and Experiment Ledger. Route evaluator, benchmark, data, or
   research-frame threats according to the frozen out-of-scope policy rather
   than changing the contract in place.
5. Make Evidence audit the total candidate count, selection path, information
   exposed during search, primary sources, and multiple-comparison risk.
6. Let Paper use Radar output only as a citation lead. Require primary-source
   verification and prohibit citing the RSS summary itself.

**Verification:**

```bash
python3 -m unittest \
  tests.test_autoresearch_workflow_contract \
  tests.test_karpathy_autoresearch_adapter_contract \
  tests.test_autoresearch_experiment_contract \
  tests.test_autoresearch_evidence_contract \
  tests.test_autoresearch_paper_contract -v
```

---

## Task 5: Make standard discovery exactly eight skills

**Files:**

- Rename the nested MVP0 source manifest to a non-discoverable compatibility
  filename
- Modify `skills/autoresearch-paper/scripts/install-mvp0.sh`
- Modify compatibility installation/layout tests only as required

### Steps

1. Ensure the repository contains exactly eight recursively discoverable
   top-level `SKILL.md` files.
2. Keep the deprecated MVP0 payload physically available but not visible to
   default or full-depth skill discovery.
3. Make the explicit compatibility installer copy the renamed source to the
   installed target as `SKILL.md`.
4. Verify that the standard eight-skill installer never installs MVP0 and the
   explicit compatibility installer still does.

**Verification:**

```bash
npx skills add . --list
npx skills add . --list --full-depth
python3 -m unittest tests.test_modular_suite_contracts -v
cd skills/autoresearch-paper && scripts/setup.sh test
```

Both list commands must show the same exact eight standard skills.

---

## Task 6: Update public release documentation

**Files:**

- Modify `README.md`, `CHANGELOG.md`, `docs/ROADMAP.md`, and
  `.github/repo-meta.yml`
- Create this plan and
  `docs/superpowers/specs/2026-08-12-autoresearch-radar-design.md`

### Steps

1. Publish v0.22.0 as 1 thin router, 5 lifecycle skills, and 2 conditional
   capabilities.
2. Show Radar as a sidecar in architecture, entry, artifact, and boundary
   documentation; do not depict it as a required lifecycle hop.
3. Document Watch Profile, stable signal manifest, three state layers,
   primary-source verification, zero-forwarded success, and fail-closed sync.
4. State that standard install discovers exactly eight skills and MVP0 remains
   an explicit v0.20 compatibility install only.
5. Preserve the 2026-08-07 v0.21 design and plan unchanged as historical
   records.

**Verification:**

```bash
python3 -m unittest tests.test_repository_documentation -v
```

---

## Task 7: Release verification

### Steps

1. Validate every top-level skill with `quick_validate.py`.
2. Run all modular tests, then the full compatibility regression suite.
3. Install the standard suite into an isolated temporary destination and list
   it; prove there are exactly eight installed skills and no MVP0 entry.
4. Clone the pushed branch into a fresh directory and repeat list, validation,
   and modular tests from the remote bytes.
5. Conduct a fresh-context forward test for Radar with a synthetic profile and
   source snapshot. Confirm it publishes or fails without taking adoption or
   routing authority.
6. Review the final diff for accidental edits to v0.21 historical documents or
   unrelated user files.

**Release gate:** v0.22.0 is ready only when all eight skills validate, modular
and compatibility tests pass, local and remote discovery both expose exactly
eight standard skills, and the stable Radar manifest can only reference a
fully validated immutable run.
