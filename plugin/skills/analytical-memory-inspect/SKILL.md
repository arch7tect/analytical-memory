---
name: analytical-memory-inspect
description: Inspect Analytical Memory through MCP when the user asks what data is available, whether the memory is ready, or how its namespaces, entities, fields, relations, and query capabilities are currently exposed. This is a read-only workflow.
---

# Inspect Analytical Memory

Read `memory://catalog`. Inspect the memory requested by the user; otherwise
inspect `default`. Read its summary first. There is no active selection and an
unavailable name must not fall back to default. An empty default does not imply
that named memories are empty.

Read full resources only when the request needs them:

- capabilities for operation availability, provider details, or full limits;
- ontology for fields, privacy, coverage, or relation declarations;
- `memory://schema/current` for the structural contract or fingerprint;
- `memory://guide` for an unfamiliar workflow.

Report only the information relevant to the request:

- initialization and backend readiness;
- resolved memory name;
- structural and ontology fingerprints;
- namespaces and their descriptions;
- entity types, fields, effective JSON types, privacy, and observed coverage;
- active relation declarations and their endpoint types.

Read `memory://operations/query_execute` and
`memory://schema/query-ir/current` only when the user asks how to query a
specific part of the ontology. Distinguish an uninitialized store from an empty
initialized ontology and from an unsupported capability.

Do not import data, declare ontology, materialize joins, run queries, inspect raw
evidence, or call any other mutating tool. Keep the summary concise and use the
current metadata descriptions rather than inferring business meaning from names.
