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

"""Release-blocking regressions, not evidence that any database upgrade works."""

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
import upgrade_release_gate as gate
import upgrade_release_matrix as matrix
import yaml


@pytest.fixture
def release(tmp_path, monkeypatch):
    persistence = tmp_path / "src/powercontext/builtin/persistence/tables.py"
    persistence.parent.mkdir(parents=True)
    persistence.write_text("# disposable persistence input\n")
    contract = tmp_path / "openapi/powercontext.yaml"
    contract.parent.mkdir()
    contract.write_text("info:\n  version: 2.0.0\n")
    (tmp_path / "release").mkdir()
    policy = {
        "format": 2,
        "target_version": "2.0.0",
        "mode": "fresh-install-only",
        "schema_review": {"persistence_sha256": gate.managed_digest(tmp_path), "rationale": "No upgrades supported"},
        "cases": [],
        "automatic_sources": None,
    }
    (tmp_path / gate.MANIFEST).write_text(json.dumps(policy))
    monkeypatch.setattr(
        matrix,
        "fetch_catalog",
        lambda: {
            "releases": {
                "1.3.0": [
                    {
                        "filename": "powercontext-1.3.0-py3-none-any.whl",
                        "packagetype": "bdist_wheel",
                        "url": "https://files.pythonhosted.org/packages/test.whl",
                        "digests": {"sha256": "a" * 64},
                    }
                ]
            }
        },
    )
    for language in ("en", "zh"):
        page = tmp_path / f"docs/{language}/docs/get-started/install-and-run.md"
        page.parent.mkdir(parents=True)
        page.write_text("<!-- upgrade-support:start -->\nplaceholder\n<!-- upgrade-support:end -->\n")
    gate.check_docs(tmp_path, policy, write=True)
    wheel = tmp_path / "powercontext-2.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("powercontext-2.0.0.dist-info/METADATA", "Name: powercontext\nVersion: 2.0.0\n")
    return tmp_path, wheel, policy


def test_fresh_install_policy_does_not_claim_upgrade_acceptance(release):
    root, wheel, policy = release
    gate.gate(root, wheel, root / "evidence", release=True, release_notes=gate.support_text(policy, "en"))
    result = json.loads((root / "evidence/result.json").read_text())
    assert result["mode"] == "fresh-install-only" and result["cases"] == []
    assert result["target_wheel_sha256"] == gate.sha256(wheel)


def test_release_notes_cannot_omit_the_support_limit(release):
    root, wheel, _ = release
    with pytest.raises(gate.GateError, match="notes"):
        gate.gate(root, wheel, root / "evidence", release=True, release_notes="Upgrade your deployment now.")


def test_release_rejects_wrong_artifact_version(release):
    root, wheel, _ = release
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("powercontext-9.0.0.dist-info/METADATA", "Name: powercontext\nVersion: 9.0.0\n")
    with pytest.raises(gate.GateError, match="Wheel version"):
        gate.gate(root, wheel, root / "evidence", release=True)


def test_schema_change_needs_a_new_compatibility_review(release):
    root, _, _ = release
    (root / "src/powercontext/builtin/persistence/tables.py").write_text("# different schema\n")
    with pytest.raises(gate.GateError, match="Persistence changed"):
        gate.load_policy(root)


def test_supported_mode_cannot_succeed_with_an_empty_matrix(release):
    root, _, policy = release
    policy["mode"] = "supported-upgrades"
    (root / gate.MANIFEST).write_text(json.dumps(policy))
    with pytest.raises(gate.GateError, match="matrix disagree"):
        gate.load_policy(root)


@pytest.mark.parametrize(
    "relative",
    [
        "src/powercontext/server/identity.py",
        "src/powercontext/server/authz/repository.py",
        "src/powercontext/builtin/code/seekdb.py",
        "src/powercontext/limits.py",
    ],
)
def test_schema_owners_outside_persistence_need_compatibility_review(release, relative):
    root, _, _ = release
    owner = root / relative
    owner.parent.mkdir(parents=True, exist_ok=True)
    owner.write_text("# changed managed schema input\n")
    with pytest.raises(gate.GateError, match="Persistence changed"):
        gate.load_policy(root)


def supported_case(root, policy):
    suite = root / "tests/release_upgrades/test_example.py"
    suite.parent.mkdir(parents=True)
    suite.write_text("# This fixture is only used to exercise gate failures.\n")
    policy["mode"] = "supported-upgrades"
    policy["cases"] = [
        {
            "source_version": "1.3.0",
            "backend": "sqlite",
            "configuration": "full-server",
            "suite": suite.relative_to(root).as_posix(),
        }
    ]
    (root / gate.MANIFEST).write_text(json.dumps(policy))
    gate.check_docs(root, policy, write=True)


