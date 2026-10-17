# Documentation

User guides run from a downloaded, verified release bundle. Source checkout
commands are for contribution and release work. The quickstart is a human
walkthrough with commands and results. The root README links
directly to plugin installation for assistants arriving via the GitHub repository.

## Get started

| Guide | Use it to |
| --- | --- |
| [Getting started](getting-started.md) | Use a bundle: import, connect, aggregate and drill with commands and results |
| [Plugin installation](plugin-installation.md) | Install the complete plugin for Claude, Kimi, Codex, or a generic host such as OpenCode |

## Use and operate the memory

| Reference | Covers |
| --- | --- |
| [MCP](reference/mcp.md) | Configuration, named memories, resources, tools, and errors |
| [Querying](reference/querying.md) | Structured query syntax, supported operators, results, and limits |
| [Text and semantic retrieval](reference/semantic-retrieval.md) | Searchable fields, local full-text search, and optional external embeddings |
| [Operations](reference/operations.md) | Readiness, integrity, snapshots, transfer, and guarded deletion |
| [Evidence portability](reference/evidence-portability.md) | Evidence identities, fragments, privacy, retention, and export formats |
| [Backend portability](reference/backend-portability.md) | PostgreSQL in Docker, conformance tests, and verified backend transfer |

## Understand and contribute

- [System design](design.md) describes the implemented architecture and its
  invariants; deferred capabilities are listed separately.
- [Contributing](../CONTRIBUTING.md) contains development and verification steps.
- [Release guide](releasing.md) covers artifacts and publication.
- [Changelog](../CHANGELOG.md) records changes by version.

## Decision and delivery history

- [ADR 0001](decisions/0001-dynamic-ontology-query-ir.md) records the accepted
  dynamic ontology and Query IR decision, with subsequent contract clarifications.
- [Implementation history](implementation-plan.md) retains completed milestone
  acceptance criteria. Milestones 0–4 describe a superseded ingestion model;
  use the current guides for commands and behavior.

## Native analytics

- [Native analytics reference](reference/native-analytics.md): v2 queries,
  bundles, observations, freshness and exact detail.
- [ADR 0002](decisions/0002-native-analytics-observations.md): accepted decisions.
- [Delivery record](native-analytics-delivery.md): slices, verification and limits.
- [Accepted proposal](proposals/native-analytics-and-quickstart.md): original
  requirements and fixture expectations; the reference defines current syntax.

## Documentation maintenance

Keep the product overview in the root README, procedures in guides, and exact
behavior in references. Agent instructions live in `plugin/skills/` and the
packaged MCP resources, rather than in the product README.

When changing behavior, update its guide or reference and link it here. Preserve
decision history with explicit status and supersession notes. The packaged
structural schema, Query IR contract, and runtime capabilities define exact
machine-readable shapes; prose should explain them without inventing additional
operators or interfaces.

Run `uv run python scripts/check_docs.py` to check repository Markdown links
and heading anchors. This check also runs in CI. Host installation syntax should
be checked against the host's current documentation and local CLI help when
editing an installation guide.
