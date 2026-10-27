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

"""Durable evidence-dependency nodes and their propagated availability.

Every mutation joins the caller's transaction. A node row stores its exact
binding as canonical JSON so a restart can resolve the original reference
without re-reading the artifact family.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.errors import InvalidRepositoryArgumentError
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE
from powercontext.limits import MAX_SCOPE_ID_LENGTH

LifecycleFamily = Literal["source", "memory", "topic"]
LifecyclePolicy = Literal["all", "any"]

_NODE_ID_LIMIT = 128


class StoredSourceLifecycleNode(BaseModel):
    """One registered lifecycle node with its current propagated availability."""

    node_id: str
    position: int
    family: LifecycleFamily
    binding: dict[str, Any]
    parents: tuple[str, ...] = ()
    policy: LifecyclePolicy = "all"
    revision: int
    available: bool
    last_sequence: int = 0
    last_fingerprint: str | None = None


class SourceLifecycleRepository:
    """Persist lifecycle nodes using caller-owned short transactions."""

    async def load(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        /,
    ) -> StoredSourceLifecycleNode | None:
        _require_scope(scope_id)
        _require_node_id("node_id", node_id)
        table = SOURCE_LIFECYCLE_NODES_TABLE
        row = (
            (await connection.execute(select(table).where(table.c.scope_id == scope_id, table.c.node_id == node_id)))
            .mappings()
            .one_or_none()
        )
        return None if row is None else _decode(row)

    async def list(self, connection: AsyncConnection, scope_id: str, /) -> tuple[StoredSourceLifecycleNode, ...]:
        _require_scope(scope_id)
        table = SOURCE_LIFECYCLE_NODES_TABLE
        rows = (
            await connection.execute(
                select(table).where(table.c.scope_id == scope_id).order_by(table.c.position, table.c.node_id)
            )
        ).mappings()
        return tuple(_decode(row) for row in rows)

    async def insert(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node: StoredSourceLifecycleNode,
        /,
    ) -> None:
        _require_scope(scope_id)
        await connection.execute(
            insert(SOURCE_LIFECYCLE_NODES_TABLE).values(
                scope_id=scope_id,
                node_id=node.node_id,
                position=node.position,
                family=node.family,
                binding=_encode(node.binding),
                parents=_encode(list(node.parents)),
                policy=node.policy,
                revision=node.revision,
                available=node.available,
                last_sequence=node.last_sequence,
                last_fingerprint=node.last_fingerprint,
            )
        )

    async def set_available(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        available: bool,
        /,
    ) -> None:
        _require_scope(scope_id)
        _require_node_id("node_id", node_id)
        table = SOURCE_LIFECYCLE_NODES_TABLE
        await connection.execute(
            update(table).where(table.c.scope_id == scope_id, table.c.node_id == node_id).values(available=available)
        )

    async def record_event(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        /,
        *,
        available: bool,
        sequence: int,
        fingerprint: str,
    ) -> None:
        _require_scope(scope_id)
        _require_node_id("node_id", node_id)
        table = SOURCE_LIFECYCLE_NODES_TABLE
        await connection.execute(
            update(table)
            .where(table.c.scope_id == scope_id, table.c.node_id == node_id)
            .values(available=available, last_sequence=sequence, last_fingerprint=fingerprint)
        )

    async def unavailable_topics(self, connection: AsyncConnection, scope_id: str, /) -> frozenset[str]:
        """Return Topic artifact ids whose registered Topic nodes are inactive."""

        _require_scope(scope_id)
        table = SOURCE_LIFECYCLE_NODES_TABLE
        rows = (
            await connection.execute(
                select(table.c.binding).where(
                    table.c.scope_id == scope_id,
                    table.c.family == "topic",
                    table.c.available.is_(False),
                )
            )
        ).scalars()
        artifact_ids: set[str] = set()
        for raw in rows:
            binding = json.loads(raw)
            artifact_id = binding.get("artifact_id")
            if isinstance(artifact_id, str):
                artifact_ids.add(artifact_id)
        return frozenset(artifact_ids)


def canonical_json(value: object) -> str:
    """Return stable JSON so equal bindings compare and persist identically."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _encode(value: object) -> str:
    return canonical_json(value)


def _decode(row: Any) -> StoredSourceLifecycleNode:
    binding = json.loads(row["binding"])
    parents = json.loads(row["parents"])
    return StoredSourceLifecycleNode(
        node_id=str(row["node_id"]),
        position=int(row["position"]),
        family=row["family"],
        binding=binding,
        parents=tuple(str(parent) for parent in parents),
        policy=row["policy"],
        revision=int(row["revision"]),
        available=bool(row["available"]),
        last_sequence=int(row["last_sequence"]),
        last_fingerprint=None if row["last_fingerprint"] is None else str(row["last_fingerprint"]),
    )


def _require_scope(scope_id: str) -> None:
    if not isinstance(scope_id, str) or not scope_id or len(scope_id) > MAX_SCOPE_ID_LENGTH:
        raise InvalidRepositoryArgumentError("scope_id", "must be a non-empty identifier within the length limit")


def _require_node_id(field: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > _NODE_ID_LIMIT:
        raise InvalidRepositoryArgumentError(field, "must be a non-empty trimmed identifier within the length limit")


__all__ = ["SourceLifecycleRepository", "StoredSourceLifecycleNode", "canonical_json"]
