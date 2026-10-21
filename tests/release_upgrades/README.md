# Installed-release upgrade acceptance

`release/upgrade-support.json` is the explicit upgrade support policy. Currently it declares
`fresh-install-only`: **no production database upgrade combination is supported**. An empty matrix in this mode
does not prove a migration works. Full migration integration is tracked in #2154.

To advertise an upgrade, add a reviewed case with `source_version` (an exact published package version), `backend`
(`sqlite`, `seekdb`, or `oceanbase`), a stable `configuration` identifier, and a `suite` path under this directory.
Set `mode` to `supported-upgrades`. Optional features that change persistent objects need explicit cases/configurations.
No ranges, moving refs, silent backend fallback, or implicit combinations are supported.

The runner creates separate source/target environments, installs the exact published source package and the built
target wheel, verifies their versions, then executes the reviewed suite in an isolated working directory. Repository
pytest configuration and deployment environment variables are excluded. The suite must exercise those installed
processes, not import the current checkout's runtime in place of either version. Use `-I` when invoking their Python.

The suite receives:

- `PC_UPGRADE_SOURCE_PYTHON`, `PC_UPGRADE_TARGET_PYTHON`: isolated installed interpreters.
- `PC_UPGRADE_BACKEND`, `PC_UPGRADE_CONFIGURATION`: the declared case.
- `PC_UPGRADE_WORK`: disposable workspace for both databases, controlled inference fixtures, and environment files.
- `PC_UPGRADE_EVIDENCE`: destination for backend evidence JSON.

Provide these behavioral tests (additional tests are allowed):

| Test | Required behavior |
| --- | --- |
| `test_source_release_database` | Start the actual source Server to create its complete database. Populate representative Memory history, references, permissions, Candidates, tasks and cursors through that version's public interfaces; verify the data before shutdown. Do not create a minimal schema by hand. |
| `test_public_migration_commands` | Stop writers, run the target artifact's public maintenance commands, and validate full readiness. A limited bundle verification does not pass. |
| `test_target_startup` | Start the target Server against the migrated database and verify readiness. |
| `test_read_write_and_retrieval` | Read the old records, write new ones, and retrieve both through public interfaces. |
| `test_authorization` | Verify permitted and denied access and preservation of relevant grants. |
| `test_candidates_and_processing` | Verify retained Candidates and task consumption, including idempotency. |
| `test_preserved_history_and_cursors` | Verify exact history/references and unchanged or declared-transformed cursor and receipt semantics. |
| `test_fresh_upgrade_equivalence` | Initialize a fresh target database; compare schema/backend objects and behavior with the upgraded database, explicitly allowing only registered retained/archive objects. |

Use a session fixture for the shared lifecycle; do not depend on pytest's test execution order. All collected tests
must execute and pass. Empty collection, missing phases, skips (including missing backends), xfail, failure, command
failure, and missing/malformed reports fail the gate. A real OceanBase suite must provision an isolated database and
fail if its required environment is unavailable; it cannot replace execution with mocks. Controlled model responses
may test domain behavior, but do not establish model quality.

Write backend evidence containing `backend`, nonempty `engine_version`, `driver_version`, and recorded schema
inventories or their digests in `source_schema`, `target_schema`, and `fresh_schema`. OceanBase additionally requires
`tenant_mode: "mysql"` and `proxy_version` (or `direct`). Do not record credentials or business payloads. The controller
records installed Python/package versions, target wheel SHA-256, policy SHA-256, and the individual case result.

Evidence is created during the gate run in a new directory. There is no option to import old successful reports.
Test names and metadata do not themselves prove correctness: reviewers must inspect the assertions and confirm
they follow the public operations and compare actual persisted data. This contract is intended to host the real
upgrade acceptance added with #2154, without claiming that it already exists.

For example, after implementing and reviewing an actual suite, a case would have this shape:

```json
{
  "source_version": "1.3.0",
  "backend": "sqlite",
  "configuration": "full-server-no-vector",
  "suite": "tests/release_upgrades/test_sqlite_130.py"
}
```

This example is not an existing supported case. Regenerate installation support regions with
`uv run python scripts/upgrade_release_gate.py --write-docs` and run `make upgrade-policy-check`. When persistence
inputs change, calculate `managed_digest(ROOT)` from `upgrade_release_gate`, review the compatibility impact, and
update both the digest and rationale in `schema_review`. The inputs include persistence, optional code storage,
Server identity and authorization, and shared limits used in table definitions. Add new schema owners to
`MANAGED_INPUTS` when introducing them. The digest intentionally includes non-schema code: it forces a review of
changes, but does not infer semantic compatibility or replace real upgrade tests.

Build exactly one wheel into `dist/`, then run `make upgrade-release-test`. Before release, additionally run
`uv run python scripts/run_upgrade_release_gate.py --release --release-notes /path/to/notes.md`. The notes must contain
the exact English support declaration generated in the installation guide. The release workflow performs this check
against the GitHub event's notes and gates both PyPI publication and release assets on the same tested wheel.

Repository administrators must require **Upgrade release gate** in branch protection. Workflow code cannot configure
that setting. Because the release workflow starts on `release.published`, it can block package/asset publication,
not the earlier manual creation of a GitHub Release; run the prepublication command before publishing that page.
