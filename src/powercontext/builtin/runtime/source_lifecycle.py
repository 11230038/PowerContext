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

"""Propagate Source withdrawal and restore through a scope's evidence DAG.

Callers register each Source, Memory entry and Topic artifact once with its
parents and an ``all`` / ``any`` support policy. Applying a Source lifecycle
event recomputes every descendant's availability in registration order, keeps
Memory entries inactive through the native state, and hides unsupported Topic
artifacts from native recall. References recorded at registration stay exact,
so ``audit`` can still read a withdrawn revision.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import Memory, MemoryEntryVersion
from powercontext.builtin.artifacts.topic_memory import TopicMemory
from powercontext.builtin.persistence.errors import RepositoryNotFoundError
from powercontext.builtin.persistence.source_lifecycle import (
    LifecycleFamily,
    LifecyclePolicy,
    SourceLifecycleRepository,
    StoredSourceLifecycleNode,
    canonical_json,
)
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory import MemoryService
    from powercontext.builtin.runtime.relational import RelationalContexts

__all__ = ["SourceLifecycleError", "SourceLifecycleEvent", "SourceLifecycleService"]

LifecyclePurpose = Literal["generation", "audit"]
_DEACTIVATION_REASON = "source-lifecycle"
_SOURCE_POLICY: LifecyclePolicy = "all"


class SourceLifecycleError(ValueError):
    """Reject a lifecycle graph mutation or an event that breaks the contract."""


class SourceLifecycleEvent(BaseModel):
    """One accepted Source lifecycle transition, validated field by field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-blank string")  # noqa: TRY003
        return value


