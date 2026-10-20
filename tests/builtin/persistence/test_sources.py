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

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote, unquote

import pytest
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import delete, insert, update

from powercontext import InvalidSourceDefinitionError
from powercontext.builtin.persistence import (
    InvalidRepositoryArgumentError,
    InvalidStoredPayloadError,
    RepositoryNotFoundError,
    StoredPayloadConflictError,
)
from powercontext.builtin.persistence.atomic_memory_evidence_schema import SOURCE_EVIDENCE_BINDINGS_TABLE
from powercontext.builtin.persistence.codec import dump_model
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.tables import SHARED_TABLES, SOURCES_TABLE
from powercontext.builtin.runtime import SubmitSourceObservation
from powercontext.builtin.runtime.relational import RelationalContexts
from powercontext.sources import (
    AdapterSourceDefinition,
    MemoryEvidenceDeclaration,
    Source,
    SourceDefinitionRegistry,
    SourceMaterialization,
    SourceObservation,
    SourceRef,
    manifest_for_definition,
    project_source_for_transport,
)
from tests.builtin.persistence.contract import (
    SOURCE_ADAPTERS,
    CommitSource,
    NoteSource,
    repository_profile,
)


class SerializationAliasInput(BaseModel):
    source_id: str
    body: str


class SerializationAliasSource(Source):
    body: str = Field(serialization_alias="wire_text")


class CamelCaseSource(SerializationAliasSource):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UpperCaseSource(SerializationAliasSource):
    model_config = ConfigDict(alias_generator=str.upper, populate_by_name=True)


class NativeCamelCaseSource(SerializationAliasSource):
    model_config = ConfigDict(alias_generator=to_camel)

    body: str


class SerializationAliasAdapter:
    name = "serialization-alias"
    input_class = SerializationAliasInput

    def __init__(self, source_class: type[SerializationAliasSource]) -> None:
        self.source_class = source_class

    async def resolve(self, value: SerializationAliasInput, /) -> SerializationAliasSource:
        return self.source_class(
            name=value.source_id,
            definition_version="2",
            materialization=SourceMaterialization.CAPTURED,
            description="Remote alias description.",
            body=value.body,
        )

    async def read(self, source: SerializationAliasSource, /) -> str:
        return source.body


def test_two_source_adapters_share_one_repository_and_journal() -> None:
    async def scenario() -> None:
        async with repository_profile() as (profile, repositories):
            commit = CommitSource(
                name="abc123",
                materialization=SourceMaterialization.REFERENCED,
                revision="abc123",
            )
            note = NoteSource(
                name="note-1",
                materialization=SourceMaterialization.CAPTURED,
                body="Review the repository boundary.",
            )
            async with profile.database.transaction() as connection:
                first = await repositories.sources.add(connection, "scope-a", commit)
                second = await repositories.sources.add(connection, "scope-a", note)
                repeated = await repositories.sources.add(connection, "scope-a", commit)

                assert first.journal_position == 1
                assert second.journal_position == 2
                assert repeated == first
                assert await repositories.sources.journal_position(connection, "scope-a") == 2
                assert await repositories.sources.list(connection, "scope-a", after=1) == (second,)

            async with profile.database.transaction() as connection:
                loaded = await repositories.sources.get(connection, "scope-a", first.ref)
                assert type(loaded.value) is CommitSource
                assert loaded.value == commit

    asyncio.run(scenario())


def test_reusing_a_stable_source_identity_with_different_payload_is_a_conflict() -> None:
    async def scenario() -> None:
        async with repository_profile() as (profile, repositories):
            original = NoteSource(
                name="note-1",
                materialization=SourceMaterialization.CAPTURED,
                body="original",
            )
            changed = NoteSource(
                name="note-1",
                materialization=SourceMaterialization.CAPTURED,
                body="changed",
            )
            async with profile.database.transaction() as connection:
                await repositories.sources.add(connection, "scope-a", original)
                with pytest.raises(StoredPayloadConflictError):
                    await repositories.sources.add(connection, "scope-a", changed)

    asyncio.run(scenario())


