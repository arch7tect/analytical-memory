# Analytical Memory Design

## Status

Implemented architecture through Milestone 5 and target architecture for later
milestones. Milestones 0 through 4 describe the superseded foundation; ADR 0001
authorizes the clean-break current-state model implemented by M5.

## Purpose

Analytical Memory stores durable conclusions together with the provenance
needed to inspect, challenge, reproduce, and revise them. New data extends the
current ontology, which automated clients inspect before constructing queries.
The ontology language and query language are the core product contracts.

The memory supports four complementary query modes:

1. exact relational queries and aggregates;
1. bounded graph traversal;
1. full-text and semantic retrieval;
1. provenance explanation for every returned result.

The canonical store is relational. Graph behavior comes from explicit nodes
and directed relations. Semantic indexes are rebuildable projections and never
establish truth. Raw evidence bytes live in a separate content-addressed store.

## Goals

- Store imported and analytically produced current values through the same
  attribute, relation, and metric carriers.
- Bind every current value and computed result directly to its source,
  evidence, and ingestion or analytical run.
- Support relational, graph, full-text, vector, and hybrid queries in v1.
- Keep the logical contract independent of the selected relational backend.
- Keep the structural contract stable while deriving the current ontology from
  canonical data and explicit declarations.
- Expose the structural contract, current ontology, query language, and runtime
  capabilities to automated clients.
- Accept independent streaming JSONL datasets and link existing objects only
  through explicit, atomic join materialization.
- Make ingestion transactional, idempotent, and safe to retry.
- Keep raw evidence separate from canonical relational records.
- Move canonical memory and available evidence through verified snapshots.
- Rebuild derived indexes without changing canonical knowledge.

## Non-goals

- Treating semantic similarity as proof.
- Automatically reconciling competing analytical claims.
- Storing raw evidence as relational database blobs.
- Exposing arbitrary write SQL to automated clients.
- Generating and applying unreviewed schema migrations.
- Inferring or applying semantic links without an explicit user or agent
  declaration through the API.
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

Nodes, addressable attributes, directed relations, metrics, and constraints are
stored in ordinary relational tables. Graph traversal is a bounded query over
relation rows.

### Imported and analytical values share one model

A current scalar or structured value is a NodeAttribute whether it came from a
source dataset or an AnalyticalRun. A current link between objects is a
Relation. Direct provenance distinguishes how the value was produced; a
separate AnalyticalFinding record does not duplicate the same
subject-predicate-value shape.

### Preserve source evidence, not duplicate operational history

Raw evidence objects, ingestion batches, and analytical runs preserve the
reproducible source of current records. V1 does not also retain every prior
attribute value, relation state, or analytical conclusion as a claim chain.

### Derived indexes are disposable

Full-text and vector indexes are projections over exact source records. Losing
an index may reduce performance or coverage, but cannot destroy canonical
knowledge.

### Contract metadata is authoritative

Versioned metadata defines stable record shapes, validation, query semantics,
privacy rules, and exposed capabilities. Canonical data and explicit ontology
declarations define the current entity, attribute, and relation vocabulary.
Database introspection verifies physical conformance; it does not invent either
contract.

### Ontology and query form a closed loop

Ingestion changes the current ontology without requiring a physical migration.
Clients read that ontology, construct a query against it, execute the query,
and receive results with provenance and the ontology fingerprint used for
interpretation.

### Privacy is conservative and identity-bound

V1 has only `public` and `private`, with `public` as the default. Derived records
inherit `private` when any input is private. Lowering a class requires a
separately materialized sanitizer output with a new content identity. Existing
records may tighten from `public` to `private` in place. Loosening an existing
record is rejected because its evidence may remain private.

### Repeated work is idempotent

Stable logical keys prevent retries from duplicating canonical or derived
records. A repeated import or analytical run updates one current record per
attribute or relation identity.

## Conceptual architecture

