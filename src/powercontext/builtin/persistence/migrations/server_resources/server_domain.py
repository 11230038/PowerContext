# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Registered Server 1.3 maintenance and live readiness requirements."""

import json
import runpy
from pathlib import Path

from sqlalchemy import inspect, text

from powercontext.builtin.persistence.experience_index import (
    APPROVED_ARTIFACT_PROJECTION_VERSION,
    rebuild_experience_projections,
    rebuild_skill_projections,
)
from powercontext.builtin.persistence.lexical_projection import (
    LEXICAL_ANALYZER_VERSION,
    record_lexical_projection_version,
    refresh_lexical_projections,
)
from powercontext.builtin.persistence.migrations.models import MigrationError
from powercontext.builtin.persistence.migrations.pinned import finish, pinned

assert_atomic_memory_migration_ready = runpy.run_path(str(Path(__file__).parent / "atomic_memory_readiness_1300.py"))[
    "assert_atomic_memory_migration_ready"
]


def dream():
    return runpy.run_path(str(Path(__file__).parent / "dream/upgrade.py"))


def preflight(connection, *, configuration):
    names = set(inspect(connection).get_table_names())
    if not names or names == {"pc_schema_revision"}:
        return
    if configuration.get("embedding_enabled"):
        raise MigrationError(
            "unsupported_upgrade_configuration", "This registered full Server path requires no vector provider."
        )
    # Real 1.3.0 publishes Atomic Memory already. An old schema with pre-1.3
    # collection data needs its separately declared conversion, never a stamp.
    finish(assert_atomic_memory_migration_ready(pinned(connection)))
    if "pc_artifact_candidate_versions" in names:
        module = dream()
        try:
            module["validate_dream_tasks"](connection)
            module["validate_dream_processing_manifest"](
                connection, target_manifest=configuration["processing_manifest"]
            )
        except module["DreamUpgradeError"] as error:
            raise MigrationError(
                error.reason, "The legacy Dream task or Processing configuration needs maintenance."
            ) from error


def apply(connection, *, configuration):
    # Dream's schema revision preserves the legacy manifest; this is the only
    # permitted ownership transformation, not an unconditional target overwrite.
    old = json.loads(
        connection.exec_driver_sql(
            "SELECT config_manifest FROM pc_artifact_processing_schema WHERE singleton=1"
        ).scalar_one()
    )
    if "handoff.dream.v1" not in old["bindings"]:
        upgraded = dream()["validate_dream_processing_manifest"](
            connection, target_manifest=configuration["processing_manifest"]
        )
        connection.execute(
            text("UPDATE pc_artifact_processing_schema SET config_manifest=:value WHERE singleton=1"),
            {"value": json.dumps(upgraded, sort_keys=True, separators=(",", ":"))},
        )
    connection.exec_driver_sql(
        "INSERT INTO pc_access_relationship_heads (name,revision) SELECT 'authorization',0 WHERE NOT EXISTS (SELECT 1 FROM pc_access_relationship_heads WHERE name='authorization')"
    )
    async_connection = pinned(connection)
    from powercontext.builtin.persistence.atomic_memory_index_schema import atomic_memory_current_table

    finish(refresh_lexical_projections(async_connection, atomic_memory_current_table()))
    finish(rebuild_experience_projections(async_connection))
    finish(rebuild_skill_projections(async_connection))
    finish(
        record_lexical_projection_version(
            async_connection, "pc_artifact_heads", version=APPROVED_ARTIFACT_PROJECTION_VERSION
        )
    )
    if connection.dialect.name == "sqlite":
        from powercontext.builtin.persistence.sqlite.atomic_memory_index import SQLiteAtomicMemoryIndex

        finish(SQLiteAtomicMemoryIndex().rebuild_fts(async_connection))
        connection.exec_driver_sql("DELETE FROM pc_artifact_fts")
        connection.exec_driver_sql(
            "INSERT INTO pc_artifact_fts (scope_id,family,artifact_id,revision,searchable_text) SELECT scope_id,family,artifact_id,revision,searchable_text FROM pc_artifact_heads WHERE family IN ('experience','skill') AND searchable_text IS NOT NULL"
        )
        # Both FTS tables are registered schema; this initializer only refreshes
        # their rows and existing marker when the analyzer has changed.
        from powercontext.builtin.persistence.sqlite.topic_memory_index import SQLiteTopicMemoryFTSIndex
        from powercontext.builtin.persistence.topic_memory import TopicMemoryRepository

        finish(TopicMemoryRepository(index=SQLiteTopicMemoryFTSIndex()).initialize(async_connection))
    else:
        from powercontext.builtin.persistence.oceanbase.topic_memory_index import OceanBaseTopicMemoryFTSIndex
        from powercontext.builtin.persistence.topic_memory import TopicMemoryRepository

        finish(TopicMemoryRepository(index=OceanBaseTopicMemoryFTSIndex()).initialize(async_connection))


