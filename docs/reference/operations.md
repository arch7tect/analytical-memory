# Operations Reference

This reference covers integrity checks, backup and restore, backend transfer,
evidence verification, and retention for a local v1 installation.

## Readiness and integrity

```console
uv run memory status
uv run memory validate
```

`status` reports backend and evidence-store readiness plus the runtime and
schema fingerprints. `validate` checks the relational store, foreign keys,
bounded evidence completeness, and evidence digests. Treat any issue as a stop
condition for transfer, snapshot, or retention work.

Run the commands with the same backend and path environment that the MCP server
uses. PostgreSQL configuration is documented in
[`backend-portability.md`](backend-portability.md).

## Evidence verification and audit

```console
uv run memory evidence status <sha256>
uv run memory evidence verify <sha256>
uv run memory evidence audit
```

Verification records append-only outcomes for the object and its fragments.
Audit also reports provider objects that have no canonical catalog record as
orphans. Audit never deletes an orphan or repairs corrupted evidence.

## Snapshot backup and restore

Create a private restore snapshot at a new path:

```console
uv run memory snapshot create backup.zip
uv run memory snapshot verify backup.zip
```

A snapshot contains canonical records, the structural contract, and available
evidence bytes. It is private operational material and should be protected like
the original evidence store.

Restore only into an empty target store and evidence root:

```console
uv run memory snapshot import backup.zip
uv run memory validate
```

After restore, compare the ontology fingerprint and representative ordered
Query IR results with the source. Keep the source unchanged until acceptance.

## Backend transfer

Canonical backend transfer intentionally differs from a private snapshot: it
does not copy evidence bytes and rebuilds backend-derived projections. Use
`memory transfer export` and `memory transfer import` according to
[`backend-portability.md`](backend-portability.md). The command never switches
the active backend automatically.

## Retention

Start with a report at an explicit time when reproducibility matters:

```console
uv run memory retention report --as-of 2026-08-27T00:00:00Z
uv run memory retention plan retirement-plan.json
```

Review the immutable plan. Retirement requires its exact `plan_id` as explicit
confirmation:

```console
uv run memory retention retire retirement-plan.json --confirm <plan-id>
```

The command records tombstones before removing provider bytes. A changed or
blocking acquisition state rejects the plan. Keep a verified private snapshot
when evidence must remain recoverable; retention never infers that backup
policy for the operator.

## Recovery rules

- Unknown schema versions fail closed; do not alter migration ledgers manually.
- A failed canonical import leaves its transaction uncommitted. Evidence audit
  may report an orphan if the process died before compensation; preserve it for
  investigation and remove it only through an explicit operator decision.
- Evidence corruption is reported without rewriting canonical content.
- On post-commit transfer verification failure, do not select the target;
  recreate its dedicated schema and retry from the unchanged source artifact.