```text
                       versioned contract metadata
                                   |
                         contract compiler
                                   |
                         structural contract
                                   |
       JSONL input --> application core --> current ontology
                            |      |               |
                            |      +---- Query IR -+
                            |
             +--------------+--------------+
             |              |              |
        MemoryStore    EvidenceStore   retrieval ports
             |              |              |
      SQLite/PostgreSQL  local files  FTS/exact vectors
             |              |              |
             +--------------+--------------+
                            |
                 Python API, CLI, stdio MCP
```

The application core depends on ports rather than database connections,
filesystem paths, model libraries, or transport details. Adapters implement
those ports and report their capabilities explicitly.

## Versioned contracts

The system versions five independent dimensions:

- **storage version**: physical tables, indexes, constraints, and migrations;
- **contract version**: canonical record shapes, API rules, and compatibility;
- **ontology fingerprint**: the current entity, attribute, and relation
  vocabulary derived from data and explicit declarations;
- **query IR version**: backend-neutral query syntax and semantics;
- **embedding profile version**: model identity, preprocessing, dimensions,
  and similarity function.

Changing an embedding profile does not migrate canonical records. Loading a new
entity or attribute, inferring the first effective type for a field, or declaring
a relation changes the ontology fingerprint without changing the storage or
contract version.
Materializing more current records under an unchanged ontology updates
statistics but not the ontology fingerprint. A physical migration is required
only when the stable core record shapes change.

### Structural Contract Document

The metadata compiler produces a backend-neutral canonical JSON document with:

- contract and Query IR versions;
- contract fingerprint and compatibility range;
- privacy classes and propagation rules;
- stable node, current-attribute, current-relation, metric, and provenance
  record shapes;
- normalized ingestion batch schemas;
- evidence object and fragment locator schemas;
- semantic index policies;
- Query IR operators and result-envelope rules.

### Current Ontology Document

The ontology document combines explicit entity declarations with current
canonical data and accumulated observed shape. It includes:

- declared and observed namespaces, entity types, and their optional
  human-readable descriptions;
- optional declared field types, required fields, nullability, and entity- or
  field-level privacy even for entity types with no rows;
- top-level field names, optional descriptions, one declared or inferred JSON
  type, declared required and nullable constraints, and search eligibility;
- declared relation rules, optional descriptions, endpoint types, review state,
  and provenance;
- observed entity, field, and relation counts;
- supported query operators and entity-specific query fields;
- a deterministic ontology fingerprint.

Declared constraints and observed structure remain distinguishable. A user or
agent may create logical entity schema before import, but an undeclared import
is valid and produces observed structure after it succeeds. The server derives
effective types, counts, matches, and coverage only from successful data. The
current ontology is derived on read in v1; materialized ontology revisions are
deferred.

The fingerprint covers the queryable shape: namespaces, entities, top-level
field names, effective types, declared required and nullable constraints,
search eligibility, descriptions, and active relation declarations. Import key selectors,
exact row and edge counts, presence and null ratios, distinct counts, samples,
join coverage, and other statistics are excluded from the fingerprint.

### Query IR Document

The first query representation is a versioned canonical JSON AST. Its semantic
model follows property-graph standards: node and edge patterns, predicates,
projection, ordering, grouping, bounded traversal, and result construction.
The JSON form is deliberately a replaceable frontend. A future GQL-compatible
text parser compiles to the same internal AST and execution semantics.

V1 supports only operators advertised by runtime capabilities. Unknown or
unsupported operators fail validation; they are never ignored or partially
interpreted.

### Runtime Capabilities Document

Runtime capabilities are separate from the logical schema and include:

- selected storage backend and migration version;
- enabled full-text and vector engines;
- exact or approximate search mode;
- embedding readiness and indexed-versus-eligible coverage;
- evidence-store provider and limits;
- enabled transports and bounded operation limits.

Canonical UTF-8 JSON serialization uses sorted object keys, deterministic
number encoding, duplicate-key rejection, and no non-finite numbers. Contract
and ontology fingerprints exclude timestamps, absolute paths, credentials, and
backend connection values. The runtime fingerprint covers the contract and
ontology fingerprints plus selected adapter capabilities.