def test_repository_batch_reads_deduplicate_refs_and_bound_the_journal_window() -> None:
    async def scenario() -> None:
        async with repository_profile() as (profile, repositories):
            first_source = NoteSource(
                name="note-1",
                materialization=SourceMaterialization.CAPTURED,
                body="first",
            )
            second_source = NoteSource(
                name="note-2",
                materialization=SourceMaterialization.CAPTURED,
                body="second",
            )
            third_source = NoteSource(
                name="note-3",
                materialization=SourceMaterialization.CAPTURED,
                body="third",
            )
            async with profile.database.transaction() as connection:
                first = await repositories.sources.add(connection, "scope-a", first_source)
                second = await repositories.sources.add(connection, "scope-a", second_source)
                third = await repositories.sources.add(connection, "scope-a", third_source)

                loaded = await repositories.sources.get_many(
                    connection,
                    "scope-a",
                    (second.ref, first.ref, second.ref),
                )
                window = await repositories.sources.list_window(
                    connection,
                    "scope-a",
                    after=first.journal_position,
                    through=second.journal_position,
                )

                assert loaded == (second, first)
                assert window == (second,)
                assert third.journal_position > second.journal_position
                with pytest.raises(RepositoryNotFoundError):
                    await repositories.sources.get_many(
                        connection,
                        "scope-a",
                        (SourceRef(source_type="note", source_id="missing"),),
                    )
                with pytest.raises(InvalidRepositoryArgumentError):
                    await repositories.sources.list_window(connection, "scope-a", after=2, through=1)

    asyncio.run(scenario())


@pytest.mark.parametrize("source_class", (SerializationAliasSource, CamelCaseSource, UpperCaseSource))
def test_remote_observation_ingestion_accepts_serialization_aliases(
    source_class: type[SerializationAliasSource],
) -> None:
    async def scenario() -> None:
        worker = SourceDefinitionRegistry((
            AdapterSourceDefinition(SerializationAliasAdapter(source_class), version="2"),
        ))
        source = await worker.resolve(SerializationAliasInput(source_id="remote-1", body="Remote note text."))
        manifest = manifest_for_definition(worker.definition_for_name("serialization-alias"))
        observation = project_source_for_transport(worker, source)

        async with repository_profile() as (profile, _repositories):
            contexts = RelationalContexts(database=profile.database, source_registry=SourceDefinitionRegistry(()))
            await contexts.register_source_definition(manifest)
            receipt = await contexts.submit_source_observation(
                SubmitSourceObservation(scope_id="scope-a", observation=observation)
            )
            context = await contexts.get("scope-a")
            stored = await context.sources.get(observation)

        assert receipt.source_ref == SourceRef(source_type="serialization-alias", source_id="remote-1")
        assert isinstance(stored, SourceObservation)
        assert stored.payload == {
            "name": "remote-1",
            "definition_version": "2",
            "materialization": "captured",
            "description": "Remote alias description.",
            "wire_text": "Remote note text.",
        }

    asyncio.run(scenario())


def test_native_generated_alias_source_survives_read_replay_and_restart(tmp_path) -> None:
    async def scenario() -> None:
        adapter = SerializationAliasAdapter(NativeCamelCaseSource)
        registry = SourceDefinitionRegistry((AdapterSourceDefinition(adapter, version="2"),))
        value = SerializationAliasInput(source_id="native-2", body="Keep the native version and body.")
        source = await adapter.resolve(value)
        # Keep the persisted version nondefault regardless of the constructor's alias rules.
        source.definition_version = "2"
        config = SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'native-alias.db'}")

        async with SQLiteProfile.open(config, tables=SHARED_TABLES) as profile:
            contexts = RelationalContexts(database=profile.database, source_registry=registry)
            context = await contexts.get("scope-a")
            assert await context.sources.add(source) == source
            loaded = await context.sources.get(source)
            assert loaded == source
            assert await context.sources.read(loaded) == value.body
            assert await context.sources.add(source) == source
            assert await context.sources.journal.position(source) == 1

        async with SQLiteProfile.open(config, tables=SHARED_TABLES) as profile:
            contexts = RelationalContexts(database=profile.database, source_registry=registry)
            context = await contexts.get("scope-a")
            loaded = await context.sources.get(source)
            assert loaded == source
            assert loaded.definition_version == "2"
            resolved = await context.sources.resolve(value)
            assert resolved == source
            assert await context.sources.add(resolved) == source
            assert await context.sources.journal.position(resolved) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("current_version", ["1", "2"])
