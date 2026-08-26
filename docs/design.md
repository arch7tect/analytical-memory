# Analytical Memory Design

## Status

Proposed v1 architecture. This document defines logical behavior,
implementation boundaries, and repository organization.

## Purpose

Analytical Memory stores durable conclusions together with the provenance
needed to inspect, challenge, reproduce, and revise them. It supports four
complementary query modes:

1. exact relational queries and aggregates;
1. bounded graph traversal;
1. full-text and semantic retrieval;
1. provenance explanation for every returned result.

The canonical store is relational. Graph behavior comes from explicit nodes
and directed relations. Semantic indexes are rebuildable projections and never
establish truth. Raw evidence bytes live in a separate content-addressed store.

## Goals

- Preserve structured findings and their revision history.
- Bind every assertion and computed result to a source and analytical run.
- Support relational, graph, full-text, vector, and hybrid queries in v1.
- Keep the logical contract independent of the selected relational backend.
- Derive the active schema from versioned metadata.
- Expose schema and runtime capabilities to automated clients.
- Make ingestion transactional, idempotent, and safe to retry.
- Keep raw evidence separate from canonical relational records.
- Move canonical memory and available evidence through verified snapshots.
- Rebuild derived indexes without changing canonical knowledge.

## Non-goals

- Treating semantic similarity as proof.
- Automatically resolving contradictory assertions.
- Storing raw evidence as relational database blobs.
- Exposing arbitrary write SQL to automated clients.
- Generating and applying unreviewed schema migrations.
- Providing a networked multi-user service in v1.
- Providing automatic remote replication or background evidence deletion in
  v1.
- Standardizing every possible ontology or evidence format.

## Design principles

### Evidence before conclusion

A conclusion is useful only when its source, method, time scope, and evidence
availability are known. Evidence may become unavailable without erasing the
recorded conclusion; the loss is surfaced as degraded provenance.

### Relational truth, graph interpretation

Nodes, addressable attributes, directed relations, assertions, and constraints
are stored in ordinary relational tables. Graph traversal is a bounded query
over relation rows.

### Facts and assertions are different

A node attribute or relation states fact content. An assertion records that a
source or analytical run supports or contradicts that fact. Evidence binds to
the assertion rather than directly to every fact representation.

### History is append-only

New information supersedes or retracts an earlier assertion instead of
silently overwriting it. Current and historical views are derived from the same
record history.

### Derived indexes are disposable

Full-text and vector indexes are projections over exact source records. Losing
an index may reduce performance or coverage, but cannot destroy canonical
knowledge.

### Schema metadata is authoritative

Versioned metadata defines logical types, validation, saved queries, privacy
rules, and exposed capabilities. Database introspection verifies physical
conformance; it does not invent the logical schema.

### Privacy propagates monotonically

Derived records inherit the strictest privacy class of their inputs. Lowering
a class requires a separately materialized sanitizer output with a new content
identity.

### Repeated work is idempotent

Stable logical keys prevent retries from duplicating canonical or derived
records. A new analytical run may add new assertions about existing facts
without changing earlier history.

## Conceptual architecture

```text
                       versioned metadata
                               |
                    schema compiler and registry
                               |
                +--------------+---------------+
                |                              |
       logical schema document        runtime capabilities
                |                              |
                +--------------+---------------+
                               |
                         application core
                               |
        +----------------------+----------------------+
        |                      |                      |
   MemoryStore             EvidenceStore        retrieval ports
        |                      |                      |
 SQLite / PostgreSQL    local immutable files    FTS / exact vectors
        |                      |                      |
        +----------------------+----------------------+
                               |
                    Python API, CLI, stdio MCP
```

The application core depends on ports rather than database connections,
filesystem paths, model libraries, or transport details. Adapters implement
those ports and report their capabilities explicitly.

## Versioned contracts

The system versions three independent dimensions:

- **storage version**: physical tables, indexes, constraints, and migrations;
- **ontology version**: allowed node, attribute, relation, assertion, and
  metric definitions;
- **embedding profile version**: model identity, preprocessing, dimensions,
  and similarity function.

Changing an embedding profile does not migrate facts. An additive ontology
change does not require a physical migration unless it changes the stable core
record shapes.

### Current Schema Document

