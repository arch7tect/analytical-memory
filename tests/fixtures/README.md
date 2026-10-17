# Legacy artifact fixtures

`legacy-0.6.1.zip` and `legacy-0.6.1.json` are synthetic snapshot/transfer artifacts
produced by the unmodified 0.6.1 source at commit
`c18287aa32a44d00d346a25af128276a4499115b`. Each contains one `shop.Order` with
`order_id=legacy-order` and `amount_cents=10000`, no private or operational data.
They retain the original format-1 identities, table hashes, schema and evidence
bytes. Tests verify those hashes before applying compatibility adapters.

Reproduce using a temporary checkout of that commit, initialize SQLite plus a
new evidence root, import the single JSONL object with a typed `order_id` key,
then call `snapshot_create` and `transfer_export`. Capture metadata/UUIDs may
change on regeneration; the original logical contract and tested business
values remain fixed. These test-owned fixtures must not be replaced with
production backups.
