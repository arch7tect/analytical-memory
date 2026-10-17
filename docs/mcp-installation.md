# MCP installation

This guide connects the standalone Analytical Memory MCP server to a local
assistant. The server uses stdio: the client starts a local process and talks
to it over standard input and output. It has no HTTP URL or OAuth login.

If you want the server plus bundled import/query and inspection skills, use
[plugin installation](plugin-installation.md). Choose one installation route
per client to avoid duplicate servers.

## 1. Install and initialize

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and clone
the repository. Python 3.12 or newer is required; uv can provision it.

```console
git clone https://github.com/arch7tect/analytical-memory.git
cd analytical-memory
uv sync --locked --no-dev
```

Choose permanent absolute paths for your database and evidence root. Add these
values to the ignored `.env` in the repository root, replacing the examples:

```dotenv
ANALYTICAL_MEMORY_DB=/absolute/path/to/memory-data/memory.db
ANALYTICAL_MEMORY_EVIDENCE_ROOT=/absolute/path/to/memory-data/evidence
```

Absolute paths keep the selected store consistent when the assistant starts in
a different project. Then initialize it and verify readiness:

```console
uv run --locked --no-dev memory init
uv run --locked --no-dev memory status
```

An API key is unnecessary for imports, structured queries, graph traversal, and
local full-text search. Configure PostgreSQL or external embeddings only if you
need them; see the [configuration reference](reference/mcp.md#configuration).

For PostgreSQL, follow the [Docker setup](reference/backend-portability.md#select-a-backend),
set its connection in the same checkout `.env`, and include `--extra postgres`
in both initialization and the client's `uv run` arguments. For example, the
server command becomes `uv run --directory /absolute/path/to/analytical-memory
--locked --no-dev --extra postgres memory-mcp`. Keep the database container
running while the client uses that memory.

## 2. Register the server with your client

Replace `/absolute/path/to/analytical-memory` with the checkout path. The client
must be able to find `uv`; use the absolute uv executable path if its environment
does not include your shell's PATH. Keep the checkout in place after registration.

### Codex

Run in a terminal:

```console
codex mcp add analytical-memory -- uv run \
  --directory /absolute/path/to/analytical-memory \
  --locked --no-dev memory-mcp
codex mcp list
```

Start a new chat or restart the client connection. In the CLI, `/mcp` shows the
active server. See the [official MCP configuration guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
for manual configuration and startup timeouts.

### Claude Code

Run in a terminal:

```console
claude mcp add --transport stdio --scope user analytical-memory -- uv run \
  --directory /absolute/path/to/analytical-memory \
  --locked --no-dev memory-mcp
claude mcp list
```

Start a new session and check `/mcp`. The
[official MCP guide](https://code.claude.com/docs/en/mcp) explains scopes and
connection diagnostics.

### Other local stdio clients

For clients that use an `mcpServers` JSON configuration, merge this entry into
their existing settings:

```json
{
  "mcpServers": {
    "analytical-memory": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/absolute/path/to/analytical-memory",
        "--locked", "--no-dev", "memory-mcp"
      ]
    }
  }
}
```

Clients with another configuration format need the same command and arguments.
The `--directory` option makes the server load the checkout's `.env` and resolve
any remaining relative paths there. A remote-only client cannot directly launch
this stdio server.

## 3. Verify the connection

Ask your assistant:

> Inspect Analytical Memory's catalog and report whether the default memory is
> ready, which entity types it contains, and which operations are available.

A working connection exposes `memory://guide`, `memory://catalog`, and tools
such as `memory_query_manage`. A fresh initialized memory is ready but empty.
The assistant can discover the schema and ontology through MCP; it does not
need access to repository code. See the [MCP reference](reference/mcp.md) for
the complete surface.

To check the repository's real stdio integration independently of your client:

```console
uv run --locked python scripts/mcp_smoke.py
```

This check uses isolated temporary stores and synthetic data.

## Troubleshooting and upgrades

| Symptom | Check |
| --- | --- |
| Client cannot launch `uv` | Use the absolute executable path and restart the client |
| Store is uninitialized | Run `memory init` from the configured checkout, then check `memory status` |
| Expected records are missing | Verify the database/evidence paths and selected memory name; plugin and standalone defaults differ |
| JSONL file cannot be read | Supply an absolute path accessible to the local server process |
| Server times out during startup | Run dependency installation in the terminal first; inspect the client's MCP error log |
| Semantic search is degraded | Check the optional API key and embedding profile using the [retrieval reference](reference/semantic-retrieval.md) |

Before upgrading, create and verify a private snapshot using the
[operations guide](reference/operations.md). Review the [changelog](../CHANGELOG.md),
stop connected server processes, update the checkout, sync locked dependencies,
and run `memory init` with the same configured paths before reconnecting.
Initialization applies compatible pending migrations; unknown versions fail
closed. Pre-M5 development databases use a superseded model and must not be
upgraded in place without preserving their source data.
