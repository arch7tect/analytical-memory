# Analytical Memory Implementation Plan

## Status

Proposed delivery plan for v1. The plan optimizes for the earliest useful
working implementation while preserving the invariants in
[the system design](design.md).

## Delivery objective

The first milestone must prove one complete path through the system:

```text
initialize -> preview -> ingest -> query -> explain
```

It must persist canonical records in SQLite, copy one evidence object into the
local evidence store, and return an explanation that resolves a fact through an
assertion and binding to the stored object. Everything not required for this
path is deferred.

This walking skeleton is the foundation for later graph, full-text, semantic,
snapshot, MCP, and PostgreSQL work. Each milestone extends a running system
rather than building an isolated subsystem.

## Definition of a working first milestone

A clean clone is working when a contributor can:

1. install the project with `uv`;
1. initialize a local SQLite database and evidence root;
1. preview and apply a synthetic normalized batch;
1. query the current facts written by that batch;
1. explain one result down to a hash-verified whole-object evidence fragment;
1. repeat ingestion without creating duplicates;
1. run the complete test suite with one documented command.

The quickstart must use only synthetic repository fixtures and temporary local
state. It must not require PostgreSQL, a model download, a native extension, a
network service, or private data.

## Delivery rules

### Prefer vertical slices

Every milestone ends with a user-visible command or interface. A layer that is
not exercised by an end-to-end path is implemented only when the next slice
requires it.

### Keep the first path narrow

The first milestone supports only the record types, locator kind, saved query,
and explanation shape required by the quickstart. The checked-in schema
document covers only the metadata the first path uses; the compiler arrives in
Milestone 2.

### Preserve replacement boundaries from the start

The domain and application layers depend on `MemoryStore` and `EvidenceStore`
ports. SQLite and the local filesystem are the first adapters. PostgreSQL is
implemented later, but application-generated IDs, canonical values, query
plans, ordering, and migration target fingerprints are backend-neutral from the
first commit.

### Delay optional acceleration

Exact application vector search is implemented before any accelerator.
Approximate search, native extensions, remote providers, and network transports
cannot block a v1 milestone.

### Keep changes demonstrable

Each milestone includes a quickstart update, focused tests, and one scripted
smoke path. A milestone is incomplete if its components pass unit tests but the
documented path does not run from a clean clone.

### Keep preview and apply identical

Ingestion has one validation and planning path. Preview derives and returns an
immutable plan without persisting it in Milestone 0. Apply re-derives the plan
from the batch through the same planner, then revalidates its schema fingerprint
before committing it. The two commands must not contain separate normalization
or decision logic.

## Planned development contract

The foundation establishes:

- Python `>=3.12`;
- `pyproject.toml` as the package, dependency, and tool configuration;
- `uv.lock` committed to the repository;
- a `src/analytical_memory` package;
- pytest, Ruff, and mypy in development dependency groups;
- one console entry point named `memory`;
- continuous integration running the same commands used locally.

The target local workflow is:

```text
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

No framework is selected until a milestone requires it. Standard-library
components are preferred for the first path when they keep the code clear and
testable.

## Milestone 0: Working SQLite vertical slice

### Deliver

- `pyproject.toml`, `uv.lock`, and the smallest used portions of
  `src/analytical_memory`;
- test, lint, format, and type-check configuration;
- continuous integration;
- a temporary-state convention under a gitignored `.local/` directory;
- one console entry point named `memory`;
- a checked-in minimal Current Schema Document and deterministic fingerprint;
- domain records required for Source, AnalyticalRun, Node, NodeAttribute,
  Assertion, EvidenceObject, EvidenceFragment, EvidenceBinding, and
  IngestionBatch;
- one AnalyticalRun per batch, with identity derived from the batch idempotency
  key;
- stable keys, append-only supersession, and all four current fact states for
  node-attribute facts;
- assertion valid time, recorded time, and method identity, with valid time and
  method identity as parts of the stable assertion key, while historical
  queries remain deferred;
- a privacy class field on canonical records with one bootstrap default;
- the `MemoryStore` and `EvidenceStore` abstract base classes;
- one hand-written SQLite migration tracked by `PRAGMA user_version` and a
  transactional adapter;
- a local content-addressed filesystem adapter;
- whole-object fragments only;
- normalized JSON batch validation;
- one shared ingestion planner used by preview and transactional apply;
- schema-fingerprint validation on ingest apply;
- declared canonical JSON normalization, collation, case handling, null
  ordering, and saved-query result ordering implemented outside backend
  defaults;
- one saved current-facts query;
- provenance explanation for facts returned by that query;
- one synthetic quickstart batch and evidence object.

### Quickstart path

```text
uv run memory init
uv run memory ingest preview examples/quickstart/batch.json
uv run memory ingest apply examples/quickstart/batch.json
uv run memory query current-facts
uv run memory explain <record-id>
```

Commands use `.local/` defaults and accept explicit database and evidence-root
overrides. Ingestion output prints stable IDs needed by the query and explain
steps.

### Acceptance

- `uv sync --all-groups` and every planned development command pass from a
  clean clone;
- `uv run memory --help` exits successfully;
- the package imports without adapter side effects;
- adapters inherit from explicit abstract interfaces; structural `Protocol`
  interfaces are not used;
- the quickstart runs from a clean clone without external services;
- a second apply of the same batch is recognized as a replay, returns the
  original batch result and canonical IDs, and writes no rows;
- a validation failure occurs before `EvidenceStore.put` and writes neither
  database rows nor evidence-store objects;
- a batch prepared against a different fingerprint is rejected with the
  current fingerprint and a refresh pointer;
- the query derives `supported`, `contested`, `contradicted`, and `unasserted`
  states without selecting an automatic winner;
- the saved query matches a golden ordered result independent of backend
  collation and null-order defaults;
- explanation reaches a hash-verified whole-object fragment;
- missing evidence produces an explicit unavailable state derived at read time
  from `EvidenceStore.stat(digest)` without persisted EvidenceLocation rows;
- SQLite foreign-key and integrity checks pass;
- a failure after evidence preparation rolls back database state and leaves any
  unreferenced immutable object addressable by digest through
  `EvidenceStore.stat` rather than deleting it implicitly;
- store-facing tests run through a backend-parameterized `MemoryStore` fixture
  with SQLite as the only registered backend;
- repository documentation contains no machine-specific paths.

### Explicitly deferred

- metrics;
- relation facts and graph traversal;
- multi-kind fragments;
- full-text and semantic retrieval;
- snapshots and retention execution;
- persisted evidence locations and verification history;
- the metadata compiler and general migration runner;
- MCP;
- PostgreSQL.

## Milestone 1: MCP access to the walking skeleton

### Deliver

- a Runtime Capabilities Document for the implemented subset;
- `memory status` and `memory validate` over the current store and capabilities;
- local stdio MCP discovery resources;
- typed MCP tools for ingestion preview, ingestion apply, the current-facts
  query, and provenance explanation;
- interface contract tests shared by CLI and MCP.

### Acceptance

- an MCP client discovers the implemented types, query, limits, and
  capabilities without filesystem access;
- the quickstart batch can be previewed, applied, queried, and explained through
  MCP with the same result shapes as the CLI;
- MCP writes enforce the same schema fingerprint as CLI writes;
- evidence reads remain separate, bounded operations;
- no tool exposes arbitrary write SQL or schema migration operations.

## Milestone 2: Useful local querying

### Deliver

- complete single- and multi-valued slot semantics;
- Relation records, relation-targeted assertions, and relation traversal;
- immutable metrics and deterministic current-metric selection;
- saved relational queries and bounded relation traversal;
- FTS over declared SearchDocuments;
- complete provenance explanation and coverage reporting;
- the metadata compiler and generated Current Schema Document;
- an ordered migration runner and SchemaMigration ledger beginning with the
  second SQLite migration, including a backfilled initial-migration row derived
  from `PRAGMA user_version`, the original migration checksum, and its logical
  target fingerprint;
- corresponding CLI and MCP query tools.

### Acceptance

- CLI and MCP return the same typed query and explanation shapes;
- discovery reports the expanded saved queries and capabilities;
- traversal follows relation edges only, enforces depth and result limits, and
  defaults to supported and contested states;
- FTS results resolve to canonical targets and provenance;
- no interface exposes arbitrary write SQL or schema migration operations.

## Milestone 3: Evidence portability and lifecycle

### Deliver

- acquisition, location, derivation, and verification records;
- deterministic structured, byte, line, time, and sample fragment locators;
- monotonic privacy propagation;
- evidence audit and bounded read operations;
- retention report, immutable plan, confirmation, and retirement;
- private snapshot create, verify, and import;
- separate sanitized export.

### Acceptance

- fragment hashes reproduce from canonical locator parameters;
- persisted EvidenceLocation and EvidenceVerification history agrees with
  current provider state while preserving earlier checks;
- ambiguous inputs are materialized before fragment addressing;
- later stricter acquisitions raise effective privacy without rewriting content
  identity;
- retirement cannot remove an object with an active retention requirement;
- snapshot import restores canonical query results, bindings, availability,
  and tombstones without original source paths;
- a failed verification or import leaves existing canonical state unchanged.

## Milestone 4: Exact semantic retrieval

### Deliver

- property-scoped EmbeddingProfile and EmbeddingRecord support;
- a local embedding-provider port and one pinned local provider;
- canonical finite little-endian float32 BLOB storage;
- exact application-level vector search;
- exact structured prefilters and deterministic ordering;
- coverage, readiness, stale-input, and model-artifact checks;
- vector rebuild commands;
- hybrid exact-filter plus semantic-ranking queries.

### Acceptance

- a profile or input change creates a new embedding record;
- a missing or mismatched model artifact degrades only semantic retrieval;
- index deletion and rebuild preserve canonical records;
- exact search returns deterministic fixture results;
- restricted inputs cannot reach a provider that exceeds their privacy policy;
- any later accelerator must match the application oracle before it can be
  selected.

### Approval gate

Select and pin the first model artifact, preprocessing contract, dimensions,
license, and distribution method before implementing the provider adapter.

## Milestone 5: PostgreSQL conformance and transfer

### Deliver

- PostgreSQL migrations and `MemoryStore` adapter;
- the shared backend conformance suite;
- canonical SQLite export and PostgreSQL import;
- transfer verification and rollback workflow;
- PostgreSQL full-text and exact-vector integration behind existing ports.

### Acceptance

- SQLite and PostgreSQL preserve logical IDs, hashes, fact states, metrics, and
  deterministic ordered query results for the same fixtures;
- both migration sets declare the same logical target fingerprint;
- transfer rebuilds derived indexes rather than copying backend projections;
- a failed or cancelled import leaves the SQLite source unchanged and the
  PostgreSQL target unselected;
- switching backend configuration changes capabilities, not API shapes.

## Milestone 6: Operational hardening and release

### Deliver

- crash-recovery and corruption tests;
- backup and restore drills;
- bounded performance and storage measurements;
- compatibility tests across supported schema versions;
- release packaging, versioning, changelog, and contribution guidance;
- operator documentation for integrity, snapshot, transfer, and retention
  workflows.

### Acceptance

- recovery and restore are executed in automated tests;
- limits and failure states are reported through capabilities and status;
- destructive operations remain exact, planned, and explicit;
- a clean published package installs and runs the documented quickstart;
- release artifacts contain no private data or machine-specific paths.

## Cross-cutting verification

Tests are added with the milestone that introduces the behavior:

- unit tests for canonicalization, stable keys, state derivation, privacy, and
  supersession;
- golden tests for schema documents, fingerprints, manifests, and fragments;
- transaction and idempotency property tests;
- interface contract tests shared by Python, CLI, and MCP;
- backend contract tests shared by SQLite and PostgreSQL;
- differential tests for transfer and exact vector engines;
- negative tests for stale writes, unsafe export, unbounded traversal,
  unavailable evidence, and forbidden operations;
- scripted clean-clone quickstart tests using synthetic fixtures only.

Store-facing tests use a backend-parameterized `MemoryStore` fixture from
Milestone 0. SQLite is the only registered backend until Milestone 5, which
registers PostgreSQL against the existing test bodies rather than creating a
second suite.

## Scope controls

The following work does not enter a milestone unless its acceptance criteria
require it:

- generalized plugin systems;
- arbitrary query languages;
- network APIs;
- multi-user authorization;
- remote evidence providers;
- approximate vector indexes;
- automatic background retention;
- separate graph databases;
- performance optimization without a measured failing threshold.

New ideas are recorded under `docs/decisions/` or a later milestone rather than
expanding the active slice.

## Immediate next action

Implement Milestone 0 as one end-to-end delivery. Do not stop at an empty
package scaffold: the milestone is complete only when the clean-clone
quickstart reaches a hash-verified explanation.
