# Native analytics and a business quickstart

Status: accepted on 2026-10-17 and implemented in 0.7.0. See [ADR 0002](../decisions/0002-native-analytics-observations.md) and [the current reference](../reference/native-analytics.md). Baseline: Analytical Memory 0.6.1,
commit `c18287aa32a44d00d346a25af128276a4499115b`. Date: 2026-10-17.

Extend the memory so a user can import independent datasets, connect them,
calculate native aggregates, inspect one aggregate's contributing records,
and retain a verifiable analytical observation. Build the new quickstart on
these capabilities. Grouping and calculation belong to the memory; the example
runner presents results and checks expectations.

This document retains the accepted design and its 0.6.1 baseline for decision
history. The [native analytics reference](../reference/native-analytics.md)
defines the implemented 0.7.0 contracts; the human quickstart and plugin
installation guide are the current user procedures.

## Product outcome

The example answers: **Which deliveries attract customer complaints, how many
orders do those complaints affect, and what evidence supports the result?**

A successful walkthrough demonstrates these capabilities in sequence:

1. Load orders into an empty memory and discover their fields.
2. Load support tickets independently and discover another entity type.
3. Explicitly connect tickets to orders and inspect unmatched records.
4. Run a connected query and identify repeated complaints.
5. Calculate a grouped native aggregate with a correct denominator.
6. Select an aggregate row and drill into its contributing orders and tickets.
7. Save the observation with server-generated input provenance.
8. Add a field to existing orders and inspect the evolved ontology.
9. Change data, observe stale analytical results, and explicitly recalculate.

The core walkthrough uses synthetic data, SQLite, and no API key. PostgreSQL 17
in Docker must produce the same logical results. Search, privacy, idempotency,
and backup become short extensions to the same business story.

## Current behavior and proposed changes

| Area | Released in 0.6.1 | Proposed target |
| --- | --- | --- |
| JSONL import | Atomic patch/upsert and dynamic fields | Preserve; expose before/after changes in the walkthrough |
| Linking | Explicit add-only materialization with skip counts | Preserve; add bounded inspection of unmatched source records |
| Connected queries | Required connected patterns and literal filters | Preserve v1; add a versioned optional pattern for aggregate denominators |
| Aggregation | One count as the sole projection | Grouping, binding counts, distinct-node counts, exact integer sums, ratios |
| Aggregate details | Caller builds another query | Typed server drill-down tied to the original query, group, measure, and data revision |
| Analytical metrics | Caller supplies values and free-form coverage | Explicit native capture computes values and their input manifest in the server |
| Freshness | Ontology fingerprint describes shape, not data changes | Per-memory data revision and explicit observation freshness |
| Provenance | Current fields reference source/batch/run/evidence | Aggregate manifests include exact inputs and preserved values |
| Quickstart | Two sessions, two messages, one result row | An end-to-end business analysis with expected outputs and evolution |

The baseline contracts are in [querying](../reference/querying.md),
[MCP](../reference/mcp.md), [system design](../design.md), and
[ADR 0001](../decisions/0001-dynamic-ontology-query-ir.md).

## Example data and expected answers

### Orders

`orders.jsonl` contains 12 `shop.Order` records. Its fields are `order_id`,
`carrier`, `region`, and `amount_cents`. Import by a typed string `order_id`.
Every order has `amount_cents: 10000`. Repeated amounts deliberately test that
summing distinct orders is different from summing distinct monetary values.

| Carrier | Region | Order IDs |
| --- | --- | --- |
| FastShip | North | O-101, O-102, O-103 |
| FastShip | South | O-104, O-105, O-106 |
| EcoPost | North | O-107, O-108, O-109 |
| EcoPost | South | O-110, O-111, O-112 |

### Support tickets

`tickets.jsonl` contains 16 `shop.Ticket` records with `ticket_id`, optional
`order_id`, `issue_code`, and `message`. Import by string `ticket_id`.
The category is a source field, not an LLM classification or search score.

