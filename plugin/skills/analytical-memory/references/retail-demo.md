# Retail demo through the plugin

Read this only when the user requests the bundled retail example or its
quickstart. Perform the requested stage and explain its result; do not run the
entire scenario ahead of the conversation. The human guide is a sequence of
prompts, while this reference supplies the operational mapping.

Use native plugin tools for every data step, including samples and join coverage.
After installation, do not run shell/Python helpers, read JSONL to compute or
verify answers, or preflight fixtures. Pass JSONL paths directly to the importer.
The host's read-file tool may read the selected JSON query/declaration file;
reuse that document as an object without serializing it or rebuilding its shape.
Report only values returned by the plugin. Installation commands are separate.

## Locate inputs and select a memory

In an installed bundle, start at the directory containing this skill's
`SKILL.md` (`skills/analytical-memory/`) and resolve `../..` to the payload.
It contains `examples/retail/`. Use the host's actual installed skill
path, including a managed cache copy. During source development, the repository
root contains `examples/retail/`. Resolve absolute paths for the MCP server;
never ask the user to unpack files or define a shell helper.

Read `memory://catalog` and `memory://operations/memory_configure`. For a fresh
demo choose an unused name such as `retail-demo` or `retail-demo-2`. Create a
SQLite memory using absolute database and evidence paths in a new persistent
demo directory outside the plugin and existing evidence roots. Prefer
`<plugin-data-directory>/demos/<memory-name>/memory.db` with sibling `evidence/`;
resolve the configured plugin data directory and use absolute paths. Do not wipe,
reuse, or import into an existing memory unless explicitly requested. Set
`memory` to the chosen name on operation tools and report that name. Discovery
instead uses `memory://memories/<name>/summary` and
`memory://memories/<name>/schema/ontology/current`; it has no `memory` argument.

`memory_configure action=create` creates the database, its parent directories and
the evidence directory itself. Call it with the intended absolute paths directly;
do not run `mkdir`, `ls`, path probes or any other filesystem preparation. Use its
returned target paths and the catalog to confirm the configuration.

Create the memory, then import directly. The import discovers `shop`, `Order`,
`Ticket` and their fields as data arrives. Do not declare namespaces/entities
or send empty trial writes as preparation.

Confirm readiness, read `memory://schema/current` for the real contract
fingerprint, and use the selected operation's specification for exact payloads.
Do not use examples in the human guide as execution output.

## Stage mapping

| User request | File under `examples/retail/` | Operation |
| --- | --- | --- |
| Load orders | `orders.jsonl` | `memory_ingest_manage`, `jsonl_import`, entity `shop.Order`, string key `order_id` |
| Load support tickets | `tickets.jsonl` | Same action, entity `shop.Ticket`, string key `ticket_id` |
| Connect by order number | `join.json` | `memory_relation_manage`, `materialize`; use this declaration and the current contract fingerprint |
| Show connected delivery tickets | `linked-query.json` | `memory_query_manage`, `execute` |
| Compare carriers and coverage | `analysis.json` | `memory_query_manage`, `analysis_execute` |
| Compare carrier and region | `query.json` or analysis member `by_carrier_region` | Native aggregate query |
| Add warehouse information | `enrichment.jsonl` | Import into `shop.Order` with the original string key `order_id` |
| Correct a ticket | `correction.jsonl` | Import into `shop.Ticket` with the original string key `ticket_id` |

JSONL imports take an absolute `source_path`. Query and analysis actions take
`payload={"document": <JSON object>}`: neither payload nor document is a string
or file path. For `linked-query.json`, preserve `match.nodes` and `match.edges`
inside `match`; do not move edges to the root. Inspect the selected
memory's ontology after each import and join; render entity, field and relation
changes for the user. Show sample rows by querying the imported data.

The join result supplies `created_relations`, `skipped_unmatched` and
`skipped_null_or_missing`. Use those counts to explain immediate coverage.
For deeper coverage use the analysis's `unattributed_reasons` and
`delivery_coverage` members, or native `relation_inspect`; never recompute joins
from JSONL. Query the imported tickets when business IDs or field values are
needed to explain a returned source Node ID.

To identify unmatched tickets immediately after joining, read the
`memory://operations/relation_inspect` spec. Obtain current state via `data_state`
if not already returned, then call `relation_inspect` with
`payload={"document":{"name":"ticket_to_order","expected_state":<state>}}`.
Both fields are required; an empty document is valid only for `data_state`.
Use the returned per-source reasons and query their imported business IDs.

The analysis already defines carrier/region, carrier totals, grand totals,
ticket inventory and coverage. Its optional delivery match preserves all orders
in the denominator. Count distinct identities, not distinct monetary values;
never calculate population totals by adding a page of returned detail.

## Detail, capture and comparison

Reuse the latest returned `expected_state`. If a state is needed separately, read
`memory://operations/data_state` and call `memory_query_manage` with
`{"action":"data_state","memory":"<name>","payload":{"document":{}}}`.
Read required operation specs before their calls, not in parallel with a call
whose arguments depend on that spec.

For live detail, select the returned EcoPost / South typed group key. Use
`query_drill_down` with that key, the original `by_carrier_region` query,
`measure="affected_orders"`, and the exact returned `expected_state`. Detail
returns orders; use the connected query or delivery-ticket drill to show their
tickets. Do not claim order detail itself includes ticket attributes.

When asked to save, use `memory_ingest_manage` action `analysis_capture` with
`document={"analysis": <analysis JSON>, "expected_state": <returned state>,
"definition_version": "retail-delivery-1"}` inside its payload. Retain the
returned observation ID. If the state changed, rerun before capturing.

After enrichment, query the warehouse values and call `analysis_read` with the
saved observation ID and `view="status"` to explain freshness. After correction, rerun the same
analysis and compare with that saved observation (`view="results"` if the
original results are no longer in context). For historical contacts use
`query_drill_down` with `observation_id`, `query_name="by_carrier_region"`, the
same group key, and `measure="delivery_tickets"`. For current contacts use the
live query, current state and the same measure. Do not replace the saved result
with a new capture while presenting it as historical.

Classification uses `issue_code`. The correction changes T14's code while
retaining its original message. Explain this when showing the two together.
Report actual results and freshness; do not fabricate a successful step after
an installation, tool or state-guard failure.

Keep the default compact query/drill format. Values remain in `projections`
for ordinary queries and `attributes` for entity drill-down. Reuse the recipe,
parsed example documents and stable operation contracts within the session;
refresh ontology and expected data state after writes. Read detailed provenance
only when the human asks for its evidence, using the original observation for
historical records.
