# Research Signal Package

Each Radar cycle publishes one immutable run manifest and, only after the run
validates, atomically updates `autoresearch/research-radar/manifest.json` as a
compact pointer to that run and its hash. This pointer is the only mutable
commit root; Source Cursor state is an immutable artifact linked by it.

## Candidate decision

Write one decision for every extracted candidate. Bind the decision to the
candidate ID and `candidate_sha256`; do not drop ignored or deferred items.

Each decision records these orthogonal fields:

| Field | Meaning |
| --- | --- |
| `relevance` | Relationship to the frozen project question, independent of source prestige. |
| `evidence_level` | `summary-only`, `primary-opened`, `method-checked`, or `result-checked`. |
| `contract_fit` | `in-scope`, `adjacent`, `out-of-scope`, or `unknown` under the frozen watch policy. |
| `signal_type` | `method-opportunity`, `evaluator`, `benchmark`, `dataset`, `novelty-threat`, `contradiction`, or `background`. |
| `source_claim` | Faithful statement of what the source itself claims. |
| `applicable_scope` | Population, task, data, metric, setting, and caveats to which that claim applies. |
| `verification_status` | `unverified`, `primary-verified`, `qualified`, or `contradicted`. |

The candidate ledger carries source identity, title, canonical URL, publication
and effective times. Its paired decision carries candidate ID/digest, profile
identity/hash, decision (`forwarded|ignored|deferred`), the scientific fields
above, reason, uncertainty, and receipts. Primary-source references and hashes
live in both the forwarded evidence artifact and its matching receipt set.

An RSS summary is discovery metadata, never primary scientific evidence.
Forwarding requires the minimum primary-source verification frozen by the watch
profile. The evidence artifact must match the candidate ID **and** digest,
profile identity/hash, every scientific decision field, and the exact hashed
primary-source receipt set. Preserve mismatches between summary and paper in
the decision.

## Run manifest

The immutable run manifest links:

- vendored watch profile, authority artifacts, public key, authenticated
  refresh receipt, and their hashes;
- source-instance identity, cache/database snapshot hashes, vendored database,
  and extraction bounds;
- immutable extraction manifest and input commit-root hash;
- candidate and decision ledgers plus their hashes;
- counts for extracted, forwarded, ignored, and deferred candidates;
- content-addressed evidence and primary-source receipts for every forwarded
  signal;
- previous commit-root hash, proposed immutable state hash, and run-validation
  status/timestamp.

The stable pointer contains only schema version, run ID, immutable manifest
path/hash, profile identity/hash, committed state path/hash, previous commit
root, committed outcome, and completion time. It is a lookup and commit root,
not a third lifecycle handoff.

## Consumer rule

A forwarded signal is a bounded proposal input, not a scientific result. It
cannot change a frozen evaluator, contract, candidate decision, Claim Boundary,
or manuscript claim. The consuming stage records any later proposal/adoption in
its own ledger, leaving Radar's decision immutable.
