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

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from powercontext.cli import git_source
from powercontext.cli.git_source import InvalidGitHubSourceError, github_clone_url, source_checkout
from powercontext.cli.system import SetupError


def test_github_clone_url_rejects_unencrypted_http_source() -> None:
    with pytest.raises(InvalidGitHubSourceError):
        github_clone_url("http://github.com/oceanbase/powercontext")


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def remote_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repository = tmp_path / "remote"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "config", "user.name", "Test")
    (repository / "plugin.txt").write_text("first", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "first")
    monkeypatch.setenv("POWERCONTEXT_HOME", str(tmp_path / "state"))

    def clone(_source: str, ref: str, target: Path) -> None:
        _git(tmp_path, "clone", "--branch", ref, str(repository), str(target))

    monkeypatch.setattr(git_source, "clone_github_source", clone)
    return repository


def test_remote_upgrade_keeps_previous_checkout_usable(remote_repository: Path) -> None:
    first = source_checkout("oceanbase/powercontext", "main")
    (remote_repository / "plugin.txt").write_text("second", encoding="utf-8")
    _git(remote_repository, "commit", "-am", "second")

    second = source_checkout("oceanbase/powercontext", "main")

    assert second != first
    assert (first / "plugin.txt").read_text(encoding="utf-8") == "first"
    assert (second / "plugin.txt").read_text(encoding="utf-8") == "second"


@pytest.mark.parametrize("failure", [SetupError, KeyboardInterrupt])
def test_failed_refresh_preserves_checkout_and_cleans_staging(
    remote_repository: Path, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    installed = source_checkout("oceanbase/powercontext", "main")

    def fail_clone(_source: str, _ref: str, target: Path) -> None:
        target.mkdir()
        (target / "partial").write_text("incomplete", encoding="utf-8")
        raise failure

    monkeypatch.setattr(git_source, "clone_github_source", fail_clone)
    with pytest.raises(failure):
        source_checkout("oceanbase/powercontext", "main")
    assert (installed / "plugin.txt").read_text(encoding="utf-8") == "first"
    assert list(installed.parent.iterdir()) == [installed]
