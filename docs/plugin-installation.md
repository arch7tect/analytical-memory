# Plugin Installation

The plugin bundles the same local MCP server and skills for Claude Code, Kimi
Code, and Codex. Build all three variants from the repository root:

```console
uv run python scripts/build_plugin_bundles.py
```

Only `uv` and the selected host are required. The first start creates a private
Python environment in the host's plugin copy.

## Claude Code

```console
claude plugin marketplace add --scope user "$(pwd)/dist/plugins/claude"
claude plugin install --scope user analytical-memory@analytical-memory-local
```

Start a new session or run `/reload-plugins`.

## Kimi Code

In Kimi Code, run:

```text
/plugins install <absolute repository path>/dist/plugins/kimi/analytical-memory
/plugins info analytical-memory
/reload
```

## Codex

```console
codex plugin marketplace add "$(pwd)/dist/plugins/openai"
codex plugin add analytical-memory@analytical-memory-local
codex plugin list
```

Start a new Codex task after installation.

## Local Data

Plugin data is stored outside the installed plugin cache so upgrades do not
replace it:

- macOS: `~/Library/Application Support/analytical-memory/`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/analytical-memory/`
- Windows: `%LOCALAPPDATA%\analytical-memory\`

The SQLite database is initialized automatically on first start. Put optional
configuration such as `OPENAI_API_KEY` or PostgreSQL settings in `.env` inside
that directory. Set `ANALYTICAL_MEMORY_PLUGIN_DATA` to use another directory.

The same directory contains `memories.json` after the first named memory is
configured. This file is only a local address book: it maps a short memory name
to a SQLite path or to a PostgreSQL connection-environment name and schema, plus
its evidence root. It contains no database URL, password, records, ontology, or
active-memory state. Omitting `memory` in any tool continues to use the single
default `memory.db` and `evidence/` pair.

## Release Build

Build the Python wheel, source distribution, three host archives, and their
SHA-256 file locally:

```console
uv run python scripts/build_release.py --tag v0.5.5
```

Artifacts are written to `dist/release/`. In GitHub Actions, every pull request
and main-branch push builds both the unpacked plugin bundles and a complete
release candidate. Pushing a tag that matches the project version, such as
`v0.5.5`, rebuilds the same artifacts and publishes them to a GitHub Release.

For the normal publishing path, open the `Release` workflow in GitHub Actions,
select `Run workflow` on `main`, and start it. The workflow reads
`project.version`, creates the matching `v<version>` tag on the selected `main`
commit, and publishes the release. It refuses to replace an existing tag or
release. Pushing a matching tag manually remains supported.