class SourceLifecycleService:
    """Create scope-bound lifecycle views over one composition's storage."""

    def __init__(self, contexts: RelationalContexts) -> None:
        self._contexts = contexts

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._contexts, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    """Register one scope's evidence graph and apply Source lifecycle events."""

    def __init__(self, contexts: RelationalContexts, scope_id: str) -> None:
        self._contexts = contexts
        self.scope_id = scope_id
        self._repository = SourceLifecycleRepository()

    async def register_source(
        self,
        node_id: str,
        source_ref: SourceRef,
        /,
        *,
        revision: int = 3,
    ) -> None:
        """Bind one captured Source as an initially available lifecycle root."""

        _validate_node_id(node_id)
        _validate_revision(revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source_ref must be a SourceRef")  # noqa: TRY003
        binding = {"source_type": source_ref.source_type, "source_id": source_ref.source_id}
        async with self._contexts.database.transaction() as connection:
            existing = await self._repository.load(connection, self.scope_id, node_id)
            if existing is not None:
                _require_same_registration(existing, "source", binding, (), _SOURCE_POLICY, revision)
                return
            try:
                await self._contexts.repositories.sources.get(connection, self.scope_id, source_ref)
            except RepositoryNotFoundError as error:
                raise SourceLifecycleError(f"unreadable source reference for {node_id!r}") from error  # noqa: TRY003
            position = await self._next_position(connection)
            await self._repository.insert(
                connection,
                self.scope_id,
                StoredSourceLifecycleNode(
                    node_id=node_id,
                    position=position,
                    family="source",
                    binding=binding,
                    parents=(),
                    policy=_SOURCE_POLICY,
                    revision=revision,
                    available=True,
                ),
            )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: tuple[str, ...],
        policy: LifecyclePolicy = "all",
    ) -> None:
        """Bind one exact Memory entry to registered parents and reconcile its state."""

        _validate_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("citation must be a MemoryCitation")  # noqa: TRY003
        checked_parents = await self._checked_derived(node_id, parents, policy)
        binding = _citation_binding(citation)
        memory_service = await self._memory_service()
        try:
            await memory_service.validate_citation(citation)
        except Exception as error:
            raise SourceLifecycleError(f"unreadable memory citation for {node_id!r}") from error  # noqa: TRY003
        row, created = await self._register_derived(node_id, "memory", binding, checked_parents, policy, revision=1)
        if created or not row.available:
            await self._reconcile_memory(row)

    async def register_topic(
        self,
        node_id: str,
        reference: ArtifactRef,
        /,
        *,
        parents: tuple[str, ...],
        policy: LifecyclePolicy = "all",
    ) -> None:
        """Bind one exact Topic artifact to registered parents."""

        _validate_node_id(node_id)
        if not isinstance(reference, ArtifactRef) or reference.family != TopicMemory.family:
            raise SourceLifecycleError("reference must be a Topic Memory ArtifactRef")  # noqa: TRY003
        checked_parents = await self._checked_derived(node_id, parents, policy)
        binding = _reference_binding(reference)
        async with self._contexts.database.transaction() as connection:
            try:
                await self._contexts.repositories.artifacts.get(connection, self.scope_id, reference)
            except RepositoryNotFoundError as error:
                raise SourceLifecycleError(f"unreadable topic reference for {node_id!r}") from error  # noqa: TRY003
        await self._register_derived(node_id, "topic", binding, checked_parents, policy, revision=1)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Record one Source event, propagate it, and return sorted available ids."""

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event must be a SourceLifecycleEvent")  # noqa: TRY003
        await self._apply_event(event)
        rows = await self._reconcile_scope()
        return sorted(row.node_id for row in rows if row.available)

    async def resolve(self, node_id: str, purpose: LifecyclePurpose = "generation") -> Any:
        """Return the original reference when the node may be used for ``purpose``."""

        _validate_node_id(node_id)
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("unknown lifecycle purpose")  # noqa: TRY003
        async with self._contexts.database.transaction() as connection:
            row = await self._repository.load(connection, self.scope_id, node_id)
        if row is None:
            raise SourceLifecycleError(f"unknown lifecycle node {node_id!r}")  # noqa: TRY003
        if purpose == "generation" and not row.available:
            raise SourceLifecycleError(f"lifecycle node {node_id!r} is not available")  # noqa: TRY003
        return _decode_reference(row)

    # -- registration internals -------------------------------------------------

    async def _checked_derived(
        self,
        node_id: str,
        parents: tuple[str, ...],
        policy: LifecyclePolicy,
    ) -> tuple[str, ...]:
        if policy not in ("all", "any"):
            raise SourceLifecycleError("policy must be 'all' or 'any'")  # noqa: TRY003
        if isinstance(parents, str) or not isinstance(parents, (tuple, list)) or not parents:
            raise SourceLifecycleError("a derived node requires at least one parent")  # noqa: TRY003
        ordered: list[str] = []
        seen: set[str] = set()
        for parent in tuple(parents):
            _validate_node_id(parent)
            if parent == node_id:
                raise SourceLifecycleError("a node cannot depend on itself")  # noqa: TRY003
            if parent in seen:
                raise SourceLifecycleError("parents must be unique")  # noqa: TRY003
            seen.add(parent)
            ordered.append(parent)
        async with self._contexts.database.transaction() as connection:
            known = {row.node_id for row in await self._repository.list(connection, self.scope_id)}
        missing = [parent for parent in ordered if parent not in known]
        if missing:
            raise SourceLifecycleError(f"unregistered parent {missing[0]!r}")  # noqa: TRY003
        return tuple(ordered)

    async def _register_derived(
        self,
        node_id: str,
        family: LifecycleFamily,
        binding: dict[str, Any],
        parents: tuple[str, ...],
        policy: LifecyclePolicy,
        *,
        revision: int,
    ) -> tuple[StoredSourceLifecycleNode, bool]:
        async with self._contexts.database.transaction() as connection:
            existing = await self._repository.load(connection, self.scope_id, node_id)
            if existing is not None:
                _require_same_registration(existing, family, binding, parents, policy, revision)
                return existing, False
            row = await self._insert_derived(connection, node_id, family, binding, parents, policy)
            return row, True

    async def _insert_derived(
        self,
        connection: Any,
        node_id: str,
        family: LifecycleFamily,
        binding: dict[str, Any],
        parents: tuple[str, ...],
        policy: LifecyclePolicy,
        *,
        revision: int = 1,
    ) -> StoredSourceLifecycleNode:
        rows = {row.node_id: row for row in await self._repository.list(connection, self.scope_id)}
        available = _supported((rows[parent].available for parent in parents), policy)
        row = StoredSourceLifecycleNode(
            node_id=node_id,
            position=await self._next_position(connection),
            family=family,
            binding=binding,
            parents=parents,
            policy=policy,
            revision=revision,
            available=available,
        )
        await self._repository.insert(connection, self.scope_id, row)
        return row

    async def _next_position(self, connection: Any) -> int:
        rows = await self._repository.list(connection, self.scope_id)
        return 1 if not rows else max(row.position for row in rows) + 1

    async def _memory_service(self) -> MemoryService:
        context = await self._contexts.get(self.scope_id)
        return context.artifacts.memory

    # -- propagation internals --------------------------------------------------

    async def _apply_event(self, event: SourceLifecycleEvent) -> None:
        fingerprint = _fingerprint(event)
        async with self._contexts.database.transaction() as connection:
            rows = {row.node_id: row for row in await self._repository.list(connection, self.scope_id)}
            source = rows.get(event.node_id)
            if source is None or source.family != "source":
                raise SourceLifecycleError(f"unknown Source lifecycle node {event.node_id!r}")  # noqa: TRY003
            if event.revision != source.revision:
                raise SourceLifecycleError("event revision does not match the registered Source")  # noqa: TRY003
            if event.sequence < source.last_sequence:
                raise SourceLifecycleError("event sequence must increase monotonically")  # noqa: TRY003
            if event.sequence == source.last_sequence:
                if fingerprint != source.last_fingerprint:
                    raise SourceLifecycleError("event sequence was already used by different content")  # noqa: TRY003
            else:
                await self._repository.record_event(
                    connection,
                    self.scope_id,
                    event.node_id,
                    available=event.available,
                    sequence=event.sequence,
                    fingerprint=fingerprint,
                )
                rows[event.node_id] = source.model_copy(
                    update={
                        "available": event.available,
                        "last_sequence": event.sequence,
                        "last_fingerprint": fingerprint,
                    }
                )
            await self._propagate(connection, rows)

    async def _propagate(
        self,
        connection: Any,
        rows: dict[str, StoredSourceLifecycleNode],
    ) -> None:
        derived = sorted(
            (row for row in rows.values() if row.family != "source"),
            key=lambda row: row.position,
        )
        for row in derived:
            available = _supported((rows[parent].available for parent in row.parents), row.policy)
            if available == row.available:
                continue
            await self._repository.set_available(connection, self.scope_id, row.node_id, available)
            rows[row.node_id] = row.model_copy(update={"available": available})

    async def _reconcile_scope(self) -> tuple[StoredSourceLifecycleNode, ...]:
        async with self._contexts.database.transaction() as connection:
            rows = await self._repository.list(connection, self.scope_id)
        for row in rows:
            if row.family == "memory":
                await self._reconcile_memory(row)
        return rows

    async def _reconcile_memory(self, row: StoredSourceLifecycleNode) -> None:
        citation = MemoryCitation.model_validate(row.binding)
        memory_service = await self._memory_service()
        memory, entries = await memory_service.head_entries(citation.memory_ref.artifact_id)
        version = next((entry for entry in entries if entry.entry_id == citation.entry_id), None)
        if version is None:
            raise SourceLifecycleError(f"bound entry for {row.node_id!r} is missing from the head")  # noqa: TRY003
        target = "active" if row.available else "inactive"
        if _entry_state(memory, version) == target:
            return
        if target == "active":
            await memory_service.reactivate(memory, entries=(version,), reason=_DEACTIVATION_REASON)
        else:
            await memory_service.forget(memory, entries=(version,), reason=_DEACTIVATION_REASON)


def _supported(values: Any, policy: LifecyclePolicy) -> bool:
    support = tuple(values)
    return all(support) if policy == "all" else any(support)


def _entry_state(memory: Memory, version: MemoryEntryVersion) -> str:
    for item in memory.content.manifest.entries:
        if item.entry_id == version.entry_id:
            if item.entry_version_id != version.entry_version_id:
                raise SourceLifecycleError("registered entry version changed underneath the binding")  # noqa: TRY003
            return item.state
    raise SourceLifecycleError("registered entry is not present in the Memory head")  # noqa: TRY003


def _citation_binding(citation: MemoryCitation) -> dict[str, Any]:
    return {
        "entry_id": citation.entry_id,
        "entry_version_id": citation.entry_version_id,
        "memory_ref": {
            "family": citation.memory_ref.family,
            "artifact_id": citation.memory_ref.artifact_id,
            "revision": citation.memory_ref.revision,
        },
    }


def _reference_binding(reference: ArtifactRef) -> dict[str, Any]:
    return {
        "family": reference.family,
        "artifact_id": reference.artifact_id,
        "revision": reference.revision,
    }


def _decode_reference(row: StoredSourceLifecycleNode) -> Any:
    if row.family == "source":
        return SourceRef.model_validate(row.binding)
    if row.family == "memory":
        return MemoryCitation.model_validate(row.binding)
    return ArtifactRef.model_validate(row.binding)


def _require_same_registration(
    existing: StoredSourceLifecycleNode,
    family: LifecycleFamily,
    binding: dict[str, Any],
    parents: tuple[str, ...],
    policy: LifecyclePolicy,
    revision: int,
) -> None:
    if (
        existing.family != family
        or canonical_json(existing.binding) != canonical_json(binding)
        or existing.parents != tuple(parents)
        or existing.policy != policy
        or existing.revision != revision
    ):
        raise SourceLifecycleError(f"node {existing.node_id!r} is already registered differently")  # noqa: TRY003


def _fingerprint(event: SourceLifecycleEvent) -> str:
    material = canonical_json({
        "node_id": event.node_id,
        "revision": event.revision,
        "sequence": event.sequence,
        "available": event.available,
        "reason": event.reason,
    })
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _validate_node_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
        raise SourceLifecycleError("node_id must be a non-empty trimmed string of at most 128 characters")  # noqa: TRY003


def _validate_revision(value: int) -> None:
    if type(value) is not int or value < 1:
        raise SourceLifecycleError("revision must be a positive integer")  # noqa: TRY003
