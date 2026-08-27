---
name: analytical-memory
description: Use Analytical Memory through MCP to import JSONL datasets, connect entity types explicitly, inspect the evolving ontology, and run JSON Query IR queries.
---

# Analytical Memory

Use one linear pass for each request.

1. Read `memory://capabilities/current`, `memory://schema/current`, and
   `memory://schema/ontology/current`. Use the structural fingerprint from the
   schema for writes.
2. Perform the requested operation:
   - For JSONL ingestion, call `memory_jsonl_import` with the source path,
     namespaced entity type, and ordered typed key.
   - To connect existing entity types, call `memory_join_materialize` with the
     explicit field mapping. Never infer or create joins unless the user asks
     to connect the datasets.
   - For a query, read `memory://schema/query-ir/current`, build one Query IR
     document from the current ontology, and call `memory_query_execute`.
3. After an import, join, or ontology declaration, read
   `memory://schema/ontology/current` once more and summarize the resulting
   queryable shape.

Do not add preview, review, evidence, verification, audit, reporting, or
sub-agent stages. Do not call evidence tools unless the user explicitly asks
for evidence. If a write fails with `schema_changed`, refresh the structural
schema once and retry once. Return the result and relevant entity, relation, or
node identifiers concisely.