Every write carries the contract fingerprint against which it was prepared. A
stale contract fails with the current fingerprint and a refresh pointer. A
post-hoc join validates against the current ontology and materializes relations
inside the same transaction; it has no preview-derived authorization token or
resolution hash.

## Canonical data model

```text
Node -- current NodeAttribute --> typed value
  |               |
  |               +-- direct provenance --> EvidenceFragment
  |
  +-- current Relation(active) --> Node
          |
          +-- direct provenance --> EvidenceFragment

text NodeAttribute or EvidenceFragment
  --> SearchDocument --> EmbeddingRecord --> vector projection
```

### Source

A logical provenance container. It records a stable ID, kind, safe locator,
optional content hash, privacy class, verification status, and availability.
It does not imply that source bytes are stored in the relational database.

### AnalyticalRun

A bounded analytical execution. It records a stable ID and idempotency key,
scope, valid-time window, method versions, contract and ontology fingerprints,
lifecycle state, coverage, limitations, and primary source. Every generated
attribute, relation, and metric records its producing run directly. An
AnalyticalRun may optionally reference an ingestion batch but does not require
one.

### Node

A stable graph object with:

- application-generated UUID;
- namespaced type;
- optional display label;
- privacy class;
- recorded timestamps.

Only identity and operational fields live directly on a node. Domain values
use addressable attribute rows. Deleting a Node deletes its owned attributes
and every Relation for which it is the source or target in the same
transaction. It does not delete shared evidence objects or ingestion and
analytical-run records. Search documents and embedding rows owned by deleted
attributes cascade as disposable projections.

### NodeAttribute

A typed scalar or bounded structured current value attached to one node. There
is exactly one row per `(node_id, attribute_name)`. It records the canonical
value, effective JSON type, privacy class, source, optional ingestion batch,
evidence fragment, optional analytical run, and update time.

A successful later import of the same entity and field overwrites this row
transactionally. If the field is absent from the later JSON object, the current
row is preserved. Fields selected as an import key remain ordinary attributes.
An explicit non-key JSON `null` is stored when there is no declaration or when
the declared field is nullable; otherwise the complete import fails.

An AnalyticalRun writes the same record shape and sets its run provenance. The
attribute name and entity declaration determine identity and validation; the
value does not acquire a separate Finding wrapper merely because analysis
produced it.

### Relation

A directed current link connecting two nodes. There is exactly one row per
`(source_node_id, type, target_node_id, logical_key)`. It records an `active`
flag, privacy class, source, optional ingestion batch, evidence fragment, and
update time, plus an optional analytical run. Correction changes the current row
explicitly; ordinary traversal reads
only active rows. Deleting either endpoint Node deletes the Relation.

V1 relations do not accept arbitrary domain properties. A relationship that
requires independently queryable properties is represented as a node connected
by ordinary relations.

### Current semantics

Imported values have simple current-state semantics:

- a NodeAttribute row is the current value for its node and name;
- a missing NodeAttribute row means the field is currently unknown;
- an active Relation row is traversable;
- an inactive Relation row is retained to prevent accidental recreation and is
  visible only when explicitly requested;
- source, batch, evidence fragment, and update time explain the current row.

Analytically produced attributes and relations obey the same current-state
rules. A later analytical run may overwrite a current analytical value and its
provenance. Simultaneous competing claims and derived claim states are outside
v1.

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
- `EvidenceVerification`: append-only audit of object, fragment, snapshot, or
  import verification.

NodeAttribute, Relation, and Metric records store their current evidence
fragment reference directly. A result that needs several inputs refers to a
derived manifest fragment produced by its AnalyticalRun rather than introducing
a second claim model.

Content identity is independent of acquisition policy. Effective object
privacy is the strictest class across acquisitions, and retirement is blocked
while any acquisition requires retention.

### SearchDocument

An exact text input derived from one text-valued attribute or evidence
fragment. It records the target, chunk index, privacy class, content hash,
extraction or chunking version, and lifecycle state.

### EmbeddingProfile

A property-scoped semantic index policy. It records target eligibility,
provider and model identity, dimensions, preprocessing, similarity function,
readiness, and coverage. External providers are eligible for public text only.
Provider credentials are runtime configuration and are never canonical records
or snapshot members.