| Ticket IDs | Order | Issue |
| --- | --- | --- |
| T-01 | O-101 | late_delivery |
| T-02 through T-05 | O-104 | late_delivery, four separate contacts |
| T-06 | O-107 | late_delivery |
| T-07 | O-108 | damaged |
| T-08 | O-110 | late_delivery |
| T-09 | O-111 | damaged |
| T-10 | O-112 | late_delivery |
| T-11 through T-14 | O-102, O-105, O-109, O-112 respectively | billing |
| T-15 | O-999 | late_delivery, unknown order |
| T-16 | missing order_id | damaged |

The `ticket_to_order` declaration creates an `order` relation from
`shop.Ticket.order_id` to `shop.Order.order_id`. It creates 14 edges and reports
one unmatched source and one source with a missing key. Filtering connected
tickets to `late_delivery` and `damaged` returns 10 order-ticket pairs.

### Native aggregate

The unit of the percentage is an **order**, not a ticket or joined row.
The denominator contains all orders in a carrier/region group, including those
with no qualifying ticket. The numerator contains distinct orders with at least
one qualifying ticket. Monetary values are counted once per affected order.

| Carrier | Region | Orders | Delivery tickets | Affected orders | Complaint rate | Affected order value in cents |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| FastShip | North | 3 | 1 | 1 | 1/3 | 10000 |
| FastShip | South | 3 | 4 | 1 | 1/3 | 10000 |
| EcoPost | North | 3 | 2 | 2 | 2/3 | 20000 |
| EcoPost | South | 3 | 3 | 3 | 1 | 30000 |
| Total | | 12 | 10 | 7 | 7/12 | 70000 |

The total rate is calculated from total numerator and denominator, not by
averaging displayed percentages. The two unattributed delivery tickets remain
visible in coverage and are excluded from carrier/region assignment.

The supported conclusion is descriptive: the carriers each have five linked
delivery tickets, but these affect two FastShip orders and five EcoPost orders.
The value column is the value of affected orders, not revenue lost, refunds,
or proven damage. The sample does not establish a causal or statistical claim.

## Memory changes

### Versioned native aggregate queries

Introduce Query IR v2 while retaining v1 input/result behavior. Dispatch by
`query_ir_version`; do not reinterpret existing v1 documents. Add grouping and
measure output only to v2. Keep one backend-neutral AST and exact capability
discovery; public APIs never accept backend SQL.

The first implementation supports these bounded features:

- `group_by` over fields on the required base pattern;
- `count` of bound node occurrences and `count_distinct` of node IDs;
- `sum` of an integer-valued numeric field, with optional node-identity
  deduplication through `distinct_on`;
- measure conditions testing whether an optional node is bound or unbound;
- derived `ratio` from two named measures, with explicit zero-denominator
  behavior;
- ordering by group or measure aliases and deterministic group tie-breakers.

AVG, HAVING, arbitrary expressions, recursive patterns, nested optional patterns,
and multiple independent optional branches are follow-up work. They are not
required for this example. The implementation must reject unsupported shapes.

### Preserve orders with no complaints

The required base pattern is `shop.Order`. A single optional pattern adds
qualifying `shop.Ticket` nodes through active `order` edges. Its category filter
belongs inside that optional pattern. If no ticket passes, retain one base row
with an unbound ticket alias. A billing-only order therefore remains in the
denominator but contributes no delivery ticket.

Optional nodes are represented as null bindings in v2, distinct from a bound
node whose attribute is explicitly null. Required aliases remain non-null.
Every optional pattern must connect to a base alias; unanchored Cartesian
products and alias reuse fail validation.

Putting the delivery category filter in the global `where` would eliminate
orders without a matching ticket. The contract and examples must demonstrate
this distinction explicitly.

### Illustrative aggregate request

