# Native analytics delivery record

Status: delivered in Analytical Memory 0.7.0.
Design: [ADR 0002](decisions/0002-native-analytics-observations.md).
Public behavior: [native reference](reference/native-analytics.md).

## Slices

| Slice | Implementation | Verification |
| --- | --- | --- |
| 1. Contracts and fixtures | Separate v2 models/dispatcher, exact retail fixtures, generated contract, accepted decision | Original v1 suite and v2 validation |
| 2. Revisions and transactions | Per-memory generation/revision, all-writer lock and fact digest, explicit snapshots | Replay, rollback, provenance updates, concurrent reader/writer and capture/writer |
| 3. Native calculations | Anchored optional, typed scalar groups, distinct identities, integer sums, exact ratios and named bundles | SQLite/PostgreSQL business fixture, empty/null populations, resource failures |
| 4. Detail and coverage | Server-reconstructed membership, ratio denominator detail, join inspection and guarded pages | Four contacts/one order/three denominator orders; stale-page rejection and join reasons |
| 5. Capture and portability | Immutable manifests, native Metrics, freshness/privacy, mandatory retention, snapshot 2 and transfer 2 | Capture replay/commit rollback, metadata verification, privacy tightening, missing evidence, saved values after restore, real 0.6.1 snapshot |
| 6. Walkthrough and interfaces | Human/default and versioned JSON output, optional extensions, persistent named memory, lazy MCP specs, shared plugin skills | CLI walkthrough, stdio MCP, packages and four plugin bundle checks |

## Consultation decisions

Claude was consulted before implementation and on the native engine/store diff.
Confirmed findings led to generation rotation on restore, manifest/observation
metadata comparison, no-op declaration replay tests, commit-failure cleanup and
SUM contributor detail. A final follow-up found a SUM group-ID shadowing defect;
the repair has a dedicated identity assertion. Exact ratio ordering, null ordering,
integer-valued numeric input and cancellation also have regression checks. Concurrent read/capture scenarios run on both backends.

Plain `count` and SUM without `distinct_on` deliberately count binding
occurrences. Optional fan-out is part of that contract; changing those measures
to implicitly deduplicate would violate the accepted example (40000 versus
10000 cents for FastShip South). Tests and reference make the difference explicit.
Local private detail remains allowed under the existing product privacy model;
native public reuse invokes its explicit freshness/privacy gate.

## Initial implementation limits

The evaluator uses a bounded memory fact snapshot in the server. Writer change
detection hashes current facts twice. Captures conservatively retain that bounded
fact population and referenced provenance; their privacy can therefore be stricter
than the selected fields alone. Incremental revision tracking and finer capture
footprints are deferred optimizations, not weaker correctness gates.

Referenced manifests remain required. There is no implicit observation deletion
or evidence cleanup. Old observations retain historical values after restore,
with unknown freshness in the target generation. An explicit new capture is
needed for a current result. No external embedding provider is required or called
by the core/extended walkthrough.

## Verification log

Final local verification on 2026-10-17:

- `uv sync --all-groups --extra postgres --locked` completed.
- Full suite: **189 passed**, including real PostgreSQL 17 in Docker and SQLite;
  no backend skips. This includes additive upgrade of populated pre-native stores,
  original 0.6.1 snapshot/transfer restoration, concurrency, commit rollback,
  exact arithmetic, membership manifests, native API/CLI/stdio MCP and legacy v1.
- Ruff lint/format, strict mypy, compiled schema/Query IR checks and Markdown links
  passed.
- Legacy smoke, extended retail walkthrough, MCP smoke and deterministic
  benchmark passed. The representative SQLite benchmark remained below one second
  locally; this is a check result, not a scalability guarantee.
- Wheel and sdist installed and ran the new walkthrough in independent clean
  environments. Distribution scans passed.
- All four host/generic plugin bundles built; shared skill/doc checks passed. All seven
  release candidate artifacts built in a fresh temporary directory; no existing
  release assets were overwritten or published.
- Earlier SQLite/PostgreSQL migration manifest entries and checksums are unchanged.

Twelve MCP tools are retained. The existing bounds remain enforced: tools/list
23,600 bytes, individual manager tool 1,600 bytes, operations index 6,000 bytes,
guide 5,100 bytes, contextual capabilities 10,000 bytes. Capabilities version 6
shares interface defaults; operations index version 3 keeps detailed effects in
individual lazy specs.

Publication follows the [release guide](releasing.md), with CI required on the
release commit before publishing versioned archives.

## Unified plugin installation acceptance

Installation now has one entry point in the product README. A fourth, generic
bundle contains the same runtime and shared skills, plus an OpenCode 2
configuration generator. The former MCP installation page links to that guide.
All host launchers include the PostgreSQL extra; Docker remains the documented
PostgreSQL setup.

Local acceptance used OpenCode 2.0.29 and an extracted generic release archive:

- OpenCode connected to the included MCP server, exposed its eight discovery
  resources, discovered both shared skills, and loaded the inspection skill.
- The configured runtime command passed MCP imports of 12 orders and 16 tickets,
  materialized 14 edges, and returned seven affected orders with coverage
  16 imported / 12 delivery / 10 attributed / 2 unattributed contacts.
- No model provider was required for host discovery, skill loading, or the
  direct MCP operation checks.
- All four archives and both Python distributions passed content scans and
  checksum verification. The full SQLite/PostgreSQL suite passed 189 tests.

The [installation guide](plugin-installation.md#generic-environments-opencode)
contains the reproducible host setup. Configuration shapes follow the
[OpenCode 2 MCP](https://opencode.ai/v2/docs/mcp-servers/) and
[skills](https://opencode.ai/v2/docs/skills/) contracts.
