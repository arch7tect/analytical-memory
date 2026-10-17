# Plugin installation from a bundle

Install Analytical Memory as one plugin: the archive contains its MCP server,
import/query and inspection skills, documentation, and example data. The host
starts the included server; there is no separate MCP installation.

## Instructions for an assistant performing installation

The human entry point is a single request:

> Install the plugin https://github.com/arch7tect/analytical-memory/

Own the complete installation from that request. Read this guide through the
README link; do not send the user back to manual download or setup instructions.
Use the current assistant host when it is known (Codex for a request in Codex).
Ask which host only if the environment does not identify it. Use SQLite by
default; PostgreSQL is an explicit alternative with the Docker setup below.

1. Identify the requested host. Resolve the latest stable GitHub release (for
   example, `gh release view --repo arch7tect/analytical-memory` or the public
   GitHub releases API). Select its release archive below, or use the
   generic archive for OpenCode and other hosts without a matching marketplace.
2. Download the archive and checksum file from the same release, verify them,
   and extract into a permanent directory. Resolve `BUNDLE_ROOT` and `PAYLOAD_ROOT`.
   Do not clone the repository or build from source.
3. Check `uv` and the host's local help. If `uv` is missing, use its official
   installation instructions linked below and verify it is available to the host.
   Install the complete plugin using its
   host section. In a generic environment, connect **both** its shared skills
   and included server; OpenCode's generator configures both in one operation.