```json
{
  "query_ir_version": "2",
  "match": {
    "nodes": [{"type": "shop.Order", "as": "o"}]
  },
  "optional_match": [{
    "nodes": [{"type": "shop.Ticket", "as": "t"}],
    "edges": [{
      "type": "order", "from": "t", "to": "o",
      "logical_key": "ticket_to_order"
    }],
    "where": [{
      "left": {"field": "t.issue_code"}, "op": "in",
      "right": {"values": ["late_delivery", "damaged"]}
    }]
  }],
  "group_by": [
    {"field": "o.carrier", "as": "carrier"},
    {"field": "o.region", "as": "region"}
  ],
  "measures": [
    {"as": "orders", "op": "count_distinct", "node": "o"},
    {"as": "delivery_tickets", "op": "count_distinct", "node": "t"},
    {
      "as": "affected_orders", "op": "count_distinct", "node": "o",
      "when": {"bound": "t"}
    },
    {
      "as": "affected_order_value", "op": "sum",
      "field": "o.amount_cents", "distinct_on": "o",
      "when": {"bound": "t"}
    }
  ],
  "derive": [{
    "as": "complaint_rate", "op": "ratio",
    "numerator": "affected_orders", "denominator": "orders",
    "zero_denominator": "null"
  }],
  "order_by": [
    {"result": "complaint_rate", "direction": "desc"},
    {"result": "carrier", "direction": "asc"},
    {"result": "region", "direction": "asc"}
  ],
  "limit": 100,
  "offset": 0
}
```

An aggregate row returns typed dimension keys, named measures, ratio
numerator/denominator, effective ordering, its group ID, privacy, and a result
reference containing the population hash and memory data revision. Scalar group keys
distinguish `missing`, explicit `null`, and a typed value. Arrays and objects
are not grouping keys in the first implementation.

Separate a full request hash from a population hash. The population hash covers
versioned matching/filtering, optional patterns, grouping, measure definitions,
derivations, and numeric semantics. It excludes presentation-only ordering,
limit, and offset. Group IDs hash typed keys and the population hash, so sorting
or paging does not change identity. Keep the full request hash for audit.
An analysis population hash binds each stable member name and kind to its
population definition: a query population hash for `kind: query`, or the
canonical declaration, source filters, and inspection options for
`kind: relation_inspection`. It also includes the explicit coverage scope.
Inspection presentation-only pagination is excluded, just like query paging;
capture consumes its complete bounded source population.

`count(t)` counts bound occurrences and excludes unbound tickets; it is not a
unique-ticket count when parallel matches exist. Use `count_distinct(t)` for the
business ticket measure. `count_distinct(o)` counts Node identity, so repeated
contacts cannot inflate the numerator.

Without `distinct_on`, sum includes each qualifying binding. With `distinct_on`,
the alias must be the owner of the summed field; a different alias fails
validation. A node contributes once if any of its bindings passes `when`.
Deduplicate by Node ID, not by price: two different EUR 100 orders contribute
EUR 200. FastShip/South must yield 10000 with `distinct_on=o` and 40000 without
it. Numeric null/missing values are excluded from sum and counted in measure
coverage. An empty sum is zero with zero contributing values. Fractional sums
are deferred: the initial exact sum accepts integer-valued numbers within the
JSON safe integer range and fails on overflow or unsupported fractional input.
Ratios preserve exact integer numerator/denominator and a decimal string with
12 fractional places, rounded half even by one application policy on both
backends. Do not encode their authoritative value through a binary float.
Ordering compares exact ratios rather than their rounded display strings;
null ratios follow the declared null ordering. Counts and integer sums remain
JSON integers within their declared safe range.

For an empty base population, grouping by dimensions returns no groups; a
global aggregate with empty `group_by` returns zero counts and a null ratio.

Aggregation consumes the complete matching population before applying group
pagination. `limit` never limits input facts. A returned group can be exact
while additional groups are omitted; v2 reports this as output truncation.
Input scan, time, and capture limits must return a structured failure rather
than an apparently complete partial total. Initial limits should be exposed
through capabilities and exercised with deliberately small test overrides.

### Native analysis bundles

The group table, carrier comparison, total, and attribution report require
separate populations. Add a read-only `analysis_execute` action to the query
manager. It accepts a bounded bundle of typed named members and returns their
discriminated results from one database snapshot and one generation/revision.
A `query` member contains a v2 query. A `relation_inspection` member contains
a stored join declaration name, source-field predicates, and explicit inspection
options. Member names are unique and form the references used by coverage. The runner does not
sum displayed groups or reconstruct coverage in Python.

The quickstart bundle contains five native queries and one inspection member:

