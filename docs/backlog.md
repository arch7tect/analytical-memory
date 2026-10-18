# Backlog

Deferred ideas, reviewed against 0.7.2 on 2026-10-18. These are not supported
features, approved implementation scope, or promises for the next release.
Installation and the native conversational quickstart are delivered; the
[archived proposal](archive/native-analytics-and-quickstart.md) is complete.

| Idea | Current boundary and acceptance needed before implementation |
| --- | --- |
| Dependency-specific freshness | Current freshness is conservative and memory-wide. Track exact field, entity and join dependencies without missing provenance-only changes or weakening privacy checks. |
| Smaller captures and incremental revision tracking | Captures retain the bounded fact population and writes compare fact digests. Reduce storage and write cost while preserving exact saved detail, retention, privacy and all-writer coverage on both backends. |
| Richer aggregate expressions | Fractional SUM, AVG, HAVING and calculated expressions need explicit precision, null, identity, coverage and drill-down semantics. Integer sums and exact ratios remain the supported contract. |
| More flexible query composition | Multiple or nested optional branches, optional-side grouping and recursive analytics need unambiguous populations, denominators, membership and evaluation limits. Current v2 supports one anchored optional branch and base scalar grouping. |
| Explicit refresh automation | Automatic recalculation needs a separate policy and execution contract. Historical captures must remain immutable; reading an analysis must not silently replace it. |
| General temporal analysis | Reconstructing past field/relation state needs a separate history and retention design. Saved observation-time values already work; they do not provide a general temporal database. |

Sources: [native analytics limits](reference/native-analytics.md#limits-and-failures),
[ADR 0002](decisions/0002-native-analytics-observations.md#delivery-choices-and-bounds),
and the [archived release boundary](archive/native-analytics-and-quickstart.md#review-choices-and-release-boundary).
Other deferred platform capabilities remain in the
[system design](design.md#deferred-capabilities).