### EmbeddingRecord

One derived vector for one SearchDocument under one EmbeddingProfile. Its
logical identity is the search document, profile, and input content hash. A
profile or input change creates a new record rather than overwriting the old
representation.

### Operational records

- `NamespaceDeclaration`: a required non-empty description for one explicitly
  declared exact namespace. It
  may exist before any entity in that namespace and carries direct provenance.
- `EntityDeclaration`: optional logical schema that may be created before
  import. It records entity type, optional entity and field descriptions,
  declared fields and JSON types, required and nullable flags, entity and field
  privacy, provenance, and contract
  fingerprint. It may describe an entity with zero rows and never rejects
  undeclared fields. Import key selection is not part of this record.
- `OntologyDeclaration`: a provenance-bearing join declaration with an optional
  description. It augments entity declarations and observed structure and is
  never a second store of observed counts or values.
- `ObservedField`: one `(entity_type, field_name)` entry with an effective JSON
  type and first- and last-seen ingestion batches. Null does not establish or
  change its type; an all-null field remains `unresolved` until the first
  non-null value.
- `IngestionBatch`: idempotency key, canonical request and result, source and
  extractor versions, counts, timestamps, and failure summary.
- `SchemaMigration`: backend profile, migration version, checksum, logical
  target fingerprint, applied time, and tool version.

### Stable uniqueness

Both relational backends enforce the same logical keys:

- Node: application-generated UUID;
- NodeAttribute: `(node_id, attribute_name)`;
- Relation: `(source_node_id, type, target_node_id, logical_key)`;
- EntityDeclaration: namespaced entity type;
- NamespaceDeclaration: exact namespace name;
- ObservedField: `(entity_type, field_name)`;
- Metric: `(run_id, definition_version, canonical_dimensions_hash)`;
- EvidenceFragment: object, locator, and extractor identity;
- SearchDocument: target, chunk index, and extraction version;
- EmbeddingRecord: document, profile, and input content hash;
- IngestionBatch: idempotency key.

## Time and revision semantics

NodeAttribute and Relation rows expose only current state and their latest
update time, regardless of whether import or analysis produced them. V1 does
not reconstruct their earlier values from canonical rows. Immutable
EvidenceObject, IngestionBatch, and AnalyticalRun records retain the source
material needed for a later explicit replay facility while that evidence is
available. Metrics remain immutable results of one run.

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

If a database transaction using a newly installed object rolls back, its owner
removes the temporary file and removes the final object only when that object
was created exclusively by the failed attempt. A content-identical object that
predated the attempt is shared and must not be removed. A process crash between
filesystem installation and database commit may leave an unreferenced immutable
object addressable by digest. Evidence audit reports these objects. Automated
crash-window cleanup is deferred; ordinary handled rollback does not leave an
orphan and never deletes a shared content-addressed object.

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
corrupt object never silently validates any bound canonical record.

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

Full-text and semantic projections, including profiles and vectors, are
excluded. A profile is recreated and vectors are rebuilt through a matching
provider contract after restore. Canonical queries and provenance remain
available without semantic retrieval.

A privacy-filtered export is a separate sanitized interchange artifact and is
not accepted by the restore importer.

## JSONL ingestion and ontology evolution

JSONL is the only general ingestion format in v1. Each non-empty line is one
JSON object. Python accepts a binary stream, the CLI accepts a file or standard
input, and the local stdio MCP tool accepts a server-local file path together
with the import parameters. The path is runtime input and is never canonical
metadata. No surface accepts the whole file as one in-memory JSON string.
The internal reader boundary remains stream-oriented so CSV can be added later,
but no CSV parser or public CSV import contract is part of v1.