| Member name | Population and grouping | Purpose |
| --- | --- | --- |
| by_carrier_region | The request above | Four business groups |
| by_carrier | Same matching and measures, group by carrier only | Native 5/5 ticket and 2/5 affected-order comparison |
| totals | Same matching and measures, empty group_by | 12 orders, 10 tickets, seven affected orders, 70000 cents, exact 7/12 ratio |
| delivery_coverage | Delivery tickets with optional linked orders, no groups | 12 delivery tickets, 10 attributed, two unattributed |
| ticket_inventory | All Ticket nodes, no groups | 16 imported tickets, including billing |
| unattributed_reasons | relation_inspection on ticket_to_order, source issue_code in late_delivery/damaged | Bindings and reasons for one unknown order and one missing key |

Coverage scope is a typed mapping from coverage roles to member names and,
where applicable, measure names. For example, known orders references
`totals.orders`, imported tickets references `ticket_inventory`, and delivery
attribution references `delivery_coverage` plus `unattributed_reasons`. It is not
a free-form assertion of success or a client-supplied count. Validate those
references and include every canonical member request and the scope mapping in
the analysis identity and retained manifest.

No rollup syntax or general subquery language is needed in this slice. Bundle
members share the same read snapshot; independently executed requests cannot
be combined into one supposedly consistent observation.

The delivery coverage request is:

```json
{
  "query_ir_version": "2",
  "match": {"nodes": [{"type": "shop.Ticket", "as": "t"}]},
  "where": [{
    "left": {"field": "t.issue_code"}, "op": "in",
    "right": {"values": ["late_delivery", "damaged"]}
  }],
  "optional_match": [{
    "nodes": [{"type": "shop.Order", "as": "o"}],
    "edges": [{
      "type": "order", "from": "t", "to": "o",
      "logical_key": "ticket_to_order"
    }]
  }],
  "group_by": [],
  "measures": [
    {"as": "delivery_tickets", "op": "count_distinct", "node": "t"},
    {
      "as": "attributed", "op": "count_distinct", "node": "t",
      "when": {"bound": "o"}
    },
    {
      "as": "unattributed", "op": "count_distinct", "node": "t",
      "when": {"unbound": "o"}
    }
  ],
  "limit": 100,
  "offset": 0
}
```

### Data revisions and consistent reads

Add a persisted per-memory state with a generation UUID and monotonic
`data_revision`. Advance it once per committed fact-changing transaction,
inside that transaction, rather than once per imported row. Relevant writes are:
node/attribute changes, relation creation/deactivation, and declarations that
change data interpretation or privacy. Changes to fact provenance, source/batch
references, or update times advance revision even if business values are equal.
A differently hashed import can replace those references and is not a no-op.
Rolled-back writes and exact idempotency replays do not advance revision.
A fresh join invocation that adds no edges and changes no declaration also
leaves fact revision unchanged, even if it records an operational run.
Wipe creates a new generation.

Metric capture, evidence verification, and embedding maintenance must not
advance the fact revision merely by recording operational results. A query
observation must not immediately make itself stale.

Read facts, ontology, revision, and aggregate inputs in one consistent database
snapshot. PostgreSQL requires an explicit suitable read isolation level;
SQLite requires an explicit read transaction. A sequence of independent
autocommit statements is insufficient.

For capture, the caller's expected state must equal the computation snapshot's
state. PostgreSQL then locks the per-memory state row with `SELECT FOR UPDATE`
and verifies that the current generation/revision still equals that snapshot
before observation commit. SQLite performs capture under `BEGIN IMMEDIATE`.
Every fact writer participates in the same revision lock protocol. A mismatch
aborts capture; it cannot be rescued by storing the caller's expected number.

Install the immutable manifest before database commit and apply the existing
ownership-aware evidence rollback rules. Remove only an object created solely
by the failed attempt; preserve a pre-existing deduplicated object. A crash can
leave an orphan manifest, which evidence audit must report without deleting it.

Treat a revision change conservatively as potential staleness, even when the
changed field is unrelated to a particular metric. Dependency-based selective
invalidation is deferred. Ontology fingerprints remain shape fingerprints:
changing a message without adding a field can advance data revision while
leaving the ontology fingerprint unchanged.

### Native drill-down

Add a read-only `query_drill_down` operation routed through the existing query
manager, with CLI and Python equivalents. Its request identifies the memory,
original v2 query or stored observation, exact typed group key, measure alias,
expected generation/revision, and detail pagination. The server reconstructs
the selector; a client does not translate a displayed row into new ad hoc
filters. Bundle results additionally identify the named query. The selector
uses population hash rather than output-page identity.

