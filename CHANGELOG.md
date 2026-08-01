# Changelog

## v0.20.1 — 2026-07-31

- Replace planner-authored Worker conformance JSON with
  `attest-worker-output-conformance`: Runtime first validates one genuine
  positive response through the live content validators, then mechanically
  derives wrong-count, digest-authority, ID/path, order, duplicate, and
  placeholder-content rejection cases.
- Add optional immutable source-inventory construction contracts that bind
  hypotheses, questions, and the exact UTF-8 candidate digest in addition to
  existing source identity and line grounding.
- Align lifecycle conformance with the real continuation path by requiring a
  terminal decision, stage report, accepted strongest-model review, and exact
  continuation-draft binding before `RECORDED -> CONTRACTED`.
- Generate continuation authority from the applied `authorize_contract`
  receipt instead of accepting a hand-authored assurance, and bind a
  Runtime-used plan-wide deadline plus aggregate frontier boundary conformance
  into activation and CP-01.
- Preserve plan040 and plan043 as immutable negative evidence. They exposed a
  generic real-brief compiler gap after the earlier fixed T032 lineage passed;
  they are not rewritten or retroactively accepted.
- Preserve plan044 as a fresh independent `revise` result. Its successful
  transport exposed stale evaluator-admission replays, a lifecycle path that
  could freeze before canonical Worker dispatch, assurances bound to older
  Runtime bytes, premature evaluator-freeze ordering, partial Worker identity
  validation, and incomplete full-input budget accounting.
- Restrict candidate freeze to `DEVELOPING` plus the exact committed Worker
  dispatch marker/journal and promotion lineage. Upgrade the stage-report
  validator to `/3` with exact model/agent/provider matching and upgrade the
  Worker lifecycle conformance to `/4` with a skipped-dispatch rejection case.
- Add Runtime-authored Worker tool-intersection receipts, activate-time
  Runtime-hash checks for separately manifest-bound Worker assurances, and
  optional full-task preflight arithmetic over every declared input, maximum
  output bytes, task-contract/prompt overhead, and both task/stage budgets.
- Preserve plan046 as immutable `revise` evidence. It exposed contradictory
  Stage 2 semantics, unbound origin-to-snapshot provenance, underspecified
  Worker serialization, self-declared Worker identity, indistinguishable
  replay executions, and ambiguous one-dispatch retry language.
- Upgrade source-inventory validation to `/8`: the construction contract now
  freezes UTF-8 encoding, separators, terminal-newline policy, top-level and
  record key order, and the exact cited-line observation rule; noncanonical
  serialization is an explicit fifteenth rejection case.
- Add Runtime-bound Worker identity-attestation assurances and immutable
  post-transport identity receipts covering the resolved Claude executable,
  model argument, provider evidence, agent, persistent session/turn, command,
  transport metadata, and result. Terminal stage reports must bind this
  controller-owned receipt instead of relying on Worker self-identification.
- Make plan047 bind the snapshot manifest plus origin/Git verification,
  separately manifest the positive Worker fixture, use zero retries for its
  single dispatch, normalize Stage 2 to literature/comparator admission and
  Stage 3 to evaluator implementation, and distinguish both deterministic
  evaluator replays with independent execution receipts.
- Preserve plan047 as immutable `revise` evidence. Its audit accepted the
  resource arithmetic, evaluator lineage, Worker capability/identity boundary,
  staged ordering, and continuation authority, while exposing one historical
  snapshot newline mismatch, insufficient official arXiv capture provenance,
  and a Markdown rather than closed-JSON terminal-report positive fixture.
- Validate manifest-bound origin provenance during activation: local origins
  require exact file/snapshot SHA-256 equality; URL sources require a
  plan-owned official capture digest plus machine-true arXiv ID/title match.
- Extend Worker output conformance through the terminal stage-report validator.
  A positive fixture must now be closed JSON with exact fixed bindings, and a
  malformed terminal report is an explicit negative case. Plan048 also
  declares typed PAUSED transitions for candidate validation, report
  validation, and terminal-review rejection.
- Preserve plan048 as immutable `revise` evidence. It confirmed local
  provenance, evaluator readiness, staged ordering, and figure deferral, while
  exposing directory-level Worker read leakage, non-manifested official
  captures, a circular “real Worker before CP-01” entry criterion, and typed
  pause transitions declared only in the plan.
- Dispatch Workers from a clean per-run cwd containing only hash-verified
  immutable copies of declared inputs, expose only that directory to Claude,
  and persist the exact declared-path/sandbox-path access receipt.
- Upgrade lifecycle authority to `/5` with typed failure-to-PAUSED transitions
  from `DEVELOPING`, `CANDIDATE_FROZEN`, and `RECORDED` plus executable
  conformance. Plan049 separately manifests a readable exact official-capture
  bundle, labels preapproval fixtures synthetic, and reserves 180k review
  tokens for terminal review.
- Preserve plan049 as immutable `revise` evidence. All earlier criticals were
  closed; its sole remaining critical required the declared-input sandbox
  receipt to become terminally acceptance-critical rather than advisory.
- Bind `input-access-receipt.json` and every immutable sandbox copy into Worker
  status. Terminal stage-report recording now reconstructs the exact task input
  manifest, requires one matching sandbox path/hash per input, rehashes every
  copy, and rejects missing, extra, stale, or substituted access lineage.

## v0.20.0 — 2026-07-30

- Switch the product Host role to Codex after a fresh installed v0.19.4 task
  passed the bounded T032 lineage on plan039: Stage 1 reached canonical
  `RECORDED`, the frozen Stage 2 continuation received an accepted real
  `gpt-5.6-sol`/`ultra` review, and Stage 2 resumed the exact Stage 1 Claude
  session as turn 2 with real L2 heartbeats and a terminal receipt.
