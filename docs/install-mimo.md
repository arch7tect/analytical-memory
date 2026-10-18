# Install the plugin in MiMo Code

Use this guide when the user asks MiMo Code to install
<https://github.com/arch7tect/analytical-memory/>. Install one **generic release
bundle**, containing both skills and the MCP server. This configuration and the
bounded checks below are verified with MiMo Code 0.1.15.

## 1. Get the bundle

Resolve the latest stable [GitHub release](https://github.com/arch7tect/analytical-memory/releases)
and download `analytical-memory-<version>-generic.tar.gz` and its release
`SHA256SUMS` file. Use an explicitly supplied local candidate instead when testing.
Verify the archive's SHA-256, then unpack into a permanent directory. Set
`PAYLOAD_ROOT` to its `analytical-memory/` directory (containing `pyproject.toml`,
`.mcp.json`, `skills/` and `scripts/`). Set `WORKSPACE` to the user's current project.
Do not clone or build from source. Preserve existing installations and memories.

Check `uv --version` and `mimo --version`. If uv is absent, follow its
[official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
Do not inspect the MiMo executable, search host internals, print full configuration,
or dump skill bodies to discover installation syntax; the bundled command below
already implements it. No model/provider or authentication changes are needed.

## 2. Connect both skills and the server

```console
uv sync --project "$PAYLOAD_ROOT" --frozen --no-dev --no-editable --extra postgres --python 3.12
uv run --project "$PAYLOAD_ROOT" --frozen --no-dev --no-editable --extra postgres --python 3.12 \
  python "$PAYLOAD_ROOT/scripts/configure_mimo.py" --workspace "$WORKSPACE"
```

Expected: `Configured both plugin skills and MCP: …/.mimocode/mimocode.jsonc`.
The generated project configuration connects both skills and the included stdio
server with absolute paths and a 10-minute timeout. Keep the payload at that path.
SQLite works immediately; no separate MCP package or embedding key is required.

For an isolated installation, add `--data-root /absolute/path/to/test-data` to the
configuration command. An existing `ANALYTICAL_MEMORY_PLUGIN_DATA` environment
variable is also honored. Otherwise the plugin uses its normal per-user data
location. For PostgreSQL use the [Docker setup](reference/backend-portability.md#select-a-backend).

An identical repeat is accepted. Existing different settings, JSONC comments and
other config files are preserved: run the same command with `--print`, then merge
only `skills.paths` and `mcp.analytical-memory` into the active configuration.
Preserve other settings; replace an old Analytical Memory connection rather than
adding a duplicate. Do not edit credentials or global model configuration.

## 3. Check and activate

```console
uv run --project "$PAYLOAD_ROOT" --frozen --no-dev --no-editable --extra postgres --python 3.12 \
  python "$PAYLOAD_ROOT/scripts/configure_mimo.py" --workspace "$WORKSPACE" --check
```

This checks MiMo's resolved launch command, skill inventory and `mimo mcp list`,
returning one short JSON
summary: both skills `available`, MCP `connected`, readiness pending activation.
It does not speak MCP or query the memory. Do not print the unfiltered skill
inventory: it contains entire skill documents.

Reload/restart MiMo and **resume this conversation**, retaining its history.
Before reload, report **configured; activation pending** and stop the installation
turn. Never construct an auxiliary MCP client or probe, use the Python API, or
inspect database files to work around tools not yet appearing.

After reload, use the actual plugin tool `memory_discover` with
`uri="memory://catalog"`, then `uri="memory://memories/default/summary"`.
Confirm ready status. A fresh installation is empty; preserve existing data on
repeat installs. Both `analytical-memory` and `analytical-memory-inspect` must be
available. The next quickstart request may perform these checks and continue in
the same turn. If native tools are unavailable, keep activation pending and use
the bounded check above; do not substitute a client.

Report the version, two skills, connection and readiness briefly. Then follow the
[human quickstart](getting-started.md) when asked. The installed usage skill's
`references/retail-demo.md` locates all fixtures and explains native operations.
Load that skill and read its recipe before any data-step action. After activation,
do not run shell/Python checks, preview/count JSONL, or create directories:
the plugin configures its storage, imports files, queries samples and reports
join coverage. Host file reads are for instructions and JSON query definitions.