The metadata compiler produces a backend-neutral canonical JSON document with:

- contract and ontology versions;
- schema fingerprint and compatibility range;
- privacy classes and propagation rules;
- node, attribute, relation, assertion, and metric definitions;
- normalized ingestion batch schemas;
- evidence object and fragment locator schemas;
- semantic index policies;
- saved query parameters and result schemas.

### Runtime Capabilities Document

Runtime capabilities are separate from the logical schema and include:

- selected storage backend and migration version;
- enabled full-text and vector engines;
- exact or approximate search mode;
- embedding readiness and indexed-versus-eligible coverage;
- evidence-store provider and limits;
- enabled transports and bounded operation limits.

Canonical UTF-8 JSON serialization uses sorted object keys, deterministic
number encoding, duplicate-key rejection, and no non-finite numbers. The
logical fingerprint excludes timestamps, absolute paths, credentials, and
backend connection values. The runtime fingerprint covers the logical
fingerprint plus selected adapter capabilities.

Every write carries the schema fingerprint against which it was prepared. A
stale write fails with the current fingerprint and a schema refresh pointer.

## Canonical data model

```text
Node -- NodeAttribute --> typed value
  |           |
  |           +-- Assertion -- EvidenceBinding --> EvidenceFragment
  |
  +-- Relation --> Node
          |
          +-- Assertion -- EvidenceBinding --> EvidenceFragment

text NodeAttribute or EvidenceFragment
  --> SearchDocument --> EmbeddingRecord --> vector projection
```

### Source

A logical provenance container. It records a stable ID, kind, safe locator,
optional content hash, privacy class, verification status, and availability.
It does not imply that source bytes are stored in the relational database.

### AnalyticalRun

A bounded analytical execution. It records a stable ID and idempotency key,
scope, valid-time window, method versions, schema and ontology versions,
lifecycle state, coverage, limitations, and primary source. Every generated
assertion and metric belongs to one run.

### Node

A stable graph object with:

- application-generated UUID;
- namespaced type;
- stable natural key within the namespace and type;
- optional display label;
- privacy class;
- recorded timestamps.

Only identity and operational fields live directly on a node. Domain values
use addressable attribute rows.

### NodeAttribute

A typed scalar or bounded structured value attached to one node. It records an
attribute name, ontology cardinality (`single` or `multi`), canonical value,
value hash, and privacy class.

The row states a proposition but does not claim the proposition is true.

### Relation

A directed fact connecting two nodes. It records source node, namespaced type,
target node, non-null logical key, and privacy class. Confidence and provenance
belong to assertions.

V1 relations do not accept arbitrary domain properties. A relationship that
requires independently queryable properties is represented as a node connected
by ordinary relations.

### Assertion

A provenance-bearing claim about exactly one relation or node attribute. It
records:

- target kind and target ID;
- stance: `supports` or `contradicts`;
- basis: `observed`, `computed`, `inferred`, or `declared`;
- confidence and review status;
- valid time and recorded time;
- source and analytical run;
- optional superseded assertion;
- lifecycle: `active`, `superseded`, or `retracted`.

Supersession may cross fact rows. This permits a new assertion to replace an
earlier value in a single-valued attribute slot while preserving both facts and
their provenance.

### Current fact semantics

Fact state is derived from active assertions:

- `supported`: one or more supports and no contradictions;
- `contested`: one or more supports and one or more contradictions;
- `contradicted`: no supports and one or more contradictions;
- `unasserted`: no active assertions.

Contested facts are surfaced and never resolved automatically. A candidate in
a single-valued attribute slot is any value whose fact state is `supported` or
`contested`:

- zero candidates: `missing`;
- one supported candidate: current value;
- one contested candidate: contested slot with no trusted current value;
- two or more candidates: slot conflict.

A multi-valued slot returns every candidate with its individual fact state.

### Metric

An immutable computed result scoped to one analytical run. It records a
definition version, value, unit, numerator, denominator, canonical dimensions,
method version, and coverage notes.

Metrics are not general-purpose fact carriers. A correction invalidates a run
or writes a new run and result. A saved current-metric query selects the latest
complete, non-invalidated run for an exact scope, definition, and dimension set
using a declared deterministic ordering.

### Evidence records

