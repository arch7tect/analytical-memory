# Original v1 smoke example

This walkthrough imports two synthetic JSONL datasets, connects messages to
sessions, and queries messages belonging to failed sessions. It uses SQLite and
needs no API key or external database.

For assistant setup, use [plugin installation](plugin-installation.md).

## Run from a bundle

Follow [download and unpack](plugin-installation.md#download-and-unpack), then run
from the payload directory:

```console
cd "$PAYLOAD_ROOT"
uv run --frozen --no-dev --python 3.12 memory-quickstart --smoke
```

The automated example creates an isolated temporary memory and removes only its
own temporary files when finished. A successful run reports:

```json
{"created_relations": 2, "ok": true, "query_rows": 1}
```

## Create a persistent local memory

Run the following commands from the bundle payload directory:

```console
uv run memory init
uv run memory status
uv run memory schema show
```

The default database is `.local/memory.db`; evidence is stored separately in
`.local/evidence/`. These paths are relative to the working directory. For persistent use, configure absolute
paths outside the bundle as described in the plugin installation guide. Keep both when backing up your memory. For configuration and named
memories, see the [MCP reference](reference/mcp.md).

Copy the `schema_fingerprint` value from `schema show`. Replace
`<contract-fingerprint>` in each write command below with that value.

## Import and connect the sample datasets

```console
uv run memory jsonl import examples/quickstart/sessions.jsonl \
  --entity-type example.Session \
  --key '[{"field":"id","type":"string"}]' \
  --contract-fingerprint <contract-fingerprint>

uv run memory jsonl import examples/quickstart/messages.jsonl \
  --entity-type example.SessionMessage \
  --key '[{"field":"id","type":"string"}]' \
  --contract-fingerprint <contract-fingerprint>

uv run memory ontology describe

uv run memory join materialize examples/quickstart/join.json \
  --contract-fingerprint <contract-fingerprint>
```

Each import is atomic. The typed key selects matching current records; it is
not a separate persistent identity. Repeating the exact import returns its
recorded result. A different file with an existing key patches the fields it
contains and preserves omitted fields.

The join is explicit and creates two relations on a fresh memory. Importing more
records does not run it automatically; rerun materialization when needed. Reruns
add missing pairs and preserve explicitly deactivated relations.

## Query the connected data

```console
uv run memory query execute --document examples/quickstart/query.json
```

On a fresh sample memory the result has one row. Each projected field includes
its current value and provenance identifiers. The query also returns node
bindings and fingerprints so clients can interpret the result against the
correct ontology. Read the [querying reference](reference/querying.md) to write
your own queries.

## Data handling and privacy

- Imported data defaults to `public`. Declare an entity or its fields `private`
  before importing sensitive records. An optional declaration also sets field
  types, required-on-create constraints, descriptions, and search eligibility.
- Local queries and searchable full-text fields can return private values.
  Privacy labels are not user access controls.
- Shareable exports and external embeddings exclude private records. Optional
  semantic search also sends query text to the embedding provider; use public
  query text only.
- The evidence store copies source bytes. Current-value updates do not retain a
  second historical attribute row; their original source evidence remains
  separately addressable while retained.
- Credentials are rejected by ingestion rather than stored as private data.

See [system design](design.md#privacy-and-security) for the privacy contract and
[operations](reference/operations.md) for verified backups and retention.

## Next steps

Use [text and semantic retrieval](reference/semantic-retrieval.md) for search,
[backend portability](reference/backend-portability.md) for PostgreSQL, or the
[documentation index](README.md) for the full guide list.
