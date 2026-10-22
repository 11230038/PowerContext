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

"""Terminate a migration client after the remote backend completes registered DDL."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import Engine, event

from powercontext.builtin.persistence.oceanbase import OceanBaseConfig
from tests.builtin.persistence.test_mysql_migration_runner import _BackendTarget, _full_server_runner


def main() -> None:
    evidence = Path(sys.argv[1])
    backend = _BackendTarget(
        OceanBaseConfig(url=SecretStr(os.environ["POWERCONTEXT_MIGRATION_CRASH_TARGET"])), evidence
    )

    @event.listens_for(Engine, "after_cursor_execute")
    def exit_after_ddl(connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().startswith("CREATE TABLE pc_retained_dream_candidate_versions"):
            connection_id = connection.exec_driver_sql("SELECT CONNECTION_ID()").scalar_one()
            with (evidence / "client-exit.json").open("w", encoding="utf-8") as marker:
                json.dump({"connection_id": connection_id}, marker)
                marker.flush()
                os.fsync(marker.fileno())
            # Bypass Python cleanup and leave the remote interruption unacknowledged.
            os._exit(73)

    runner = _full_server_runner(backend)
    plan = runner.plan(backup_policy="manual")
    runner.apply(
        plan_id=plan.plan_id,
        accepted=True,
        maintenance_confirmed=True,
        backup_policy="manual",
        backup_confirmed=True,
        backup_ref="operator://manual-backup",
    )
    raise AssertionError("The registered DDL exit point was not reached")  # noqa: TRY003


if __name__ == "__main__":
    main()
