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

"""Offline refresh preserves authority and vectors, and skips compatible projections."""

import asyncio

from pydantic import JsonValue
from sqlalchemy import select, text, update

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.atomic_memory_index_schema import atomic_memory_current_table
from powercontext.builtin.persistence.tables import (
    ARTIFACT_HEADS_TABLE,
    ARTIFACTS_TABLE,
    SKILL_PACKAGES_TABLE,
    SOURCES_TABLE,
    TOPIC_MEMORY_ACTIVE_CHUNKS_TABLE,
    TOPIC_MEMORY_ACTIVE_TOPICS_TABLE,
)
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import BuiltinConfig, RuntimeConfig, open_builtin_runtime
from powercontext.builtin.scope import ScopeDraft
from tests.e2e.atomic_memory_migration_backend import migration_profile


class _Embedding:
    profile = EmbeddingProfile(profile_id="lexical-upgrade", model="fixture", dimension=3)

    async def embed(self, texts, /):
        return EmbeddingResult(vectors=tuple((1.0, 0.0, 0.0) for _ in texts))


async def _snapshot(connection):
    tables = (
        ARTIFACTS_TABLE,
        SOURCES_TABLE,
        SKILL_PACKAGES_TABLE,
        ARTIFACT_HEADS_TABLE,
        atomic_memory_current_table(),
        TOPIC_MEMORY_ACTIVE_TOPICS_TABLE,
        TOPIC_MEMORY_ACTIVE_CHUNKS_TABLE,
    )
    return {
        table.name: (await connection.execute(select(*(c for c in table.c if c.name != "searchable_text")))).all()
        for table in tables
    }


def test_startup_refreshes_changed_words_preserving_exact_records_and_vectors(migration_backend):
    config = BuiltinConfig(database=migration_backend.config, runtime=RuntimeConfig(artifact_processing_families=()))
    embedding = _Embedding()
    marker = "部署地址"
    contents: dict[str, dict[str, JsonValue]] = {
        "atomic-memory": {"kind": "fact", "text": marker + " 127.0.0.1:8000"},
        "experience": {"situation": marker, "action": "配置服务", "outcome": "可访问", "lesson": "核对端口"},
        "skill": {"name": "deployment", "description": marker, "instructions": "配置服务", "validation": ["核对端口"]},
        "topic-memory": {"title": marker, "summary": "服务配置", "detail": "地址固定在 127.0.0.1:8000"},
    }

    async def scenario():
        async with open_builtin_runtime(
            config, embedding_model=embedding, scheduler_path=migration_backend.directory / "scheduler"
        ) as runtime:
            assert runtime.scopes is not None
            scope = (
                await runtime.scopes.create(
                    ScopeDraft(title="Upgrade", summary="Lexical acceptance", idempotency_key="upgrade")
                )
            ).scope_id
            application = runtime.artifacts.for_scope(scope)
            originals = {
                family: await runtime.records.for_scope(scope).create_artifact(family, ArtifactWrite(content=content))
                for family, content in contents.items()
            }
            originals = {
                family: await runtime.records.for_scope(scope).get_artifact_revision(
                    family, value.artifact_id, value.revision
                )
                for family, value in originals.items()
            }
            assert runtime.atomic_memory is not None
            before_vectors = await runtime.atomic_memory.for_scope(scope).search(marker, mode="vector")
            assert before_vectors.hits

        async with migration_profile(migration_backend.config) as profile, profile.database.transaction() as connection:
            authority = await _snapshot(connection)
            # Canonical revisions, states and vectors survive an analyzer change.
            for table in (
                atomic_memory_current_table(),
                TOPIC_MEMORY_ACTIVE_TOPICS_TABLE,
                TOPIC_MEMORY_ACTIVE_CHUNKS_TABLE,
            ):
                await connection.execute(update(table).values(searchable_text="legacy stale terms"))
            await connection.execute(
                update(ARTIFACT_HEADS_TABLE)
                .where(ARTIFACT_HEADS_TABLE.c.family.in_(("experience", "skill")))
                .values(searchable_text="legacy stale terms")
            )
        async with open_builtin_runtime(
            config, embedding_model=embedding, scheduler_path=migration_backend.directory / "scheduler"
        ) as runtime:
            application = runtime.artifacts.for_scope(scope)
            for family, original in originals.items():
                result = await application.search(family, {"query": "请告诉我部署地址是什么", "mode": "text"})
                assert [match.artifact_ref.artifact_id for match in result.matches] == [original.artifact_id]
                assert (
                    await runtime.records.for_scope(scope).get_artifact_revision(
                        family, original.artifact_id, original.revision
                    )
                    == original
                )
            assert runtime.atomic_memory is not None
            after_vectors = await runtime.atomic_memory.for_scope(scope).search(marker, mode="vector")
            assert after_vectors == before_vectors
            async with runtime.primary_database.transaction() as connection:
                assert await _snapshot(connection) == authority
                assert set(
                    (await connection.execute(select(atomic_memory_current_table().c.projection_format))).scalars()
                ) == {"powercontext.atomic-memory.current.v1"}
            fresh = await runtime.records.for_scope(scope).create_artifact(
                "atomic-memory", ArtifactWrite(content={"kind": "fact", "text": "freshmarker"})
            )
            assert (await application.search("atomic-memory", {"query": "freshmarker"})).matches[
                0
            ].artifact_ref.artifact_id == fresh.artifact_id

    asyncio.run(scenario())


def test_startup_keeps_compatible_projection_and_fts_rows_unchanged(tmp_path):
    from powercontext.builtin.persistence.sqlite import SQLiteConfig

    config = BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'compatible.db'}"),
        runtime=RuntimeConfig(artifact_processing_families=()),
    )

    async def scenario():
        async with open_builtin_runtime(config, scheduler_path=tmp_path / "scheduler") as runtime:
            assert runtime.scopes is not None
            scope = (
                await runtime.scopes.create(
                    ScopeDraft(title="Compatible", summary="Existing index", idempotency_key="compatible")
                )
            ).scope_id
            original = await runtime.records.for_scope(scope).create_artifact(
                "atomic-memory", ArtifactWrite(content={"kind": "fact", "text": "compatiblemarker"})
            )
        async with migration_profile(config.database) as profile, profile.database.transaction() as connection:
            before = await _snapshot(connection)
            schema = (
                await connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"))
            ).all()
            fts = (await connection.execute(text("SELECT rowid, * FROM pc_atomic_memory_current_fts"))).all()
            await connection.execute(
                text(
                    "CREATE TRIGGER refuse_projection_update BEFORE UPDATE ON pc_atomic_memory_current BEGIN SELECT RAISE(ABORT, 'compatible projection must not be rewritten'); END"
                )
            )
        async with open_builtin_runtime(config, scheduler_path=tmp_path / "scheduler") as runtime:
            result = await runtime.artifacts.for_scope(scope).search("atomic-memory", {"query": "compatiblemarker"})
            assert result.matches[0].artifact_ref.artifact_id == original.artifact_id
            async with runtime.primary_database.transaction() as connection:
                assert await _snapshot(connection) == before
                assert (
                    await connection.execute(
                        text("SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name")
                    )
                ).all() == schema
                assert (
                    await connection.execute(text("SELECT rowid, * FROM pc_atomic_memory_current_fts"))
                ).all() == fts

    asyncio.run(scenario())
