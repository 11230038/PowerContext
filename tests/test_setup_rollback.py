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


"""Installation failure restores exact user configuration bytes."""

from pathlib import Path

import pytest

from powercontext.cli import installation


def test_failed_local_publication_restores_exact_configuration_bytes(tmp_path, monkeypatch):
    original = b'{\r\n  "custom": true,\n  "note": "keep original line endings"\r\n}\r\n'
    home = tmp_path / "workbuddy"
    home.mkdir()
    settings = home / "settings.json"
    settings.write_bytes(original)
    monkeypatch.setenv("WORKBUDDY_HOME", str(home))
    write = installation.write_bytes

    def fail_settings(path, content):
        if path == settings:
            raise OSError("settings write failed")  # noqa: TRY003
        write(path, content)

    monkeypatch.setattr(installation, "write_bytes", fail_settings)
    with pytest.raises(OSError, match="settings write failed"):
        installation.installers()["workbuddy"]().install(installation.PluginSource(str(Path(__file__).parents[1])))
    assert settings.read_bytes() == original
    assert not (home / "hooks/workbuddy_powercontext_hook.py").exists()
