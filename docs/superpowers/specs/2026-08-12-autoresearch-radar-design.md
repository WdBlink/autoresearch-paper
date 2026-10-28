# Auto-Research Radar Design

**Date:** 2026-08-12

**Status:** Accepted for v0.22.0

**Target release:** v0.22.0

## 1. Context

v0.21 split the research lifecycle into stage-specific skills so that one run
loads only one optimization objective. That boundary must survive the addition
of ongoing literature and method monitoring. A recurring feed scan is useful
throughout a long experiment campaign, but it is not another scientific stage:
it neither chooses the research question nor changes the frozen Experiment
Contract.

This design adds Research Radar as a conditional, asynchronous capability. It
periodically refreshes an authorized source, classifies new items against an
Adapter-issued watch profile, verifies promising leads, and publishes a compact
Research Signal Package. Experiment may consider those signals only within the
contract it already owns.

## 2. Architecture

The public suite is exactly **1 thin router + 5 lifecycle skills + 2 conditional capabilities**:

| Role | Skill | Unique responsibility |
| --- | --- | --- |
| Thin router | `autoresearch-workflow` | Select one next owner, then stop |
| Lifecycle | `autoresearch-discovery` | Decide what problem is worth researching |
| Lifecycle | `karpathy-autoresearch-adapter` | Define how the frozen problem can be implemented, run, and measured in this repository |
| Lifecycle | `autoresearch-experiment` | Search for a better candidate inside the frozen contract |
| Lifecycle | `autoresearch-evidence` | Validate what claims actually hold |
| Lifecycle | `autoresearch-paper` | Express frozen claims faithfully and compile the manuscript package |
| Conditional capability | `autoresearch-evaluator-engineering` | Build missing measurement capability and return it to Adapter |
| Conditional capability | `autoresearch-radar` | Monitor authorized research sources and publish verified, contract-aware signals |

```text
Discovery -> Adapter -> Experiment -> Evidence -> Paper
                |            ^
                |            | verified, contract-compatible signal proposals
                |            |
                +------ Research Radar
                |
                +------ Evaluator Engineering -> Adapter

Workflow routes lifecycle and explicit conditional requests; it executes none.
```

Radar is a sidecar, not a sixth lifecycle stage. A Radar completion or failure
does not automatically route the project anywhere. An explicit refresh request
may route to Radar, but the active lifecycle owner resumes from its own durable
artifact and authority.

Installed does not mean loaded. All eight skills may remain installed while an
invocation reads only the selected skill, its compact input artifact, and the
necessary linked project files.

## 3. Ownership boundaries

Adapter owns the monitoring policy. After explicit apply authorization it
freezes `autoresearch/research-watch-profile.yaml`, linked to the Research Brief
and, when available, the Experiment Contract. The profile defines source
identity, project queries and keywords, allowed signal types, minimum evidence
level, contract-fit rules, proposal budget, and the action for out-of-scope
findings. Radar may not broaden that policy.

Radar owns source synchronization, candidate classification, primary-source
verification, and signal publication. It never edits the Research Brief,
Experiment Contract, evaluator, candidate, Claim Boundary, or manuscript. It
also never marks a signal as adopted.

Experiment owns adoption. A signal becomes a literature-guided proposal only
when it satisfies the frozen external-research policy. Experiment records the
selection or rejection in its Adoption Ledger and counts every resulting
candidate in the Experiment Ledger. A signal cannot change the frozen evaluator,
metric, data split, permissions, budget, or acceptance rule.

Evidence audits the entire selection path, including Radar-derived candidates,
search multiplicity, exposed data or metrics, and any multiple-comparison risk.
Paper may use a Radar item as a citation lead only after verifying the primary
source; it cannot cite a feed summary as scientific support.

## 4. Artifacts

### 4.1 Research Watch Profile

Canonical path: `autoresearch/research-watch-profile.yaml`.

It is Adapter-issued, plan-first, and persisted only after explicit apply
authorization. It contains at least:

- profile schema version and stable identity;
- Research Brief identity, hash, and reference;
- Experiment Contract identity/hash/reference when a ready contract exists;
- source instance and authorized subscription scope;
- project terms, exclusions, and time window;
- allowed signal types and minimum evidence level;
- contract-fit tests and literature-guided proposal budget;
- out-of-scope disposition;
- refresh freshness and failure policy; and
- a trusted external refresh-producer identity plus an Ed25519 public-key reference/hash.

Discovery does not write this file, and Radar does not infer a replacement when
it is missing or invalid.

### 4.2 Research Signal Package

Each successful cycle writes immutable run artifacts below
`autoresearch/research-radar/runs/<run-id>/`. After validation, Radar atomically
updates the stable pointer `autoresearch/research-radar/manifest.json` to the
committed run manifest.

The package records every candidate and one decision per candidate. A forwarded
signal includes source identity, canonical URL, signal type, source claim,
applicable scope, relevance, evidence level, contract fit, verification status,
primary-source references, uncertainty, and content hashes. Ignored and deferred
items retain explicit reasons so later runs do not silently reinterpret history.

An **RSS summary is a lead**, not evidence. It may trigger retrieval, but it
cannot satisfy novelty, method, benchmark, evaluator, or claim support by
itself. Forwarding requires the applicable primary paper, official repository,
dataset card, benchmark specification, or other authoritative source. If that
source cannot be verified, the item remains deferred or is rejected.

