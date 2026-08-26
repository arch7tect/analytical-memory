# Analytical Memory

Analytical Memory is an evidence-backed, local-first memory for durable
analysis. It is designed to support relational, graph, full-text, vector, and
hybrid queries without treating semantic similarity as truth.

The project is currently in the design and bootstrap phase. The planned v1
focuses on:

- SQLite as the default local backend, with PostgreSQL as a conforming
  replacement;
- explicit nodes, attributes, relations, assertions, and analysis runs;
- provenance bindings to immutable evidence objects and deterministic
  fragments;
- schema discovery through a backend-neutral API and local MCP adapter;
- rebuildable full-text and exact vector-search projections;
- portable private snapshots and separate sanitized exports.

Implementation milestones and contribution guidance will be added with the
first development slice.

## License

Apache License 2.0. See [LICENSE](LICENSE).
