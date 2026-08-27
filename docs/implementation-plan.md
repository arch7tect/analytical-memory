# Analytical Memory Implementation Plan

## Status

Milestones 0 through 7 are implemented and complete the working v1. Milestones
0 through 4 remain the
description of the original foundation. Milestone 5, approved by ADR 0001, is a
clean-break contract with dynamic ontology, JSON Query IR, and a simpler
current-state model for imported and analytical data.

The M5 migration deliberately supersedes parts of the agent-facing M0-4 data
semantics without rewriting the historical milestone record. Existing tests
may be replaced when they assert superseded behavior; development databases are
reinitialized instead of migrated.

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

### Keep planning and writes consistent

Normalized-batch ingestion has one validation and planning path. Preview derives
and returns an immutable plan without persisting it in Milestone 0. Apply
re-derives the plan from the batch through the same planner, then revalidates
its schema fingerprint before committing it. The two commands must not contain
separate normalization or decision logic. This rule does not add a preview to
Milestone 5: JSONL import has no inspector and uses one atomic import operation.
Join materialization similarly validates, declares, resolves, and writes in one
transaction. Neither operation produces an apply token or authorization hash.

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
uv run mypy src tests
uv run python scripts/compile_schema.py --check
uv run python scripts/smoke.py
uv run python scripts/mcp_smoke.py
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
- an explicit embedding-provider port and one fixed commercial API adapter;
- canonical finite little-endian float32 BLOB storage;
- exact application-level vector search;
- exact structured prefilters and deterministic ordering;
- coverage, readiness, stale-input, and provider/model identity checks;
- vector rebuild commands;
- hybrid exact-filter plus semantic-ranking queries.

### Acceptance

- a profile or input change creates a new embedding record;
- a missing key, provider failure, or model mismatch degrades only semantic retrieval;
- index deletion and rebuild preserve canonical records;
- exact search returns deterministic fixture results;
- restricted inputs cannot reach a provider that exceeds their privacy policy;
- any later accelerator must match the application oracle before it can be
  selected.

### Approval gate

Approved v1 contract: OpenAI `text-embedding-3-small`, 1536 dimensions,
`unicode-nfc-lines-v1` preprocessing, cosine similarity, float responses, and
an API key loaded from a gitignored `.env`. The default provider privacy ceiling
is `restricted`, so all content except explicitly `forbidden` text is eligible.
Privacy classes on existing graph and search records are immutable in V1.

## Milestone 5: Dynamic ontology and JSON Query IR

Status: implemented.

### Deliver

- JSONL as the only general v1 import format, consumed from Python streams,
  CLI files or standard input, and server-local paths supplied through stdio
  MCP without materializing the full source in memory;
- optional NamespaceDeclaration and EntityDeclaration creation before import,
  with human-readable descriptions, a namespaced entity type, optional field
  type, required and nullable constraints, and entity- or field-level privacy,
  but no import identity definition;
- one current EntityDeclaration per entity type; replacement validates current
  rows and leaves the prior declaration active on failure;
- one atomic JSONL import contract that always carries entity type and typed
  ordered key as a transient current-attribute lookup, applies an active
  declaration when present, otherwise accepts every field name, and has no
  separate mapping or import preview;
- zero key matches create a Node with an application-generated UUID, one match
  updates it, and multiple matches or duplicate incoming key tuples reject the
  complete batch, without ExternalIdentity or natural-key storage;
- a canonical content-derived idempotency key with exact replay, plus
  disk-backed unique key-hash detection for bounded-memory duplicate rejection;
- deterministic two-pass ingestion that hashes and validates into temporary
  evidence, then writes bounded chunks inside one database transaction and
  returns actual counts, ontology delta, and the resulting fingerprint;
- one typed atomic JSONL-import method on the existing `MemoryStore` abstract
  interface; M5 adds no separate transaction interface;
- one current NodeAttribute row per `(node_id, attribute_name)`, overwritten
  transactionally for fields present in a later successful import and left
  unchanged for absent fields, with direct source, batch, evidence-fragment,
  and update-time provenance;
- one current Relation row per stable edge identity, with an `active` flag and
  direct provenance, plus transactional cascade deletion when either endpoint
  Node is deleted;
- analytically produced scalar or structured results written as ordinary
  NodeAttribute rows, graph results written as Relation rows, and aggregate
  results written as Metrics, all with direct AnalyticalRun provenance and no
  separate Finding or Assertion record;
- nullable ingestion-batch provenance on AnalyticalRun so analysis does not
  require a synthetic import;
- one ObservedField entry per `(entity_type, field_name)` with one declared or
  inferred effective JSON type and an `unresolved` state for all-null fields;
- a two-class privacy contract with `public` as default, optional `private`
  schema annotations, public-only shareable export and external processing, and
  pre-commit rejection of credentials and other prohibited stored content;
