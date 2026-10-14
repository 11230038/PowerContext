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

"""Apply the frozen additive p0004 revision to runtime-owned evidence tables.

The production bundle covers a historical subset of business tables. Runtime
profiles therefore apply this same frozen additive revision independently of
that bundle's whole-database inventory, without stamping unrelated schema or
backfilling declarations for old Source/Artifact rows. SQLite DDL joins the
caller's transaction; MySQL DDL may commit and is resumed by exact postconditions.
"""

from __future__ import annotations

import json
from pathlib import Path

from aiosqlite import Connection as SQLiteConnection
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.atomic_memory_evidence_schema import (
    ATOMIC_MEMORY_EVIDENCE_SCHEMA_TABLE,
    ATOMIC_MEMORY_EVIDENCE_SCHEMA_VERSION,
    ATOMIC_MEMORY_EVIDENCE_TABLES,
)
from powercontext.builtin.persistence.errors import PersistenceError


class AtomicMemoryEvidenceSchemaError(PersistenceError):
    """An evidence schema is not the registered versioned layout."""

    def __init__(self, detail: str) -> None:
        message = {
            "version": "Atomic Memory evidence schema version is unsupported",
            "shape": "Atomic Memory evidence table has an incompatible shape",
        }[detail]
        super().__init__(message)


async def apply_atomic_memory_evidence_migration(connection: AsyncConnection) -> None:
    """Add only missing p0004 tables, validate exact shapes, then mark ready.

    No reads or writes of Source/Artifact history are needed, and no current
    declaration is used to invent accepted historical inputs.
    """

    if connection.dialect.name == "sqlite":
        driver = (await connection.get_raw_connection()).driver_connection
        if isinstance(driver, SQLiteConnection) and not driver.in_transaction:
            await connection.exec_driver_sql("BEGIN IMMEDIATE")
    dialect = "sqlite" if connection.dialect.name == "sqlite" else "mysql"
    resources = Path(__file__).parent / "resources/schemas/atomic_memory_evidence_v1.json"
    statements = json.loads(resources.read_text())[dialect]
    for table, statement in zip(ATOMIC_MEMORY_EVIDENCE_TABLES, statements[:-1], strict=True):
        exists = await connection.run_sync(lambda sync, name=table.name: inspect(sync).has_table(name))
        if not exists:
            await connection.exec_driver_sql(statement)
        await _require_shape(connection, table.name, statement, dialect)
    marker = ATOMIC_MEMORY_EVIDENCE_SCHEMA_TABLE
    versions = tuple((await connection.execute(select(marker.c.schema_version))).scalars())
    if not versions:
        await connection.exec_driver_sql(statements[-1])
    elif versions != (ATOMIC_MEMORY_EVIDENCE_SCHEMA_VERSION,):
        raise AtomicMemoryEvidenceSchemaError("version")


async def _require_shape(connection: AsyncConnection, name: str, statement: str, dialect: str) -> None:
    if dialect == "sqlite":
        actual = await connection.exec_driver_sql(
            "SELECT type, name, sql FROM sqlite_schema WHERE (name = ? OR tbl_name = ?) "
            "AND substr(name, 1, 7) != 'sqlite_' ORDER BY type, name",
            (name, name),
        )
        if actual.all() != [("table", name, statement)]:
            raise AtomicMemoryEvidenceSchemaError("shape")
        return
    # Reuse the frozen MySQL inventory parser so physical formatting accepted
    # by the shared backend does not become a second schema convention.
    from powercontext.builtin.persistence.migrations.mysql_schema import _matches, _parse_table

    actual = (await connection.exec_driver_sql(f"SHOW CREATE TABLE `{name}`")).one()[1]
    actual_name, actual_table = _parse_table(actual)
    expected_name, expected_table = _parse_table(statement)
    if not _matches(
        {"tables": {actual_name: actual_table}, "views": [], "triggers": []},
        {"tables": {expected_name: expected_table}, "views": [], "triggers": []},
    ):
        raise AtomicMemoryEvidenceSchemaError("shape")