4. Preserve unrelated host settings and use one Analytical Memory connection.
   For PostgreSQL, configure the plugin's external data-directory `.env` and
   start the [Docker database](reference/backend-portability.md#select-a-backend).
5. After registering the clean bundle, [prepare the first launch](#prepare-the-first-launch).
   Reconnect the host and verify both skills and memory readiness. If the host
   loads plugins only in a fresh chat, report installation as pending activation
   and give that single next action; do not claim a live connection in the old
   chat. After activation, the first quickstart data request can perform the
   readiness check and continue. Report the installed version, verification
   status, and any required next action concisely. Keep installed/data paths
   available for troubleshooting. Do not import tutorial data during setup.
6. For the subsequent retail demo request, locate `examples/retail/` inside the
   installed payload. The usage skill's `references/retail-demo.md` describes
   the MCP operations and fixtures. The file map below also provides the handoff
   directly; consult the installed MCP operation specifications for exact payloads.
   Keep the human-facing quickstart free of installer commands and internal payloads.

Installation is complete when the host has the two skills and a working server,
not merely when an archive exists. Preserve existing memories on repeat requests;
inspect the installed version before choosing an upgrade or reporting it ready.
Do not register the GitHub source repository itself as a plugin marketplace:
the host-specific marketplace is generated inside its release archive.

### Retail example handoff

Resolve these files relative to the installed payload, including when the host
has copied it into its managed cache. Do not ask the user to locate files.

| Human request | Bundled file | Memory entity / key |
| --- | --- | --- |
| Orders | `examples/retail/orders.jsonl` | `shop.Order` / string `order_id` |
| Support tickets | `examples/retail/tickets.jsonl` | `shop.Ticket` / string `ticket_id` |
| Connect by order number | `examples/retail/join.json` | Explicit ticket-to-order join |
| Connected delivery rows | `examples/retail/linked-query.json` | Query across the explicit relation |
| Carrier and region aggregate | `examples/retail/query.json` | Native grouped query |
| Delivery analysis | `examples/retail/analysis.json` | Native analysis and coverage |
| Warehouse enrichment | `examples/retail/enrichment.jsonl` | Update `shop.Order` / string `order_id` |
| Ticket correction | `examples/retail/correction.jsonl` | Update `shop.Ticket` / string `ticket_id` |

Use a fresh named SQLite memory via `memory_configure`, with absolute database
and evidence paths outside the installed payload and other evidence roots.
Pass the chosen memory name to every subsequent operation. Never wipe an existing
demo to start again. Read the actual structural fingerprint and operation specs;
use native query/capture/drill actions to compute results from the imported data.

## Download and unpack

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and your
assistant. The first launch needs network access to obtain Python 3.12 and
locked Python dependencies. Core imports and analytics need no API key.

From [GitHub Releases](https://github.com/arch7tect/analytical-memory/releases),
download two files from **the same release**:

| Assistant | Archive | Payload directory inside the extracted archive |
| --- | --- | --- |
| Claude Code | `analytical-memory-<version>-claude.tar.gz` | `analytical-memory/` |
| Kimi Code | `analytical-memory-<version>-kimi.tar.gz` | `analytical-memory/` |
| Codex | `analytical-memory-<version>-openai.tar.gz` | `plugins/analytical-memory/` |
| Generic / OpenCode | `analytical-memory-<version>-generic.tar.gz` | `analytical-memory/` |

The second file is `analytical-memory-<version>-SHA256SUMS`. Use the numeric
version from the filenames, without the `v` tag prefix. The following commands
are for a macOS/Linux shell. Run them in the download directory; replace the
version placeholder and choose `claude`, `kimi`, `openai`, or `generic`:

```console
VERSION='<version from the downloaded filenames>'
HOST='openai'
ARCHIVE="analytical-memory-$VERSION-$HOST.tar.gz"
awk -v file="$ARCHIVE" '$2 == file' "analytical-memory-$VERSION-SHA256SUMS" | shasum -a 256 -c -
```

Expected: `analytical-memory-<version>-openai.tar.gz: OK`. Stop if verification
fails. On Linux, `sha256sum -c -` can replace `shasum -a 256 -c -`.

Extract to a permanent installation directory, then resolve the two paths:

```console
INSTALL_ROOT="$HOME/.local/opt/analytical-memory"
mkdir -p "$INSTALL_ROOT"
tar -xzf "$ARCHIVE" -C "$INSTALL_ROOT"
BUNDLE_ROOT="$INSTALL_ROOT/analytical-memory-$VERSION-$HOST"
case "$HOST" in
  openai) PAYLOAD_ROOT="$BUNDLE_ROOT/plugins/analytical-memory" ;;
  claude|kimi|generic) PAYLOAD_ROOT="$BUNDLE_ROOT/analytical-memory" ;;
esac
```

`BUNDLE_ROOT` is the marketplace root and has a README linking to installation
and the human quickstart. `PAYLOAD_ROOT` contains `pyproject.toml`,
`uv.lock`, `src/`, `docs/`, and `examples/retail/`. Keep the extracted bundle in
place. The [quickstart](getting-started.md) is a conversation with the installed
plugin. The assistant resolves example paths from its installed payload.

For Claude, Kimi, and Codex, register the clean extracted bundle before using
its payload for command-line diagnostics. If you used the payload for CLI work
first, extract a fresh copy into a different directory for plugin installation; this keeps its local
Python environment out of the host's managed copy. OpenCode uses the payload
in place, so its generator and server share the same environment.

## Claude Code

With `HOST=claude` and the corresponding archive extracted:

```console
claude plugin marketplace add --scope user "$BUNDLE_ROOT"
claude plugin install --scope user analytical-memory@analytical-memory-local
```

Start a new session or run `/reload-plugins`. Check `/mcp` for the server.
See the [Claude Code marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces)
for host-specific scope behavior.

## Kimi Code

With `HOST=kimi`, the bundle includes an unattended installer for **Kimi Code
0.39.1**. The assistant runs it from the verified extracted payload:

```console
uv run --no-project --python 3.12 python "$PAYLOAD_ROOT/scripts/install_kimi.py"
```

It uses `KIMI_CODE_HOME` when set, otherwise `~/.kimi-code`; `--home` selects an
isolated host directory and `--kimi` selects the executable. It copies both
skills and server into a fresh managed directory, prepares the locked runtime,
and registers the plugin using Kimi's version-1 installation registry. Other
plugin entries and settings are preserved. Updates retain the old copy and a
registry backup; identical repeat installs reuse the existing copy. Do not edit
plugin settings concurrently with installation.

The result reports the installed payload `root` and **pending activation**.
Keep that root to resolve example files. Restart Kimi or run `/reload`, then
call the native `memory_discover` tool with `uri="memory://catalog"`, followed
by `uri="memory://memories/default/summary"`. Confirm both plugin skills are
available. Do not rerun installation just because the current session has not
reloaded. The installer already prepares the first launch for Kimi.

This adapter is version checked because Kimi's unattended registration format
is an internal host contract. On another version, use its native TUI commands:

```text
/plugins install /absolute/install/directory/analytical-memory-<version>-kimi/analytical-memory
/plugins info analytical-memory
/reload
```

These are **interactive commands**, not shell commands: `kimi --prompt
"/plugins install ..."` sends text to a model and does not install a plugin.
See the [Kimi Code plugin guide](https://moonshotai.github.io/kimi-code/en/customization/plugins.html).

A standalone server probe does not prove Kimi loaded the plugin. If native tools
are missing, keep installation pending and inspect host plugin diagnostics.
Do not build a helper client, call Python application APIs, or edit the database
to continue the quickstart. Specifications and discovery are available through
`memory_discover`; no external MCP resource reader is required. Kimi plugin
server working directories must start with `./`, including the plugin root `./`.

## Codex

With `HOST=openai` and the corresponding archive extracted:

```console
codex plugin marketplace add "$BUNDLE_ROOT"
codex plugin add analytical-memory@analytical-memory-local
codex plugin list
```

Start a new Codex chat. These commands require a CLI with `codex plugin`
support; check `codex plugin --help`. For a client without local marketplace
support, use the [generic integration](#generic-environments-opencode) to
connect the plugin's skills and included server using your client's configuration.

## Generic environments: OpenCode

Use `HOST=generic` when downloading and unpacking. This portable plugin has
`plugin.json`, `.mcp.json`, `skills/`, and the same runtime as the host-specific
bundles. A generic host connects the skills directory and the included stdio
server using its own configuration format. Both components come from this one
installation.

The following example uses **OpenCode 2.x**. Its
[skills support](https://opencode.ai/v2/docs/skills/) loads the plugin's shared
instructions, and its [MCP configuration](https://opencode.ai/v2/docs/mcp-servers/)
starts the included server. No JavaScript extension or npm package is required.

Check your host, then create a dedicated project for the example:

```console
opencode --version
WORKSPACE="$HOME/analytical-memory-opencode-demo"
mkdir -p "$WORKSPACE"
uv run --project "$PAYLOAD_ROOT" --frozen --no-dev --no-editable --extra postgres --python 3.12 \
  python "$PAYLOAD_ROOT/scripts/configure_opencode.py" \
  --output "$WORKSPACE/opencode.json"
```

Expected: `Configured plugin skills and server: …/opencode.json`.
The generated OpenCode 2 configuration includes:

- `skills`: the absolute path to this plugin's `skills/` directory;
- `mcp.servers.analytical-memory`: its exact runtime command, absolute payload
  paths, a 120-second startup allowance and a 10-minute execution timeout.

Keep the payload at that path. Existing files are not overwritten: an identical
configuration is accepted on repeat, while a different JSON or existing JSONC
configuration requires merging. To print the settings for an existing project,
run the same command without `--output`; merge the skill path and this server
entry into the existing configuration, preserving other entries.

Start OpenCode in the configured project and check the connection:

```console
cd "$WORKSPACE"
opencode mcp list
opencode
```

Expected: `analytical-memory` is connected. In the new session, ask:

> Load `analytical-memory-inspect`. Inspect the default memory and report
> readiness and available entity types.

A new installation reports a ready, empty memory. Both `analytical-memory` and
`analytical-memory-inspect` must be discoverable. Server readiness alone is not
complete plugin verification: check that the shared instructions are available
as well. This connection check needs no embedding key; an interactive assistant
session uses your normal OpenCode model/provider setup.

The runtime initializes its default memory automatically outside the bundle.
For an isolated test installation, add `--data-root /absolute/path/to/test-data`
to the generator command. This sets `ANALYTICAL_MEMORY_PLUGIN_DATA` for this
connection; without it the plugin uses the shared per-user location below.

For another generic host, use `plugin.json` to locate the skills and `.mcp.json`
server definition. Resolve the definition's relative project/runtime paths
against `PAYLOAD_ROOT`, register that single server, and expose both skill
folders through the host's instruction mechanism. Keep the runtime arguments,
including the locked dependency and PostgreSQL extra options.

## Prepare the first launch

After registering the clean bundle with the host, populate the Python and
package caches from the extracted payload before reconnecting:

```console
uv sync --project "$PAYLOAD_ROOT" --frozen --no-dev --no-editable --extra postgres --python 3.12
```

This downloads the runtime and locked dependencies outside the server startup
timeout. Wait for it to finish successfully. For hosts that copy plugins, do
this after registration so the source's new `.venv` is not copied into the host
cache. Generic hosts use this environment in place. The host must be able to
find `uv` in its own launch environment as well as in the assistant's shell.

## Verify the connection

Ask the assistant:

> Inspect Analytical Memory's catalog. Report readiness and entity types in
> the default memory. Do not import anything yet.

Expected: the default memory is ready and, on a new installation, empty.
Both `analytical-memory` and `analytical-memory-inspect` skills should be
available. Continue with the [step-by-step quickstart](getting-started.md).
Install the plugin once per host to avoid duplicate connections.

## Local data

The plugin stores data outside its installed copy:

| Platform | Default data directory |
| --- | --- |
| macOS | `~/Library/Application Support/analytical-memory/` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/analytical-memory/` |
| Windows | `%LOCALAPPDATA%\analytical-memory\` |

The first start initializes `memory.db` and `evidence/`. Optional configuration
belongs in `.env` inside that data directory. Set
`ANALYTICAL_MEMORY_PLUGIN_DATA` to override the plugin directory. All host bundles share this default location unless explicitly overridden.
Command-line tools also load the
per-user `.env`; without explicit configuration their database/evidence defaults
are relative to the working directory. Use absolute paths when overriding them.

Named memories use `memories.json`, an address book of absolute database/evidence
paths or PostgreSQL connection-environment names and schemas. It contains no
passwords or records. The quickstart creates a separate named `retail-demo`
memory and specifies its name on every operation.

The plugin launch command installs the locked `postgres` extra for all hosts,
so selecting PostgreSQL needs no second server installation. Follow the
[Docker setup](reference/backend-portability.md#select-a-backend), and put the
backend, connection URL, schema and evidence path in the data-directory `.env`.
The same plugin launcher initializes the selected backend.
Backups include both database records and evidence; see
[operations](reference/operations.md).

## Upgrade and troubleshoot

Create and verify a private snapshot before an upgrade. Read the
[changelog](../CHANGELOG.md), download and verify the new archive, extract it
alongside the old installation, and update/reinstall the host plugin from its
new path. Start a fresh session and check readiness. Preserve the old bundle and
data until the new connection is verified.

If startup fails, check that the host can find `uv` and allow time for dependency
installation. If a memory appears empty, compare its selected name and data
paths. Inspect the host's MCP diagnostics and confirm that both skill names are loaded.
Source builds and publication belong to the [maintainer release guide](releasing.md).

For an OpenCode upgrade, run the new bundle's generator without `--output`.
Replace the old plugin path in `skills` and the existing
`mcp.servers.analytical-memory` entry with the newly printed values; do not append
a second skill source for the same plugin. Restart/reconnect OpenCode and check
both skills and server readiness. Keep the old bundle until the new connection
is verified.
