# Changelog

## Unreleased

- Expose resource and operation specifications through `memory_discover` for
  hosts without a resource browser, with optional top-level section selection.
- Include a version-checked unattended Kimi Code installer, preserving other
  plugins and previous copies while preparing the complete plugin runtime.
- Direct plugin skills to use native host tools and wait for activation instead
  of constructing auxiliary clients.

- Fix the Kimi bundle's working-directory path so the host loads its MCP server.
- Default MCP v1 queries and native drill-down to compact values and record IDs;
  preserve full responses with `payload.response_format="full"` and explicit
  provenance expansion. Python/CLI defaults and stored snapshots are unchanged.
- Add verified freshness-only analysis reads with `document.view="status"`.
- Teach plugin skills to reuse stable contracts and keep routine table output
  compact, while refreshing current ontology and data state after writes.

All notable changes to Analytical Memory are documented here.

## 0.7.1 - 2026-10-17

- Start the human quickstart with a single plugin-installation request, then
  guide the retail example through prompts, expected answers and structure diagrams.
- Explain assistant-owned bundle selection, verification, installation and
  activation; prepare locked dependencies before the first server startup.
- Include a retail operation reference in the usage skill so assistants can
  locate fixtures and perform each requested stage through the plugin.

## 0.7.0 - 2026-10-17

- Add Query IR v2 native optional groups, identity-aware counts and integer sums,
  exact ratios, stable group IDs and named consistent analysis bundles.
- Add generation/revision guards, live and immutable saved drill-down, explicit
  analytical capture, native Metric separation and freshness/privacy checks.
- Add additive SQLite/PostgreSQL migrations, snapshot format 2 with verified
  0.6.1 restore compatibility, and transfer format 2 with native manifests.
- Replace the default quickstart with an orders/support delivery walkthrough;
  retain the original smoke example under `memory-quickstart --smoke`.
- Make installation bundle-first and add a command-by-command quickstart with
  actual result excerpts and evolving ontology diagrams; link plugin
  installation directly from the product README.
- Unify installation around the complete plugin, add a generic bundle and
  OpenCode 2 configuration generator for its skills and included MCP server,
  and include PostgreSQL dependencies in every host launch.

## 0.6.1 - 2026-10-17

- Reorganized human documentation around a product README, a guide index,
  a runnable walkthrough, and separate MCP, plugin, and release instructions.
- Corrected architecture and reference descriptions to match the implemented
  import, query, search, provenance, and snapshot contracts.
- Included linked documentation in all plugin bundles and added local Markdown
  link and heading checks to CI and bundle validation.
- Documented Docker PostgreSQL setup and made real PostgreSQL conformance part
  of the complete local verification procedure.

## 0.6.0 - 2026-09-02

- Made local full-text search depend only on the field's `searchable` flag,
  while keeping public export and external embeddings privacy-filtered.
- Allowed entity redeclaration to reclassify current Nodes, attributes,
  relations, and search documents between public and private in either
  direction without changing evidence privacy history.

## 0.5.5 - 2026-08-31

- Corrected the agent-visible `required` description to match the
  required-on-create import contract introduced in 0.5.4.
- Moved the MCP server instruction, complete agent guide, and shared
  field-declaration descriptions into one packaged JSON resource.
- Added contract tests that keep input and output schemas aligned with the
  packaged agent guidance and verify its presence in distributions.

## 0.5.4 - 2026-08-31

- Defined declared required fields as required when an import creates a Node,
  while updates may omit them and retain their current values.
- Kept required-field declaration changes prospective so schema evolution does
  not retroactively invalidate or lock existing Nodes.
- Added regression coverage for partial updates, atomic rollback on incomplete
  creation, explicit nullability, and required-field schema migration.

## 0.5.3 - 2026-08-30

- Applied the canonical Ruff formatting required by the complete CI gate.

## 0.5.2 - 2026-08-30

- Reduced the always-visible MCP instruction and tool surface while linking
  manager actions directly to their lazy operation specifications.
- Added an additive agent catalog projection and a compact, per-memory summary
  without changing persisted catalog or physical storage contracts.
- Clarified operation-specific idempotency, fingerprint mapping, and targeted
  stale-contract recovery in lazy specifications.
- Preserved complete high-level discovery names and descriptions through lazy
  progressive disclosure instead of mechanical truncation.
- Restored the structural contract fingerprint in replayed JSONL import results.

## 0.5.1 - 2026-08-28

- Applied the canonical Ruff formatting required by the full CI gate without
  changing lifecycle behavior.

## 0.5.0 - 2026-08-28

- Added one explicit lifecycle surface for inspecting destructive guard counts,
  wiping default or named memories, and deleting named memories.
- Required exact node, attribute, active-relation, and evidence-object counts so
  stale destructive requests fail closed, plus a full canonical-row fingerprint
  rechecked under a backend write lock.
- Removed canonical data and raw evidence on wipe, and removed backing storage
  plus the catalog entry on named-memory deletion.
- Added matching CLI commands, MCP discovery contracts, agent guidance, and
  SQLite regression coverage.

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