A user or agent may create an EntityDeclaration through API, CLI, or MCP before
import, but this step is optional. A declaration exists independently from data
and immediately appears in the Current Ontology Document. Its shortest form
contains a namespaced entity `type` and optional privacy. Every field may declare
its allowed JSON types, required presence, nullability, and a description. An
entity may also have a description. An explicit namespace declaration requires
a description. Description metadata is
replaced by each declaration; omitting an optional entity, field, or join
description clears it. Descriptions must explain meaning without embedding
credentials, PII, or example records, and do not change privacy classification.
Fields not mentioned by the declaration remain valid, inherit entity-level
privacy, and extend observed ontology. Import key selection is not part of the
declaration. Without a declaration, privacy defaults to `public`.

```json
{
  "type": "calls.Session",
  "privacy": "public",
  "fields": {
    "id": {"types": ["string"], "required": true, "nullable": false},
    "status": {"types": ["string"], "required": true, "nullable": false},
    "duration": {"types": ["integer"], "required": false, "nullable": false},
    "message": {
      "types": ["string"],
      "required": false,
      "nullable": false,
      "privacy": "private"
    }
  }
}
```

The public import contract always supplies a namespaced entity type, typed
ordered composite key, and JSONL source. It has no separate field mapping or
import preview. If an active declaration exists, its constraints are enforced.
If none exists, every JSON field name is accepted and receives one inferred
effective type. Every accepted top-level field, including each selected key
field, becomes an ordinary current NodeAttribute. Arrays and objects remain
canonical JSON values and are not expanded into nodes or relations in v1.

The ordered typed key is a transient lookup expression. For each input record,
the importer queries current attributes of Nodes with the requested entity type.
Zero exact matches create a Node with a new application-generated UUID, one
match updates it, and more than one match reject the complete batch as
ambiguous. Duplicate key tuples within the source also reject the batch. The
memory creates no ExternalIdentity, natural-key column, deterministic UUID, or
persistent identity mapping. IngestionBatch retains the key selector only as
operation provenance and is never consulted to resolve a later import.

The import idempotency key is the canonical hash of entity type, ordered typed
key selector, and JSONL content hash. An exact retry returns the stored result
without applying the records again.

Fields absent from a declaration are always accepted and add their inferred
effective types to the ontology. Required, type, and nullability constraints apply only to
declared fields and are validated before any canonical write. Without a
declaration, explicit non-key JSON null is an accepted current value. Key
comparison uses canonical, type-strict tuples, so string `"42"` and number `42`
are different. A missing or null key component, a non-scalar key value, or a
duplicate composite key within one source rejects the complete import with its
line number.

Replacing field constraints validates all current records of that entity type
before the replacement becomes active. Failure leaves the previous declaration
active. Successful replacement changes the ontology fingerprint without
changing the generic physical tables. Declaration revision history is deferred.

Import is atomic and streaming. The first pass validates JSONL, calculates its
content hash, writes a temporary evidence object, retains only bounded schema
statistics, and inserts composite-key hashes into a disk-backed temporary table
with a unique index. The second pass reads the stored bytes in bounded record
chunks and writes Nodes, current attributes with direct provenance, the
IngestionBatch, and the ontology delta inside one database transaction. Chunks
bound memory but never commit independently. Before database commit the
temporary object is atomically installed at its content-addressed location.
Handled rollback follows the evidence cleanup rules above. A successful import
returns inserted and updated counts, the ontology delta, and the new ontology
fingerprint. Independently loaded datasets remain valid when no relations have
been declared. A separate JSONL inspection operation is deferred.

New entity types and attribute names extend the ontology without a physical
migration. An undeclared field receives one effective type from the first
successful batch containing a non-null value. Every non-null value for that
field in the batch must have the same canonical JSON type. Null may be stored
but does not establish or change the type; an all-null field is reported as
`unresolved` until a later non-null value fixes its type.

Re-importing an existing composite key updates each present non-key field and
its direct provenance in place. Fields absent from the incoming object remain
unchanged. A later incompatible value type rejects the complete batch without
changing current data or ontology. V1 performs no implicit coercion; semantic
formats such as timestamps are annotations. The prior current value remains
only in immutable source evidence and ingestion metadata, not as another
NodeAttribute row.

### Explicit one-step post-hoc joins