- Freeze a field acceptance report that binds 70 evidence objects and passes
  post-freeze path/SHA-256 verification with zero mismatch. Preserve plan035
  through plan038 as immutable negative evidence for prompt overflow,
  artifact-identity, report-binding, and deadline-boundary failures.
- Keep the claim boundary explicit: this release does not establish Stage 2
  scientific completion, SOTA, 24h or 7x24 stability, production readiness,
  or full production cutover.
- Integrate the remaining standalone-install validation from the migration
  branch: copied Agent Skills bundles validate without repository parents,
  unrelated container READMEs are ignored, and source layouts still fail
  closed when the repository README is missing.

## v0.19.4 — 2026-07-30

- Bound large frontier evidence by immutable path, SHA-256, and byte size
  without duplicating its full body into the Codex prompt. Small review
  evidence remains embedded directly.
- Enforce the Codex turn-start character ceiling before transport and release
  the prelaunch reservation on a deterministic overflow. The first installed
  T032 field attempt is preserved as the negative plan035 sample that exposed
  this failure.
- Keep the product status at T032 pending until a new installed task proves
  Stage 1 terminal → strong reviewed continuation → Stage 2 Worker start.

## v0.19.3 — 2026-07-30

- Persist a controller-owned digest-authority record when an exact-schema
  Worker delegates hashing with literal `controller-compute`, and replay that
  record before promotion of canonical digest-bearing results.
- Require `RECORDED` for every next-stage compilation. Human reauthorization
  may resume a paused stage but cannot redefine `PAUSED` as scientific
  completion.
- Expand installed Codex Host CP-01 evidence to the durable objective,
  constraints, evaluator, applicable unattended evaluator admission, and a
  plan-local immutable snapshot of every Dashboard runtime asset.
- Compile the bounded frontier evidence into one tool-free prompt, estimate
  that exact serialization before transport, and bound response cardinality
  and string size. This removes the repeated tool-read amplification observed
  in immutable plan034.
- Keep the product status at T032 pending until a fresh installed task proves
  Stage 1 terminal → strong reviewed continuation → Stage 2 Worker start.

## v0.19.2 — 2026-07-30

- Make the terminal strongest-model `STAGE-REVIEW` review two inseparable
  things: canonical Stage 1 terminal evidence and the exact immutable Stage 2
  envelope, raw preflight inputs, and Worker task contract. Automatic compile,
  authorization, capsule creation, and dispatch reject any hash or path drift.
- Treat initial human continuation authorization as a bounded authority ceiling,
  never as approval of Stage 2 content. `PAUSED` stages cannot consume the
  automatic crossing; a human-explicit reauthorization path remains replayable.
- Require new continuation Worker schemas to bind exact artifact identities,
  paths, count, literal `controller-compute`, and Runtime-enforced declaration
  order. The Host alone computes the accepted exact-byte digest; legacy task
  contracts retain their prior verified-digest compatibility behavior.
- Put the actual `harness-runtime.py` implementation and the applied initial
  authorization receipt directly in the CP-01 evidence manifest, alongside the
  lifecycle implementation and seven-case conformance receipt.
- Keep the product status at T032 pending until a fresh installed task proves
  Stage 1 terminal → strong reviewed continuation → Stage 2 Worker start.

## v0.19.1 — 2026-07-30

- Expand installed Codex Host CP-01 requests with direct preparation,
  activation, durable-graph, first task-contract, otherwise-unseen task-input,
  and Worker-session-policy evidence instead of relying on transitive digests.
- Add a small Runtime-used lifecycle module and six-case conformance receipt
  for exact returned UTF-8 hashing, terminal-newline sensitivity, exact-byte
  staging, mismatch rejection, and ordered Stage 1 → Stage 2 transitions.
- Move acceptance-critical proposal hashing from read-only Workers to the
  trusted Host via `controller-compute`. A supplied digest is still accepted
  only when it matches the exact returned bytes.
- Preserve plan032 and its blocked CP-01 as immutable negative evidence. A
  fresh two-stage field lineage remains required before claiming Host cutover.

## v0.19.0 — 2026-07-30

- Reverse the v1 target boundary: Codex becomes the intended bootstrap,
  planning, strong-review, and loop-control Host while MiniMax M3 remains in a
  physically separate Claude Code runtime.
- Bind each plan to one controller-generated Claude session UUID. The first
  Worker turn uses `--session-id`; later turns use exact `--resume`. An
  exclusive non-blocking lease rejects concurrent senders before Worker
  capacity is consumed.
- Persist immutable instruction bindings and per-turn terminal receipts with
  explicit token/cache observations. Missing usage is recorded as unknown;
  resumed context and cache telemetry never become transition authority.
- Freeze the session UUID and policy in a separate immutable binding, reconcile
  mutable turn state against the immutable receipt chain, require canonical
  capsules for unattended durable dispatch, and converge Worker/session state
  together after a PREPARED-operation crash. If exact process termination
  cannot be proven, keep the Worker nonterminal and the session `BUSY`, record
  `delivery_uncertain`, and do not freeze a terminal transport receipt.
- Keep `--stateless-worker-session` only as an explicit compatibility/testing
  path. T031/T032 remain required for bootstrap cutover and the complete
  first-stage-to-second-stage field lineage.
- Add the T031 `bootstrap-host-runtime` transaction over the existing durable
  controller and runtime-assurance primitives. READY now requires an L1
  non-due probe, an actual L1 removal followed by zero-model L0 recovery, an
  immutable L2 conformance contract, Dashboard evidence bindings, and one
  cleanup-owned runtime-resource record. Crash/retry converges without
  duplicate launchd resources.
- Expose Host bootstrap readiness, the last L0 action, its bound health tick,
  and explicit absence of real L2 Worker evidence through read-only Runtime
  inspection and the compiled Dashboard. T032 remains the real Worker-heartbeat
  and two-stage field Gate.
