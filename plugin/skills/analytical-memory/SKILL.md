---
name: analytical-memory
description: Use Analytical Memory through MCP to select a default or named memory, import JSONL datasets, connect entity types explicitly, inspect the evolving ontology, and run JSON Query IR queries.
---

# Analytical Memory

Use one linear pass for each request.

1. Read `memory://catalog`. Use the memory requested by the user; otherwise omit
   `memory` and use `default`. There is no active selection. Read that memory's
   summary when choosing among memories or assessing available content. An empty
   default does not imply that named memories are empty.
2. Use the action-to-spec link in the selected tool description. Read
   `memory://operations` only when the operation is not known. Read capabilities
   only for readiness or availability questions, the ontology only when exact
   entity/field/relation names are needed, and `memory://schema/current` only for
   writes. Read `memory://guide` only for an unfamiliar workflow.
3. Read the selected operation's exact spec, then perform the operation:
   - For JSONL ingestion, use `memory_ingest_manage` action `jsonl_import`.
   - To connect existing entity types, use `memory_relation_manage` action
     `materialize`. Never infer joins unless the user asks to connect datasets.
   - For a query, read `memory://schema/query-ir/current`, build one Query IR
     document from the current ontology, and use `memory_query_manage` action
     `execute`.
   - Only when the user explicitly asks to wipe or delete a memory, call
     `memory_lifecycle_manage` with action `status`, retain its exact state, then
     pass that state unchanged to action `wipe` or `delete`. Never delete
     `default`; wipe it instead.
4. After an import, join, or ontology declaration, read the selected memory's
   current ontology once more and summarize the resulting queryable shape.

Do not add preview, review, evidence, verification, audit, reporting, or
sub-agent stages. Do not call evidence tools unless the user explicitly asks
for evidence. If a write fails with `schema_changed`, refresh the structural
schema once and retry once. Never fall back to another memory after an error.
Return the result, resolved memory, and relevant entity, relation, or Node IDs
concisely.
