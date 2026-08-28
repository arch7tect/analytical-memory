# Changelog

All notable changes to Analytical Memory are documented here.

## 0.4.0 - 2026-08-28

- Expanded array-valued source join fields into their Cartesian product when
  materializing relations.
- Kept target join fields scalar and preserved exact typed matching, ambiguity
  detection, pair deduplication, and add-only materialization.
- Documented the array join contract in the MCP guide and operation
  specification.
- Added regression coverage for empty, null, duplicate, invalid, and
  multi-array source values, plus target-array rejection.

## 0.3.0 - 2026-08-27

- Added one implicit default memory and stateless optional named-memory routing
  across MCP data tools and the CLI.
- Added an atomic per-user non-secret catalog plus one create-or-attach
  lifecycle operation.
- Added named capabilities and ontology discovery with strict target and
  evidence-root isolation.
- Added an MCP agent guide, per-memory discovery links, operation semantics, and
  complete input descriptions for source-code-independent clients.
- Replaced atomic MCP tools with compact manager/action tools and lazy exact
  operation specifications, reducing the serialized tool catalog by over 80%.

## 0.2.1 - 2026-08-27

- Added a read-only skill for inspecting readiness and the current ontology.
- Added Codex-native metadata for both bundled skills.
- Kept Claude and Kimi bundles free of Codex-only skill sidecars and added a
  regression test for the host-specific layouts.

## 0.2.0 - 2026-08-27

- Added dynamic, incrementally discovered ontology with optional declarations.
- Added provenance-bearing namespace, entity, field, and relation descriptions
  to ontology discovery.
- Added streaming JSONL patch/upsert and explicit cross-dataset joins.
- Changed import-key resolution to drive from the existing typed attribute index,
  avoiding a growing node scan for each incoming record.
- Added agent-discoverable JSON Query IR v1, typed MCP contracts, node bindings,
  structured errors, traversal, explanations, and current metrics.
- Added evidence verification, audit, retention, snapshots, and portable local
  package resources.
- Added exact semantic retrieval with public-only external embedding policy.
- Added a conforming PostgreSQL 17 backend and verified canonical
  SQLite-to-PostgreSQL transfer.
- Added crash, corruption, compatibility, distribution-safety, snapshot, and
  reproducible benchmark gates for the working v1 release.

## 0.1.0

- Established the local-first evidence store, canonical relational model,
  abstract interfaces, SQLite migrations, CLI, and stdio MCP foundation.