- in-place privacy tightening from public to private, rejected loosening, and a
  fixed public-only ceiling for external embedding providers;
- rollback compensation that removes temporary and exclusively newly installed
  evidence and preserves pre-existing deduplicated objects; crash-window orphan
  cleanup remains an evidence-audit concern;
- a derived Current Ontology Document with namespace, entity, attribute, and
  relation descriptions plus query fields, statistics, and provenance;
- independent contract and ontology fingerprints;
- a structural-contract version and fingerprint bump for the streaming JSONL
  import, ontology, Query IR, and join-materialization request schemas;
- read-only JSON Query IR v1 with fixed-length node and edge patterns, typed
  conjunctive predicates, provenance-aware projection, deterministic ordering,
  limit, offset, and count;
- one Query IR validator and canonical AST shared by Python, CLI, MCP, and both
  future relational backends;
- one atomic post-hoc join-materialization request between previously loaded
  objects, containing the join declaration and using exact typed equality;
- validation, declaration persistence, endpoint resolution, and Relation writes
  in one transaction, with no inspection, preview token, second apply call, or
  resolution hash;
- missing and null source keys, unmatched targets, existing active Relations,
  and existing inactive Relations returned as separate counts, while any
  ambiguous target rolls back the whole operation;
- persisted provenance-bearing join declarations that are never run
  automatically;
- rejection when a join name is reused with a different canonical definition;
- deterministic relation identity with join name as `logical_key`, a
  content-addressed declaration Source, and one synthetic ingestion batch and
  analytical run per materialization invocation;
- explicit relation deactivation and correction that preserve relation identity
  and prevent a join rerun from silently restoring an inactive edge;
- explicit Node deletion with cascading attributes, relations, search
  documents, and embedding projections while retaining shared provenance;
- MCP resources for the structural contract, current ontology, namespace
  ontology, Query IR, and runtime capabilities;
- MCP and Python API operations for namespace and entity declaration, streaming atomic JSONL
  import, ontology description, Query IR execution, one-step join
  materialization, relation deactivation, and Node deletion;
- matching CLI operations while preserving the existing saved-query,
  traversal, search, and explanation commands as convenience templates.

### Acceptance

- declaring a Session entity with field constraints changes the ontology
  fingerprint and makes its logical schema discoverable before any Session row
  exists, without declaring how imports identify a row;
- importing the same entity type and typed key without a prior declaration is
  valid, creates observed ontology only after success, accepts every field name,
  and infers one effective type per field;
- every selected key field is imported as an ordinary current attribute; the
  key selector is retained only in IngestionBatch provenance and is never used
  as persistent Node identity;
- an import key matching zero current Nodes creates one, matching one updates
  it, and matching more than one rejects the complete batch as ambiguous;
- importing a JSONL Session stream against that declaration makes automatically
  discovered allowed attributes queryable without a physical migration or
  explicit field mapping;
- fields absent from an active declaration are accepted, inherit entity-level
  privacy, and extend observed ontology;
- when a declaration exists, its required, type, and nullability constraints
  validate the entire stream before canonical writes;
- an undeclared entity or field defaults to public; a private entity declaration
  makes all its fields private, while a public declaration may mark individual
  fields private;
- private records never reach shareable export or an external embedding
  provider, and prohibited credentials fail before evidence or canonical commit;
- a declaration replacement that conflicts with a current row fails without
  changing the active declaration or ontology fingerprint;
- string and numeric key components remain distinct; missing, null, non-scalar,
  or duplicate composite keys reject the complete import with a line reference;
- a large synthetic JSONL source is read with bounded memory, written in chunks
  inside one transaction, and leaves no canonical partial batch on failure;
- a handled rollback removes evidence created exclusively by the failed import
  and never removes a pre-existing deduplicated object; a process crash may
  leave an immutable orphan that evidence audit reports;
- importing a separate SessionMessage dataset succeeds without declaring any
  relation and adds its own ontology description;
- re-importing an entity updates exactly one current row for each present
  non-key field, records the latest direct provenance, and preserves fields
  absent from that incoming object;
- all non-null values for one new field in its first batch must have one exact
  canonical JSON type; incompatible types reject the complete batch;
- a later value whose type differs from the field's effective type rejects the
  complete batch without changing current data or ontology;
- null does not establish or change field type, and an all-null field remains
  `unresolved` until a non-null value fixes its type;
- an AnalyticalRun can write `classification` as the same current
  NodeAttribute shape used by import, distinguished by run provenance rather
  than a Finding wrapper;
- deleting a Node deletes its attributes and every incoming and outgoing
  Relation but preserves evidence objects, ingestion batches, and analytical
  run records;
