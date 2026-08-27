# Querying Reference

Analytical Memory exposes a backend-neutral, read-only JSON Query IR. An agent
can discover the complete machine-readable contract at
`memory://schema/query-ir/current` and the current data ontology at
`memory://schema/ontology/current`.

## Planning a query

Use this sequence for every new or refreshed connection:

1. Read `memory://capabilities/current` and confirm that
   `memory_query_execute` is available.
2. Read `memory://schema/ontology/current` to discover entity types, fields,
   exact effective JSON types, explicit relations, and statistics.
3. Read `memory://schema/query-ir/current` for the authoritative input and
   result JSON Schemas, semantic rules, limits, defaults, and examples.
4. Build a Query IR document and call `memory_query_execute`.
5. Re-read the ontology if a response carries an unfamiliar ontology
   fingerprint. Re-read `memory://schema/current` and retry a write if it fails
   with `schema_changed`.

The ontology fingerprint excludes row counts, so clients need to replan only
when queryable shape changes. The structural contract fingerprint gates writes.

## Query IR document

Every document has `query_ir_version: "1"`, a fixed graph pattern, optional
conjunctive predicates, one or more return items, and optional ordering and
pagination.

```json
{
  "query_ir_version": "1",
  "match": {
    "nodes": [
      {"type": "example.Session", "as": "session"},
      {"type": "example.Message", "as": "message"}
    ],
    "edges": [
      {"type": "session", "from": "message", "to": "session"}
    ]
  },
  "where": [
    {
      "left": {"field": "session.status"},
      "op": "eq",
      "right": {"value": "failed"}
    },
    {
      "left": {"field": "message.text"},
      "op": "exists"
    }
  ],
  "return": [
    {"field": "session.status"},
    {"field": "message.text"}
  ],
  "order_by": [
    {"field": "session.status", "direction": "asc"}
  ],
  "limit": 100,
  "offset": 0
}
```

### `match.nodes`

Each node has a namespaced ontology `type` and a query-local alias in `as`.
Aliases must be unique. A query accepts 1 to 8 nodes.

### `match.edges`

Each edge matches a directed, active relation. `type` is the relation type;
`from` and `to` reference node aliases. Optional `logical_key` restricts the
match to one relation key. Edge aliases and inactive-relation matching are not
supported. A query accepts at most 8 edges.

### Field references

Fields use `<node-alias>.<attribute-name>`, for example `session.status`. The
alias must be declared by `match.nodes`, and the attribute must exist in the
current ontology for that node type.

### Predicates

`where` is an implicit AND. OR and nested Boolean groups are not supported.

| Operator | Right operand | Meaning |
| --- | --- | --- |
| `eq` | `{"value": ...}` | Equal |
| `ne` | `{"value": ...}` | Not equal |
| `lt`, `lte` | `{"value": ...}` | Less than, optionally equal |
| `gt`, `gte` | `{"value": ...}` | Greater than, optionally equal |
| `in` | `{"values": [...]}` | Equal to one listed value |
| `exists` | none | A current attribute row exists |

Comparisons are type-strict: strings, numbers, booleans, arrays, objects, and
null are never coerced into one another. A missing attribute means no current
attribute row. Explicit null is a present value, so `exists` is true for it.
Typed comparisons against unresolved fields produce no matches. `ne` only
matches present attributes of the effective field type; missing attributes do
not match it.

### Return items

`{"field": "alias.name"}` returns the current attribute and its direct
provenance. `{"count": true}` returns a count and must be the only return item.
The query language does not return raw evidence bytes.

A projected missing attribute is returned with both `value: null` and
`record_id: null`. An explicit null has `value: null` and a non-null
`record_id`; use the record ID to distinguish the two cases.

### Ordering and pagination

`order_by` accepts field references and `asc` or `desc`; direction defaults to
`asc`. String order is Unicode casefold order followed by original code-point
order. Numeric order is numeric. Present values sort before missing attributes.
All node IDs, in alias order, are appended as deterministic tie-breakers.

`limit` defaults to 100 and is bounded to 1 through 1000. `offset` defaults to
0. `truncated` is computed with a limit-plus-one probe. Cursor pagination is
not part of v1.

Node patterns that are not connected by an edge form a Cartesian product.
This is sometimes useful, but can make a query expensive even when `limit` is
small; agents should normally connect multi-node patterns with declared
relations.

## Result contract

A non-count result contains:

- `rows[].bindings`, mapping every node alias to its stable internal node ID;
- `rows[].projections`, with field, value, effective JSON type, node and record
  IDs, and source/batch/run/evidence-fragment/update-time provenance;
- `ordering`, including effective tie-breakers;
- `truncated`, the structural and ontology fingerprints.

The binding is how an agent carries an entity discovered by one query into
`memory_traverse_relations`, `memory_explain`, analytical writes, relation
corrections, or deletion. Edge IDs are intentionally not bound; use traversal
or relation explanation when a relation identity is needed.

```json
{
  "rows": [
    {
      "bindings": {"session": "018f..."},
      "projections": [
        {
          "field": "session.status",
          "value": "failed",
          "json_type": "string",
          "node_id": "018f...",
          "record_id": "0190...",
          "source_id": "0191...",
          "batch_id": "0192...",
          "run_id": "0193...",
          "fragment_id": "0194...",
          "updated_at": "2026-01-01T00:00:00Z"
        }
      ]
    }
  ]
}
```

## Validation and errors

Unknown fields in an input object are rejected. Invalid shapes, aliases,
operators, types, limits, or ontology references return an MCP tool error whose
text ends with a JSON envelope:

```json
{
  "code": "query_validation",
  "details": {},
  "message": "...",
  "retryable": false
}
```

The MCP transport may prepend `Error executing tool <name>:`; parse the JSON
object beginning at the first `{`. The complete error-code registry is exposed
by `memory://capabilities/current`.

## CLI

```console
uv run memory ontology describe
uv run memory ontology describe --namespace example
uv run memory query execute --document examples/quickstart/query.json
```

Variable-length paths, aggregation beyond count, grouping, OR, cursor
pagination, textual GQL parsing, and text or vector ranking inside Query IR are
deferred.