def test_canonical_history_survives_current_identity_aliases(current_version) -> None:
    class CurrentSource(NativeCamelCaseSource):
        name: str = Field(alias="source_name")

    async def scenario() -> None:
        original = SourceRepository((SerializationAliasAdapter(NativeCamelCaseSource),))
        source = NativeCamelCaseSource(
            name="canonical", materialization=SourceMaterialization.CAPTURED, body="Retained."
        )
        material = source.model_dump(mode="json", by_alias=True)
        payload = json.dumps({
            "encoding": "powercontext-source-v1",
            "representation": "native",
            "value": material,
        }).encode()
        async with repository_profile() as (profile, _repositories), profile.database.transaction() as connection:
            stored = await original.add(connection, "scope-a", source)
            await connection.execute(
                update(SOURCES_TABLE).where(SOURCES_TABLE.c.source_id == source.name).values(payload=payload)
            )
            await connection.execute(delete(SOURCE_EVIDENCE_BINDINGS_TABLE))
            expected = await SourceRepository(()).historical_evidence(connection, "scope-a", (stored.ref,))
            current = SourceRepository(
                SourceDefinitionRegistry((
                    AdapterSourceDefinition(SerializationAliasAdapter(CurrentSource), version=current_version),
                ))
            )
            assert await current.historical_evidence(connection, "scope-a", (stored.ref,)) == expected
            assert expected[0].definition_version == "1"
            assert expected[0].declaration == MemoryEvidenceDeclaration()

    asyncio.run(scenario())


@pytest.mark.parametrize("business_version", ["1", "2"])
def test_bound_aliased_history_does_not_treat_business_fields_as_identity(business_version) -> None:
    class AliasedSource(NativeCamelCaseSource):
        definition_version: str = Field(alias="source_version")
        materialization: SourceMaterialization = Field(alias="source_materialization")
        business_version: str = Field(alias="definition_version")
        business_kind: str = Field(alias="materialization")

    async def scenario() -> None:
        declaration = MemoryEvidenceDeclaration(authority="repository_attested", verification="verified")
        registry = SourceDefinitionRegistry((
            AdapterSourceDefinition(SerializationAliasAdapter(AliasedSource), version="2", memory_evidence=declaration),
        ))
        repository = SourceRepository(registry)
        source = AliasedSource(
            name="aliased-history", source_version="2", source_materialization=SourceMaterialization.CAPTURED,
            definition_version=business_version, materialization="referenced", body="Retained.",
        )
        async with repository_profile() as (profile, _repositories), profile.database.transaction() as connection:
            stored = await repository.add(connection, "scope-a", source)
            expected = await repository.historical_evidence(connection, "scope-a", (stored.ref,))
            payload = json.dumps({
                "encoding": "powercontext-source-v1", "representation": "native",
                "value": source.model_dump(mode="json", by_alias=True),
            }).encode()
            await connection.execute(
                update(SOURCES_TABLE).where(SOURCES_TABLE.c.source_id == source.name).values(payload=payload)
            )
            assert await repository.historical_evidence(connection, "scope-a", (stored.ref,)) == expected
            assert expected[0].definition_version == "2"
            assert expected[0].materialization is SourceMaterialization.CAPTURED
            assert expected[0].declaration == declaration

    asyncio.run(scenario())


def test_precanonical_generated_alias_source_rows_remain_readable_and_replayable() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((
            AdapterSourceDefinition(SerializationAliasAdapter(NativeCamelCaseSource), version="2"),
        ))
        repository = SourceRepository(registry)
        source = NativeCamelCaseSource(
            name="legacy-2", definition_version="2", materialization=SourceMaterialization.CAPTURED, body="Retained."
        )
        material = source.model_dump(mode="json", by_alias=True)
        material["definitionVersion"] = material.pop("definition_version")
        payload = json.dumps({
            "encoding": "powercontext-source-v1",
            "representation": "native",
            "value": material,
        }).encode()
        async with (
            repository_profile() as (profile, _repositories),
            profile.database.transaction() as connection,
        ):
            await connection.execute(
                insert(SOURCES_TABLE).values(
                    scope_id="scope-a",
                    source_type="serialization-alias",
                    source_id=source.name,
                    payload=payload,
                    journal_position=1,
                )
            )
            ref = SourceRef(source_type="serialization-alias", source_id=source.name)
            with pytest.raises(InvalidStoredPayloadError):
                await SourceRepository(()).historical_evidence(connection, "scope-a", (ref,))
            loaded = await repository.get(connection, "scope-a", ref)
            assert loaded.value == source
            assert await repository.add(connection, "scope-a", source) == loaded
            assert await repository.journal_position(connection, "scope-a") == 1

    asyncio.run(scenario())