- no relation is inferred or applied from `session_id` or value overlap;
- one explicit materialization call can declare a join and connect stored
  SessionMessage objects to stored Session objects without re-declaring either
  endpoint;
- a missing endpoint is never created; null and unmatched keys are skipped and
  counted, while an ambiguous target rolls back the complete operation;
- materialization validates the current ontology and commits declaration and
  Relations in one transaction without a preview token or resolution hash;
- reusing a join name with a different canonical definition fails;
- a stored join does not execute during later imports; an explicit rerun adds
  only pairs never previously materialized by that join, does not restore
  inactive relations, and reports previously materialized active and inactive
  pairs as separate counts;
- the updated ontology exposes the declared relation, materialized edge count,
  state, and provenance;
- one JSON Query IR request filters Sessions and follows the declared incoming
  relation to project SessionMessage attributes;
- Query IR is read-only, unsupported operators fail validation, and
  every result reports deterministic ordering, truncation, current-record IDs,
  direct provenance, and the ontology fingerprint;
- ontology statistics may change without changing the ontology fingerprint;
  adding an entity, field, or active relation declaration, or resolving a
  field's effective type, must change it;
- ordinary predicates, import keys, and join keys resolve the same current
  NodeAttribute values; target lookups with zero or multiple matches are
  unmatched or ambiguous rather than selected;
- join materialization writes a deterministic `logical_key`, Source, ingestion
  batch, analytical run, current Relations, and direct evidence references and
  reruns idempotently for already materialized pairs;
- after a source join-key value changes, rerunning a join may add a new Relation
  without removing the old one; removing the obsolete Relation is an explicit
  V1 correction;
- a correction can deactivate a current relation without deleting its identity
  or evidence, and a later rerun of the same join preserves that correction;
- no supported, contested, contradicted, or unasserted state is derived in M5;
  competing-claim semantics remain deferred;
- the complete JSONL-to-ontology-to-query flow runs through a real stdio MCP
  client using a streamed synthetic fixture rather than a JSON string argument.

### Approval gate

ADR 0001 was accepted on 2026-08-26. M0-4 local databases are development
baselines and are reinitialized for the new storage contract rather than
migrated through a competing-candidate policy.

### Explicitly deferred

- CSV and every other non-JSONL import reader and public import contract;
- full GQL, SQL/PGQ, or openCypher textual parsing and conformance;
- implicit type coercion, normalization, and fuzzy key matching;
- automatic relation inference or automatic join execution;
- JSONL and join inspection operations;
- ontology rename, entity merge, and materialized ontology revision history;
- point-in-time reconstruction and automatic replay of prior imported field or
  relation state from retained evidence;
- complete per-field and per-edge operational history;
- competing analytical claims, support and contradiction states, and
  supersession history;
- variable-length path expansion, grouping, cursor pagination, and text or
  semantic ranking inside Query IR;
- automated deletion of evidence objects orphaned by a process crash;
- arbitrary expressions, subqueries, unbounded traversal, and general graph
  mutation.

## Milestone 5.1: Agent-executable contract

Status: implemented.

### Objective

An MCP client with no CLI access and no source-code knowledge can discover the
complete contract and ontology, import data, construct a valid query, obtain
canonical Node IDs, write analytical results, traverse and correct relations,
and delete a Node.

### Deliver

- replacement of the existing `memory://schema/query-ir/current` payload with a
  complete machine-readable JSON Schema and semantic contract generated from
  the same constants and limits used by Query IR validation;
- `bindings` on every non-count Query IR row, mapping every pattern alias to its
  canonical Node ID without adding node or edge projections to Query IR v1;
- typed MCP boundary models for Query IR requests and results, ontology
  documents, entity declaration fields, JSONL key selectors, and join
  endpoints, while storage-adapter dictionaries remain internal;
- structured stable error codes, details, retry guidance, and refresh-resource
  hints where applicable;
- transport-aware capabilities, including exact Query IR pattern limits,
  defaults, a stable error-code registry, and a capabilities-document version
  bump;
- typed saved-query parameters, defaults, and result fields;
- agent-facing reference documentation with complete `match`, `where`,
  `return`, `order_by`, `count`, null, missing, ordering, pagination, result,
  and provenance semantics;
- packaged schema and migration resources resolved through `importlib.resources`
  so the installed wheel does not depend on a repository checkout;
- schema compilation and fingerprint bump before recording SQLite migration
  006 in the migration manifest and ledger;
- SQLite migration 006 adding `sort_text_folded`, `sort_text_exact`, and
  IEEE-754 `sort_number` projections, followed by an idempotent initialization
  backfill before the store becomes usable; every attribute writer maintains
  the projections, preserving missing-last ordering and removing the
  process-local `canonical_text` collation from the query path;
- a structural contract and fingerprint bump covering the agent-visible result,
  discovery, and storage changes.

