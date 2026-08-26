# ADR 0001: Dynamic ontology and a backend-neutral Query IR

## Status

Accepted for Milestone 5 on 2026-08-26. Milestones 0 through 4 remain a record
of the delivered foundation, but M5 is a clean-break contract and may replace
their assertion-backed storage, commands, and tests. Development databases are
reinitialized rather than migrated.

## Context

The Node, current NodeAttribute, current Relation, Metric, analytical-run, and
evidence records are a storage foundation, not the primary user contract. The
memory must accept new datasets incrementally, describe the entity and relation
vocabulary currently available for queries, and let automated clients construct
relational, graph, text, vector, and hybrid queries without direct database
access.

The first implementation compiled a static schema document from checked-in
metadata. Its ontology MCP resource is a placeholder, its ingestion format is
a verbose normalized batch, and relation endpoints must be re-declared in the
same batch. Those constraints were useful for the initial vertical slices but
do not satisfy the central incremental-memory scenario.

## Decision

### Separate the structural contract from the current ontology

The structural contract defines canonical record shapes, validation,
interfaces, Query IR semantics, and compatibility. Its fingerprint gates
writes and changes only with a contract release.

The current ontology describes namespaces, entities, attributes and their
single effective JSON types, relations, search eligibility, and queryable fields. It is
derived from canonical data plus explicit provenance-bearing ontology
declarations. Its fingerprint covers queryable shape, not row counts or
coverage statistics, and never requires a physical migration by itself.

Observed shape and declared constraints are separate. A user or agent may create
an entity declaration through API or MCP before import, but declaration is not
required. The shortest declaration contains only a namespaced entity type and
privacy. An extended declaration may constrain field types, required presence,
and nullability and assign field-level privacy. Fields absent from the
declaration are always accepted, inherit entity-level privacy, and become part
of observed ontology. Import key selection is not part of the declaration.

When present, a declaration is logical schema metadata and exists even when the
entity has no rows. The server derives one effective type per undeclared field,
plus counts, matches, and coverage, from successful imports. The Current
Ontology Document combines any declared constraints with observed shape and
works when either side is absent.

V1 stores one current declaration per entity type. Replacement first validates
current rows transactionally and leaves the earlier declaration active on
failure. Declaration revision history is deferred; canonical declaration
evidence and the operation record preserve provenance.

### Use JSONL as the first general ingestion format

JSONL is the only general import format in v1. Each non-empty line is one JSON
object and input is consumed as a byte stream rather than materialized in
memory. A separate JSONL inspector is not part of M5.

Import is one atomic operation whose public inputs are a namespaced entity type,
a typed ordered composite key, and a JSONL stream. All accepted top-level fields
become ordinary queryable attributes, including fields selected as the import
key. When an active declaration exists, its field constraints are enforced.
Without a declaration, the import accepts every JSON field name and infers one
effective type per field only after the batch succeeds.

The import key is a transient lookup expression, not Node identity or ontology.
For each record the importer finds current Nodes of the requested entity type
whose key attributes exactly match the typed composite value. Zero matches
create a Node with an application-generated UUID, one match updates it, and more
than one match reject the complete batch as ambiguous. Duplicate key values
within the incoming stream also reject the complete batch. No ExternalIdentity,
natural-key column, deterministic UUID, or persistent identity mapping is
created. IngestionBatch retains the request only as operation provenance. The
batch idempotency key is the canonical hash of the entity type, ordered typed
key selector, and JSONL content hash. An exact retry returns the stored result
without applying records again.

Every import accepts fields not mentioned by a declaration and adds their
inferred type to the ontology without an import mapping, preview, or physical
migration. All non-null values for one new field in the first batch must have
one compatible JSON type. A later incompatible type rejects the complete batch
instead of adding another type identity. An explicit non-key JSON null is stored
as the current null value when the field is undeclared or declared nullable;
absence means that a later import does not update that field.