def test_excluded_native_identity_is_rejected_before_capture() -> None:
    class ExcludedVersionSource(NativeCamelCaseSource):
        definition_version: str = Field(default="1", exclude=True)

    async def scenario() -> None:
        repository = SourceRepository((SerializationAliasAdapter(ExcludedVersionSource),))
        source = ExcludedVersionSource(
            name="excluded", materialization=SourceMaterialization.CAPTURED, body="Retained."
        )
        async with repository_profile() as (profile, _repositories), profile.database.transaction() as connection:
            with pytest.raises(InvalidStoredPayloadError):
                await repository.add(connection, "scope-a", source)
            ref = SourceRef(source_type="serialization-alias", source_id=source.name)
            with pytest.raises(RepositoryNotFoundError):
                await repository.get(connection, "scope-a", ref)
            assert await repository.journal_position(connection, "scope-a") == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("identity_field", ["name", "definition_version", "materialization"])
def test_encoded_native_identity_is_rejected_before_capture(identity_field) -> None:
    class EncodedSource(NativeCamelCaseSource):
        @field_serializer("name", "definition_version", "materialization")
        def encode_identity(self, value, info):
            if info.field_name == identity_field:
                return quote(f"wire:{value}", safe="")
            return value

        @field_validator("name", "definition_version", "materialization", mode="before")
        @classmethod
        def decode_identity(cls, value, info):
            if info.field_name == identity_field:
                return unquote(value).removeprefix("wire:")
            return value

    async def scenario() -> None:
        repository = SourceRepository((SerializationAliasAdapter(EncodedSource),))
        source = EncodedSource(name="note/42", materialization=SourceMaterialization.CAPTURED, body="Retained.")
        assert EncodedSource.model_validate_json(source.model_dump_json(by_alias=True)) == source
        async with repository_profile() as (profile, _repositories), profile.database.transaction() as connection:
            with pytest.raises(InvalidStoredPayloadError):
                await repository.add(connection, "scope-a", source)
            ref = SourceRef(source_type="serialization-alias", source_id=source.name)
            with pytest.raises(RepositoryNotFoundError):
                await repository.get(connection, "scope-a", ref)
            assert await repository.journal_position(connection, "scope-a") == 0

    asyncio.run(scenario())


def test_explicit_name_alias_evidence_survives_restart_without_the_native_definition(tmp_path) -> None:
    class AliasedSource(NativeCamelCaseSource):
        name: str = Field(alias="source_name")
        business_name: str = Field(alias="name")
        description: str | None = Field(default="captured description", exclude=True)

    class UpdatedSource(AliasedSource):
        description: str | None = Field(default="current description", exclude=True)

    async def scenario() -> None:
        declaration = MemoryEvidenceDeclaration(authority="repository_attested", verification="verified")
        registry = SourceDefinitionRegistry((
            AdapterSourceDefinition(
                SerializationAliasAdapter(AliasedSource),
                version="2",
                memory_evidence=declaration,
            ),
        ))
        source = AliasedSource(
            source_name="native-alias",
            name="business label",
            definition_version="2",
            materialization=SourceMaterialization.CAPTURED,
            body="Retained.",
        )
        config = SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'explicit-alias.db'}")
        repository = SourceRepository(registry)
        async with (
            SQLiteProfile.open(config, tables=SHARED_TABLES) as profile,
            profile.database.transaction() as connection,
        ):
            stored = await repository.add(connection, "scope-a", source)
            assert (await repository.get(connection, "scope-a", stored.ref)).value == source
            assert await repository.add(connection, "scope-a", source) == stored
            evidence = await repository.evidence(connection, "scope-a", (stored.ref,))
            assert evidence[0].declaration == declaration
        async with (
            SQLiteProfile.open(config, tables=SHARED_TABLES) as profile,
            profile.database.transaction() as connection,
        ):
            updated = SourceDefinitionRegistry((
                AdapterSourceDefinition(SerializationAliasAdapter(UpdatedSource), version="2"),
            ))
            loaded = await SourceRepository(updated).get(connection, "scope-a", stored.ref)
            assert loaded.value.description == "current description"
            assert await SourceRepository(()).historical_evidence(connection, "scope-a", (stored.ref,)) == evidence

    asyncio.run(scenario())


def test_repository_rejects_a_scope_outside_the_relational_identity_baseline() -> None:
    async def scenario() -> None:
        async with repository_profile() as (profile, repositories):
            source = NoteSource(
                name="note-1",
                materialization=SourceMaterialization.CAPTURED,
                body="x",
            )
            async with profile.database.transaction() as connection:
                with pytest.raises(InvalidRepositoryArgumentError) as error:
                    await repositories.sources.add(connection, "x" * 257, source)
                assert error.value.field == "scope_id"

    asyncio.run(scenario())


