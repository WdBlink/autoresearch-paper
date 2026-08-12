# FOLO local source protocol

Use this protocol only for a watch profile that explicitly authorizes the local
FOLO source. The source adapter is a transport boundary; it does not decide
scientific relevance or create Research Signals.

## Refresh precondition

An external harness first refreshes the **FOLO official UI** on the all-items
timeline, completes bounded pagination, waits until the cache is stable, and
writes an authenticated refresh receipt. The receipt records the source
instance, Watch Profile identity/hash, refresh time, all-items timeline,
pagination completion, cache stability, and exact cache/database snapshot
digests. Its external producer identity and Ed25519 signature must match the
trust anchor frozen in the Watch Profile; the source adapter cannot self-attest
a refresh.

After the UI reports a stable refresh, the harness may use the read-only
`doctor --json` result to obtain the exact snapshot hash, then sign the receipt.
Candidate extraction reconstructs the source again and requires the same hash.

If the receipt is missing, stale, incomplete, or bound to another source, stop.
Do not interpret a **stale cache** as an empty result. UI automation details and
scheduling belong to the external harness, not this Skill or source adapter.

The Adapter-issued YAML/JSON profile must set `schema_version: 1`,
`profile_id`, `source: folo-local`, `source_instance_id`, the three
`source_scope` fields, `scan.hours|limit`, the three `policy` fields, and the
three `refresh_trust` fields named in the Adapter contract. The receipt must set
the same schema/source/instance/profile identity and profile hash, the trusted
`producer_identity`, `status: synced`, `timeline: all`, both
`pagination_complete` and `cache_stable` to true, `refreshed_at`, and:

```text
attestation.kind = folo-official-ui-refresh
attestation.source_snapshot_sha256 = <exact cache snapshot hash>
attestation.database_snapshot_sha256 = <exact reconstructed SQLite hash>
attestation.verified = true
```

Set `signature_ed25519` to the lowercase hexadecimal Ed25519 signature over
UTF-8 JSON of every other receipt field, with Unicode preserved, keys sorted,
no extra whitespace, and no NaN values. The Watch Profile stores only a
contained raw 32-byte public-key path and its SHA-256; the external refresh
harness retains the private key. The adapter rejects a receipt whose producer,
profile, either snapshot, signature, or freshness differs.

## Read-only extraction

Use `scripts/folo-source doctor` before candidate extraction. The adapter creates
a **read-only local cache snapshot** by copying the Chromium LevelDB store into
a controlled disposable scratch directory, reconstructs `/follow.db`, opens
SQLite with immutable read-only and query-only settings, runs integrity and
required-table checks, and deletes the snapshot.
It never writes into FOLO's live application-support tree.

Candidate extraction reads only current `subscriptions` whose type is `feed`,
then applies the profile's explicit authorized feed IDs, query terms,
exclusions, time window, and candidate limit.
It must not alter subscriptions, **read/unread** state, **favorites**, folders,
entries, or the local cache. Stable candidate IDs use `folo:<entry-id>`; content
digests, normalized time, bounded body text, and deterministic sorting make
replays auditable.

The immutable state reached through the current stable pointer filters already
processed items and due deferred retries. `doctor` and `candidates` never
mutate it. Production `record` accepts only the extraction manifest, never a
bare candidate ledger; that manifest binds profile, refresh receipt, source
snapshot, candidate ledger, input state, input commit root, and extraction
bounds. Before publication, the adapter repeats the deterministic extraction
from the bound database and requires exact ledger equality.

## Adapter invocation

Use one explicit artifact root for every run. First validate the live source,
then extract into new immutable paths:

```text
scripts/folo-source doctor --json
scripts/folo-source candidates --profile PROFILE --refresh-receipt RECEIPT \
  --artifact-root ROOT --output CANDIDATES \
  --extraction-manifest EXTRACTION
```

After Radar has written exactly one decision per candidate and all forwarded
evidence/primary-source receipts below `ROOT`, publish only through:

```text
scripts/folo-source record --extraction-manifest EXTRACTION \
  --decisions DECISIONS --artifact-root ROOT
```

Use `--stable-pointer` only to select a nondefault pointer below the same
artifact root. Use `--expected-commit-root-sha256` when the caller already has a
current pointer digest. Exit `0` is success, `2` is a fail-closed pre-commit
error, and `3` is commit-indeterminate. Standard output is machine-readable
JSON; diagnostics are machine-readable JSON on standard error.

## Commit safety

`record` requires exactly one digest-bound decision per candidate. Forwarded
decisions require three hash-bound receipt classes: the exact Watch Profile, a
complete Research Signal evidence artifact, and every primary source named by
that evidence. Deferred decisions require a future retry time and a due item
may be deferred again only while binding its prior decision hash.

Publication writes content-addressed immutable candidates, the exact input
state, database snapshot, authority artifacts, normalized decisions, evidence,
primary sources, extraction provenance, derived output state, profile, public
key, refresh receipt, and run manifest. Historical pointer validation repeats
the frozen extraction and derives the output state again from the input state
and decision ledger. While holding a stable sibling lock, it rechecks the input commit
root and then atomically replaces **one** stable pointer as the sole mutable
commit root. Identical replay is a byte-stable no-op; conflicting replay and
stale compare-and-swap fail closed. Receipt paths stored in the package are
relative to the artifact root.

On synchronization, snapshot, extraction, verification, validation, or any
failure before pointer replacement, **stop before state advancement** and keep
the last stable pointer byte-identical. If replacement completes but parent
directory synchronization fails, return the distinct `commit-indeterminate`
status; do not retry until the observed pointer is classified as old, new, or
invalid.
