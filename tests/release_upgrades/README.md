# Installed-release upgrade acceptance

`release/upgrade-support.json` is the explicit upgrade support policy. Currently it declares
`fresh-install-only`: **no production database upgrade combination is supported**. Discovered candidates in this mode
are not accepted upgrades. Full migration integration is tracked in #2154.

## Fixed source and current target

The `automatic_sources` policy uses `strategy: "fixed-version"` and `source_version: "1.3.0"`, with SQLite,
embedded seekDB, and OceanBase profiles. Every run expands that exact source across the three backends. The target
is the **actual wheel built by this job**, not the latest published PyPI package. Thus releases 1.4.1 and 1.5.0
exercise 1.3.0 → 1.4.1 and 1.3.0 → 1.5.0 without adding test scripts or changing the source version. Newly published
intermediate versions do not become additional sources. This fixed baseline does not establish support for every
intermediate release's database or data shapes; add explicit `cases` if those need separate acceptance.

The runner resolves the exact source wheel from public PyPI and installs its URL with a SHA-256. Missing/yanked
source wheels, invalid artifact metadata, catalog outages, and a target at or below the source version fail the gate.
Evidence records the catalog digest, exact source artifact, target artifact digest, and expanded matrix. The resolver
requires universal `py3-none-any` wheels; a distribution format change must extend it explicitly.

Currently the three profiles have `suite: null` and the mode remains `fresh-install-only`. Resolving candidates
executes and accepts **zero** positive upgrades. To activate supported upgrades, implement the complete suite
contract below for each backend, replace the null paths, set `mode` to `supported-upgrades`, and regenerate the
installation notices. A missing suite fails supported mode. Tests must fail when migration support is missing;
the runner never changes expected success into a rejection automatically.

`cases` remains available for additional exact source versions/configurations. Each case needs `source_version`,
`backend`, `configuration`, and `suite`; overlapping cases fail. Optional features that create persistent objects
require additional profiles. The fixed CI baseline and advertised upgrade support must stay consistent.

PR/master and publication CI start an isolated OceanBase CE container using the image and MySQL tenant setup from
the existing E2E workflow. They wait for SQL readiness and adequate datafile capacity before testing, save diagnostics,
and remove the container even when a check fails. No external database credentials are needed. Embedded seekDB
runs directly in a temporary runner directory. A backend startup failure fails the job instead of skipping it.

The runner creates separate source/target environments, installs the exact published source package and the built
target wheel, verifies their versions, then executes the reviewed suite in an isolated working directory. Repository
pytest configuration and deployment environment variables are excluded. The suite must exercise those installed
processes, not import the current checkout's runtime in place of either version. Use `-I` when invoking their Python.

The suite receives:

- `PC_UPGRADE_SOURCE_PYTHON`, `PC_UPGRADE_TARGET_PYTHON`: isolated installed interpreters.
- `PC_UPGRADE_SOURCE_VERSION`: the exact source release selected for this case.
- `PC_UPGRADE_BACKEND`, `PC_UPGRADE_CONFIGURATION`: the declared case.
- `PC_UPGRADE_WORK`: disposable workspace for both databases, controlled inference fixtures, and environment files.
- `PC_UPGRADE_EVIDENCE`: destination for backend evidence JSON.
- `PC_UPGRADE_OCEANBASE_URL`, `PC_UPGRADE_OCEANBASE_FRESH_URL`: dedicated disposable MySQL-tenant databases for
  the upgraded and fresh-install comparisons. CI supplies both; local positive OceanBase suites must supply their
  own isolated databases. Each suite must isolate/reset its own fixtures when multiple configurations run.

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

For example, after implementing and reviewing actual suites, automatic selection would have this shape:

```json
{
  "strategy": "fixed-version",
  "source_version": "1.3.0",
  "profiles": [
    {"backend": "sqlite", "configuration": "full-server-no-vector", "suite": "tests/release_upgrades/test_sqlite.py"},
    {"backend": "seekdb", "configuration": "full-server-no-vector", "suite": "tests/release_upgrades/test_seekdb.py"},
    {"backend": "oceanbase", "configuration": "full-server-no-vector", "suite": "tests/release_upgrades/test_oceanbase.py"}
  ]
}
```

These suite paths illustrate the contract; they do not exist yet. Regenerate installation support regions with
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

## Actual historical rejection regressions

The PR/master and publication jobs run `ci_legacy_upgrade_rejection.py` for **SQLite, embedded seekDB, and OceanBase**
against a database created and populated by installed PowerContext 1.3.0. It uses separate source/target environments, one disposable
database per backend, sequential process ownership, and public HTTP writes/readback before testing target CLI behavior.
The installed drivers inventory the actual tables and record each environment's engine, driver, and binding versions.
OceanBase uses the container's dedicated `pc_upgrade_test` database and records its MySQL tenant mode and direct
connection. The negative runner only accepts the local test database and verifies it is empty before starting the
old Server; it refuses to overwrite existing data. No external service or credentials are needed. A missing embedded
binding or unavailable OceanBase instance fails the job; neither backend is skipped.

The regressions require historical startup rejection, full-baseline migration rejection, and rejection after adding
only the prototype revision table to the disposable fixture. The last operation is deliberately **not a migration**.
SeekDB and OceanBase permit either the known CHECK-reflection rejection or unknown-baseline rejection, so fixing #2160 does not
require retaining the parser defect. These tests do not certify that an upgrade succeeds.

CI invokes them with `--respect-policy` after the main gate. Once supported-path acceptance is activated, these
historical rejection assertions are recorded as `not-applicable` instead of failing because migration was fixed.
The preceding positive gate must still execute all required version/backend cases and accept no skips.