def test_remote_definition_cannot_shadow_the_active_registry() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry.from_adapters(SOURCE_ADAPTERS)
        manifest = manifest_for_definition(registry.definition_for_name("note"))
        async with repository_profile() as (profile, _repositories):
            contexts = RelationalContexts(database=profile.database, source_registry=registry)

            with pytest.raises(InvalidSourceDefinitionError, match="active Source Definition"):
                await contexts.register_source_definition(manifest)

    asyncio.run(scenario())


def test_stored_observation_representation_does_not_depend_on_the_active_registry() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry.from_adapters(SOURCE_ADAPTERS)
        source = NoteSource(
            name="note-1",
            materialization=SourceMaterialization.CAPTURED,
            body="Persist the representation explicitly.",
        )
        observation = project_source_for_transport(registry, source)
        writer = SourceRepository(())
        reader = SourceRepository(SOURCE_ADAPTERS)

        async with (
            repository_profile() as (profile, _repositories),
            profile.database.transaction() as connection,
        ):
            stored = await writer.add(connection, "scope-a", observation)
            loaded = await reader.get(connection, "scope-a", stored.ref)

        assert isinstance(loaded.value, SourceObservation)
        assert loaded.value == observation

    asyncio.run(scenario())


def test_semantically_equal_observations_are_idempotent_across_object_key_order() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry.from_adapters(SOURCE_ADAPTERS)
        source = NoteSource(
            name="note-1",
            materialization=SourceMaterialization.CAPTURED,
            body="Keep semantic idempotency.",
        )
        observation = project_source_for_transport(registry, source)
        first = SourceObservation.model_validate(
            observation.model_dump(mode="json") | {"payload": observation.payload | {"metadata": {"a": 1, "b": 2}}}
        )
        reordered = SourceObservation.model_validate(
            observation.model_dump(mode="json") | {"payload": observation.payload | {"metadata": {"b": 2, "a": 1}}}
        )
        repository = SourceRepository(())

        async with (
            repository_profile() as (profile, _repositories),
            profile.database.transaction() as connection,
        ):
            initial = await repository.add(connection, "scope-a", first)
            replay = await repository.add(connection, "scope-a", reordered)

        assert replay == initial

    asyncio.run(scenario())


def test_repository_reads_legacy_native_source_payloads_without_an_envelope() -> None:
    async def scenario() -> None:
        source = NoteSource(
            name="note-1",
            materialization=SourceMaterialization.CAPTURED,
            body="Keep existing native rows readable.",
        )
        repository = SourceRepository(SOURCE_ADAPTERS)

        async with (
            repository_profile() as (profile, _repositories),
            profile.database.transaction() as connection,
        ):
            await connection.execute(
                insert(SOURCES_TABLE).values(
                    scope_id="scope-a",
                    source_type="note",
                    source_id=source.name,
                    payload=dump_model(source, kind="source", name="note"),
                    journal_position=1,
                )
            )
            loaded = await repository.get(
                connection,
                "scope-a",
                SourceRef(source_type="note", source_id=source.name),
            )

        assert loaded.value == source

    asyncio.run(scenario())


def test_source_journal_allocator_serializes_concurrent_scope_writes_without_idempotency_gaps(tmp_path) -> None:
    async def scenario() -> None:
        config = SQLiteConfig(
            url=f"sqlite+aiosqlite:///{tmp_path / 'concurrent-sources.db'}",
            busy_timeout_ms=10_000,
        )
        repository = SourceRepository(SOURCE_ADAPTERS)
        async with SQLiteProfile.open(config, tables=SHARED_TABLES) as profile:

            async def add(scope_id: str, source: NoteSource):
                async with profile.database.transaction() as connection:
                    return await repository.add(connection, scope_id, source)

            unique = await asyncio.gather(
                *(
                    add(
                        "scope-concurrent",
                        NoteSource(
                            name=f"note-{index}",
                            materialization=SourceMaterialization.CAPTURED,
                            body=f"body-{index}",
                        ),
                    )
                    for index in range(16)
                )
            )
            assert sorted(item.journal_position for item in unique) == list(range(1, 17))

            repeated_source = NoteSource(
                name="same-note",
                materialization=SourceMaterialization.CAPTURED,
                body="same-body",
            )
            repeated = await asyncio.gather(*(add("scope-idempotent", repeated_source) for _ in range(8)))
            assert {item.journal_position for item in repeated} == {1}
            following = await add(
                "scope-idempotent",
                NoteSource(
                    name="following-note",
                    materialization=SourceMaterialization.CAPTURED,
                    body="following-body",
                ),
            )
            assert following.journal_position == 2

    asyncio.run(scenario())