The memory never infers or applies a semantic relation from field names,
overlapping values, embeddings, or statistical confidence. After either or
both datasets have been loaded, a user or agent explicitly submits a named join
through the API or MCP. One `materialize_join` operation both declares the join
and materializes its currently resolvable Relations in a single transaction.

The request contains a name, relation type, ordered source fields, and ordered
target fields. The operation validates entity and field references and exact
type compatibility, verifies that an existing declaration with the same name
has the same canonical definition, resolves current endpoint values, stores a
new declaration when necessary, and writes missing Relations before commit.
There is no preview, apply token, resolution hash, or join-inspection operation
in M5.

```json
{
  "name": "message_to_session",
  "relation": "session",
  "from": {
    "type": "calls.SessionMessage",
    "fields": ["session_id"]
  },
  "to": {
    "type": "calls.Session",
    "fields": ["id"]
  }
}
```

Missing or null source keys and keys with no target are skipped and counted. A
source key matching multiple target Nodes fails with `ambiguous_target` and
rolls back the entire operation. Existing Relations are counted rather than
duplicated. The operation never creates a missing endpoint.

V1 sets Relation `logical_key` to the join name, making edge identity
independent of declaration revision. Relation privacy is the strictest class of
its endpoints.

Join declaration and execution reuse the canonical provenance model. The
canonical declaration is stored as a content-addressed evidence object and
represented by a `Source` of kind `join-declaration`. Each materialization
invocation creates a synthetic IngestionBatch and one AnalyticalRun. Each
Relation binds directly to declaration evidence and records the creating run
and batch. Resolution excludes every pair previously materialized by the same
join, including inactive rows, so an explicit rerun creates current relations
only for pairs the join has never materialized. The result reports previously
materialized active and inactive pairs separately. Restoring an inactive pair
requires an explicit correction operation; rerun never silently reverses a
correction.

V1 equality is type-strict and exact. String `"12"` does not equal number `12`.
Normalization and coercion functions require later, explicitly versioned Query
IR operators.

An accepted join is a provenance-bearing ontology declaration. It remains
queryable even when it currently materializes zero edges. Loading future JSONL
records does not run active joins automatically; a user or agent must invoke
`materialize_join` again. Reruns add only pairs never previously materialized by
that join. Reusing a join name with a different canonical definition fails;
changing its meaning requires an explicit future revision operation.

Join materialization is not synchronization. If a source join-key value changes,
a later rerun may add a relation to a newly matched target without deactivating
the relation materialized from the earlier value. Removing obsolete relations
is an explicit correction in V1.

Disabling a join prevents later execution but does not silently deactivate
relations. Changing a join declaration is deferred. Removing a materialized
relation is an explicit operation that sets its current row to inactive and
updates its direct correction provenance. The relation identity remains
reserved, so a later join rerun does not silently recreate it.

## Query model

### Canonical JSON Query IR

The JSON Query IR is the only v1 query language exposed through API, CLI, and
MCP. It is a typed, read-only AST rather than backend SQL:

```json
{
  "query_ir_version": "1",
  "match": {
    "nodes": [
      {"type": "calls.Session", "as": "session"},
      {"type": "calls.SessionMessage", "as": "message"}
    ],
    "edges": [
      {
        "type": "session",
        "from": "message",
        "to": "session"
      }
    ]
  },
  "where": [
    {
      "left": {"field": "session.status"},
      "op": "eq",
      "right": {"value": "failed"}
    }
  ],
  "return": [
    {"field": "session.id"},
    {"field": "message.side"},
    {"field": "message.message"}
  ],
  "limit": 100
}
```

Each ordinary field reference resolves from the unique current NodeAttribute
row to one typed value or to missing. Import key fields have no special query
semantics. Projection returns the value, its canonical record ID, and direct
source, batch, and evidence references. Ordinary field predicates do not choose
among historical candidates.

Each source join expression therefore resolves to one current value or to
missing. A target lookup must resolve to exactly one current entity identity;
zero matches are unmatched and multiple matches are ambiguous and make the
whole materialization fail. V1 does not coerce types or select a historical
value.

