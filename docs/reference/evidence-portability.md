# Evidence Portability and Lifecycle

Canonical memory rows and raw evidence bytes are separate. SQLite stores
content identities, acquisitions, relative provider locations, deterministic
fragments, append-only verification history, retention requirements, and
retirement tombstones. The local filesystem stores immutable objects by
SHA-256 beneath the configured evidence root. Neither surface persists the
absolute evidence-root path.

## Evidence operations

```console
uv run memory evidence status <sha256>
uv run memory evidence read <sha256> --offset 0 --limit 65536
uv run memory evidence verify <sha256>
uv run memory evidence audit --limit 1000
```

Reads return base64 and are limited to 1 MiB per call. Verify and audit append
new object and fragment checks while preserving earlier outcomes. Provider
availability remains independent from verification and retention state.

An ingestion batch may add an `evidence.fragment` object. Supported kinds are
`whole_object`, `structured`, `record_key`, `byte_range`, `line_range`,
`time_interval`, and `sample_interval`. Locator parameters are canonicalized
and the extracted bytes are hashed. Structured and record-oriented inputs are
materialized into canonical JSON or JSON Lines before fragment addressing when
their source representation is not canonical.

Effective evidence privacy is monotonic. It is the strictest class contributed
by the evidence declaration, source, bound targets, and every acquisition.
Content IDs remain digest-based when privacy becomes stricter.

## Retention

Retention has no background worker. The CLI produces an immutable plan, then
requires its exact ID as confirmation:

```console
uv run memory retention report
uv run memory retention release <sha256> --confirm <sha256> --reason "reviewed"
uv run memory retention plan retirement-plan.json --digest <sha256>
uv run memory retention retire retirement-plan.json --confirm <plan-id>
```

New acquisitions require retention by default. The CLI-only release command
records when and why all acquisitions for one digest stopped requiring it; an
independent future `retain_until` still blocks retirement. Planning includes
only present objects without an active acquisition requirement. Retirement
revalidates every planned digest and size, removes only
the content-addressed store copy, and records a tombstone. It never mutates or
deletes the original acquisition source. A required or unexpired acquisition
blocks retirement.

## Private snapshots

```console
uv run memory snapshot create memory.snapshot.zip
uv run memory snapshot verify memory.snapshot.zip
uv run memory snapshot import memory.snapshot.zip
```

A private restore snapshot contains the compiled schema, canonical table rows,
verified bytes for objects currently recorded as present, and missing or
retired states for the rest. It excludes FTS and future vector projections;
FTS is rebuilt after import. Member hashes, evidence digests, row counts,
artifact type, format version, and schema fingerprint are verified before any
canonical import. Import requires an empty canonical store and preserves IDs,
timestamps, bindings, verification history, and tombstones.

The initial in-process snapshot implementation limits total uncompressed
members to 64 MiB. Larger stores require a future streaming snapshot profile.

Sanitized interchange is deliberately separate:

```console
uv run memory export public-memory.json --privacy-ceiling public
```

This JSON artifact contains filtered current facts and relations, no evidence
bytes, and `restore_compatible: false`. The snapshot importer rejects it.
