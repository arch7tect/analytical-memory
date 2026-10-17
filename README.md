# Analytical Memory

Analytical Memory helps you explore connected datasets and trace answers back
to their sources. It keeps structured data, explicit relationships, analytical
results, and the evidence behind them in a memory you control locally.

Use it with an MCP-compatible assistant, from the command line, or through its
Python API. SQLite works out of the box; PostgreSQL 17 is available for a
separate database deployment.

## What you can do

- **Bring datasets together.** Import JSONL files independently and connect
  matching records through explicit join rules.
- **Explore what is available.** Discover entity types, fields, relationships,
  and descriptions as the memory grows.
- **Ask precise questions.** Filter and count records, follow relationships,
  search text, and optionally find semantically related content.
- **Inspect the evidence.** Trace current values and analytical results to
  their source data and recorded method.
- **Keep projects separate.** Use a default memory or configure independent
  named memories.
- **Back up your work.** Verify evidence, create private restore snapshots,
  and export public data for sharing.

For example, import sessions and messages from two files, connect each message
to its session, and find the messages associated with failed sessions. The
[getting started guide](docs/getting-started.md) walks through this example.

## Start here

- [Install the MCP server](docs/mcp-installation.md) to connect your assistant.
- [Install a plugin](docs/plugin-installation.md) for Claude Code, Kimi Code,
  or Codex, including the MCP server and bundled workflows.
- [Try the command-line walkthrough](docs/getting-started.md) with synthetic
  sample data.
- [Browse the documentation](docs/README.md) for configuration, querying,
  operations, architecture, and development.

## What to expect

The current implementation supports atomic JSONL imports, explicit graph joins,
structured read-only queries, local full-text search, optional semantic search,
and verified snapshots. See the [release history](CHANGELOG.md) for changes.

Your database and evidence stay on your machine or your chosen PostgreSQL
deployment. Optional semantic search sends eligible public text and query text
to an external embedding provider. The core workflows need no API key.

Data is public by default. Declare private entities or fields before importing
sensitive data. Public/private labels govern sharing and external processing;
local queries can read private data. See [data handling and privacy](docs/getting-started.md#data-handling-and-privacy).

The memory keeps current values and source evidence. It does not automatically
infer relationships or reconstruct earlier values. It is a local tool without
multi-user authentication or a hosted HTTP service.

## Contributing and license

[Contributing](CONTRIBUTING.md) explains setup and verification.
Analytical Memory is licensed under [Apache License 2.0](LICENSE).