@pytest.mark.parametrize(
    "blocker", ["migration_required", "unmanaged full Server layout", "migration_framework_not_ready"]
)
def test_any_upgrade_stage_failure_blocks_release_and_records_failure(release, monkeypatch, blocker):
    root, wheel, policy = release
    supported_case(root, policy)

    def fail(*_args):
        raise gate.GateError(blocker)

    monkeypatch.setattr(gate, "run_case", fail)
    with pytest.raises(gate.GateError, match=blocker):
        gate.gate(root, wheel, root / "evidence")
    assert json.loads((root / "evidence/result.json").read_text())["status"] == "failed"


def test_missing_suite_cannot_be_advertised(release):
    root, _, policy = release
    supported_case(root, policy)
    (root / policy["cases"][0]["suite"]).unlink()
    with pytest.raises(gate.GateError, match="Missing acceptance suite"):
        gate.load_policy(root)


def test_installation_guidance_cannot_drift_from_matrix(release):
    root, _, policy = release
    page = root / "docs/en/docs/get-started/install-and-run.md"
    page.write_text(page.read_text().replace(gate.NOTICE["en"], "All upgrades are supported."))
    with pytest.raises(gate.GateError, match="instructions differ"):
        gate.check_docs(root, policy)


@pytest.mark.parametrize("invalid", ["empty", "missing-startup", "skipped", "failure", "error", "truncated"])
def test_partial_or_skipped_acceptance_is_not_passing_evidence(tmp_path, invalid):
    report = tmp_path / "junit.xml"
    suite = ElementTree.Element("testsuite")
    for phase in sorted(gate.PHASES):
        if invalid == "empty" or (invalid == "missing-startup" and phase == "test_target_startup"):
            continue
        case = ElementTree.SubElement(suite, "testcase", name=phase)
        if phase == "test_target_startup" and invalid in {"skipped", "failure", "error"}:
            ElementTree.SubElement(case, invalid)
    ElementTree.ElementTree(suite).write(report)
    if invalid == "truncated":
        report.write_text("<testsuite>")
    with pytest.raises((gate.GateError, ElementTree.ParseError)):
        gate.validate_junit(report)


def test_complete_passing_report_is_accepted(tmp_path):
    report = tmp_path / "junit.xml"
    suite = ElementTree.Element("testsuite")
    for phase in gate.PHASES:
        ElementTree.SubElement(suite, "testcase", name=phase)
    ElementTree.ElementTree(suite).write(report)
    gate.validate_junit(report)


def test_missing_backend_evidence_fails_even_with_a_passing_report(tmp_path):
    report = tmp_path / "backend.json"
    report.write_text(json.dumps({"backend": "oceanbase", "engine_version": "4.6.3"}))
    with pytest.raises(gate.GateError, match="driver_version"):
        gate.validate_backend_evidence(report, "oceanbase")


def test_old_evidence_directory_cannot_be_reused(release):
    root, wheel, _ = release
    gate.gate(root, wheel, root / "evidence")
    with pytest.raises(FileExistsError):
        gate.gate(root, wheel, root / "evidence")


def catalog_for(*versions):
    return {
        "releases": {
            version: [
                {
                    "filename": f"powercontext-{version}-py3-none-any.whl",
                    "packagetype": "bdist_wheel",
                    "yanked": False,
                    "url": f"https://files.pythonhosted.org/packages/powercontext-{version}-py3-none-any.whl",
                    "digests": {"sha256": "a" * 64},
                }
            ]
            for version in versions
        }
    }


def automatic_policy(policy, *, minimum="1.4.0"):
    policy["automatic_sources"] = {
        "strategy": "all-stable-since",
        "minimum_version": minimum,
        "profiles": [
            {"backend": backend, "configuration": "full-server-no-vector", "suite": None}
            for backend in ("sqlite", "seekdb")
        ],
    }


@pytest.mark.parametrize(
    "target,expected",
    [
        ("1.4.1", ["1.4.0"]),
        ("1.5.0", ["1.4.0", "1.4.1"]),
        ("1.5.1", ["1.4.0", "1.4.1", "1.5.0"]),
        ("1.5.1.dev2", ["1.4.0", "1.4.1", "1.5.0"]),
    ],
)
def test_release_window_expands_for_each_target_without_new_test_scripts(release, monkeypatch, target, expected):
    _, _, policy = release
    automatic_policy(policy)
    monkeypatch.setattr(
        matrix, "fetch_catalog", lambda: catalog_for("1.3.0", "1.4.0", "1.4.1", "1.5.0rc1", "1.5.0", "1.5.1", "1.6.0")
    )
    resolved = matrix.resolve_matrix(policy, target)
    assert [(case["source_version"], case["backend"]) for case in resolved["candidate_cases"]] == [
        (version, backend) for version in expected for backend in ("sqlite", "seekdb")
    ]
    assert resolved["required_cases"] == []  # Discovery does not establish upgrade support.
    assert all(case["source_artifact"]["sha256"] == "a" * 64 for case in resolved["candidate_cases"])