- `EvidenceObject`: immutable content identity, stored-byte SHA-256, size,
  media type, and safe immutable metadata.
- `EvidenceAcquisition`: one use of an object with source, analytical run,
  privacy, retention, method, and review metadata.
- `EvidenceLocation`: provider, configured root ID, relative object key,
  verification time, and availability.
- `EvidenceFragment`: deterministic selection from one object with canonical
  locator parameters, extractor version, byte size, and extracted-byte hash.
- `EvidenceBinding`: exactly one assertion or metric target, one fragment,
  binding role, confidence, and review state.
- `EvidenceVerification`: append-only audit of object, fragment, snapshot, or
  import verification.

Content identity is independent of acquisition policy. Effective object
privacy is the strictest class across acquisitions, and retirement is blocked
while any acquisition requires retention.

### SearchDocument

An exact text input derived from one text-valued attribute or evidence
fragment. It records the target, chunk index, privacy class, content hash,
extraction or chunking version, and lifecycle state.

### EmbeddingProfile

A property-scoped semantic index policy. It records target eligibility, model
resolver key, model identity and artifact digest, dimensions, preprocessing,
similarity function, privacy ceiling, generation mode, readiness, and coverage.
Model artifacts are runtime dependencies and are not canonical snapshot
members.

### EmbeddingRecord

One derived vector for one SearchDocument under one EmbeddingProfile. Its
logical identity is the search document, profile, and input content hash. A
profile or input change creates a new record rather than overwriting the old
representation.

### Operational records

- `OntologyType`: versioned logical type definition and validation rules.
- `IngestionBatch`: idempotency key, source and extractor versions, preview and
  apply results, counts, timestamps, and failure summary.
- `SchemaMigration`: backend profile, migration version, checksum, logical
  target fingerprint, applied time, and tool version.

### Stable uniqueness

Both relational backends enforce the same logical keys:

- Node: `(namespace, type, natural_key)`;
- NodeAttribute: `(node_id, attribute_name, value_hash)`;
- Relation: `(source_node_id, type, target_node_id, logical_key)`;
- Assertion: stable target, stance, basis, source, run, valid interval, and
  method identity;
- Metric: `(run_id, definition_version, canonical_dimensions_hash)`;
- EvidenceFragment: object, locator, and extractor identity;
- EvidenceBinding: target, fragment, and role;
- SearchDocument: target, chunk index, and extraction version;
- EmbeddingRecord: document, profile, and input content hash;
- IngestionBatch: idempotency key.

## Time and revision semantics

Assertions use two time axes:

- **valid time**: when a claim applies;
- **recorded time**: when the memory learned or revised the claim.

Current queries evaluate the latest recorded lifecycle state while applying
valid-time filters. Historical queries reconstruct the state visible at a
specified recorded time.

## Evidence store

### Provider contract

The application depends on a small provider-neutral port:

```text
put(stream, metadata) -> EvidenceObject
stat(digest) -> EvidenceStatus
open(digest) -> bounded byte stream
verify(digest) -> VerificationResult
iter_missing(digests) -> digest list
export(digests, destination) -> SnapshotManifest
import_snapshot(source) -> ImportResult
```

V1 provides a local filesystem adapter. `put` hashes a stream into a temporary
file and atomically installs it at a deterministic content-addressed path. It
copies source bytes and never mutates the source.

Absolute machine paths are runtime configuration and never canonical metadata.
An evidence URI contains an algorithm, digest, and optional fragment identity;
the adapter resolves it beneath a configured root.

### Deterministic fragments

A fragment may address a whole object, canonical JSON value, record key, byte
range, line range, time interval, or sample interval. Every locator records
extractor identity and version, canonical parameters, extracted byte size, and
extracted-byte SHA-256.

Time-based records require a canonical timestamp field and parser. Sample
intervals require canonical uncompressed encoding metadata, including rate,
channel layout, sample format, bit width, byte order, and interleaving. Inputs
that cannot reproduce a stable selection are first materialized as a derived
object with a new digest.

### Evidence state

Availability, verification, and retention are orthogonal:

- availability: `present` or `missing`;
- verification: `unverified`, `verified`, or `corrupt`;
- retention: `active`, `expired`, or `retired`.

Retirement records a tombstone and sets availability to `missing`. A missing or
corrupt object never silently validates a bound assertion.

