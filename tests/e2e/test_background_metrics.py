# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import pytest

from powercontext.builtin.persistence.oceanbase import OceanBaseConfig


@pytest.mark.parametrize("migration_backend", ["oceanbase"], indirect=True)
def test_background_cli_serves_only_authorized_metrics_and_stops_cleanly(tmp_path, migration_backend):
    import os
    import signal
    import socket
    import subprocess
    import sys
    import time

    import httpx

    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("POWERCONTEXT_SERVER_")}
    assert isinstance(migration_backend.config, OceanBaseConfig)
    environment.update({
        "POWERCONTEXT_SERVER_DATABASE_KIND": "oceanbase",
        "POWERCONTEXT_SERVER_DATABASE_URL": migration_backend.config.url.get_secret_value(),
        "POWERCONTEXT_SERVER_ACCESS_MODE": "enforced",
        "POWERCONTEXT_SERVER_AUTH_TOKEN": "background-fixture-token",
        "POWERCONTEXT_SERVER_METRICS_BACKGROUND_PORT": str(port),
        "POWERCONTEXT_SERVER_METRICS_ENABLED": "true",
    })
    with (tmp_path / "background.log").open("w+") as output:
        process = subprocess.Popen(
            [
                os.path.join(os.path.dirname(sys.executable), "powercontext"),
                "server",
                "run",
                "--role",
                "background",
                "--no-env-file",
            ],
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 20
            ready = False
            with httpx.Client(timeout=0.5) as client:
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        ready = client.get(base + "/health/live").status_code == 200
                    except httpx.TransportError:
                        time.sleep(0.05)
                    if ready:
                        break
                output.flush()
                output.seek(0)
                assert ready, output.read()
                assert client.get(base + "/metrics").status_code == 401
                headers = {"Authorization": "Bearer background-fixture-token"}
                response = client.get(base + "/metrics", headers=headers)
                assert response.status_code == 200
                assert 'powercontext_server_readiness_state{state="ready"} 1.0' in response.text
                assert client.get(base + "/v1/scopes/default", headers=headers).status_code == 404
                process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
