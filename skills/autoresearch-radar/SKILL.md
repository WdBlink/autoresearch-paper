---
name: autoresearch-radar
description: Use when an Adapter-issued research watch profile needs a scheduled or explicit refresh that turns newly synchronized external research into a verified, auditable Research Signal Package.
---

# AutoResearch Radar

## Core contract

Refresh one frozen research watch profile without reopening the scientific
lifecycle. Synchronize an authorized source, extract candidates read-only,
classify every candidate, verify promising claims against primary sources, and
publish one compact Research Signal Package. This is a conditional capability,
not a continuous research stage.

## Sole handoff modes

Accept exactly one compact input per invocation:

| Mode | Sole input artifact |
| --- | --- |
| Scheduled or explicit scan | `autoresearch/research-watch-profile.yaml` |

The profile must be Adapter-issued and bind its Research Brief identity/hash,
project and repository scope, source queries, allowed signal types, minimum
evidence level, contract-fit rules, scan bounds, and out-of-scope disposition.
Reject a missing, mutable, unbound, or superseded profile.

## Source cycle

For FOLO, read [the local-source protocol](references/folo-local-source.md) before
access. An external harness must first refresh through the FOLO official UI and
produce a fresh, Ed25519-signed refresh receipt bound to the Watch Profile and
the exact cache and reconstructed-database snapshots. Then run the shipped
`scripts/folo-source` adapter against a read-only local cache snapshot. Never
interpret an old cache as “nothing new.”

Use this order:

1. Validate the profile, source instance, scan window, budget, and refresh
   receipt. On missing or stale synchronization, stop with
   `research-radar-sync-failed`.
2. Run source `doctor`, then extract deterministic candidates from only the
   profile-authorized feeds and frozen query scope. Candidate extraction is
   read-only and never updates durable state.
3. Apply the frozen watch criteria and write **one decision for every extracted candidate**,
   including ignored and deferred candidates.
4. For a potentially forwardable item, treat its RSS summary only as a lead.
   Open and verify the primary source. A summary cannot satisfy the minimum
   evidence level, scientific claim, or citation requirement.

Do not change subscriptions, read state, favorites, source content, or the live
cache. Do not broaden the query or scoring rules during a scan.

## Signal decisions

Read [the signal package contract](references/research-signal-package.md). Keep
these axes independent for every decision: `relevance`, `evidence_level`,
`contract_fit`, and `signal_type`. Record the source claim, applicable scope,
verification status, evidence links, exclusion reason, and content digest.

Forward only a signal that meets the profile's evidence and fit thresholds.
Evaluator, benchmark, dataset, novelty-threat, and out-of-contract method
signals remain classified leads; they do not silently change the running
research contract. Preserve negative and conflicting sources rather than
optimizing the feed for agreement.

## Three state layers

- **Source Cursor** — this capability owns which stable source items and
  deferred retries were processed. It is immutable run state reached through
  the stable commit-root pointer, not a second mutable file.
- **Signal Decision Ledger** — this capability owns how each extracted item was
  classified and why.
- **Adoption Ledger** — Experiment owns whether a forwarded signal generated a
  proposal and what happened to it. Radar never marks a signal adopted.

Never merge these layers. “Seen,” “forwarded,” and “adopted” are distinct facts.

## Commit order

Build an immutable, content-addressed run under
`autoresearch/research-radar/runs/<run-id>/`:

1. write `candidates.jsonl` plus an extraction manifest binding the frozen
   profile, authenticated refresh receipt, source snapshot, input state, and
   input commit root;
2. write `decisions.jsonl` with a one-to-one candidate ID and digest binding;
3. validate every record, referenced receipt, hash, path, and package invariant,
   including deterministic re-extraction from the bound database snapshot;
4. vendor the database, exact input state, authority artifacts, profile, public
   key, refresh receipt, evidence, and primary sources; write the immutable run
   manifest and derived output state; then atomically replace the sole stable commit-root pointer
   `autoresearch/research-radar/manifest.json` while holding its commit lock.

A successful scan with new candidates and zero forwarded signals still advances
processed state because every candidate has a committed decision. A truly empty
successful scan still records an auditable run while leaving the logical Source
Cursor unchanged. A stale cache, extraction error, failed verification, invalid
package, or pre-replace commit failure does not advance state; preserve the
previously valid pointer byte-for-byte. If replacement happened but directory
durability cannot be proven, report an indeterminate commit and inspect the
observed pointer before any retry.

## Stop

Emit exactly one outcome and stop:

- `research-radar-cycle-complete` after the run, stable pointer, and Source
  Cursor commit are valid;
- `research-radar-sync-failed` when fresh synchronization cannot be proven; or
- `research-radar-cycle-failed` for any failure before pointer replacement; or
- `research-radar-commit-indeterminate` when replacement may have happened but
  durable completion cannot be proven.

Never route directly into a scientific stage. The next invocation must be an
explicit route or external scheduled request using the frozen profile.

## Boundaries

The external platform owns the scheduler. Discovery owns the Research Brief;
Adapter owns the Experiment Contract and watch policy; evaluator engineering
owns evaluator construction; Experiment owns each candidate and Adoption
Ledger; Evidence owns the Claim Boundary; Paper owns the paper. Radar owns only
source refresh, candidate classification, primary-source verification, the
Signal Decision Ledger, and its Research Signal Package.