def verify(connection, *, configuration):
    dream()["verify_dream_storage"](connection)
    validate(connection, configuration=configuration)


def validate(connection, *, configuration):
    finish(assert_atomic_memory_migration_ready(pinned(connection)))
    expected = {
        "pc_atomic_memory_current": LEXICAL_ANALYZER_VERSION,
        "pc_topic_memory_active_topics": LEXICAL_ANALYZER_VERSION,
        "pc_topic_memory_active_chunks": LEXICAL_ANALYZER_VERSION,
        "pc_artifact_heads": APPROVED_ARTIFACT_PROJECTION_VERSION,
    }
    actual = dict(
        connection
        .exec_driver_sql("SELECT projection, analyzer_version FROM pc_lexical_projection_versions")
        .tuples()
        .all()
    )
    if actual != expected:
        raise MigrationError("projection_migration_required", "The registered search projections are not current.")
    manifest = json.loads(
        connection.exec_driver_sql(
            "SELECT config_manifest FROM pc_artifact_processing_schema WHERE singleton=1"
        ).scalar_one()
    )
    target = configuration.get("processing_manifest")
    if target and any(manifest[key] != target[key] for key in ("bindings", "mode", "capabilities")):
        raise MigrationError(
            "incompatible_processing_configuration", "Processing ownership differs from the migrated declaration."
        )
    from powercontext.builtin.persistence.dream import DreamRepository

    for scope, run in connection.exec_driver_sql("SELECT scope_id,run_id FROM pc_dream_runs"):
        finish(DreamRepository().get(pinned(connection), scope, run))
    from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository

    for scope, binding in connection.exec_driver_sql(
        "SELECT scope_id,binding_name FROM pc_artifact_processing_intents"
    ):
        finish(ArtifactProcessingIntentRepository().load(pinned(connection), scope, binding))
    # Check exact current projection identities without comparing mutable heads
    # to retained pre-upgrade Candidate snapshots.
    if connection.exec_driver_sql(
        "SELECT 1 FROM pc_atomic_memory_current p WHERE NOT EXISTS (SELECT 1 FROM pc_artifact_heads h WHERE h.scope_id=p.scope_id AND h.family='atomic-memory' AND h.artifact_id=p.artifact_id AND h.revision=p.revision) LIMIT 1"
    ).first():
        raise MigrationError(
            "projection_verification_failed", "An Atomic Memory projection references a missing current head."
        )

    from powercontext.builtin.persistence.topic_memory import TopicMemoryRepository

    if connection.dialect.name == "sqlite":
        from powercontext.builtin.persistence.sqlite.topic_memory_index import SQLiteTopicMemoryFTSIndex

        index = SQLiteTopicMemoryFTSIndex()
        _validate_sqlite_fts(connection)
    else:
        from powercontext.builtin.persistence.oceanbase.topic_memory_index import OceanBaseTopicMemoryFTSIndex

        index = OceanBaseTopicMemoryFTSIndex()
    finish(TopicMemoryRepository(index=index).initialize(pinned(connection), validate_only=True))


def _validate_sqlite_fts(connection):
    # Read-only multiset comparison also catches duplicate/stale helper rows.
    projections = (
        (
            "pc_atomic_memory_current",
            "pc_atomic_memory_current_fts",
            "scope_id,artifact_id,revision,state_version,content_hash,projection_format,kind,text,searchable_text,tag_keys",
            "",
        ),
        (
            "pc_artifact_heads",
            "pc_artifact_fts",
            "scope_id,family,artifact_id,revision,searchable_text",
            " WHERE family IN ('experience','skill') AND searchable_text IS NOT NULL",
        ),
        (
            "pc_topic_memory_active_topics",
            "pc_topic_memory_topic_fts",
            "scope_id,artifact_id,revision,searchable_text",
            "",
        ),
        (
            "pc_topic_memory_active_chunks",
            "pc_topic_memory_chunk_fts",
            "scope_id,artifact_id,revision,chunk_ordinal,searchable_text",
            "",
        ),
    )
    for source, helper, columns, predicate in projections:
        expected = f"SELECT {columns},COUNT(*) FROM {source}{predicate} GROUP BY {columns}"  # noqa: S608 -- Only frozen schema names and projections are interpolated.
        actual = f"SELECT {columns},COUNT(*) FROM {helper} GROUP BY {columns}"  # noqa: S608 -- Only frozen schema names and projections are interpolated.
        for left, right in ((expected, actual), (actual, expected)):
            if connection.exec_driver_sql(f"SELECT 1 FROM ({left} EXCEPT {right}) LIMIT 1").first():  # noqa: S608 -- Only frozen schema names and projections are interpolated.
                raise MigrationError(
                    "projection_verification_failed", "A full-text helper differs from its authoritative current rows."
                )