The successful run vendors the exact Watch Profile and authenticated refresh
receipt used for validation. Its extraction manifest also binds the source
snapshot, candidate ledger, extraction bounds, input immutable state, and input
commit-root hash. Publication repeats deterministic extraction from the bound
database so a hand-written ledger cannot acquire valid provenance.

## 5. Three separate state layers

The design deliberately separates discovery from scientific adoption:

1. **Source Cursor** — owned by Radar; which stable source items have been
   processed for this watch profile. It is immutable state reached through the
   stable pointer, not a separately replaced mutable file.
2. **Signal Decision Ledger** — owned by Radar; how each observed item was
   ignored, deferred, or forwarded, with receipts and reasons.
3. **Adoption Ledger** — owned by Experiment; whether a verified forwarded
   signal was considered, selected, rejected, or yielded candidates under the
   frozen contract.

The Experiment Adoption Ledger is not writable by Radar. This prevents a source
scanner from turning relevance into experimental authority.

## 6. FOLO local-source protocol

FOLO support follows a fail-closed local-source adapter:

1. Refresh the FOLO official UI and capture a fresh, externally authenticated
   synchronization receipt bound to profile identity and source-snapshot hash.
2. Read only a disposable snapshot of the local cache; never mutate the live
   cache or fabricate synchronization from local timestamps.
3. Query subscribed feeds only and preserve stable source/item identities.
4. Preserve read/unread and favorites metadata as prioritization context, not
   truth or scientific authority.
5. Validate the cache, required tables, source-instance binding, receipt age,
   and deterministic candidate order before classification.
6. Stop before state advancement when the cache is stale, synchronization is
   unproven, package validation fails, or publication fails before pointer
   replacement.

Candidate extraction and state commit are separate operations. Radar first
writes immutable `candidates.jsonl` and a provenance manifest, then complete
`decisions.jsonl`, then content-addressed run artifacts. Under a stable sibling
lock it rechecks the input commit root and finally replaces one stable manifest
pointer as the sole mutable commit root. The linked Source Cursor state is
immutable. This compare-and-swap protocol prevents overlapping cycles from
overwriting one another.

A successful cycle with new candidates and zero forwarded signals still records
the decisions and advances processed source state. A truly empty cycle also
publishes an auditable run while its logical cursor is unchanged. A stale
cache, incomplete decision set, failed validation, or any pre-replace failure
advances nothing. Deferred items remain pending until their declared retry time
and may be deferred again only with a prior-decision binding. Replaying an
identical commit is idempotent; a conflicting replay fails closed. If pointer
replacement occurs but directory durability cannot be proven, Radar reports a
distinct commit-indeterminate result and requires inspection before retry.

## 7. Routing and scientific loops

Workflow recognizes an explicit `research-radar-refresh-requested` route to
`autoresearch-radar`. Radar emits operational completion or failure status and
the stable manifest reference, then stops. Neither status creates a scientific
return edge. The lifecycle owner later consumes the linked signal package under
its own input rules.

The scientific return loops remain exactly two:

1. Evidence `insufficient-evidence` returns to Experiment through a bound
   evidence request.
2. Paper `research-frame-invalid` waits for human confirmation, then returns to
   the confirmed Evidence or Experiment target.

Radar refresh, evaluator construction, Adapter reclassification, and frozen
deterministic Paper recovery are operational detours, not additional scientific
loops. There is no automatic return to Discovery.

## 8. Failure and stop conditions

Radar stops without advancing source state or replacing the stable pointer when:

- the Watch Profile is absent, malformed, unauthorized, or source-mismatched;
- fresh official synchronization cannot be proven;
- the cache snapshot is invalid or required source tables are absent;
- candidate identity or ordering is non-deterministic;
- any candidate lacks exactly one auditable decision;
- a forwarded signal lacks required primary-source verification;
- run artifacts fail schema, hash, or completeness validation; or
- atomic publication or Source Cursor compare-and-swap fails.

If the pointer may already have been replaced when durable synchronization
fails, Radar stops with `research-radar-commit-indeterminate` rather than
misreporting an ordinary pre-commit failure.

Radar may finish successfully with no candidates or no forwarded signals. An
empty scientific result is not an operational failure.

## 9. Human participation

This release does not prescribe one human policy for uncertain research stages.
Adapter retains its explicit plan/apply authorization boundary. Paper remains
autonomous when given a valid frozen evidence package. Radar can be invoked
manually or by an external scheduler, but it does not create, modify, or own the
scheduler.

## 10. Compatibility and installation

Standard discovery and `--all` installation expose exactly eight top-level
skills. The deprecated v0.20 `autoresearch-paper-mvp0` backend is not a ninth
discoverable skill; it is available only through its explicit compatibility
installer. The nested compatibility manifest must therefore not be named
`SKILL.md` in the standard source tree.

## 11. Non-goals

- Guaranteeing novelty, improvement, or SOTA from newly observed literature.
- Letting feed popularity, favorites, or summaries satisfy evidence gates.
- Reopening a Research Brief or Experiment Contract automatically.
- Making Radar a global controller, lifecycle stage, adoption authority, or
  paper citation authority.
- Adding a third scientific return loop.
- Coupling the suite to one scheduler or to FOLO as its only future source.