For each measure the response distinguishes:

- raw matching order-ticket rows;
- distinct counted entities, with stable Node IDs and contributing counts;
- base denominator membership, including orders without a qualifying ticket;
- current field provenance and source/evidence references.

Derived ratio details expose separate numerator and denominator views. The
FastShip/South group must reveal one affected order, four matching tickets,
and three denominator orders. EcoPost/South has three of each. Counted detail
membership must reconcile with the original measure. A detail page carries
total membership, ordering, and truncation; reading a page never changes the
aggregate's value.

For a live result, a changed generation/revision returns
`stale_query_result`, with the expected/current state and a recalculation route.
It never silently substitutes current rows for the original result. Every
detail page checks the same revision, so concurrent writes cannot mix pages
from different populations. A result reference is an integrity/selection
mechanism, not a new authentication boundary.

### Save native observations and their provenance

Add an explicit mutating `analysis_capture` operation. It accepts the bounded
named typed analysis bundle, a versioned definition and execution semantics
version, expected generation/revision, and typed coverage scope referencing
those bundle members. A single-query
capture is a one-member bundle. The server executes all populations in one
snapshot and records actual results and input provenance in one guarded
observation. Clients do not supply aggregate values.
Ordinary query execution remains read-only; capture is a separate action.

Reuse `AnalyticalRun`, `Metric`, and the evidence store. Add only the metadata
needed to locate a native observation and its manifest; do not introduce a
Finding/Assertion layer or duplicate every imported value's history.

The manifest preserves:

- named canonical query and inspection requests, their kinds,
  full request/population hashes and versions,
  definition/method versions, memory
  generation and fact revision, structural and ontology fingerprints;
- all group keys, values, exact numerator/denominator pairs, and coverage;
- base denominator members and matching ticket/order bindings, including the
  measure membership that determines deduplication;
- values used in grouping, filtering, and calculation, with record IDs,
  update times, source/batch/run IDs, fragments, and source content digests;
- the selected scope, attribution gaps, output completeness, and input digest.

IDs alone are insufficient because current attributes update in place. A
manifest hash without retained manifest bytes is also insufficient. Store the
manifest as canonical immutable evidence and reference it from the observation
and group metrics. Large captures must obey declared limits, not silently drop
inputs. Existing source evidence remains separately addressable and subject to
its retention policy.

Saved drill-down reads preserved input values even after current facts change.
It labels them as observation-time values and exposes current links separately.
It reports missing/retired original source evidence without inventing replay
availability. The manifest supports reproducing the saved calculation, not
general point-in-time queries over the whole memory.

Protect the manifest with mandatory evidence retention while any observation
references it. Retention release/retirement must reject that live dependency.
A native-observation snapshot requires its manifest bytes to be present and
verified; creation fails rather than silently omitting a manifest as missing or
retired. Original source objects retain their independent retention policy.
A manifest that later becomes unavailable is reported as degraded provenance
and saved drill-down fails with an explicit evidence-unavailable error.

Group metrics from all query members belong to one AnalyticalRun. Inspection
members contribute retained coverage, not independent business group metrics.
Store the
query name and canonical typed group keys in native dimensions; missing and
explicit null must have different canonical JSON and dimension hashes. Keep
all exact integer measures and ratio components in `Metric.value_json` and the
manifest, not the existing floating-point numerator/denominator columns.

Add an observation-origin discriminator, defaulting migrated existing rows to
`caller`. Only native capture can write origin `native`; callers cannot choose
it. Legacy `current_metric` selects caller-origin rows only and preserves their
selection semantics. A separate native selection operation handles freshness.
This avoids native rows being returned by the old API as apparently current.

Capture identity includes analysis population hash, definition and execution
semantics versions, generation, fact revision, and canonical capture scope.
Derive a deterministic native run ID from that identity. Treat result/input
content digests as integrity checks: a different digest for the same identity
is an integrity failure, not a new observation. Canonical manifest content
excludes volatile request/capture times and live evidence-check status; capture
time is stored as run metadata. An exact replay returns the stored observation.
Caller-written legacy metrics retain caller-supplied provenance.