The `where` array is an implicit conjunction evaluated in document order.
Nested Boolean expressions are deferred and can later extend this shape without
changing v1 meaning. A literal whose type conflicts with a field's known
effective type is a validation error. An `unresolved` field does not match typed
comparison predicates. Ordering and comparison use extracted typed values, not
serialized JSON text.

The semantic north star is ISO/IEC 39075 GQL. SQL/PGQ informs compilation over
relational backends, and openCypher grammar and conformance scenarios provide
an accessible implementation reference while it evolves toward GQL. V1 does
not claim conformance with any complete textual language.

The initial IR supports:

- node and edge patterns;
- connected multi-node patterns without implicit Cartesian products;
- `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, and `exists` predicates;
- projection with direct provenance, deterministic ordering, limit, and offset;
- `count`;
- active-state, privacy, and provenance filters.

Boolean nesting, variable-length paths, grouping, cursor pagination, arbitrary
expressions, subqueries, mutation, and backend-specific functions are deferred.
Text, semantic search, and bounded traversal remain separate operations in M5.

### Relational queries

Typed filters, joins, aggregates, coverage checks, and metric calculations use
the Query IR compiled by each relational adapter.

### Graph queries

Traversal follows relation edges only and requires a start node, allowed
relation types, direction, maximum depth, and result limit. It expands active
relations by default. Inactive rows require an explicit diagnostic opt-in.
Attribute filtering happens before traversal.

### Full-text and semantic queries

Search targets one advertised text property or evidence-fragment class rather
than an undifferentiated node. A semantic result is a candidate, not a fact.
Every result joins back to its SearchDocument, current canonical target,
direct source provenance, and evidence availability.

### Hybrid queries

Exact privacy, type, scope, current-value, and active-relation filters run before
similarity ranking. Results contain coverage and readiness so incomplete
indexes cannot appear complete.

### Explanation

Every returned canonical or derived record supports an explanation containing:

- canonical IDs and logical keys;
- current value or relation state and its latest update provenance;
- ingestion batch, analytical run, and method versions when applicable;
- source identity;
- evidence object and fragment hashes;
- evidence verification and availability;
- retrieval mode and semantic-index coverage;
- contract and ontology fingerprints;
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

An embedding profile reports `pending`, `building`, `ready`, or `degraded`,
plus indexed and eligible counts. A missing API key, provider failure, or model
identity mismatch creates no new vectors and never affects canonical query
results.

## Privacy and security

The logical contract defines exactly two privacy classes: `public` and
`private`. Public is the default. Public records are eligible for shareable
exports and configured external processors. Private records are excluded from
both. Private restore snapshots remain controlled portability artifacts rather
than shareable exports and may contain both classes.

An EntityDeclaration may set entity-level privacy and override individual
declared fields to `private`. Undeclared fields inherit the entity-level class.
Without a declaration, imported fields are public. A field may tighten but not
weaken the entity-level class.

The effective class of a derived record is the maximum of its declared class
and every input source, acquisition, object, fragment, and target. The class of
an existing source, node, attribute, relation, or search document is immutable
in V1. Evidence privacy may only tighten when a new acquisition is recorded.
Sanitization creates a distinct derived object, records the derivation, and
assigns a new digest.

Automation is not a trust boundary. Structured write tools validate the same
schemas and permissions as the Python API. Evidence reads are bounded and
explicit. Ordinary search and traversal do not return raw evidence bytes.

An external embedding provider receives public text only. Credentials come from
the gitignored `.env` file, are never stored in SQLite, and are never returned
by APIs. Passwords, API keys, tokens, private keys, and other content that may
not be persisted are rejected before canonical or evidence commit rather than
represented by another privacy class.

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
capabilities, not contract or ontology semantics, IDs, request shapes, or
result semantics.

### Backend transfer

Transfer uses a canonical export and transactional import rather than direct
table copying:

1. place the source in a bounded read-only window;
1. export canonical rows with contract and ontology fingerprints, counts, and
   hashes;
1. initialize the target from the same contract version;
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
memory jsonl import
memory ontology declare-namespace | declare-entity | describe
memory query current-metric | execute
memory traverse | search | explain
memory join materialize | deactivate
memory node delete
memory embedding create-profile | status | rebuild
memory evidence status | read | verify | audit
memory retention report | plan | retire
memory snapshot create | verify | import
memory transfer export | import
memory export
```