### Acceptance

- a real stdio MCP client completes declare, import, query, analytical write,
  join, traversal, relation correction, and Node deletion using IDs learned
  only through MCP resources and tool results;
- the Query IR contract validates every shipped example and exposes required
  fields, variants, defaults, limits, semantics, result schema, and examples;
- changing an operator or Query IR limit without regenerating the contract fails
  a deterministic golden test;
- every expected application error has a unique stable code and every MCP error
  returns the structured error envelope;
- every capability operation declares its supported interfaces and every `mcp`
  declaration corresponds to an actual MCP tool;
- strict boundary models leave `Any` only for intentionally open JSON values;
- a wheel installed into an empty environment outside the source tree can run
  `memory init`, schema discovery, and the synthetic quickstart.

### Explicitly deferred

- edge aliases and direct relation projection in Query IR;
- textual GQL, openCypher, or SQL parsing;
- typing every internal `MemoryStore` dictionary;
- new logical operators, grouping, variable-length paths, and mutation clauses.

## Milestone 6: PostgreSQL conformance and transfer

Status: implemented.

### Deliver

- PostgreSQL 17 migrations and a `MemoryStore` implementation built from one
  shared `SqlMemoryStore` plus small explicit SQLite and PostgreSQL dialect
  classes; no ORM, query builder, or second copy of store behavior;
- `psycopg` as an optional PostgreSQL dependency and backend selection through
  configuration without changing application, CLI, or MCP shapes;
- an explicit refactor of the M5 application fixture and behavioral tests onto
  the backend-parameterized store seam, followed by PostgreSQL registration in
  that same suite;
- canonical SQLite export and PostgreSQL import;
- transfer verification and rollback workflow;
- PostgreSQL full-text and exact-vector integration behind existing ports.
- PostgreSQL conformance in CI through a PostgreSQL 17 service container and a
  local Docker workflow using `ANALYTICAL_MEMORY_TEST_POSTGRES_URL`; local tests
  skip with a clear reason only when that variable is absent.

### Acceptance

- SQLite and PostgreSQL preserve logical IDs, hashes, current imported and
  analytical values, active relation state, metrics, deterministic Query IR
  results, traversal results, and metric selection for the same fixtures;
- both migration sets declare the same logical target fingerprint;
- transfer rebuilds derived indexes rather than copying backend projections;
- a failed or cancelled import leaves the SQLite source unchanged and the
  PostgreSQL target unselected;
- switching backend configuration changes capabilities, not API shapes.
- full-text conformance requires the same matched document IDs, coverage, and
  deterministic per-backend ordering; backend-specific relevance scores are not
  required to be numerically identical.

## Milestone 7: Operational hardening and release

Status: implemented.

### Deliver

- crash-recovery and corruption tests;
- backup and restore drills;
- bounded performance and storage measurements;
- compatibility tests across supported schema versions;
- release packaging, versioning, changelog, and contribution guidance;
- operator documentation for integrity, snapshot, transfer, and retention
  workflows.

### Acceptance

1. A wheel and source distribution install into an empty environment outside
   the source tree and run the documented quickstart successfully.
2. Forced interruption during a chunked import leaves no partial canonical
   batch; integrity remains clean and evidence audit reports any orphan without
   deleting it.
3. Snapshot create, verify, and import reproduce the same ordered Query IR
   result and ontology fingerprint in a fresh store.
4. Deliberate evidence-byte corruption is reported for the object and affected
   fragments without changing canonical rows.
5. A bounded synthetic import records duration, peak RSS, database size, and
   evidence size in a committed reproducible baseline; it does not introduce an
   optimization target without a measured failure.
6. Opening each supported schema version either migrates it forward or fails
   with a named compatibility error; it never operates silently on an unknown
   version.
7. Built artifacts contain no `.env`, credential, private fixture, or
   developer-specific absolute path.
8. The release includes a version bump, changelog, contribution guide, and
   operator documentation for integrity, snapshots, transfer, and retention.

No package registry publication is required for v1 acceptance; local wheel and
source-distribution verification is authoritative.

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

Before PostgreSQL implementation, M5 store-facing tests are refactored to use a
backend-parameterized `MemoryStore` fixture. SQLite is initially the only
registered backend; Milestone 6 registers PostgreSQL against the same test
bodies rather than creating a second behavioral suite. CI provides PostgreSQL
17 and fails if the conformance suite is skipped there; local runs skip it with
a clear reason when no test URL is configured.

## Scope controls

The following work does not enter a milestone unless its acceptance criteria
require it:

- generalized plugin systems;
- backend-specific query languages or unbounded Query IR extensions;
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

The approved working-v1 plan is complete. New product behavior belongs in a
new decision record and later milestone rather than expanding these completed
acceptance gates.
