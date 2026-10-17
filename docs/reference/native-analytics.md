# Native analytics

Native Query IR v2 computes aggregates inside Analytical Memory. The
[retail walkthrough](../getting-started.md) provides a complete example and
[ADR 0002](../decisions/0002-native-analytics-observations.md) records the decision.
Query IR v1 remains available with its existing result shape.

## Query contract

Read `memory://schema/query-ir/current`: its top-level input/result schemas are
v1; `v2` contains the separate v2 schemas and numeric semantics. Supported
versions are explicit. Start from the packaged
[retail query](../../examples/retail/query.json).

V2 supports a connected required `match`, its AND `where`, and at most one
anchored optional node with one active directed edge and an exact `logical_key`.
The optional pattern's `where` runs before null extension. An order without a
qualifying ticket survives with `t = null`; a bound ticket with a null attribute
remains a bound entity.

`group_by` accepts scalar fields of required aliases. Keys are tagged:
`{"kind":"missing"}`, `{"kind":"null"}`, or
`{"kind":"value","type":"string","value":"South"}`. Missing and null form
different groups. A group ID hashes its exact typed key and population hash.
Changing output order or pagination changes the request hash, not population
hash or group IDs.

Measures are `count` of bound occurrences, `count_distinct` of canonical Node
identity, and `sum` of safe integer-valued JSON numbers (including `1.0`). `when` accepts one optional
`bound`/`unbound` alias. SUM's optional `distinct_on` must equal the summed field's
owner alias: it sums once per entity, even when several equally priced entities
exist. Missing/null values are skipped with explicit coverage; an empty sum is
zero. Non-integral fractions, booleans and values/results outside ±(2^53−1) fail rather than
rounding. Ratios reference named measures and return exact integer
`numerator`/`denominator` plus a decimal string with 12 places, half-even rounding.
Zero denominators have a null decimal. Ordering compares exact ratios.
Null ratios sort last in both directions; group values precede explicit null
and missing keys in both directions.

An empty global query returns one zero group; an empty grouped query returns no
groups. `order_by` names a group, measure or ratio result. Output pagination runs
after the full population is evaluated. Returned groups are exact even when
`truncated=true`; this never means partially evaluated input.

## Limits and failures

Current limits: 50,000 retained fact/provenance records, 100,000 binding-work
steps, 10 seconds of evaluation, 16 named members, 1,000 output groups or detail
rows per page, and 32 MiB per capture manifest. Capture requires complete members
within its 1,000-result bound. These are discoverable in capabilities.

Resource limits abort with `analytics_limit_exceeded`; malformed queries use
`query_validation`; unsafe arithmetic uses `analytics_error`. A stale page or
capture uses `stale_query_result` with a refresh instruction. Missing/corrupt
saved evidence uses `observation_unavailable`; identity/content disagreement
uses `analytics_integrity_error`. There are no silent partial results.

AVG, HAVING, arbitrary expressions, fractional SUM, nested optional patterns,
recursive analytics and independent optional branches are deferred. Evaluation
and write revision digests currently scale with the bounded memory population;
use separate memories for large independent analytical tasks.

## Public operations

All native responses use `{"format_version":"1","result":{...}}`. CLI native
commands read their operation document with `--document FILE`. Python exposes
these operations through `MemoryAPI` and `MemoryApplication`.

| Operation | CLI query action | MCP surface |
| --- | --- | --- |
| Query v2 | `execute` | `memory_query_manage`, action `execute` |
| Named analysis bundle | `analysis-execute` | query manager, `analysis_execute` |
| Explicit capture | `analysis-capture` | `memory_ingest_manage action=analysis_capture` |
| Exact group detail | `drill-down` | query manager, `query_drill_down` |
| Saved observation | `analysis-read` | query manager, `analysis_read` |
| Join diagnostics | `relation-inspect` | query manager, `relation_inspect` |
| Generation/revision | `data-state` | query manager, `data_state` |

For manager actions, payload is `{"document": OPERATION_DOCUMENT}`. The capture manager action uses the same `payload` wrapper. Read its exact spec from
`memory://operations/<operation>`. Keep the same memory name on every call.