### Retention workflow

V1 has no background cleanup. Retention uses report, immutable plan, explicit
confirmation, and revalidation immediately before the exact planned copies are
retired. Original source data is outside this operation and remains untouched.

### Portable snapshot

A private restore snapshot contains:

- canonical records in dependency order;
- compiled logical schema and fingerprint;
- every referenced evidence identity;
- bytes for objects whose availability is `present`;
- tombstones for retired or known-missing objects;
- evidence bindings, row counts, byte counts, and member hashes.

Snapshot creation fails if a present object is absent, corrupt, or unverified.
Import verifies every present member before applying canonical records or
installing evidence bytes.

Full-text and vector projections are excluded. Imported embedding profiles are
`pending` with zero indexed coverage until a matching model artifact is
resolved and vectors are rebuilt. Canonical queries and provenance remain
available without semantic retrieval.

A privacy-filtered export is a separate sanitized interchange artifact and is
not accepted by the restore importer.

## Query model

### Relational queries

Typed filters, joins, aggregates, coverage checks, and metric calculations use
backend-neutral query plans compiled by each relational adapter.

### Graph queries

Traversal follows relation edges only and requires a start node, allowed
relation types, direction, maximum depth, result limit, and state filter. The
default expands `supported` and `contested` relations. Other states require an
explicit opt-in. Attribute filtering happens before traversal; assertion
history is returned by provenance explanation.

### Full-text and semantic queries

Search targets one advertised text property or evidence-fragment class rather
than an undifferentiated node. A semantic result is a candidate, not a fact.
Every result joins back to its SearchDocument, canonical target, fact state,
source, and evidence availability.

### Hybrid queries

Exact privacy, type, scope, time, and assertion-state filters run before
similarity ranking. Results contain coverage and readiness so incomplete
indexes cannot appear complete.

### Explanation

Every returned canonical or derived record supports an explanation containing:

- canonical IDs and logical keys;
- current and superseded assertion states;
- analytical run and method versions;
- source identity;
- evidence object and fragment hashes;
- evidence verification and availability;
- retrieval mode and semantic-index coverage;
- privacy and other declared limitations.

## Vector retrieval contract

V1 always provides an exact application-level search over finite
little-endian float32 vectors stored as canonical BLOBs. The application owns
dimension checks, normalization, similarity, filtering, and deterministic
ordering.

A backend accelerator is optional and disposable. It supplies candidates only.
The adapter over-fetches the complete boundary-score class, re-scores candidates
from canonical BLOBs with the application distance function, and orders by
exact canonical score followed by document ID. If complete over-fetch cannot be
proven, the adapter falls back to the application implementation.

Approximate search is outside v1. Exact search remains the conformance oracle
for any future optimization.

An embedding profile reports `pending`, `building`, `ready`, `degraded`, or
`failed`, plus indexed and eligible counts. A missing or mismatched model
artifact creates no new vectors and never affects canonical query results.

## Privacy and security

The logical contract defines ordered privacy classes such as `public`,
`private`, `restricted`, and `forbidden`. Deployments may rename or extend the
classes while preserving a total strictness order.

The effective class of a derived record is the maximum of its declared class
and every input source, acquisition, object, fragment, and target. Sanitization
creates a distinct derived object, records the derivation, and assigns a new
digest.

Automation is not a trust boundary. Structured write tools validate the same
schemas and permissions as the Python API. Evidence reads are bounded and
explicit. Ordinary search and traversal do not return raw evidence bytes.

V1 trusts the local process identity and filesystem permissions. Hashes detect
corruption but do not authenticate content against a malicious writer. A
network transport requires a separate authentication and authorization design.

## Backend portability

The application depends on a `MemoryStore` port for transactions, canonical
batch application, queries, traversal, explanation, migrations, export,
import, and derived-index lifecycle.

Portability rules apply from the first migration:

- generate UUIDs in the application;
- store canonical UTC timestamps;
- define JSON normalization, collation, case handling, null ordering, and
  result ordering explicitly;
- keep backend SQL inside adapters;
- rebuild backend-specific projections from canonical records;
- verify logical behavior with one shared conformance suite.

