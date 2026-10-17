# Release guide

This guide is for maintainers. End-user setup is in
[plugin installation](plugin-installation.md) and [MCP installation](mcp-installation.md).

## Prepare and verify

Update `project.version` in `pyproject.toml`, synchronize the lockfile if needed,
and record user-visible changes in [CHANGELOG.md](../CHANGELOG.md). Run the full
[contributor verification sequence](../CONTRIBUTING.md#verification), including
PostgreSQL conformance, before publishing.

Build the wheel, source distribution, three host archives, and checksum file:

```console
uv run --locked python scripts/build_release.py
```

Artifacts are written to `dist/release/`; unpacked plugins are in `dist/plugins/`.
The builder reads the version from `pyproject.toml`. An optional
`--tag v<project-version>` argument rejects a mismatched tag. Each archive
contains its host marketplace or plugin layout, runtime, skills, and
documentation. The `SHA256SUMS` artifact covers the distributions and archives.

Build commands replace their generated output directories. Keep any artifacts
you need to retain elsewhere before rebuilding.

## Publish

The [Release workflow](https://github.com/arch7tect/analytical-memory/actions/workflows/release.yml)
supports two entry points:

- Run it manually on `main`. It reads `project.version`, refuses an existing
  matching tag or release, creates the version tag on that selected commit, and
  publishes the artifacts.
- Push a tag matching `v<project-version>`. The workflow validates the version,
  rebuilds artifacts, and publishes from the existing tag.

The workflow builds artifacts; it does not run the full verification job.
Publish only a commit whose CI gates have passed. CI builds the same artifact
types for every pull request and push to `main`, making release candidates
available for inspection before publication.
