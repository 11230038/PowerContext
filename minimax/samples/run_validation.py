#!/usr/bin/env python3
"""Reproduce the complete SDD validation sample from a clean state.

Steps:
1. recreate the seekdb index and the PowerContext state database;
2. show the target tests fail on the pre-change snapshot and regression tests pass;
3. apply the recorded diff, run target and regression tests again;
4. build the task context, store progress in PowerContext, read it in a new process;
5. replace the spec with v2, re-ingest and prove the context uses the new wording.

All commands, exit codes and outputs are written to ``artifacts/logs``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MINIMAX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MINIMAX))

from sdd_context.chunking import load_documents  # noqa: E402
from sdd_context.config import Settings  # noqa: E402
from sdd_context.db import connect, ensure_schema, replace_index  # noqa: E402

APP = MINIMAX / "app"
SAMPLES = MINIMAX / "samples"
EXPECTED = json.loads((SAMPLES / "expected_context.json").read_text(encoding="utf-8"))
WORK = MINIMAX / "runs" / "validation"
ARTIFACTS = MINIMAX / "artifacts"
TASK_ID = "TASK-OVERDUE-FILTER"
TASK_FILE = SAMPLES / "task.md"
TASK_TEXT = TASK_FILE.read_text(encoding="utf-8")
PYTHON = sys.executable
ENV = {**os.environ, "PYTHONPATH": str(MINIMAX), "PYTHONIOENCODING": "utf-8"}

CHECKS: list[dict[str, Any]] = []
STEPS: list[dict[str, Any]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append({"name": name, "passed": bool(condition), "detail": detail})
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}{'' if not detail else f' — {detail}'}")


def run(command: list[str], *, cwd: Path, input_text: str | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=ENV,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    step = {
        "command": " ".join(command),
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    STEPS.append(step)
    return step


def cli(*arguments: str) -> dict[str, Any]:
    return run([PYTHON, "-m", "sdd_context", *arguments], cwd=MINIMAX)


def ingest(root: Path, label: str = "app") -> dict[str, Any]:
    documents = load_documents(root)
    connection = connect(settings)
    try:
        return replace_index(connection, documents, root=root, label=label)
    finally:
        connection.close()


def reset_workspace() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    settings.state_db.parent.mkdir(parents=True, exist_ok=True)
    settings.state_db.unlink(missing_ok=True)
    settings.state_pointer().unlink(missing_ok=True)


def copy_app(destination: Path) -> Path:
    target = destination / "app"
    shutil.copytree(
        APP,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv"),
    )
    return target


def pytest(work_app: Path, test_file: str) -> dict[str, Any]:
    return run([PYTHON, "-m", "pytest", "-q", f"tests/{test_file}"], cwd=work_app)


def apply_diff(work_app: Path, diff_path: Path) -> dict[str, Any]:
    diff_text = diff_path.read_text(encoding="utf-8")
    if shutil.which("patch"):
        return run(["patch", "-p1", "--no-backup-if-mismatch"], cwd=work_app, input_text=diff_text)
    repo_root = Path(run(["git", "rev-parse", "--show-toplevel"], cwd=MINIMAX)["stdout"].strip())
    relative = work_app.resolve().relative_to(repo_root)
    return run(
        ["git", "apply", "--whitespace=nowarn", "-p1", f"--directory={relative.as_posix()}", str(diff_path)],
        cwd=repo_root,
    )


def context_via_cli(output: Path) -> dict[str, Any]:
    step = cli(
        "context",
        "--task",
        str(TASK_FILE),
        "--task-id",
        TASK_ID,
        "--label",
        "app",
        "--out",
        str(output),
    )
    if step["exit_code"] != 0:
        raise RuntimeError(f"context command failed:\n{step['stderr']}")
    return json.loads(output.read_text(encoding="utf-8"))


def required_sources_present(context: dict[str, Any]) -> bool:
    spec_ids = {item["id"] for item in context["specs"]}
    code_sources = {item["source"] for item in context["code"]}
    test_sources = " ".join(item["source"] for item in context["tests"])
    return (
        set(EXPECTED["required_spec_ids"]).issubset(spec_ids)
        and set(EXPECTED["required_code_sources"]).issubset(code_sources)
        and any(marker in test_sources for marker in EXPECTED["required_test_source_contains"])
    )


def main() -> int:
    global settings, WORK
    settings = Settings()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    WORK = MINIMAX / "runs" / f"validation-{timestamp}"
    logs_dir = ARTIFACTS / "logs"
    context_dir = ARTIFACTS / "context"
    logs_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)
    reset_workspace()

    ensure_schema(settings)
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            engine_version = str(cursor.fetchone()[0])
    finally:
        connection.close()
    check("seekdb reachable", engine_version.startswith("5.7.25-OceanBase"), engine_version)

    run_result = ingest(APP)
    check("index built in seekdb", run_result["doc_count"] > 0, f"{run_result['doc_count']} documents")

    initial = context_via_cli(context_dir / "initial.json")
    check("context has required sources", required_sources_present(initial), str(initial["specs"][:2]))
    check(
        "context starts with empty PowerContext state",
        initial["state"]["done"] == [] and initial["state"]["todo"] == [],
        str(initial["state"]),
    )
    marker = EXPECTED["spec_update_marker"]
    check(
        "initial spec wording is v1",
        marker not in json.dumps(initial["specs"], ensure_ascii=False),
    )

    work_app = copy_app(WORK)
    before_source = (SAMPLES / "snapshots" / "before" / "service.py").read_text(encoding="utf-8")
    (work_app / "loanboard" / "service.py").write_text(before_source, encoding="utf-8", newline="\n")

    before_target = pytest(work_app, "test_loans_overdue.py")
    before_regression = pytest(work_app, "test_loans_regression.py")
    target_output = before_target["stdout"] + before_target["stderr"]
    (logs_dir / f"before-target-{timestamp}.log").write_text(target_output, encoding="utf-8")
    (logs_dir / f"before-regression-{timestamp}.log").write_text(
        before_regression["stdout"] + before_regression["stderr"], encoding="utf-8"
    )
    check("target tests fail before the change", before_target["exit_code"] == 1 and "failed" in target_output)
    check(
        "before failure is functional, not environmental",
        "ModuleNotFoundError" not in target_output and "ImportError" not in target_output,
        "no import/dependency error",
    )
    check("regression tests pass before the change", before_regression["exit_code"] == 0)

    diff_path = SAMPLES / "diffs" / "overdue_filter.diff"
    apply_step = apply_diff(work_app, diff_path)
    check("recorded diff applies cleanly", apply_step["exit_code"] == 0, apply_step["stderr"][:300])
    check(
        "patched file matches the after snapshot",
        (work_app / "loanboard" / "service.py").read_text(encoding="utf-8")
        == (SAMPLES / "snapshots" / "after" / "service.py").read_text(encoding="utf-8"),
    )

    after_target = pytest(work_app, "test_loans_overdue.py")
    after_regression = pytest(work_app, "test_loans_regression.py")
    (logs_dir / f"after-target-{timestamp}.log").write_text(
        after_target["stdout"] + after_target["stderr"], encoding="utf-8"
    )
    (logs_dir / f"after-regression-{timestamp}.log").write_text(
        after_regression["stdout"] + after_regression["stderr"], encoding="utf-8"
    )
    check("target tests pass after the change", after_target["exit_code"] == 0, after_target["stdout"][-200:])
    check("regression tests pass after the change", after_regression["exit_code"] == 0, after_regression["stdout"][-200:])

    record_step = cli(
        "record",
        "--task-id",
        TASK_ID,
        "--task-hash",
        initial["task_hash"],
        "--done",
        "实现 SPEC-LOAN-004 逾期筛选",
        "--done",
        "目标测试与回归测试通过",
        "--verification",
        f"pytest tests/test_loans_overdue.py exit={after_target['exit_code']}",
        "--verification",
        f"pytest tests/test_loans_regression.py exit={after_regression['exit_code']}",
        "--todo",
        "提交代码与材料",
    )
    check("PowerContext state write succeeds", record_step["exit_code"] == 0, record_step["stderr"][:300])

    status_step = cli("status", "--task-id", TASK_ID)
    check("state is readable in a new process", status_step["exit_code"] == 0)
    state = json.loads(status_step["stdout"])
    check(
        "stored state contains done and verification records",
        all(field in state for field in EXPECTED["required_state_fields"])
        and len(state["done"]) >= 2
        and len(state["verifications"]) >= 2
        and state.get("artifact_id"),
        json.dumps(state, ensure_ascii=False)[:300],
    )

    spec_work = copy_app(WORK / "spec-update")
    shutil.copyfile(SAMPLES / "specs" / "loans_v2.md", spec_work / "specs" / "loans.md")
    ingest(spec_work, "app")
    updated = context_via_cli(context_dir / "spec-v2.json")
    updated_text = json.dumps(updated["specs"], ensure_ascii=False)
    check(
        "updated spec is used after re-ingest",
        "严格早于" in updated_text and marker in updated_text,
        "v2 wording present",
    )
    check("updated context still has required sources", required_sources_present(updated))

    ingest(APP)
    restored = context_via_cli(context_dir / "restored.json")
    check(
        "v1 wording restored after re-ingest",
        marker not in json.dumps(restored["specs"], ensure_ascii=False),
    )

    passed = sum(1 for item in CHECKS if item["passed"])
    report = {
        "timestamp": timestamp,
        "python": sys.version,
        "engine_version": engine_version,
        "task_id": TASK_ID,
        "checks": CHECKS,
        "passed": passed,
        "total": len(CHECKS),
        "success": passed == len(CHECKS),
        "steps": STEPS,
    }
    report_path = logs_dir / f"validation-{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(CHECKS)} checks passed; report: {report_path}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
