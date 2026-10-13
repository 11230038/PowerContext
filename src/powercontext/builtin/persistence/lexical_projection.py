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

"""Refresh changed derived words using existing index initialization and transactions."""

from sqlalchemy import Table, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.artifacts.search import analyze_text
from powercontext.builtin.persistence.tables import TOPIC_MEMORY_ACTIVE_CHUNKS_TABLE, TOPIC_MEMORY_ACTIVE_TOPICS_TABLE


async def refresh_lexical_projections(connection: AsyncConnection, atomic_table: Table | None) -> None:
    """Preserve identities, authoritative fields and vectors; write only changed words."""
    projections = [
        (TOPIC_MEMORY_ACTIVE_TOPICS_TABLE, ("title", "summary")),
        (TOPIC_MEMORY_ACTIVE_CHUNKS_TABLE, ("chunk_text",)),
    ]
    if atomic_table is not None:
        projections.append((atomic_table, ("kind", "text")))
    for table, fields in projections:
        keys = tuple(table.primary_key.columns)
        columns = tuple(
            dict.fromkeys((*keys, table.c.revision, table.c.searchable_text, *(table.c[name] for name in fields)))
        )
        after = None
        changed = False
        while True:
            statement = select(*columns).order_by(*keys).limit(100)
            if after is not None:
                statement = statement.where(tuple_(*keys) > after)
            rows = (await connection.execute(statement)).mappings().all()
            if not rows:
                break
            for row in rows:
                searchable = analyze_text("\n".join(row[name] for name in fields))
                if row["searchable_text"] != searchable:
                    await connection.execute(
                        update(table)
                        .where(*(key == row[key.name] for key in keys), table.c.revision == row["revision"])
                        .values(searchable_text=searchable)
                    )
                    changed = True
            after = tuple(rows[-1][key.name] for key in keys)
        if changed and table is not atomic_table and connection.dialect.name == "sqlite":
            from powercontext.builtin.persistence.sqlite.topic_memory_index import SQLITE_TOPIC_MEMORY_FTS_MARKER_TABLE

            await connection.execute(SQLITE_TOPIC_MEMORY_FTS_MARKER_TABLE.delete())
