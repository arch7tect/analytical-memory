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

## Memory wipe and deletion

Inspect the exact guard counts immediately before a destructive action:

```console
uv run memory memories status default
```

Pass all four returned counts and the fingerprint to `wipe`. Wipe removes
canonical content and
evidence while preserving the selected target and its configuration:

```console
uv run memory memories wipe default \
  --expected-nodes 12 \
  --expected-attributes 84 \
  --expected-active-relations 11 \
  --expected-evidence-objects 3 \
  --expected-fingerprint <sha256-from-status>
```

The fingerprint covers all canonical rows, including metrics, declarations,
embedding profiles, and inactive relations. `delete` accepts the same guard,
removes the named target's storage, and removes
its catalog entry. It rejects `default`; wipe default instead. A changed count
aborts with `memory_state_changed`, so inspect again rather than weakening the
guard. Both operations remove raw evidence and are intentionally destructive.
For PostgreSQL, delete removes Analytical Memory's tables but preserves the
schema container and any unrelated objects in it.

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
uv run memory retention release <sha256> --confirm <sha256> --reason "reviewed"
uv run memory retention plan retirement-plan.json
```

Release is CLI-only, keeps any independent `retain_until` block, and requires
the exact digest plus a non-empty audit reason. Review the immutable plan.
Retirement requires its exact `plan_id` as explicit confirmation:

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
