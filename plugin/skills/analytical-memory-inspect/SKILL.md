---
name: analytical-memory-inspect
description: Inspect Analytical Memory through MCP when the user asks what data is available, whether the memory is ready, or how its namespaces, entities, fields, relations, and query capabilities are currently exposed. This is a read-only workflow.
---

# Inspect Analytical Memory

Read every `memory://` URI below using the plugin's `memory_discover` tool
with `uri` set to that URI. This works even when the host has no resource browser.
Reuse contracts already read in this session. For a write fingerprint alone,
request `memory://schema/current` with `sections=["schema_fingerprint"]`.
Call the host's plugin tools directly for all memory operations. Do not create
an MCP client, run Python application APIs, or access the database yourself.
If the tools are missing, finish plugin activation before continuing.

Read `memory://catalog`. Inspect the memory requested by the user; otherwise
inspect `default`. Read its summary first. There is no active selection and an
unavailable name must not fall back to default. An empty default does not imply
that named memories are empty.

For named memories, use `memory://memories/<name>/summary` and
`memory://memories/<name>/schema/ontology/current`. `memory_discover` selects by
URI and has no `memory` argument; unqualified ontology URIs describe default.

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


## Native analytics discovery

When asked about analytical capabilities, report native grouping, identity
counts, integer sums, exact ratios, analysis bundles, saved observations and
live/saved drill-down from the current capability and operation metadata.
Distinguish a saved result's recorded state from current memory facts and
explain freshness states from the documented contract.

This inspection workflow does not execute analyses, drill into records or
capture observations. For a request to calculate or inspect actual analytical
results, use the `analytical-memory` skill and the selected operation's spec.
