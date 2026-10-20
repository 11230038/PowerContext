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
import urllib.request

import pytest
from pydantic import Field, ValidationError
from referencing.exceptions import Unresolvable

from powercontext import InvalidSourceDefinitionError
from powercontext.builtin.persistence.source_definitions import SourceDefinitionManifestRepository
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.tables import SHARED_TABLES
from powercontext.builtin.runtime import SubmitSourceObservation
from powercontext.builtin.runtime.relational import RelationalContexts, _json_schema_validator
from powercontext.builtin.sources import CONTENT_SOURCE_DEFINITION, ContentCapture
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceCatalog,
    SourceDefinitionManifest,
    SourceDefinitionRegistry,
    SourceMaterialization,
    SourceObservation,
    TextEvidence,
    manifest_for_definition,
    project_source_for_transport,
)


class EmptySourceBackend:
    async def list(self) -> tuple[Source, ...]:
        return ()

    async def get(self, source: Source, /) -> Source:
        raise AssertionError(source)


def test_definition_manifest_has_a_stable_content_addressed_identity() -> None:
    first = manifest_for_definition(CONTENT_SOURCE_DEFINITION)
    second = manifest_for_definition(CONTENT_SOURCE_DEFINITION)

    assert first == second
    assert first.fingerprint.startswith("sha256:")
    with pytest.raises(ValidationError, match="fingerprint does not match"):
        SourceDefinitionManifest.model_validate(first.model_dump(mode="json", by_alias=True) | {"version": "2"})


def test_source_observation_remains_usable_without_worker_definition_code() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((CONTENT_SOURCE_DEFINITION,))
        source = await registry.resolve(
            ContentCapture(source_id="turn-1", content="Keep the remote contract declarative.")
        )
        projected = project_source_for_transport(registry, source)
        catalog = SourceCatalog(backend=EmptySourceBackend())
        payload = await catalog.read(projected)
        projection = catalog.project(projected, TEXT_EVIDENCE_PROJECTION_KEY)

        assert isinstance(projected, SourceObservation)
        assert catalog.as_ref(projected).model_dump() == {"source_type": "content", "source_id": "turn-1"}
        assert payload == projected.payload
        assert catalog.projection_keys(projected) == (TEXT_EVIDENCE_PROJECTION_KEY,)
        assert registry.project(projected, TEXT_EVIDENCE_PROJECTION_KEY) == projection
        assert TextEvidence.model_validate(projection).content == "Keep the remote contract declarative."

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("name_alias", "body_alias"),
    [("source_name", "wire_text"), ("body", "wire_text"), ("source_name", "name"), ("wire_text", "wire_text")],
)
def test_serialization_aliases_preserve_the_worker_envelope_during_ingestion(name_alias: str, body_alias: str) -> None:
    class AliasedSource(Source):
        name: str = Field(serialization_alias=name_alias)
        definition_version: str = Field(default="1", serialization_alias="wire_version")
        materialization: SourceMaterialization = Field(serialization_alias="wire_materialization")
        description: str | None = Field(default=None, serialization_alias="wire_description")
        body: str = Field(serialization_alias=body_alias)

    class AliasedAdapter:
        name = "aliased"
        input_class = str
        source_class = AliasedSource

        async def resolve(self, value: str, /) -> AliasedSource:
            return AliasedSource(
                name="remote-aliased",
                definition_version="2",
                materialization=SourceMaterialization.CAPTURED,
                description="Aliased description.",
                body=value,
            )

        async def read(self, source: AliasedSource, /) -> str:
            return source.body

    async def scenario() -> None:
        definition = AdapterSourceDefinition(AliasedAdapter(), version="2")
        worker = SourceDefinitionRegistry((definition,))
        source = await worker.resolve("Retain the aliased business value.")
        if body_alias == "name" or name_alias == body_alias:
            with pytest.raises(InvalidSourceDefinitionError):
                manifest_for_definition(definition)
            with pytest.raises(InvalidSourceDefinitionError):
                project_source_for_transport(worker, source)
            return
        manifest = manifest_for_definition(definition)
        observation = project_source_for_transport(worker, source)
        expected = {
            "name": "remote-aliased",
            "definition_version": "2",
            "materialization": "captured",
            "description": "Aliased description.",
            "wire_text": "Retain the aliased business value.",
        }
        assert observation.payload == expected
        assert source.model_dump(mode="json", by_alias=True) == {
            name_alias: "remote-aliased",
            "wire_version": "2",
            "wire_materialization": "captured",
            "wire_description": "Aliased description.",
            "wire_text": "Retain the aliased business value.",
        }

        async with SQLiteProfile.open(SQLiteConfig(), tables=SHARED_TABLES) as profile:
            contexts = RelationalContexts(database=profile.database, source_registry=SourceDefinitionRegistry(()))
            await contexts.register_source_definition(manifest)
            receipt = await contexts.submit_source_observation(
                SubmitSourceObservation(scope_id="scope-a", observation=observation)
            )
            stored = await (await contexts.get("scope-a")).sources.get(observation)

        assert receipt.source_ref.source_id == "remote-aliased"
        assert isinstance(stored, SourceObservation)
        assert stored.payload == expected

        async with SQLiteProfile.open(SQLiteConfig(), tables=SHARED_TABLES) as native_profile:
            async with native_profile.database.transaction() as connection:
                native_manifest = await SourceDefinitionManifestRepository().register_native(connection, definition)
            assert native_manifest is not None
            assert native_manifest.source_schema == AliasedSource.model_json_schema(mode="serialization")
            assert native_manifest.fingerprint != manifest.fingerprint

    asyncio.run(scenario())


def test_remote_source_observation_requires_captured_materialization() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((CONTENT_SOURCE_DEFINITION,))
        source = await registry.resolve(ContentCapture(source_id="turn-1", content="Retain this value."))
        observation = project_source_for_transport(registry, source)

        with pytest.raises(ValidationError):
            SourceObservation.model_validate(observation.model_dump(mode="json") | {"materialization": "referenced"})

    asyncio.run(scenario())


def test_remote_schema_references_are_rejected_without_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted = False

    def reject_request(*_args: object, **_kwargs: object) -> None:
        nonlocal attempted
        attempted = True
        raise OSError("network access is forbidden")  # noqa: TRY003

    monkeypatch.setattr(urllib.request, "urlopen", reject_request)
    validator = _json_schema_validator("remote", {"$ref": "http://127.0.0.1:9/schema"})

    with pytest.raises(Unresolvable):
        validator.validate({})
    assert not attempted

    with pytest.raises(ValidationError, match="remote schema references are not allowed"):
        SourceDefinitionManifest(
            name="remote",
            version="1",
            fingerprint=f"sha256:{'0' * 64}",
            source_schema={"$dynamicRef": "https://example.invalid/schema"},
        )