Expose freshness independently from invalidation: `current`,
`potentially_stale`, or `unknown`, together with captured/current revisions.
Do not rewrite immutable metric values or automatically recalculate them.
An explicitly requested fresh observation must fail or return a typed absence
when none exists; it must not fall back to an older apparently fresh result.
Preserve v1 `current_metric` selection behavior and expose the new selection
policy through a versioned native observation operation.

Native results inherit the strictest privacy of every counted/bound entity,
used field, optional/global filter, and join-key field behind a used relation,
including inputs not projected in the result. Capture-level manifests and
metrics conservatively inherit the strictest class across the whole bundle.
Retain an entity/field/join dependency footprint for later policy checks.

Privacy cannot be loosened by reusing an old public capture after a declaration
becomes private. For origin `native` observations, their metrics, and their
manifests, public export/external processing requires current freshness,
verified manifest bytes, and public classification under both captured and
current dependency policies. Unknown policy/dependency state fails closed.
A potentially stale observation requires explicit recalculation/capture before
public export; local historical detail remains available under process trust.
This intentionally favors conservative native-observation export over selective
invalidation. Caller-origin metrics, ordinary imported data, and existing
semantic retrieval retain their released privacy policy; they do not acquire
a requirement for a native observation merely to be exported or processed.

### Attribution coverage

Join skip counts are retained, but readers also need to inspect the records
behind them. Add a bounded read-only relation inspection action returning
source bindings, expanded source-key tuples, and attribution reasons. It accepts
AND source-field filters, including the delivery-category `in` predicate, and
uses the stored join declaration without creating relations. Require a revision
guard for pagination. Preserve existing source-array expansion semantics and
report distinct-source and tuple counts separately; they coincide in this
scalar-key fixture. Ambiguous target resolution remains a structured error.

Distinguish missing/null key, no matching target, eligible but not materialized,
explicitly inactive relation, and an active relation whose current join keys
no longer agree. Resolve keys and inspect materialized edges separately; an
eligible endpoint is not proof of an active relation. The delivery coverage
query above counts actual active links. Inspection explains the two baseline
unattributed records as unknown order and missing key.

Coverage must be computed by the named native bundle queries and relation
inspection, rather than inferred by an LLM or accepted as an unverified success
claim. Inspection used as capture coverage runs within the same snapshot and
its source bindings/reasons are included in the manifest. Attribution and
execution completeness remain separate typed fields.

For this example distinguish execution completeness from attribution coverage:
12 known orders, 16 imported tickets, 12 delivery tickets, 10 attributed
delivery tickets, and two unattributed delivery tickets. The report covers the
known order population and observed attributable complaints; it does not claim
that every customer issue has been assigned to a carrier. An empty result must
not erase unattributed records from coverage.

## Interfaces and storage work

Expose v2 input/result schemas, supported versions, aggregate operators,
optional-pattern rules, limits, drill-down selectors, freshness states, and
error recovery through packaged Query IR resources and capabilities. Provide
versioned Query IR resources while retaining v1 execution. Update lazy MCP
operation specifications, examples, server guide, and both bundled skills.
The root README remains a human product overview.

Likely implementation seams:

| Seam | Work |
| --- | --- |
| [API models](../../src/analytical_memory/api_models.py) and [Query IR](../../src/analytical_memory/query_ir.py) | Version dispatch, aggregate AST, typed group keys, response and detail schemas |
| [Shared SQL store](../../src/analytical_memory/adapters/sql_store.py) and dialects | Optional-pattern compilation, complete aggregation, deduplication, revision guards, observation persistence |
| [MemoryStore port](../../src/analytical_memory/ports.py) | Aggregate/drill/capture interfaces and explicit snapshot boundaries |
| [Application](../../src/analytical_memory/application.py) | Native capture, manifests, deterministic ratios, privacy, freshness |
| [MCP operations](../../src/analytical_memory/mcp_operations.py), CLI and API | Discoverable read versus write routes and recovery |
| Packaged schema metadata and both migration trees | Additive revision/observation metadata and regenerated contracts |
| [Snapshot](../../src/analytical_memory/snapshot.py) and [transfer](../../src/analytical_memory/transfer.py) | Preserve saved observations and manifests; verify restore semantics |
| [Quickstart](../../src/analytical_memory/quickstart.py), packaged examples and tests | Replace the tutorial scenario and keep isolated smoke coverage |

