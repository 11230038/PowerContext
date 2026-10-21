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

"""Reproduce unsupported 1.3.0 upgrade rejection on an actual old SQLite Server.

This is a negative regression, never positive upgrade acceptance. Once the path
is supported, replace this fixture with the full matrix suite before advertising it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import httpx
from ci_release_smoke import _available_port, _stop_process, _wait_until_ready
from upgrade_release_gate import installed, require, run, sha256, wheel_version


def console(python: Path) -> Path:
    return python.with_name("powercontext.exe" if os.name == "nt" else "powercontext")


def source_database(python: Path, directory: Path, environment: dict[str, str], log: Path) -> dict[str, str | bool]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    with log.open("w") as stream:
        process = subprocess.Popen(  # noqa: S603 -- installed source CLI against a disposable database
            [str(console(python)), "server", "run", "--no-env-file", "--host", "127.0.0.1", "--port", str(port)],
            cwd=directory,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
            text=True,
        )
        try:
            _wait_until_ready(base_url, process, 90)
            with httpx.Client(base_url=base_url, trust_env=False, timeout=30) as client:
                response = client.post(
                    "/v1/scopes",
                    json={
                        "title": "Upgrade fixture",
                        "summary": "Disposable old-release database for upgrade validation.",
                        "idempotency_key": "upgrade-fixture",
                    },
                )
                response.raise_for_status()
                scope_id = response.json()["scope_id"]
                response = client.post(
                    "/v1/memory/remember",
                    json={"scope_id": scope_id, "kind": "fact", "text": "Historical release migration fixture."},
                )
                response.raise_for_status()
                require(response.json().get("records"), "Old Server did not persist the fixture")
                response = client.post(
                    "/v1/memory/search", json={"scope_id": scope_id, "query": "historical migration", "mode": "fts"}
                )
                response.raise_for_status()
                require(response.json().get("hits"), "Old Server cannot retrieve its fixture")
                return {"scope_id": scope_id, "memory_readback": True}
        finally:
            _stop_process(process)


def rejected(command: list[str], environment: dict[str, str], directory: Path, log: Path, reason: str) -> None:
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(  # noqa: S603 -- installed target CLI, isolated data only
            command,
            env=environment,
            cwd=directory,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        try:
            process.wait(timeout=90)
        finally:
            _stop_process(process)
    output = log.read_text(encoding="utf-8")
    require(process.returncode != 0 and reason in output, f"Expected rejection {reason}; inspect {log.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("POWERCONTEXT_", "PYTEST_")) and key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    environment["NO_PROXY"] = environment["no_proxy"] = "localhost,127.0.0.1"
    with tempfile.TemporaryDirectory(prefix="pc-old-release-") as temporary:
        directory = Path(temporary)
        interpreters = {}
        for role, package in {"source": "powercontext[cli,server]==1.3.0", "target": f"{wheel}[cli,server]"}.items():
            venv = directory / role
            run(
                ["uv", "venv", "--python", "3.12", str(venv)],
                environment=environment,
                cwd=directory,
                log=output / f"{role}-venv.log",
            )
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            run(
                ["uv", "pip", "install", "--python", str(python), package],
                environment=environment,
                cwd=directory,
                log=output / f"{role}-install.log",
            )
            interpreters[role] = python
        metadata = {role: installed(python, environment, directory) for role, python in interpreters.items()}
        require(metadata["source"]["powercontext"] == "1.3.0", "Wrong source package")
        require(metadata["target"]["powercontext"] == wheel_version(wheel), "Wrong target package")
        database = directory / "source.db"
        environment.update({
            "POWERCONTEXT_HOME": str(directory / "home"),
            "POWERCONTEXT_SERVER_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
            "POWERCONTEXT_SERVER_ACCESS_MODE": "disabled",
        })
        seed = source_database(interpreters["source"], directory, environment, output / "source.log")
        with sqlite3.connect(database) as connection:
            schema = connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
            ).fetchall()
        tables = {row[1] for row in schema if row[0] == "table"}
        require(
            {"pc_artifact_candidate_heads", "pc_artifact_candidate_versions", "pc_scopes", "pc_artifacts"} <= tables,
            "Source fixture lacks historical Server objects",
        )
        (output / "source-schema.json").write_text(json.dumps(schema, indent=2) + "\n")
        env_file = directory / "deployment.env"
        env_file.write_text(f"POWERCONTEXT_SERVER_DATABASE_URL=sqlite+aiosqlite:///{database}\n")
        target = str(console(interpreters["target"]))
        rejected(
            [target, "server", "db-migrate", "status", "--env-file", str(env_file)],
            environment,
            directory,
            output / "status.log",
            "unknown_baseline",
        )
        rejected(
            [target, "server", "run", "--no-env-file", "--host", "127.0.0.1", "--port", str(_available_port())],
            environment,
            directory,
            output / "legacy-startup.log",
            "migration_required",
        )
        # This second negative fixture intentionally adds only the prototype control
        # table to a copy. It must never be mistaken for a completed migration.
        versioned = directory / "versioned.db"
        shutil.copyfile(database, versioned)
        with sqlite3.connect(versioned) as connection:
            connection.execute("CREATE TABLE pc_schema_revision (version_num VARCHAR(32) PRIMARY KEY)")
        environment["POWERCONTEXT_SERVER_DATABASE_URL"] = f"sqlite+aiosqlite:///{versioned}"
        rejected(
            [target, "server", "run", "--no-env-file", "--host", "127.0.0.1", "--port", str(_available_port())],
            environment,
            directory,
            output / "versioned-startup.log",
            "migration_framework_not_ready",
        )
        evidence = {
            "kind": "unsupported-upgrade-regression",
            "backend": "sqlite",
            "engine_version": sqlite3.sqlite_version,
            "installed": metadata,
            "wheel_sha256": sha256(wheel),
            "seed": seed,
            "table_count": len(tables),
            "status": "passed",
        }
        (output / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print("Actual 1.3.0 full database: all three unsupported-upgrade regressions reproduced.")


if __name__ == "__main__":
    main()
