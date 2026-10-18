# ADR 0002: Native analytics and immutable observations

Status: Accepted on 2026-10-17; implemented in Analytical Memory 0.7.0.

## Decision

Implement the [native analytics and quickstart proposal](../archive/native-analytics-and-quickstart.md)
as Milestone 8. Preserve Query IR v1 input and result behavior. Add a separate
v2 dispatcher with one anchored optional pattern, base scalar groups,
identity-aware counts and integer sums, exact ratios, stable group identities,
and output pagination after complete bounded evaluation.

Named query and relation-inspection members execute in one database snapshot.
Every fact writer locks its memory state before evaluating and committing a
change. Generation identifies a memory lifetime; revision advances once per
fact-changing transaction, including direct provenance changes. Exact replay,
no-edge joins, evidence bookkeeping and native capture do not advance it.
SQLite readers use an explicit transaction and WAL. PostgreSQL readers use
REPEATABLE READ; writers use READ COMMITTED and lock the per-schema state row.

A separate explicit capture computes and retains values and input provenance in
an immutable, verified evidence object. Native Metrics use exact JSON values
and tagged dimensions; the legacy current-metric selector reads caller metrics
only. Saved detail reads captured values. Live detail requires the original
state guard on every page. Restored observations have unknown freshness in the
new generation until the user creates a new capture.

## Delivery choices and bounds

The first implementation evaluates a bounded fact snapshot inside the server.
The walkthrough uses public operations and never aggregates rows itself.
Read the [native analytics reference](../reference/native-analytics.md) for
exact limits, operation documents, error behavior and deferred expressions.

Revision tracking initially hashes current facts before and after a write.
This favors complete writer coverage; its cost grows with memory size. The
manifest conservatively retains the bounded memory fact population and its
referenced provenance. Its privacy ceiling includes every retained field,
which can be stricter than the selected query alone. Fine-grained capture and
incremental dependency invalidation remain future optimizations.

Snapshot format 2 carries native observations. Its reader also verifies original
format-1 artifacts against the packaged 0.6.1 contract before adapting them.
Transfer format 2 embeds verified native manifests; ordinary raw evidence still
requires its existing independent transfer/retention workflow.

## Consequences

Imports, joins, search and legacy metrics retain their existing public/private
rules. Native public use additionally requires current verified public captured
and current dependencies. Captures never create permission to share private
facts. Mandatory manifests cannot be released or retired while referenced.
No background recalculation, causal inference or general temporal database is
introduced.