- Add the installed T031 `prepare-codex-host-plan` entry with a closed,
  versioned brief schema. It validates missing fields, path ownership, read
  authority, and complete model budgets before atomically publishing a plan;
  invalid input leaves no target plan directory.
- Add `activate-codex-host-plan` so one applied `authorize_contract` binds the
  exact first-stage contract, envelope, evaluator profile, isolated capacity,
  preflight, durable graph, generated dossier, and predeclared Claude session
  UUID. Host READY receipts now include the preparation and activation lineage;
  retry revalidates the same immutable bindings without duplicate schedulers.
- Close the first T032 field failure exposed by plan 031: the Worker prompt now
  requires each proposal SHA to be computed from the exact returned UTF-8
  `content` bytes after final serialization. It explicitly forbids copying a
  newline-inclusive blueprint digest onto content that omits that newline; the
  controller remains fail-closed on any mismatch.
- Close the pre-plan T032 continuation defect found by a fresh installed Codex
  task: automatic Stage 2 dispatch now freezes an immutable staged-continuation
  context capsule bound to the one continuation receipt, next-stage envelope,
  preflight, task contract, exact input manifest, and prior terminal evidence.
  Persistent Workers may not cross the stage boundary with an empty capsule.

## v0.18.0 — 2026-07-28

- Add the compiled Research Ledger Dashboard for one explicitly selected plan.
  Its Python standard-library server binds to a literal loopback address and
  exposes only GET/HEAD snapshot, rebuildable dossier, and currently bound
  bounded-log routes; local assets ship in the installed skill and require no
  Node.js or network access at runtime.
- Preserve typed absence and live, stale, empty, partial, mismatch, stopped,
  and request-error states without inventing metrics or progress. Repeated
  real Plan027 polling is byte-stable, and desktop/mobile browser validation
  covers focus targets, reduced motion, overflow, and failed-refresh retention.

- Add immutable logical retry lineages for failed named frontier checkpoints.
  Each retry receives a new request ID, spends the independent retry budget and
  a new global frontier reservation, never reopens the nominal checkpoint slot,
  and shares one exact-once apply boundary with every sibling attempt.
- Classify provider usage-window failures as `provider_quota`, recording
  `retry_not_before` when the transport reports a duration. Actual retry output
  remains capped by the frozen per-attempt retry token limit. A narrow external
  retry trigger can wake due CP-01 recovery before the full durable loop is
  admitted; its receipt explicitly denies Worker and general transition authority.
- Add a Claude-native runtime-assurance activation closure for unattended
  durable execution. The immutable receipt binds distinct external launchd L0
  and L1 scheduler/controller identities, the L2 Worker heartbeat contract,
  frozen health/stale intervals, and zero-model-call activation probes.
- Add health-only L0 ticks that run deterministic patrol and recover an unloaded
  L1 trigger without dispatching a model. Durable Workers now emit
  controller-owned start/periodic heartbeat receipts and fail closed before
  budget mutation when activation is missing, unloaded, stale, or mismatched.
- Add read-only `inspect-plan-runtime` correlation across canonical state,
  L0/L1/retry scheduler truth, Workers, process identities, heartbeats, logs,
  and declared resources. Target launchd and Worker transports bind plan-local
  stdout/stderr paths.
- Persist Worker PID, dedicated process group, OS start/command identity, and
  command hash before wait. Authenticated Worker cancellation and exact-once
  plan shutdown signal only matching identities; PID reuse and drift remain
  explicit residuals. Plan shutdown journals L0-before-L1, retry, and Worker
  deactivation without receiving artifact-deletion authority.

## v0.17.2 — 2026-07-27

- Close the remaining real CP-01 findings from frozen field plan
  `fwvg-conf-2026-021`: JSON boolean values can no longer masquerade as
  integer schema versions in source inventories or terminal stage reports.
- Upgrade the source-inventory conformance suite to twelve cases and the
  terminal-report suite to ten cases, including explicit boolean-version
  negatives. The source suite now exposes `--conformance` and exercises its
  real CLI → `validate_artifact` → hash-bound receipt path, closing the final
  Plan022 CP-01 audit warning.
- Make Controller provenance structurally unforgeable at the Worker boundary:
  a MiniMax-authored report containing `role_visible_state_sha256` is rejected,
  and only `record-stage-report` may inject the exact post-call binding into the
  canonical report.
- Preserve Plan021 and Plan022 as immutable negative field evidence. A fresh plan and fresh
  real CP-01 review are required; this patch does not reinterpret or unlock the
  blocked plan.
- Add `prepare-staged-research` after Plan024 reproduced a pre-authorization
  hash/receipt loop. The command runs the initializer's complete deterministic
  validation before any signature, emits exact file-byte hashes and the
  canonical proposal, and forces create/apply/init to bind the same record ID,
  profile, capacity, incumbent, and proposal. Plan024 remains negative evidence.
- Close the sole real Plan025 CP-01 finding by recording the frozen
  `stage-report-validator/2` path, Runtime path, both exact hashes,
  byte-identity result, conformance receipt identity, and ten-case result in
  canonical preflight. Runtime revalidates that attestation after CP-01.

## v0.17.1 — 2026-07-27

- Add an explicitly inactive evaluation-profile shape for observation-only
  stages; Gate metric, threshold, operator, margin, and query-limit fields are
  forbidden when `applicable=false`.
- Add the shipped `stage_report_validator.py` and its initial eight-case conformance
  suite. Its implementation and conformance receipt are mandatory immutable
  CP-01 review materials. `record-stage-report` validates closed report shape,
  canonical stage/candidate identity, MiniMax Worker identity, bounded
  scientific summary/findings, exact claim-to-candidate bindings, and exact
  canonical terminal-validation receipts before adding Controller provenance.