def test_newly_published_source_is_automatically_added_on_next_run(release, monkeypatch):
    _, _, policy = release
    automatic_policy(policy)
    catalog = catalog_for("1.4.0")
    monkeypatch.setattr(matrix, "fetch_catalog", lambda: catalog)
    first = matrix.resolve_matrix(policy, "1.5.0")
    catalog["releases"].update(catalog_for("1.4.1")["releases"])
    second = matrix.resolve_matrix(policy, "1.5.0")
    assert len(first["candidate_cases"]) == 2
    assert len(second["candidate_cases"]) == 4
    assert first["catalog_sha256"] != second["catalog_sha256"]


@pytest.mark.parametrize(
    "broken", ["empty", "missing-minimum", "yanked", "missing-wheel", "bad-hash", "foreign-origin"]
)
def test_unavailable_source_cannot_silently_shrink_matrix(release, monkeypatch, broken):
    _, _, policy = release
    automatic_policy(policy)
    catalog = catalog_for("1.4.0", "1.4.1")
    wheel = catalog["releases"]["1.4.0"][0]
    if broken == "empty":
        catalog["releases"] = {}
    elif broken == "missing-minimum":
        del catalog["releases"]["1.4.0"]
    elif broken == "yanked":
        wheel["yanked"] = True
    elif broken == "missing-wheel":
        catalog["releases"]["1.4.1"] = []
    elif broken == "bad-hash":
        wheel["digests"]["sha256"] = "invalid"
    else:
        wheel["url"] = "https://untrusted.invalid/package.whl"
    monkeypatch.setattr(matrix, "fetch_catalog", lambda: catalog)
    with pytest.raises(ValueError):
        matrix.resolve_matrix(policy, "1.5.0")


def test_catalog_outage_records_a_failed_gate(release, monkeypatch):
    root, wheel, policy = release
    automatic_policy(policy)
    (root / gate.MANIFEST).write_text(json.dumps(policy))

    def unavailable():
        raise OSError("Catalog unavailable")  # noqa: TRY003 -- exercise a distinct discovery outage

    monkeypatch.setattr(matrix, "fetch_catalog", unavailable)
    with pytest.raises(OSError, match="Catalog unavailable"):
        gate.gate(root, wheel, root / "evidence")
    assert json.loads((root / "evidence/result.json").read_text())["status"] == "failed"


def test_switching_to_supported_upgrades_requires_all_backend_suites(release):
    root, _, policy = release
    automatic_policy(policy)
    policy["mode"] = "supported-upgrades"
    (root / gate.MANIFEST).write_text(json.dumps(policy))
    with pytest.raises(gate.GateError, match="every backend profile"):
        gate.load_policy(root)


def test_supported_window_executes_every_discovered_version_on_every_backend(release, monkeypatch):
    root, wheel, policy = release
    supported_case(root, policy)
    suite = policy["cases"][0]["suite"]
    policy["cases"] = []
    automatic_policy(policy)
    for profile in policy["automatic_sources"]["profiles"]:
        profile["suite"] = suite
    (root / gate.MANIFEST).write_text(json.dumps(policy))
    gate.check_docs(root, policy, write=True)
    monkeypatch.setattr(matrix, "fetch_catalog", lambda: catalog_for("1.4.0", "1.4.1"))
    executed = []

    def execute(_root, _wheel, case, _output):
        executed.append((case["source_version"], case["backend"]))
        return {"case": case, "status": "passed"}

    monkeypatch.setattr(gate, "run_case", execute)
    gate.gate(root, wheel, root / "evidence")
    assert executed == [(version, backend) for version in ("1.4.0", "1.4.1") for backend in ("sqlite", "seekdb")]
    result = json.loads((root / "evidence/result.json").read_text())
    assert len(result["cases"]) == len(result["resolved_matrix"]["required_cases"]) == 4


def test_publishing_jobs_depend_on_nonoptional_preupload_upgrade_gate():
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
    build = workflow["jobs"]["release-build"]
    steps = build["steps"]
    index = next(i for i, step in enumerate(steps) if "run_upgrade_release_gate.py" in step.get("run", ""))
    assert "if" not in steps[index] and not steps[index].get("continue-on-error")
    assert "--release --release-event" in steps[index]["run"]
    upload = next(i for i, step in enumerate(steps) if step.get("with", {}).get("name") == "release-dists")
    assert index < upload
    for name in ("pypi-publish", "release-assets"):
        assert workflow["jobs"][name]["needs"] == "release-build"