An analysis document contains `members`, each with a unique `name`, `kind`
(`query` or `relation_inspection`) and `document`. A query member has a v2 query;
a relation inspection has `name`, optional `source_where`, `limit`, and `offset`.
Inspection filters use the alias `source`. Optional `coverage_scope` maps role
names to `{"member":"delivery_coverage","measure":"attributed"}`. Roles must
reference measures of complete global query members. The server computes role
values; callers cannot supply counts.

Inspection reports distinct source and expanded key-tuple totals independently.
Reasons include `linked`, `missing_or_null_key`, `no_target`,
`eligible_not_materialized`, `inactive_relation` and `active_keys_disagree`.
Current keys and actual materialized edges are inspected separately. Ambiguous
targets fail. Read-only inspection never creates or reactivates edges.

Capture document:

```json
{
  "analysis": {"members": [{"name": "totals", "kind": "query", "document": {"query_ir_version": "2", "match": {"nodes": [{"type": "shop.Order", "as": "o"}]}, "measures": [{"as": "orders", "op": "count_distinct", "node": "o"}]}}]},
  "definition_version": "orders-1",
  "expected_state": {"generation": "<from-analysis-result>", "data_revision": 3}
}
```

Capture is an explicit mutation. All members use the same locked state; values,
coverage, exact input records, binding membership, identity deduplication maps
and provenance are retained in one immutable manifest. Presentation pagination/order is normalized for capture. Repeating
its population, definition and state returns the same observation. Capturing
never advances the fact revision itself. Caller-written legacy metrics remain
separate and cannot set native origin.

## Drill-down and freshness

Live detail documents contain `query`, exact `group_key`, `measure`,
`expected_state`, optional `view`, `limit`, and `offset`. The server reconstructs
the original selector. Views are `bindings`, `counted_entities`, and `provenance`;
ratios require `numerator` or `denominator`. SUM detail reports each entity's
value, binding multiplicity and contribution; an individual contribution beyond
the safe JSON range uses an explicitly tagged decimal integer string. Aggregate
measure results still require the safe range. FastShip South reconciles four ticket
identities, one affected order and three denominator orders.

Saved detail replaces `query`/`expected_state` with `observation_id` and
`query_name`. Its `mode=observation_time` identifies immutable input values;
current source availability is independent. `raw_source_evidence` reports
verified, missing or unknown sources for returned detail, with an 8 MiB
verification budget. It is not a live requery.

Read an observation with `{"observation_id":"..."}`. Its freshness is `current`,
`potentially_stale`, or `unknown` in a different/restored generation.
`fresh_only=true` rejects an old result rather than substituting one. Any fact
or direct provenance change conservatively makes earlier observations stale.
A new warehouse field changes ontology and revision; correcting a ticket value
can change revision without changing ontology.

For native public reuse, set `public=true`: the observation must be current,
its manifest verified, and both captured and current dependencies public.
The initial manifest conservatively includes the bounded memory fact snapshot,
so an unrelated retained private field can make the whole capture private.
This does not change the legacy import, caller metric or semantic-search policy.

## Preservation and upgrade

Migrations are additive from 0.6.1. Never reapply the old M5 reset. Snapshot format
2 requires every referenced native manifest to be present and verified; a
missing raw source is represented independently. Original 0.6.1 format-1
snapshots are verified against their original schema and content hashes before
adapting caller metrics. Every restored/ transferred target has a new generation
and revision zero. Saved values remain available; execute and capture explicitly
to obtain a current observation. Transfer format 2 includes native manifests,
while other raw evidence follows the existing separate copy procedure.

## Compact presentation and status reads

MCP drill-down defaults to compact entity/attribute values with IDs; it preserves
all reconciliation, pagination, state, freshness and evidence-availability
metadata. Set `payload.response_format="full"` for the previous shape, or select
`document.view="provenance"` for explicit full evidence. Saved detail still uses
observation-time values. Python and CLI drill-down defaults remain full.

`analysis_read` accepts `view="status"` to omit saved result bodies after the
same manifest, privacy and freshness checks. The default `view="results"`
retains the previous response. See [the MCP contract](mcp.md#compact-query-responses).