Migrations must preserve 0.6.1 records and evidence. Do not repeat the pre-M5
development-database reset. An explicit 0.6.1 snapshot compatibility adapter is
a mandatory slice 5 deliverable: verify the old artifact and original hashes before upgrading its
records. Assign a new generation and initial revision 0 to the restored target;
legacy caller metrics have unknown freshness. Do not publish additive storage
changes that make all 0.6.1 backups unrestorable.
New snapshot/transfer formats must fail closed in readers that cannot interpret
them. Existing SQL migration checksums remain unchanged.

Restored and transferred observations retain captured provenance. A newly
materialized target receives a new local generation, so historical captures
report `unknown` freshness relative to the new target. Rerunning the analysis
and explicitly capturing a new observation produces current target provenance;
a read-only rerun alone does not relabel an immutable historical capture.
Preserved observation-time drill-down still works from its manifest. Backend
transfer does not silently create a claim that source and target are live peers.

## Quickstart changes

### Main walkthrough

Show a human question, the operation performed, and its meaningful result at
each step. Keep commands and full JSON available as linked examples. The
automated runner must call the same public operations; it must not calculate
the business aggregate independently in Python or access backend tables.

| Step | User-visible result | Acceptance |
| --- | --- | --- |
| Empty memory | No business entity types | Isolated paths, no existing user data touched |
| Import orders | Order and its typed fields appear | 12 orders, no ticket type or edges |
| Import tickets | Ticket appears independently | 16 tickets, 28 total nodes, zero edges |
| Materialize join | Relation and attribution report appear | 14 edges, one unknown and one missing order key |
| Connected query | Delivery complaints with order context | 10 pairs, four contacts on O-104, billing excluded |
| Native aggregate | Four groups and exact totals | Values match the table; orders without complaints remain counted |
| Drill-down | EcoPost/South expands to O-110 through O-112 | Three affected orders/tickets; source evidence is inspectable |
| Save observation | Native result has method, inputs, and provenance | Server values and manifests reconcile, no supplied totals |
| Enrich orders | New warehouse field appears; saved observation is already potentially stale | Original field values and 14 edges preserved; fact/key provenance can change; structural fingerprint unchanged |
| Recalculate enrichment | Same business values, with warehouse detail | Explicit new capture is current at the enrichment revision |
| Update and recalculate | Value-only change advances revision without changing ontology shape | Old observation becomes potentially stale; new capture is explicit; historical detail remains available |

`orders-enrichment.jsonl` contains all 12 order IDs and a new `warehouse` field.
Use W1 for O-110 through O-112 and W2 for the remaining orders. Explain how the
new field enables a new breakdown without a physical schema migration. The
patch also rewrites supplied import-key provenance, so preservation means
unchanged values, not unchanged source/batch references. Conservative freshness
marks the earlier observation potentially stale even though aggregate values
are unchanged. Recalculate and capture explicitly before the next mutation.
The shared warehouse is not proof of a complaint cause.

For the value-only update, change T-14 from `billing` to `late_delivery` in a
new patch file. The existing relation remains active. Ontology shape stays the
same, data revision advances, and EcoPost/South has four delivery tickets while
still having three affected orders and 30000 affected-order cents. Native
totals become 11 linked delivery tickets; coverage becomes 13 delivery tickets,
11 attributed and two unattributed. The previous observation remains immutable.
Use a new explicit capture after recomputation; do not silently replace it.

Display an ontology checkpoint after each import/link/enrichment and distinguish
structural fingerprint, ontology fingerprint, and data revision. The new runner
returns a readable report and a machine-readable validation summary. Preserve
the old tiny scenario as an isolated smoke fixture rather than deleting its
only coverage. Add a versioned output shape for the richer runner.

### Extensions using the same data

- Repeat an exact import and link operation: no duplicate nodes/edges and no
  fact revision increment for a true replay.
- Import one new ticket: no automatic relation; report unattributed coverage,
  explicitly rerun materialization without a caller idempotency key or with a
  fresh key, assert one new edge, then recalculate. Reusing the old key would
  replay the old invocation rather than link newly imported records.
