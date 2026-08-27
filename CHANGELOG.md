# Changelog

All notable changes to Analytical Memory are documented here.

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
