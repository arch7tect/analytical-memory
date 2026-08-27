---
name: analytical-memory-inspect
description: Inspect Analytical Memory through MCP when the user asks what data is available, whether the memory is ready, or how its namespaces, entities, fields, relations, and query capabilities are currently exposed. This is a read-only workflow.
---

# Inspect Analytical Memory

Read `memory://capabilities/current`, `memory://schema/current`, and
`memory://schema/ontology/current` once.

Report only the information relevant to the request:

- initialization and backend readiness;
- structural and ontology fingerprints;
- namespaces and their descriptions;
- entity types, fields, effective JSON types, privacy, and observed coverage;
- active relation declarations and their endpoint types.

Read `memory://schema/query-ir/current` only when the user asks how to query a
specific part of the ontology. Distinguish an uninitialized store from an empty
initialized ontology and from an unsupported capability.

Do not import data, declare ontology, materialize joins, run queries, inspect raw
evidence, or call any other mutating tool. Keep the summary concise and use the
current metadata descriptions rather than inferring business meaning from names.