Destructive retention operations require an immutable plan and explicit
confirmation. JSONL import and join materialization are direct atomic operations
without a prior preview.

### MCP

V1 exposes a local stdio adapter with normative discovery resources:

```text
memory://guide
memory://catalog
memory://schema/current
memory://schema/ontology/current
memory://schema/ontology/{namespace}
memory://schema/query-ir/current
memory://capabilities/current
memory://schema/queries
memory://operations
memory://operations/{operation}
```

`memory://schema/current` remains the stable structural contract and
compatibility fingerprint. Ontology and Query IR resources change independently
and carry their own versions or fingerprints.

Saved queries and manager actions for traversal, search, metrics, and
explanation remain versioned convenience operations. They are not a second
general query language.

Compact manager tools accept an action, an operation-specific payload, and an
optional memory. Exact payload and result schemas are loaded lazily from the
operation resources, while configuration and destructive Node deletion remain
isolated tools. The MCP adapter calls the same application services as the
Python API and CLI. No tool infers or silently applies a relation.

### Named memory routing

One process may address multiple independent memories without process-local
selection state. Every data operation accepts an optional memory name; omission
resolves to the existing environment-configured `default` memory. An explicit
unknown or unavailable name is an error and never falls back.

Named targets are recorded in a per-user `memories.json` catalog. The catalog
contains only backend coordinates: an absolute SQLite database path or a
PostgreSQL connection-environment name and schema, plus an absolute evidence
root. Secrets remain in the per-user `.env`. Default is reserved, synthesized
from existing configuration, and never stored in the catalog.

One lifecycle operation supports `create` and `attach`. Create requires a new
or empty target and initializes it. Attach requires an existing target and
validates its exact packaged migration ledger, physical integrity, and evidence
store readiness without scanning evidence contents, creating, or migrating
anything. Catalog replacement is atomic and serialized with a portable file
lock.

SQLite database paths are unique. PostgreSQL connection-environment and schema
pairs are unique. Evidence roots are also disjoint: equality and nesting are
rejected because evidence audit and retention operate across the complete root.
Different environment names that resolve to the same available PostgreSQL URL
and schema are rejected. Aliases whose connection values are unavailable while
the catalog is read remain an explicit operator risk.

The router caches only successfully resolved applications in a bounded cache.
It never records an active name, so concurrent stdio clients cannot change one
another's target. Structural schema and Query IR remain shared package
contracts; capabilities and data-derived ontology have named resource forms.
The guide is the stable entry point for a source-code-blind client. Capabilities
route every callable operation to a manager/action pair and its exact lazy
specification. Operation payload and result schemas describe every field.

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
│   ├── current.json        compiled structural contract
│   └── metadata/           source metadata for the contract compiler
├── migrations/
│   ├── sqlite/
│   └── postgresql/
├── examples/
│   └── quickstart/         synthetic end-to-end input
├── src/
│   └── analytical_memory/
│       ├── domain.py       records, value objects, and pure semantics
│       ├── application.py  use cases and orchestration
│       ├── ports.py        abstract storage and service interfaces
│       ├── api.py          typed Python API
│       ├── cli.py          command-line adapter
│       ├── mcp_server.py   stdio MCP adapter
│       └── adapters/       SQLite, filesystem, and provider adapters
├── tests/                  synthetic unit, contract, and integration tests
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
- background retention execution;
- separate graph projections;
- automatic relation inference or automatic join execution;
- point-in-time reconstruction or automatic replay of prior imported field and
  relation state from retained evidence;
- complete per-field and per-edge operational history;
- a competing-claim layer with support, contradiction, review, and
  supersession semantics;
- full ISO GQL, SQL/PGQ, or openCypher textual-language conformance.

Deferred capabilities must preserve canonical IDs, current-state semantics,
provenance, privacy propagation, and exact-query conformance.