- Expand STAGE-REVIEW to the canonical contract, envelope, report, candidate,
  decision, and terminal validation receipt. Only an exact strongest-policy
  `accept` permits bounded continuation; `revise` and `block` are hard vetoes.
- Bind active/inactive evaluation profiles bidirectionally for new and revised
  stages. Legacy active-profile observation plans remain readable, but new
  inactive profiles can never authorize an evaluative stage.
- Pre-v0.17.1 in-flight three-role STAGE-REVIEW packets and envelopes without
  the frozen report validator fail closed; create a fresh versioned stage and
  fresh review/capacity path rather than reusing them.
- Clarify that `RECORDED` is a candidate-recording state, not whole-stage
  acceptance. Terminal report, strongest-policy `STAGE-REVIEW`, and bounded
  continuation authorization remain mandatory before Stage 2 starts.

## v0.17.0 — 2026-07-27

- Make `state/staged_research/v1/` the sole runtime authority for staged
  research. `state/progress.json` and `state/research-dossier.md` are now
  explicitly rebuildable, non-authoritative projections; operators can restore
  both with `rebuild-staged-projections` without changing canonical state.
- Introduce capacity v2 with independent accounting for each stage's Worker
  dispatch quota, plan-global Worker dispatch capacity, non-transferable
  `STAGE-REVIEW` capacity, and non-fungible CP-01/CP-02/CP-04 slots. CP-03 is an
  optional named slot. Signed frontier top-ups do not mint or transfer Worker,
  stage-review, or checkpoint capacity.
- Allow the initial signed `authorize_contract` receipt to pre-authorize
  exactly one named next stage. After the source stage has a terminal decision,
  MiniMax report, and fresh strongest-policy review, `advance-staged-research`
  derives a receipt bound to that lineage, then compile → preflight → authorize
  → start exactly one next-stage Worker through an idempotent journal. Silence
  is never approval; the signed contract records `max_automatic_crossings=1`.
- Retain existing-plan lifecycle and idempotent replay compatibility for
  legacy capacity v1, but reject `advance-staged-research` unless the plan uses
  separated capacity v2. New v0.17 plan generation uses capacity v2.
- The release claim is only the bounded capability and acceptance target of
  crossing one first-stage terminal lineage into the start of one second-stage
  Worker. It does not claim second-stage completion, scientific success, 24h
  or 7x24 stability, production readiness, or full cutover.
- Keep the isolated Codex reviewer compatible with the standalone custom-agent
  schema: feature flags disable multi-agent execution, while the obsolete
  `agents.enabled=false` TOML override is no longer emitted. The latter is
  parsed as an invalid boolean role by current Codex releases.
- Treat Claude Code `auto` permission classification as an outer Harness
  boundary, not research capacity. Unattended operation requires an explicitly
  pre-authorized controller session; classifier denial occurs before frontier
  launch and must not consume a CP, review, retry, or Worker slot.
- Allow staged CP-01 envelopes to bind the concrete acceptance profile, source
  manifest, citation universe, evaluation profile, and evaluator loader
  parameters as independently hashed review materials. These remain optional
  at the generic schema layer, but a research contract may make them mandatory
  through its own execution and acceptance policy.

## v0.16.2 — 2026-07-26

- Expand every content-addressed first-stage review material into the bounded
  CP-01 Codex context instead of exposing wrapper hashes alone.
- Require readable execution-plan, evaluator, risk/stop, and figure-strategy
  materials for new initial staged envelopes.
- Reject plan-wide ChatGPT budgets that cannot fund the declared number of
  minimum-sized frontier calls; distinguish the 150k/5k admission floor from
  the 350k/15k field default after plan013 charged 294,915/11,457 tokens.
- Make a real Claude Code CP-01 pass plus first research work-unit creation the
  field acceptance gate.
- Disable the complete Codex agent surface for frontier reviews with
  `agents.enabled=false`, reject collaboration events, and validate that
  isolated configuration before reserving budget.
- Revalidate immutable staged inputs before Worker budget mutation, start the
  scientific clock at authorization, and add narrow audited recovery for a
  provably unstarted reservation or a transport denied before source access.
- Reject unavailable Claude executables and non-UTF-8 observation sources
  before any Worker run or scientific-budget mutation; precheck dispatch
  capacity and scientific capacity under one lock so a second work unit cannot
  strand either ledger.
- Grant read-only Claude workers visibility to hash-verified external input
  directories with `--add-dir`, disclose the exact closed content-validator
  schema in the Worker prompt, and freeze a six-case source-grounding evaluator
  conformance suite. Normal and legacy-normalized artifacts share the same
  declared byte-cap enforcement.
- Field acceptance on `fwvg-conf-2026-013` reached `DEVELOPING`, ran real
  MiniMax-M3 source research, and produced a validator-v2-accepted seven-record
  source inventory; no 24h, 7x24, or full-cutover claim is implied.

All notable changes to **autoresearch-paper** are documented here.
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
within the Harness contract:

- **Major** (1.0+) — breaking changes to the orchestrator contract or
  state-schema.