V1 compatibility means exact canonical JSON type equality; null is ignored for
type inference. String-to-number, number-to-string, Boolean, and structural
coercions are never implicit. A later explicit declaration replacement may
define and validate a future conversion policy.

The implementation spools and hashes the stream into temporary evidence while
validating it, then reads that file in bounded chunks inside one database
transaction. A disk-backed temporary table with a unique key-hash index detects
duplicate composite keys without retaining the complete key set in memory.
Chunks do not commit independently. The evidence object is installed before
database commit. A handled rollback deletes temporary files and any final
object created exclusively by that attempt, but never deletes a deduplicated
object that predated it. A process crash may leave an unreferenced immutable
object addressable by digest; evidence audit reports it and automated crash
cleanup is deferred. Independent datasets may be loaded without relations and
linked later.

### Require explicit one-step post-hoc joins

The memory never infers or applies a semantic link from field names, value
overlap, embeddings, or a confidence score. A user or agent explicitly submits
a named join such as `SessionMessage.session_id -> Session.id` through MCP or
the Python API. One `materialize_join` call validates and stores the declaration,
resolves existing endpoints, and creates missing Relations in one database
transaction. There is no required preview token, resolution hash, or second
apply call. A separate join-inspection operation is not part of M5.

Null or missing source keys and unmatched targets are skipped and counted. A
source key resolving to multiple target Nodes aborts and rolls back the whole
operation with `ambiguous_target`; no endpoint is created. Previously
materialized relations are counted without duplication. Reusing a join name
with the same canonical definition reruns it; reusing that name with a different
definition is an error.

The ontology fingerprint includes namespaces, entity types, top-level field
names, effective types, declared required and nullable constraints, search
eligibility, and active relation declarations. Import key selectors, observed
presence, counts, ratios, samples, and link coverage are excluded. Materializing
additional edges under an unchanged declaration does not change it.

Accepted joins are stored as provenance-bearing ontology declarations, but
they are never executed automatically. Loading future records does not create
new edges. A user or agent explicitly calls `materialize_join` again; reruns add
only pairs never previously materialized by that join.

V1 matching is type-strict exact equality. Normalization and coercion are
future, versioned Query IR operators. Disabling a join prevents later execution
but does not deactivate existing relations. Correction and deactivation are
explicit operations.

Each join supplies the relation type and a stable logical key equal to the join
name. Its canonical definition has a fingerprint used to reject conflicting
reuse of the name. Each materialization invocation is represented by a
synthetic ingestion batch, a `join-declaration` Source backed by the canonical
document, and one analytical run. Every pair previously materialized by that
join is excluded before writing, including relation rows that were later made
inactive. The result distinguishes active and inactive previously materialized
pairs, and rerun never silently restores an explicit correction.

Join materialization is not synchronization. If a source join-key attribute
changes, a later rerun may add a relation to the newly matched target without
deactivating a relation materialized from the earlier value. Removing obsolete
relations remains an explicit correction in V1.

### Materialize imported data as current state

Each non-key field has at most one current NodeAttribute row for a node. A
successful later import overwrites that current value and its direct source,
batch, evidence-fragment, and update-time provenance transactionally. A field
absent from a later record leaves the current value unchanged.

Analytical output uses the same current carriers. A scalar or structured result
is a NodeAttribute whose provenance names the AnalyticalRun that produced it. A
result that connects two objects is a Relation. An aggregate result is a
Metric. V1 has no separate AnalyticalFinding or Assertion record and does not
derive supported or contested states.

Each relation identity has one current Relation row with an `active` flag and
direct provenance. Explicit correction changes that current state. Deleting a
Node deletes every Relation in which it is either endpoint. Immutable evidence
objects, IngestionBatch records, and AnalyticalRun records retain the material
needed to replay how current state was produced while that evidence remains
available. V1 does not provide point-in-time reconstruction of attributes or
relations.

The ontology records one effective type per field. A declaration supplies it;
otherwise the first successful batch with a non-null value infers it. Null does
not establish or change the type; an all-null field remains `unresolved`. A
later incompatible type fails validation without changing current data or
ontology.