SQLite is the default embedded backend. PostgreSQL is a conforming replacement
behind the same logical contract. Backend selection changes runtime
capabilities, not schema fingerprints, IDs, request shapes, or result semantics.

### Backend transfer

Transfer uses a canonical export and transactional import rather than direct
table copying:

1. place the source in a bounded read-only window;
1. export canonical rows with schema fingerprint, counts, and hashes;
1. initialize the target from the same metadata and logical version;
1. import while preserving IDs and recorded timestamps;
1. compare hashes and representative query and explanation results;
1. rebuild derived indexes;
1. switch configuration only after verification;
1. retain the source as a rollback artifact until acceptance.

A failed import never modifies or deletes the source store or evidence bytes.

## Interfaces

### Python API

The public Python API exposes application use cases and typed request and result
models. Backend connections, SQL, filesystem roots, and embedding libraries do
not appear in domain models.

### CLI

The initial command groups are:

```text
memory init | status | validate
memory schema | capabilities
memory ingest preview | apply
memory query | traverse | search | explain
memory reindex
memory evidence status | read | verify | audit
memory retention report | plan | retire
memory snapshot create | verify | import
memory transfer export | import
memory export
```

Mutating operations support preview where meaningful. Destructive retention
operations require an immutable plan and explicit confirmation.

### MCP

V1 exposes a local stdio adapter with normative discovery resources:

```text
memory://schema/current
memory://capabilities/current
memory://schema/ontology/{namespace}
memory://schema/queries
```

Structured tools cover capabilities, schema description, ingestion preview and
apply, typed queries, traversal, search, explanation, and bounded evidence
operations. The MCP adapter calls the same application services as the Python
API and CLI.

## Python and repository organization

Python dependencies, scripts, and lock state are managed with `uv`.
`pyproject.toml` is the package, tool, and dependency-group contract. `uv.lock`
is committed after the first dependency is selected.

The planned repository layout is:

```text
.
├── pyproject.toml
├── uv.lock
├── README.md
├── docs/
│   ├── design.md
│   ├── decisions/          architecture decision records
│   ├── guides/             operator and contributor workflows
│   └── reference/          generated or stable API reference
├── schema/
│   ├── core/               stable record and batch schemas
│   ├── ontology/           versioned logical type definitions
│   ├── queries/            saved query contracts
│   └── profiles/           backend and retrieval capability metadata
├── migrations/
│   ├── sqlite/
│   └── postgresql/
├── examples/
│   └── quickstart/         synthetic end-to-end input
├── src/
│   └── analytical_memory/
│       ├── domain/         records, value objects, and pure semantics
│       ├── application/    use cases and transaction orchestration
│       ├── ports/          explicit abstract storage and service interfaces
│       ├── adapters/
│       │   ├── sqlite/
│       │   ├── postgresql/
│       │   ├── filesystem/
│       │   ├── retrieval/
│       │   └── mcp/
│       └── cli/
├── tests/
│   ├── unit/
│   ├── contract/           shared backend and interface conformance
│   ├── integration/
│   └── fixtures/           synthetic, non-sensitive fixtures
├── scripts/                repository maintenance only
└── .local/                 gitignored runtime state
```

Placement rules:

- domain semantics must not import adapters;
- application use cases depend only on domain types and ports;
- ports are abstract base classes, and adapters implement them through explicit
  inheritance;
- backend-specific SQL belongs under its adapter and migration tree;
- authoritative machine-readable contracts live under `schema/`, not `docs/`;
- `docs/design.md` describes system invariants rather than duplicating schemas;
- significant design changes receive records under `docs/decisions/`;
- generated documentation is reproducible and never authoritative;
- tests use synthetic data and shared contract fixtures;
- one-off maintenance logic belongs in Python scripts executed with `uv run`.

Delivery sequencing, development commands, milestone acceptance criteria, and
verification work are defined in the
[implementation plan](implementation-plan.md). The plan may change as code is
delivered; the invariants in this document remain the conformance boundary.

## Deferred capabilities

- network and multi-user transports;
- remote or encrypted evidence providers;
- automatic replication and disaster recovery;
- approximate vector retrieval;
- external embedding calls;
- background retention execution;
- separate graph projections.

Deferred capabilities must preserve canonical IDs, fact semantics, provenance,
privacy propagation, and exact-query conformance.