- **Minor** (0.x.0) — new feature (tier, gate, watchdog layer, etc.).
- **Patch** (0.0.x) — bug fixes, refactors, doc updates.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Conventional Commits](https://www.conventionalcommits.org/).

## [0.16.1] - 2026-07-26

### Fixed

- Structurally valid `block`/`revise` frontier advice, including critical
  findings, is retained as validated advisory evidence. An `accept` that still
  contains blockers or critical findings is now a distinct semantic failure;
  controller-observed budget overruns and malformed responses remain separately
  classified and never refund a launched call.
- A `0/0` transport usage event is charged at the full frozen reservation
  instead of being treated as free. New ChatGPT policies freeze a conservative
  `150000` input / `5000` output per-request floor and reject smaller
  reservations before login preflight, budget reservation, or transport launch.
- Signed `authorize_frontier_capacity` receipts add positive future-only call,
  input, and output capacity through an exact-once global/staged/usage journal.
  Grants bind plan, policy, active stage and envelope, and all current ledger
  hashes; they cannot refund or rewrite a launched request.
- New stage envelopes bind reviewer-required controller material through a
  plan-relative `{id,path,sha256,purpose}` manifest, including the stop policy.
  Legacy v0.16 envelopes remain readable and idempotently replayable.
- `STAGE-REVIEW` creation now fails fast unless the active stage has a canonical
  terminal Gate decision and immutable stage report, with an explicit route to
  CP-01 `approve_execution` for initial stages.

### Security

- Durable frontier commits remain limited to requests prebound to a context
  capsule. Canonical terminal staged reviews persist through
  `record-strong-stage-review`; apply-time capsule synthesis remains forbidden.
- Capacity top-ups are append-only, signed, replay-safe, crash recoverable, and
  preserve non-transferable CP-01/CP-02/CP-04 slots and
  `remaining_calls >= mandatory_future_calls`.
- This patch is bounded deterministic recovery work. It does not claim 24h,
  7x24, production, distributed, or full-cutover acceptance.

## [0.16.0] - 2026-07-25

### Added

- Versioned `state/staged_research/v1/` governance with immutable optimization
  contracts, one executable stage at a time, deterministic current-stage
  preflight, exact role-visible state, and append-only evidence/audit records.
- Non-fungible CP-01, CP-02, and CP-04 slots plus a separate retry ledger.
  Model dispatch fails closed when mandatory future calls cannot be preserved.
- One logical acceptance-Gate decision per frozen candidate. Idempotent
  transport retries keep the logical query fixed and consume independently
  frozen attempt capacity.
- Terminal MiniMax-M3 reports and fresh strongest-policy non-M3 review receipts
  are required before the controller can compile at most one next stage.
- Canonical owner authorization and reauthorization receipts, evaluator and
  adoption-policy rebaseline receipts, per-stage resource ledgers, bounded
  evidence maturity/retrieval, and replayable role-visible manifests.

### Changed

- CP-01 for v0.16 plans reviews the human-owned optimization contract,
  exactly one first-stage envelope, deterministic preflight, and named
  capacity. Legacy v0.15 evidence profiles and receipts remain valid.
- Exact figure inventory freezes at the first authorized figure-production
  stage. Provenance, renderer, exact-set, and human-review gates remain
  fail-closed; legacy v0.15 CP-01 figure receipts keep their historical
  interpretation.

### Security

- Accept promotes, reject retains the incumbent, and escalate blocks. Negative
  evidence is preserved; development evidence never becomes transfer proof.
- Strong-model findings remain advisory. Only deterministic controller
  receipts authorize execution, Gate application, and next-stage compilation.
- Staged/global frontier capacity and Gate retries use locked reconciliation
  journals; adversarial regressions cover bounded concurrent and injected
  PREPARED-state recovery without claiming long-soak or production cutover.
- One shared process lock now serializes staged audit revisions and next-stage
  compilation. Capacity and compile journals recover injected exits at their
  exact intermediate write boundaries without admitting a second writer.

## [0.15.0] - 2026-07-25

### Added

- The top-level plan declared by the controller as MiniMax M3 output now has a
  dedicated CP-01 review profile pinned to Codex `gpt-5.6-sol` at `ultra`
  reasoning.
- CP-01 carries the exact normalized brief, execution plan, risk budget, and
  figure requirements. No worker dispatch is admitted before a validated
  `accept` response is applied as `approve_execution`.

### Security

- The applied transition receipt records the reviewer profile and frozen model
  policy hash. `assert-transition` and every MiniMax worker dispatch revalidate
  that identity, so a weaker or mutated reviewer cannot unlock execution.
- Legacy policies without the new profile retain their historical behavior;
  every newly initialized v0.15.0 plan freezes the stronger CP-01 contract.
- The runtime binds the controller-declared author family; it does not claim
  cryptographic proof of which model process generated the plan bytes.

## [0.14.1] - 2026-07-25

### Fixed

- Frontier dispatch now runs executable, ChatGPT login, strict response-schema,
  and known model/transport compatibility checks before reserving the frozen
  call/token budget.
- The canonical ChatGPT frontier route uses an explicit HTTPS-only Codex
  provider, avoiding repeated WebSocket retry delays while preserving the
  authenticated ChatGPT session.
- Controller-owned plan directories pass `--skip-git-repo-check`; Codex remains
  read-only and cannot mutate lifecycle state.
- Codex event and stderr streams are persisted while the process is running,
  so a host timeout leaves durable transport evidence.
- Frontier prompts carry controller-computed response hashes and checkpoint
  recommendation constraints. The documented token budget now reflects
  measured Codex base/skill/tool context rather than artifact bytes alone.

### Security

- Proven pre-dispatch failures consume no frontier budget. Once dispatch starts,
  timeout or externally interrupted outcomes remain charged and PAUSED until
  explicit reconciliation; the runtime never rewrites the ledger or blindly
  redelivers.
- Crash recovery covers both sides of the ledger/status commit boundary.
  Reservations proven not to have launched transport are released only through
  immutable per-claim intent/receipt records, including preflight failure and
  operator expiry after restart; `SENT`/`WAITING` reservations are never
  refunded automatically.
- Existing v0.14.0 plans whose entire frontier budget was consumed cannot be
  retroactively refunded. Restart from a newly frozen plan after upgrading.
  The full failure chain and operator diagnosis are recorded in
  [`frontier-transport-incident-2026-07-25.md`](skills/autoresearch-paper/references/frontier-transport-incident-2026-07-25.md).

## [0.14.0] - 2026-07-24

### Added

- A host-neutral scientific figure artifact schema binding source inputs,
  transformations, render commands, renderer identity, outputs, hashes, and
  human review bound to every current output.
- An offline, standard-library figure validator with path-confinement,
  symlink-escape, inventory, hash, provenance, format, preview, output-bound
  human-review, and authority checks.
- A post-research-decision figure-build stage and pre-writing/package gates
  across arxiv, conference, and journal plans.
- Focused Scientific Visualization integration at the audited upstream
  revision, with Scientific Schematics retained as optional proposal-only
  assistance.

### Security

- AI-generated schematics and AI quality scores cannot approve scientific
  accuracy or figure promotion.
- Unsafe paths, undeclared or mismatched artifacts, and unreviewed proposals
  fail closed without weakening the writing gate.
- CP-04 and writing authority are bound to an immutable non-empty figure gate;
  stale PDFs, empty inventories, alias capability names, and placeholder
  review receipts fail closed.
- CP-01 freezes the exact expected figure IDs (minimum 1 arxiv, 4 conference,
  6 journal-q1); omitted or unexpected inventory entries cannot pass.

## [0.13.0] - 2026-07-23

### Added

- Frozen acceptance profiles covering the exact seven T008 fault scenarios,
  planned soak duration, required session restarts, and allowed claim kinds.
- Evidence-bound fault and session completion receipts that reject duplicate
  transitions, lost accepted evidence, excess overlap, unauthorized recovery,
  insufficient restarts, or insufficient measured duration.
- Claim validation that caps duration at the measured interval and enforces
  minimum evidence for 24h and 7×24 labels.
- A production-path acceptance regression executing all seven faults and a
  real multi-process/session bounded soak.

### Limitations

- The committed evidence validates bounded fault and restart behavior, not
  24-hour, 7×24, or full-cutover stability. Those labels remain mechanically
  rejected by the shipped profile and claim gate.

## [0.12.0] - 2026-07-23

### Added

- Two-stage episode-to-audited-memory and memory-to-proposal promotion with
  identical replay, held-out/regression validation, and independent audits at
  both boundaries.
- Skill-defect versus execution-lapse diagnosis, persistent rejected receipts,
  and a registry preventing rejected identical proposal bytes from returning
  as unreviewed novelty.
- Proposal-bound `authorize_evaluator_change` human actions.

### Security

- Learning receipts are proposal-only and explicitly carry no application
  authority. No command automatically edits skills, policy, specs, or
  evaluators.
- Learning gate evidence and auditor identity are excluded from worker-owned
  namespaces; evaluator proposals require an applied authenticated human
  receipt bound to the exact bytes.

## [0.11.0] - 2026-07-23

### Added

- Immutable controller-owned evaluator, evidence, and metric-contract
  snapshots that remove production admission from worker-owned namespaces.
- Replayed scientific-acceptance receipts binding canonical execution,
  candidate, evidence, frozen comparison, derived verdict, and current
  unattended evaluator admission.
- Deterministic `goal_drift` and `evaluator_integrity` detection, exact-once
  counters, and isolated pause/rebaseline or revoke/re-admit routes.

### Changed

- Candidate evaluation transparently rebinds hash-matching CP-02 inputs to the
  canonical controller snapshot.
- Normal writing authorization consumes a scientific-acceptance receipt rather
  than trusting a stored PASS field alone.

## [0.10.0] - 2026-07-23

### Added

- Capsule-bound MiniMax production dispatch with exact task-contract,
  purpose-bearing input-manifest, state-revision, promotion, and durable
  evidence correlation.
- Durable Codex checkpoint request derivation from the canonical capsule and
  exact checkpoint evidence-role profile.
- Exact-once controller commits that admit only immutable worker promotion or
  frontier dependent-transition receipts into the durable work-unit loop.
- Closed production transport regressions for both worker and frontier paths.

### Changed

- The production procedure no longer reconstructs worker or frontier context
  from conversation history. Generic frontier request creation remains for
  non-durable gates such as initial CP-01 approval.
- Codex advice remains read-only and cannot directly complete a durable task;
  only the deterministic controller's applied transition receipt is evidence.

## [0.9.0] - 2026-07-23

### Added

- A launchd-backed, session-independent production trigger with durable
  registration/unregistration receipts, generation-bound tick leases,
  duplicate suppression, missed-tick reconciliation, and crash recovery.
- Immutable canonical plan revisions, append-only transition/evidence chains,
  rebuildable objective/phase/evidence/blocker/approval/next-action
  projections, general dependency-driven work selection, and fresh hash-bound
  context capsules.
- Metadata-only Guardian observations with closed schemas, deterministic
  controller recovery policies, and validation of pre-authorized lifecycle
  receipts.
- Executable evaluator admission for unattended conference/journal plans,
  binding evaluator class and authority, immutable inputs, validation
  identity, identical replay, passing regression, allowed search space,
  complexity policy, and exact durable-plan evaluator identity.

### Changed

- A file-backed schedule no longer counts as a production trigger; external
  scheduler acceptance is required before a registration receipt is written.
- Unattended conference/journal registration, tick execution, graph advance,
  and work-unit result application now fail closed without current evaluator
  admission and revalidate the complete admission chain on every boundary.
- The closed M1 conformance workflow remains unchanged and distinct from the
  production state-driven loop. Fault injection and multi-session soak remain
  cutover acceptance work.

### Fixed

- External scheduler bootstrap and applied-tick crash windows now recover
  without duplicate registration, state transition, or tick effect.
- Derived state deletion rebuilds from canonical revisions and chained events;
  evaluator, goal, task, input, state-revision, or admission drift blocks
  result application.

## [0.8.0] - 2026-07-18

### Added

- A Claude Code target-runtime adapter with immutable per-plan MiniMax M3 and
  Codex model policy, bounded structured worker dispatch, and read-only tools.
- A durable `frontier-advisor-v1` bridge for CP-01 through CP-04 with hashed
  context manifests, atomic budget reservation, Codex CLI transport, response
  schema validation, durable state, and idempotent advisory consumption.
- MAVIS-free conformance coverage using fake Claude/Codex executables.
- HMAC-signed, expiring, replay-protected lifecycle, waiver, worker-cancel,
  and cleanup actions with durable audit receipts.
- Frozen evaluator contracts, hash-bound machine verdicts, authenticated
  writing waivers, and CP-04 final-evidence enforcement.
- Typed runtime/scientific failure counters, distinct scientific pivot
  eligibility, worker inspect/wait/message/cancel, file-backed patrol, and
  exact-path owned-resource cleanup.
- Plan/checkpoint/request/context-bound frontier responses, exact-once
  dependent transitions, deadline expiration, restart assertion, and changed
  artifact rejection.

### Changed

- Model-authored rescue verdicts are advisory records only. Forbidden accept,
  override, waiver, or cancellation output is converted to human escalation
  and never sent to a lifecycle command.
- MAVIS is an explicit `--legacy-mavis` compatibility dependency; Claude Code
  is the canonical Harness entry point.
- The shipped `claude-research-conformance-v1` fixture replaces arbitrary
  conformance command lists and resumes PREPARED subprocesses through stable
  runtime operation IDs; it is not the production research trigger.
- CP-02 freezes the audited metric contract; scientific direction identity no
  longer includes candidate bytes; repeated CP-03 decisions have per-request
  receipts; promotion and cleanup have recovery journals.

### Fixed

- PREPARED operation recovery now reaches command-owned pivot, human-action,
  promotion, and cleanup journals; operation-bound retries converge without
  weakening replay or changed-generation rejection.
- Writing-gate consumers revalidate the complete authority chain and exact
  candidate input; declarative evaluator metrics can no longer come from a
  candidate-independent evidence file.
- Stop-only terminal authorization now supports plans with zero eligible
  removable resources while enforcing exact cleanup coverage otherwise.
- Setup messages no longer execute Markdown backticks as shell substitutions.
- Cleanup dry-runs report intended ephemeral resource actions even when the
  corresponding legacy MAVIS file is absent on the test host.

## [0.7.0] - 2026-07-16

### Changed (breaking)

- **CLI → tool migration.** The legacy `mavis` CLI subcommands
  `mavis agent {new,delete,archive,...}`,
  `mavis cron {create,delete,trigger,list,...}`,
  `mavis session {list,compress,archive,...}`,
  `mavis hook {create,delete,list,...}` are removed by the runtime.
  The skill is rewired to:
  - Use the **native `mavis` tool** (`mavis({ command: "agent create", args: {...} })`)
    for agent / cron / session operations. The tool is the only
    supported call form in v0.7.0+.
  - **Direct file writes** for hooks
    (`~/.mavis/hooks/<name>.json.md`), crons
    (`~/.mavis/agents/<agent>/crons/<name>.md`), and watchdog agents
    (`~/.mavis/agents/<name>/agent.md`). The Mavis daemon picks these
    up on its next scan.
  - **Direct file removal** during cleanup. Cron / hook files are
    `rm -f`'d; session and agent directories are moved to
    `~/.mavis/{sessions,agents}/.archived/<name>-<ts>/` for recovery.
- **`mavis team plan abort` → `mavis team plan cancel`.** v0.7.0
  renames the abort verb to `cancel` for consistency with the cancel
  flow used elsewhere. All watchdog and rescue docs are updated.
- **`mavis communication send` deprecated.** v0.7.0 has no direct
  replacement; the watchdog should write a `findings/<ts>.md` summary
  and (for `critical` severity) an `control/escalate_to_human.json`
  signal so the L0 rescue daemon flags it on its next patrol.

### Added

- **Built-in agent safety check** in `cleanup-plan-resources.sh`.
  Agents with a `scripts/` subdir and no `agent.md` (e.g. the `mavis`
  built-in) are refused even when marked `ephemeral=true`. The
  script moves the directory to `~/.mavis/agents/.archived/` instead
  of `rm -rf`'ing it, so a misconfigured manifest can be recovered.
- **Hook filename dual-fallback.** `cleanup-plan-resources.sh` and
  `plan-l0-guard.py` try both `<name>.json.md` (current convention)
  and `<name>` (legacy) when removing or checking hooks. This avoids
  re-introducing the v0.6.0 archive-subcommand bug class for hooks.

### Fixed

- **Test prompt #3** (`tests/test-prompts.json`) — updated expected
  stderr to the new `mavis CLI not found in PATH (needed for
  `mavis team plan ...`)` message, with a v0.7.0+ annotation that the
  script no longer needs the CLI for any other subcommand.
- **FM-1 in `tests/e2e-uav-coverage.md`** — same message update.
- **Cleanup section in `tests/e2e-uav-coverage.md`** — replaces the
  `mavis cron delete` / `mavis hook delete` calls with direct file
  removals; documents the v0.7.0+ contract.
- **Plan-l0-guard health check** — the cron/hook health check no
  longer requires the removed `mavis cron list` / `mavis hook list`
  CLIs. It reads files directly under `~/.mavis/agents/<a>/crons/`
  and `~/.mavis/hooks/`, which is the v0.7.0+ contract.

### Migration recipe for downstream consumers

- Replace `mavis agent new <name> ...` with
  `mavis({ command: "agent create", args: { name: "<name>", system_prompt: "...", display_name: "...", description: "...", persona: "..." } })`.
- Replace `mavis cron create <agent> <name> ...` with a file write to
  `~/.mavis/agents/<agent>/crons/<name>.md` (markdown with
  frontmatter: `name`, `schedule`, `timezone`, `agent`, `session_mode`,
  `keep_sessions`, body=prompt).
- Replace `mavis hook create <name>.json -e <event> ...` with a file
  write to `~/.mavis/hooks/<name>.json.md` (markdown with
  frontmatter: `hookEvent`, `type`, `priority`, `matcher`, `timeout`,
  body=script).
- Replace `mavis cron trigger <agent> <name>` with
  `mavis({ command: "cron trigger", args: { cron_id: "<agent>/<name>" } })`.
- Keep `mavis team plan {status,cancel,resume,decision,run}` — those
  remain a CLI in v0.7.0+.

## [0.6.0] - 2026-06-26

### Added

- **Agent Skills monorepo layout.** The skill bundle moves to
  `skills/autoresearch-paper/` so `npx skills add WdBlink/autoresearch-paper`
  resolves it. Root `README.md` and `docs/` stay at the repo root.
- **Full test bundle under `tests/`.** Contract tests for research gate,
  L0 dry-run, plan-dir resolution, stop/cleanup JSON escaping, and
  manifest-based resource cleanup.
- **`CHANGELOG.md`** at repo root, this file.
- **`docs/ROADMAP.md`** with three-tier planning board (on-deck / candidates
  / wishlist).

### Fixed

- **Cleanup script subcommand fix.** `mavis agent archive` and
  `mavis session archive` in `references/scripts/cleanup-plan-resources.sh`
  replaced with the correct subcommands (`delete` and `compress`
  respectively). The original bug let residual agents and sessions leak
  across plans because the helper CLI exited 0 while printing an error.

### Changed

- README: adds Status, Table of Contents, Architecture, FAQ, Changelog,
  and Citation sections.
- `SKILL.md`: adds `## Versioning` section so the changelog is reachable
  from a stable anchor.

## [0.4.0] - 2026-06-26

### Added

- **Platform-portable daemon pattern.** Replaces the Linux-only `setsid`
  step in `nohup` invocations with a portable `(command &) disown` form,
  so the same bootstrap works on macOS and Linux.
- **Producer discipline pre-flight checklist.** Hardens the producer
  against the "ran a quick smoke test and exited before launching the
  full sweep" failure mode. The checklist enforces corruption-guard
  sanity, lockfile, progress.json, aggregator slot, and cron readiness
  before the worker exits.
- **In-process model preload.** For NN inference backends (VGGT-Ω,
  DUSt3R, PyTorch baselines), the model is loaded once at task start
  and passed to every cell, instead of reloaded per cell.

### Added (reviewer rubric)

- **Harness-paper honest-framing pattern.** When the harness is dormant
  on a SOTA-tuned baseline (B5 == B0 on the primary metric), the
  reviewer rubric now expects an explicit "no regression on SOTA" plus
  a separate "preventive gain on stress" claim, instead of a wrapped
  paper that hides the no-op finding.

## [0.3.1-r5] - 2026-06-25

### Added

- **Step 7.5.a + FM-15**: wide-table 2-column `multicolumn` span
  recipe for camera-ready LaTeX output. Fixes the cell-overflow issue
  in `\begin{tabular}{lcc}` when the metric column has 12+ entries.

## [0.3.1] - 2026-06-25

### Added

- **V6 evidence-driven optimization round.** Six rounds of Darwin-style
  rubric evaluation (dim1–dim9) over the 5-day window. The
  V6 evaluation surface includes engine-ceiling handling, verifier
  spot-check recipe, and the 0% framing honesty pattern for negative
  results.
- **Reviewer-readiness rubric (6 dimensions).** Structure, Effectiveness,
  Resource Integration, Checkpoints, Safety, and Reproducibility.
  The 9-dim SkillLens rubric is consulted for inspiration but the
  authoritative score uses the 6-dim version tuned for paper skills.

## [0.3.0] - 2026-06-24

### Added

- **Rescue Layer.** L0 filesystem-corruption guard, hourly watchdog
  cron, plan-rescue daemon (`references/scripts/plan-rescue-daemon.py`),
  and three failure-mode FMs (manual_retry, soft_pause, hard_abort).
- **Abort gate.** A `🔴 STOP · ABORT GATE` marker that the L0 guard
  writes when filesystem state is corrupted; the user must explicitly
  acknowledge before any cleanup.
- **Workspace isolation.** A `🔴 STOP · WORKSPACE ISOLATION` marker
  that pins the plan dir on plan start; any cross-plan write attempt
  triggers an alert and rollback.
- **`resource_manifest.json` contract.** Every ephemeral resource
  (agent, cron, hook, lock, background process) is recorded and
  walked by `cleanup-plan-resources.sh` on stop / complete / abort.

## [0.2.0] - 2026-06-23

### Added

- **Three-tier plan templates.** `references/plan-template-arxiv.md`,
  `conference.md`, `journal-q1.md`. Tier selection is driven by
  `goal-keywords.md` and `tier-decision-tree.md`.
- **Heartbeat contract.** L0 (filesystem), L1 (hourly cron), L2
  (per-task `last_seen.jsonl`). Each layer has its own recovery path.

## [0.1.0] - 2026-06-22

### Added

- Initial brief-to-paper pipeline. Receives a paragraph-level research
  brief, generates a `plan.yaml`, freezes the evaluator at T0, runs
  method/experiment loop T1–T6, gates writing at T6.1/T6.2, and
  delivers `paper.tex` + bibliography + figures + readiness report
  at T7.

[0.6.0]: https://github.com/WdBlink/autoresearch-paper/releases/tag/v0.6.0
[0.4.0]: https://github.com/WdBlink/autoresearch-paper/releases/tag/v0.4.0
[0.3.1-r5]: https://github.com/WdBlink/autoresearch-paper/compare/v0.3.1...v0.3.1-r5
[0.3.1]: https://github.com/WdBlink/autoresearch-paper/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/WdBlink/autoresearch-paper/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/WdBlink/autoresearch-paper/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/WdBlink/autoresearch-paper/releases/tag/v0.1.0