### Use two privacy classes with a public default

V1 uses only `public` and `private`. Public is the default when no active entity
declaration assigns privacy. Public records may enter shareable exports and be
sent to configured external processors. Private records may not enter either.

An optional EntityDeclaration may set privacy for the whole entity type or for
specific declared fields. Undeclared fields inherit the entity-level class. If
there is no declaration, they are public. Privacy propagates conservatively to
derived records and relations. Credentials and other content that may not be
stored are rejected before entering memory rather than represented by a third
stored privacy class.

Privacy may tighten from `public` to `private` in place. Loosening privacy on an
existing record is rejected in V1 because its evidence may remain private.

### Make the Query IR a core contract

V1 exposes a versioned read-only canonical JSON AST. It includes fixed-length
node and edge patterns, one implicit conjunction of typed predicates,
projection with provenance, deterministic ordering, `limit`, `offset`, and
`count`. Traversal, text search, and semantic search remain separate existing
operations. Join materialization has its own typed request and is not a mutation
clause in the public Query IR.

Ordinary field references resolve to the single current value or to missing.
Predicates use that typed value, and projections preserve its current-record ID
and direct provenance. Join expressions must resolve to exactly one current
type-strict key value; missing values are reported and target ambiguity is an
error. The v1 `where` list is an implicit conjunction. A predicate literal whose
type conflicts with a field's known effective type is a validation error; an
`unresolved` field does not match typed comparison predicates. Comparison and
ordering operate on extracted typed values rather than serialized JSON text.

The semantic direction is the property-graph model standardized by
[ISO/IEC 39075:2024 GQL](https://www.iso.org/standard/76120.html).
[SQL/PGQ](https://www.iso.org/standard/79473.html) informs compilation over
relational backends. The
[openCypher specification and TCK](https://opencypher.org/resources/) provide
an accessible grammar and behavioral reference while openCypher evolves toward
GQL. V1 does not claim full conformance with any textual language.

JSON is a replaceable frontend. A later GQL-compatible parser compiles to the
same canonical AST, validation, execution plan, and result semantics.

## Consequences

- Dynamic ontology and Query IR move ahead of PostgreSQL in the delivery plan.
- Contract, ontology, query-language, runtime, and embedding versions remain
  independent.
- JSONL import and post-hoc joining are separate application use cases behind
  explicit `MemoryStore` methods. M5 does not add a second transaction-port
  abstraction; backend conformance tests define the portable behavior.
- Ontology discovery is useful immediately after each import or explicit join
  declaration.
- No hidden semantic writes depend on file names, load order, or model output.
- Query compilers must implement deterministic limits, ordering, truncation,
  current-state filtering, and provenance references identically across
  backends.
- Imported and analytically produced fields use the same current-value query
  semantics and differ only in direct provenance.
- Source history is retained as immutable evidence and ingestion metadata, not
  duplicated as a row-level claim chain.

## Deferred

- CSV and other non-JSONL import formats; the internal reader remains
  stream-oriented so they can be added without changing entity semantics.
- Full GQL, SQL/PGQ, or openCypher parsing and conformance.
- Implicit key coercion and normalization functions.
- Automatic attribute-value coercion or union-typed fields.
- Automatic relation inference or automatic join execution.
- Ontology rename, entity merge, and automatic conflict resolution.
- A competing-claim or argumentation layer with support, contradiction, review,
  and supersession semantics.
- Point-in-time queries and automatic replay of prior imported field or
  relation state from retained evidence.
- Complete per-field and per-edge operational history.
- Materialized ontology revision history; the current document is derived on
  read and import or join operations provide the audit trail.
- JSONL and join inspection operations.
- Variable-length path expansion, bounded grouping, cursor pagination, and
  text or semantic ranking inside Query IR.
- Unbounded Boolean expressions, subqueries, arbitrary mutation, and
  backend-specific Query IR functions.
- Automated deletion of unreferenced evidence left by a process crash.
