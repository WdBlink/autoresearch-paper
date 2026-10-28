# Roadmap

**Autoresearch** planning board. This is a living document, not a commitment;
versions are assigned only when work ships in [CHANGELOG.md](../CHANGELOG.md).

v0.22 extends the v0.21 semantic split into 1 thin router, 5 lifecycle skills,
and 2 conditional capabilities. Evaluator Engineering builds missing
measurement; Research Radar monitors authorized sources without becoming a
lifecycle stage. Further splitting is not a roadmap goal. Future work should
improve each stage's local collaboration, field evidence, monitoring quality,
and lifecycle exits without rebuilding an all-in-one controller.

## On-deck

### Research Radar field evaluation

Run prospective, multi-cycle watches against active research projects. Measure
fresh-sync reliability, candidate recall, primary-source verification quality,
deferred-item behavior, false-positive cost, and how often contract-compatible
signals produce genuinely useful Experiment proposals.

The evaluation must keep the three state layers separate: Radar owns Source
Cursor and Signal Decision Ledger, while Experiment owns the Adoption Ledger.
A high feed relevance score is not adoption, novelty, improvement, or SOTA.
Record successful zero-forwarded cycles as honest outcomes rather than tuning
the threshold until something is emitted.

### Stage-local human collaboration

Study where a human decision materially improves one stage without forcing
approval checkpoints into every other stage. Near-term candidates include:

- structured critique of Discovery's hypothesis and falsifier;
- clearer Adapter plan/apply review and evaluator-readiness evidence;
- explicit reauthorization when an Experiment Contract must change; and
- human confirmation for Paper's rare `research-frame-invalid` return route.

The default remains stage-local: Paper stays autonomous inside a frozen Claim
Boundary, Experiment stays bounded by its frozen contract, and the router never
performs domain work.

### Real-world forward evaluation

Run the modular lifecycle prospectively on varied repositories and research
settings. Record whether a fresh agent can enter at any artifact boundary,
whether evaluators remain isolated from candidate edits, whether unsuccessful
research is reported honestly, and whether the final claims remain traceable to
frozen evidence.

Forward evaluation should measure handoff clarity, context cost,
reproducibility, return-route correctness, and manuscript package quality. It
must not turn one successful run into a claim of general autonomy or scientific
superiority.

## Candidates

### Optional rebuttal and dissemination

Explore separate, opt-in capabilities for reviewer-response preparation,
camera-ready packaging, repository or artifact release, and venue submission
checklists. These capabilities must consume the frozen manuscript package and
preserve its Claim Boundary.

External submission remains a human action unless a future design defines an
explicitly authorized dissemination boundary. The Paper skill itself will
continue to stop after producing the compiled manuscript package.

### Additional monitored-source adapters

Evaluate opt-in adapters for scholarly alerts, repository releases, benchmark
updates, and curated bibliographies. Every adapter must preserve stable source
identity, fresh-sync evidence, deterministic candidates, complete decisions,
primary-source verification, provenance-bound deterministic re-extraction, and
a single atomic commit root with explicit indeterminate recovery.
Source-specific collection code must not leak into the lifecycle skills or
weaken the frozen Watch Profile.

### Atomic compatibility-backend removal

After a documented deprecation window and evidence that active users have
migrated, remove the entire v0.20 compatibility backend in one coordinated
change: legacy prompt, MVP/MVP0 payloads, runtime references, dashboard,
installer, setup path, and compatibility tests.

Do not move or delete the path-coupled runtime piecemeal. Until atomic removal,
the backend remains deprecated, non-default, separately tested, and excluded
from the eight-skill modular architecture.

## Wishlist

- Localized manuscript templates and review rubrics for non-English venues.
- Cross-project discovery aids that surface prior failed directions without
  importing another project's full context or claims.
- Stronger package-level provenance visualization for Evidence and Paper.
- Additional deterministic evaluator fixtures across operating systems and
  repository shapes.

## Anti-roadmap

- **More top-level lifecycle splitting.** The current boundaries already map one skill
  to one unique product and stop condition. New files or checklists do not earn
  new top-level skills by themselves.
- **A new all-in-one orchestrator.** The thin router selects one owner and
  stops; it must not accumulate domain procedure or preload the suite.
- **Radar as a scientific stage or return loop.** Refresh is an operational
  sidecar action. It cannot reopen Discovery, change the Experiment Contract,
  adopt a candidate, or add a third scientific return path.
- **Paper-stage research.** Paper may present and compile frozen evidence but
  cannot change methods, evaluators, experiments, or Claim Boundary decisions.
- **Silent evaluator relaxation.** Neither Experiment nor Evidence may change
  measurement to obtain a favorable result.
- **Direct venue submission from Paper.** The manuscript package is the release
  artifact; submission and dissemination are separate responsibilities.
- **Replacement of human authorship of novel claims.** The suite preserves and
  presents supported claims; it does not invent scientific authority.

## How to propose a roadmap item

Open an issue with the `roadmap` label and a short sketch of the user pain, the
stage-local change, its artifact boundary, and the riskiest assumption. Include
how the proposal will be evaluated without weakening adjacent stages.
