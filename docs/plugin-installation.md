# Plugin Installation

The plugin bundles the local MCP server, import/query and read-only inspection
skills, and human documentation for Claude Code, Kimi Code, and Codex. It
initializes its default memory automatically. For a server without skills, use
[MCP installation](mcp-installation.md).

## Prepare a bundle

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), the
selected host, and network access for the first dependency installation. The
runtime selects Python 3.12 through uv. No API key is needed for core workflows.

Choose either a release archive or a source build:

- Download the archive ending in `-claude.tar.gz`, `-kimi.tar.gz`, or
  `-openai.tar.gz` from [GitHub Releases](https://github.com/arch7tect/analytical-memory/releases).
  Verify it against that release's `SHA256SUMS` file and extract it into a
  permanent local directory. The extracted directory corresponds to
  `dist/plugins/<host>` in the commands below; substitute its absolute path.
- To build from source, clone the repository and run from its root:

```console
git clone https://github.com/arch7tect/analytical-memory.git
cd analytical-memory
uv run --locked python scripts/build_plugin_bundles.py
```

The first server start creates a Python environment in the host's plugin copy.
The commands below use the source-build paths. Install only one Analytical
Memory server route per host to avoid duplicate connections.

## Claude Code

```console
claude plugin marketplace add --scope user "$(pwd)/dist/plugins/claude"
claude plugin install --scope user analytical-memory@analytical-memory-local
```

Start a new session or run `/reload-plugins`. Check `/mcp` for the server.
See the [Claude Code marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces)
for host-specific installation and scope behavior.

## Kimi Code

In Kimi Code, run:

```text
/plugins install <absolute repository path>/dist/plugins/kimi/analytical-memory
/plugins info analytical-memory
/reload
```

Check the plugin diagnostics for its MCP server. Local installs are copied by
the host; reinstall after rebuilding the source bundle. See the
[Kimi Code plugin guide](https://moonshotai.github.io/kimi-code/en/customization/plugins.html).

## Codex

```console
codex plugin marketplace add "$(pwd)/dist/plugins/openai"
codex plugin add analytical-memory@analytical-memory-local
codex plugin list
```

Start a new Codex chat after installation. These commands require a CLI with
`codex plugin` support; check `codex plugin --help`. If your client does not
support local marketplaces, use the [standalone MCP route](mcp-installation.md#codex).

## Verify the connection

Ask the assistant to inspect the memory catalog and report readiness and entity
types in the default memory. A new store is ready but empty. Both bundled skills
should be available: `analytical-memory` and `analytical-memory-inspect`.
Use [getting started](getting-started.md) for the sample data workflow and the
[MCP reference](reference/mcp.md) for named memories and tool details.

## Local Data

Plugin data is stored outside the installed plugin cache so upgrades do not
replace it:

- macOS: `~/Library/Application Support/analytical-memory/`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/analytical-memory/`
- Windows: `%LOCALAPPDATA%\analytical-memory\`

The SQLite database is initialized automatically on first start. The default
database is `memory.db` and raw evidence is under `evidence/`. Put optional
configuration such as `OPENAI_API_KEY` or PostgreSQL settings in `.env` inside
that directory. Set `ANALYTICAL_MEMORY_PLUGIN_DATA` to use another directory.

All three host bundles use this data directory by default, so they see the same
memory. The standalone source installation instead defaults to `.local/` in
its working directory. Keep configuration consistent when accessing a memory
from both routes. Backups must include canonical records and evidence; see
[operations](reference/operations.md).

The plugin runtime installs base dependencies only. For PostgreSQL, use the
[standalone MCP installation](mcp-installation.md) with the `postgres` extra
and the [backend configuration](reference/backend-portability.md).

The same directory contains `memories.json` after the first named memory is
configured. This file is only a local address book: it maps a short memory name
to a SQLite path or to a PostgreSQL connection-environment name and schema, plus
its evidence root. It contains no database URL, password, records, ontology, or
active-memory state. Omitting `memory` in any tool continues to use the single
default `memory.db` and `evidence/` pair.

## Upgrade and troubleshoot

Before upgrading, create and verify a private snapshot. Review the
[changelog](../CHANGELOG.md), obtain or rebuild the new host bundle, and update
or reinstall it through the host. Start a fresh session and check readiness.
Upgrades keep data outside the plugin cache; schema compatibility is still
checked on initialization. Preserve pre-M5 development data before attempting
any upgrade from that superseded model.

If the server fails to launch, check that the host can find `uv`, inspect its
MCP diagnostics, and allow time for the first dependency installation. If the
memory appears empty, compare the configured data directory and selected name.
See [MCP troubleshooting](mcp-installation.md#troubleshooting-and-upgrades) for
other connection issues. Maintainer build and publication steps are in the
[release guide](releasing.md).
