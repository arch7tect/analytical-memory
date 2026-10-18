# Documentation

The assistant installs a downloaded, verified release bundle. Source checkout
commands are for contribution and release work. The quickstart is a human
conversation: installation request, analytical questions, expected answers and
visible structure changes. The root README links
directly to plugin installation for assistants arriving via the GitHub repository.

## Get started

| Guide | Use it to |
| --- | --- |
| [Getting started](getting-started.md) | Ask your assistant to install, import, connect, aggregate and explain results |
| [Plugin installation](plugin-installation.md) | Install the complete plugin for Claude, Kimi, Codex, or a generic host such as OpenCode |

## Use and operate the memory

| Reference | Covers |
| --- | --- |
| [MCP](reference/mcp.md) | Configuration, named memories, resources, tools, and errors |
| [Native analytics](reference/native-analytics.md) | Aggregates, exact drill-down, saved observations and freshness |
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
- [Backlog](backlog.md) tracks deferred ideas; these are not supported features
  or a committed release plan.

## Decision and delivery history

[Design history](archive/README.md) indexes accepted decisions, completed delivery
records, and archived proposals. These documents remain in the source repository;
plugin bundles include current documentation and link to the repository for history
and the backlog.

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