- Submit a mixed valid/invalid patch with a string amount: reject the whole
  batch and preserve values, ontology, revision, and aggregate observations.
- Declare ticket messages searchable and demonstrate local full-text search.
  An optional semantic search extension must name its external-call boundary.
- Declare a synthetic private field before import and show that an aggregate
  depending on it is private and excluded from public export.
- Create a verified snapshot, restore into an empty target, and inspect a saved
  observation. Run the same scenario against PostgreSQL 17 in Docker.

Keep destructive lifecycle examples and unrelated administration out of the
core story. Use a dedicated named memory for an assistant-driven persistent
walkthrough; an automated run uses unique temporary stores.

## Delivery slices and acceptance

| Slice | Deliverable | Required checks |
| --- | --- | --- |
| 1 | Accepted contracts, exact fixture data, v1/v2 schemas and generated resources | Golden schemas; existing v1 examples remain valid; no v1 meaning changes |
| 2 | Fact revision and explicit consistent read boundaries | All write paths including provenance-only updates, exact replay/no-edge join behavior, concurrent writer tests, named-memory isolation |
| 3 | Native optional-pattern aggregates and named analysis bundles on both backends | Four groups plus native carrier/totals/coverage results in one snapshot; zero-ticket/billing-only groups, parallel matches, equal prices, null/missing, numeric limits, empty population, output pagination |
| 4 | Live drill-down and relation coverage inspection | Membership reconciliation, denominator inspection, wrong group/measure rejection, stale references, revision-safe pages |
| 5 | Native capture, saved detail, privacy, freshness, migration and portability | Atomicity and deterministic replay, retained immutable manifests, caller/native separation, privacy tightening, stale/manual observations, 0.6.1 upgrade and mandatory old snapshot adapter, new snapshot round trips, backend transfer |
| 6 | Human walkthrough, runner, MCP examples and packaged fixtures | Public-interface-only end-to-end run, deterministic expected business results, isolated wheel/source installs, all four plugin bundles and documentation links |

Slices 1 through 5 are product work; rewriting the quickstart alone does not
satisfy the outcome. A releasable walkthrough needs native aggregation, correct
drill-down, and the saved-observation/freshness behavior it demonstrates.

Run the complete [contributor checks](../../CONTRIBUTING.md#verification) and
mirror CI, including real PostgreSQL 17 through Docker. Add shared backend tests
at the public contract seam. Verify full result populations and concurrency,
not only the displayed sample or an isolated SQL fragment.

## Review choices and release boundary

Recommended choices are a separate Query IR v2, one optional branch initially,
native count/distinct/integer-sum/ratio, bounded named analysis bundles,
conservative memory-wide freshness,
explicit capture, and saved input manifests. Review these together before
implementation; changing one affects query semantics or observation identity.

The first release deliberately leaves dependency-specific invalidation,
automatic recalculation, multiple optional branches, fractional sums/AVG,
general temporal querying, and arbitrary query composition for later work.
Resource limits and error codes must be finalized as part of slice 1 rather
than left to backend-specific defaults.

After review, record the accepted contracts in a new ADR and add the delivery
slices to a new milestone. Update current references only with implemented
behavior. Do not mark this proposal or its syntax as accepted by publishing
the document alone.

## Design review disposition

A read-only Claude review checked the draft against the 0.6.1 implementation.
The revised proposal incorporates typed native bundle totals, inspection, and
coverage, bound and
unbound conditions, source-filtered attribution inspection, population hashes,
typed native metric keys, exact numeric storage, caller/native selection
separation, provenance-sensitive revisions, deterministic capture identity,
manifest retention, privacy tightening, and mandatory old-snapshot compatibility.

The review's suggestion to remove plugin packaging checks was not adopted:
these checks already protect the distributed MCP/skill/docs delivery. Search
remains an optional walkthrough extension using existing behavior, not a new
native-analytics implementation requirement. The user subsequently accepted staged implementation on 2026-10-17;
[ADR 0002](../decisions/0002-native-analytics-observations.md) and the
[delivery record](../native-analytics-delivery.md) track the resulting work.
A focused second review confirmed the earlier blockers were resolved and found
two additional boundaries: inspection requests must participate in capture
identity, and stricter export rules must apply only to native observations.
Both are incorporated above.
