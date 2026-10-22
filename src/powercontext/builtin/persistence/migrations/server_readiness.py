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

"""Full Server bootstrap and read-only admission for versioned storage."""

from sqlalchemy import inspect

from .bundle import sqlite_inventory
from .models import MigrationError, digest


def check_server_schema(connection):
    from .deployment import server_bundle
    from .mysql_schema import MySQLSchema, mysql_inventory

    bundle = server_bundle()
    revisions = connection.exec_driver_sql("SELECT version_num FROM pc_schema_revision").scalars().all()
    if revisions != [bundle.head]:
        raise MigrationError("migration_required", "The full Server revision chain is incomplete.")
    if connection.dialect.name == "sqlite":
        inventory = sqlite_inventory(connection)
        for name in bundle.retained_objects:
            objects = [row for row in inventory if row[1] == name or row[2] == name]
            if objects and digest(objects) not in bundle.retained_fingerprints[name]:
                raise MigrationError("incompatible_schema", "A retained migration object has changed.")
        bundle.verify(
            bundle.head,
            digest(sqlite_inventory(connection, exclude=frozenset({"pc_schema_revision", *bundle.retained_objects}))),
        )
        if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise MigrationError("verification_failed", "A live foreign key is invalid.")
        backend = "sqlite"
    else:
        schema = MySQLSchema(bundle)
        schema.verify(mysql_inventory(connection), bundle.head)
        backend = "seekdb"
    bundle.domains.validate(connection, bundle.head, backend=backend, configuration={})


def prepare_server_storage(settings, *, injected_embedding=False):
    from .deployment import deployment_runner

    database = settings.database
    if database.kind == "sqlite" and database.is_in_memory:
        return
    if injected_embedding or settings.inference.embedding_model is not None or settings.code.enabled:
        _check_unmanaged_optional_profile(database)
        return
    if database.kind == "oceanbase":
        from .connections import MaintenanceConnections

        def verify(connection, identity, guard):
            if connection is None or "pc_schema_revision" not in inspect(connection).get_table_names():
                raise MigrationError(
                    "migration_required", "Initialize the remote database with an explicit db-migrate job."
                )
            check_server_schema(connection)

        MaintenanceConnections(database).run(verify)
        return
    runner = deployment_runner(settings)
    plan = runner.plan()
    if plan.state == "uninitialized" and database.kind in {"sqlite", "seekdb"}:
        runner.apply(plan_id=plan.plan_id, accepted=True, maintenance_confirmed=True)
    elif plan.state != "ready":
        raise MigrationError(plan.state, "Stop writers and run powercontext server db-migrate apply before startup.")


def _check_unmanaged_optional_profile(database):
    """Preserve existing optional-profile bootstrap without adopting managed storage.

    Optional layouts need separate full-bundle profiles. Existing domain startup
    checks still reject old Candidate layouts; this is not an upgrade fallback.
    """
    from powercontext.builtin.persistence.dream_schema import check_dream_schema

    from .connections import MaintenanceConnections

    def check(connection):
        if "pc_schema_revision" in inspect(connection).get_table_names():
            raise MigrationError(
                "unsupported_upgrade_configuration",
                "This managed database has no registered vector/Code configuration transition.",
            )
        check_dream_schema(connection)

    if database.kind != "sqlite":
        MaintenanceConnections(database).run(
            lambda connection, identity, guard: check(connection) if connection is not None else None
        )
        return
    from pathlib import Path
    from urllib.parse import quote

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    url = make_url(database.url)
    # Unmanaged URI profiles retain their existing domain admission behavior.
    if url.query or not url.database or not Path(url.database).is_file():
        return
    path = quote(str(Path(url.database).absolute()), safe="/")
    engine = create_engine(f"sqlite:///file:{path}?mode=ro&uri=true")
    try:
        with engine.connect() as connection:
            check(connection)
    finally:
        engine.dispose()
