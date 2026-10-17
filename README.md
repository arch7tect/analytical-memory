# Analytical Memory

Analytical Memory helps you explore connected datasets and trace answers back
to their sources. It keeps structured data, explicit relationships, analytical
results, and the evidence behind them in a memory you control locally.

Use it with an MCP-compatible assistant, from the command line, or through its
Python API. SQLite works out of the box; the included Docker setup runs
PostgreSQL 17 when you need a separate database.

## Install and try

**[Plugin installation instructions](docs/plugin-installation.md)** — the entry
point for installing Analytical Memory with an assistant. Give your assistant
this request:

> Install the plugin https://github.com/arch7tect/analytical-memory/

The assistant follows the linked guide. One release bundle
includes the MCP server, shared skills, documentation, and examples.

- [Claude Code, Kimi Code, and Codex](docs/plugin-installation.md) use their host
  plugin installation.
- [Generic environments, with OpenCode](docs/plugin-installation.md#generic-environments-opencode)
  connect the same plugin's skills and included server in one configuration.
- [Quickstart for people](docs/getting-started.md) starts with that installation request,
  then walks through prompts, expected answers, and the evolving structure.
- [Documentation](docs/README.md) covers configuration, querying, operations,
  architecture, and development.

## What you can do

- **Bring datasets together.** Import JSONL files independently and connect
  matching records through explicit join rules.
- **Explore what is available.** Discover entity types, fields, relationships,
  and descriptions as the memory grows.
- **Ask precise questions.** Filter, group, sum and count distinct entities, follow relationships,
  search text, and optionally find semantically related content.
- **Inspect the evidence.** Trace current values and analytical results to
  their source data and recorded method.
- **Keep projects separate.** Use a default memory or configure independent
  named memories.
- **Back up your work.** Verify evidence, create private restore snapshots,
  and export public data for sharing.

For example, import orders and support tickets separately, connect them, compare
delivery complaint rates, and drill into the exact orders behind one result. The
[getting started guide](docs/getting-started.md) walks through this example.

## What to expect

The current implementation supports atomic JSONL imports, explicit graph joins,
structured queries with native aggregates and exact drill-down, saved analytical
observations with freshness checks, local full-text search, optional semantic search,
and verified snapshots. See the [release history](CHANGELOG.md) for changes.

Your database and evidence stay on your machine or your chosen PostgreSQL
deployment. Optional semantic search sends eligible public text and query text
to an external embedding provider. The core workflows need no API key.

Data is public by default. Declare private entities or fields before importing
sensitive data. Public/private labels govern sharing and external processing;
local queries can read private data. See [data handling and privacy](docs/getting-started.md#data-handling-and-privacy).

The memory keeps current values and source evidence. It does not automatically
infer relationships. Explicitly saved analyses retain their original input
values for historical drill-down; other current values have no general history. It is a local tool without
multi-user authentication or a hosted HTTP service.

## Contributing and license

[Contributing](CONTRIBUTING.md) explains setup and verification.
Analytical Memory is licensed under [Apache License 2.0](LICENSE).
