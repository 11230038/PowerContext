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

"""Select maintenance adapters without initializing the business runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sqlalchemy.engine import make_url

from powercontext.builtin.persistence.oceanbase import OceanBaseConfig
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.persistence.sqlite import SQLiteConfig

from .bundle import MigrationBundle
from .connections import MaintenanceConnections
from .models import MigrationError
from .mysql import MySQLMigrationRunner
from .sqlite import SQLiteMigrationRunner
from .topic_memory_recovery import TopicMemoryRecoveryMigrationRunner

if TYPE_CHECKING:
    from powercontext.server.settings import ServerSettings


def server_bundle() -> MigrationBundle:
    """The complete, shared Server revision chain."""
    return MigrationBundle(Path(__file__).parent / "server_resources")


def production_bundle() -> MigrationBundle:
    """Load installed resources; readiness is scoped to this acceptance bundle."""
    return MigrationBundle(Path(__file__).parent / "resources")


MigrationRunner = SQLiteMigrationRunner | MySQLMigrationRunner | TopicMemoryRecoveryMigrationRunner


def deployment_runner(  # noqa: C901 -- Keep ordered admission checks with their operation.
    settings: ServerSettings,
    *,
    evidence_dir: Path | None = None,
    lock_coordination: Literal["single-host"] | None = None,
    acknowledge_previous_run: str | None = None,
    bundle: Literal["server", "artifacts", "topic-memory-recovery"] = "server",
) -> MigrationRunner:
    """Use the real configured identity without opening a business profile."""
    database = settings.database
    from powercontext.builtin.runtime.config import BuiltinConfig
    from powercontext.builtin.runtime.processing_registry import canonical_processing_manifest

    configuration = database.model_dump(mode="json", exclude={"url", "echo"})
    if bundle == "server":
        if settings.inference.embedding_model is not None or settings.code.enabled:
            raise MigrationError(
                "unsupported_upgrade_configuration",
                "The registered 1.3.0 Server path covers the no-vector, Code-disabled configuration.",
            )
        config = BuiltinConfig(
            code=settings.code,
            runtime=settings.runtime,
            database=database,
            inference=settings.inference,
            handoff_report=settings.handoff_report,
            external_skills=settings.external_skills,
        )
        configuration.update(
            processing_manifest=canonical_processing_manifest(config),
            embedding_enabled=settings.inference.embedding_model is not None,
        )
    selected = server_bundle() if bundle == "server" else production_bundle()
    if bundle == "topic-memory-recovery":
        if not isinstance(database, (SQLiteConfig, SeekDBConfig, OceanBaseConfig)):
            raise MigrationError("unsupported_backend", "The database has no Topic recovery migration adapter.")
        return TopicMemoryRecoveryMigrationRunner(
            database,
            evidence_directory=evidence_dir,
            lock_coordination=lock_coordination,
            acknowledge_previous_run=acknowledge_previous_run,
        )
    if acknowledge_previous_run is not None and not isinstance(database, OceanBaseConfig):
        raise MigrationError("unsupported_option", "--acknowledge-previous-run is supported only for OceanBase.")
    if isinstance(database, (SeekDBConfig, OceanBaseConfig)):
        if evidence_dir is None:
            if isinstance(database, OceanBaseConfig):
                raise MigrationError(
                    "evidence_required",
                    "OceanBase maintenance requires --evidence-dir on one fixed host, shared by all migration Jobs.",
                )
            target = database.path.expanduser().resolve()
            evidence_dir = target.with_name(target.name + ".pc-migration-state")
        if isinstance(database, OceanBaseConfig) and lock_coordination != "single-host":
            raise MigrationError(
                "coordination_required",
                "OceanBase requires --lock-coordination single-host; run all migrators on one fixed host and evidence directory.",
            )
        return MySQLMigrationRunner(
            MaintenanceConnections(
                database,
                evidence_directory=evidence_dir,
                lock_coordination=lock_coordination,
                acknowledge_previous_run=acknowledge_previous_run,
            ),
            selected,
            evidence_directory=evidence_dir,
            configuration=configuration,
        )
    if not isinstance(database, SQLiteConfig):
        raise MigrationError("unsupported_backend", "The database has no registered migration adapter.")
    url = make_url(database.url)
    if url.query or not url.database or url.username or url.password or url.host or url.port or database.is_in_memory:
        raise MigrationError(
            "unsupported_target", "Use a regular SQLite file URL without credentials, host, port or URI options."
        )
    # Match SQLite's URL normalization before the runner expands standalone Path inputs.
    target = Path(os.path.abspath(url.database))
    return SQLiteMigrationRunner(
        target,
        selected,
        configuration=configuration,
        evidence_directory=evidence_dir,
    )
