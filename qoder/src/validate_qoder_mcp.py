"""End-to-end acceptance demo for Qoder + PowerContext native MCP."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import sys
from typing import Any

from powercontext_client import PowerContextMcpClient, PowerContextSettings

REQUIRED_TOOLS = {
    "create_scope",
    "remember_memory",
    "search_memory",
    "get_artifact",
}

DEFAULT_MEMORIES = (
    (
        "workflow",
        "Qoder workflow: before changing repository code, run the smallest targeted tests first; "
        "after the change, run the targeted tests and then the regression suite.",
    ),
    (
        "decision",
        "Qoder project decision: preserve the existing API contract unless the task explicitly "
        "requests a breaking change.",
    ),
    (
        "convention",
        "Qoder coding convention: prefer focused edits, keep public functions documented, and "
        "do not add dependencies when the Python standard library is sufficient.",
    ),
)

DEFAULT_QUERY = (
    "I am continuing a Qoder coding task. What project workflow, API compatibility decision, "
    "and coding convention should I follow before editing and validating the change?"
)


def _artifact_reference(record: dict[str, Any]) -> dict[str, Any]:
    artifact = record.get("artifact")
    return artifact if isinstance(artifact, dict) else {}


def _memory_texts(search_result: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for hit in search_result.get("hits", []):
        if not isinstance(hit, dict):
            continue
        memory = hit.get("memory")
        if isinstance(memory, dict) and isinstance(memory.get("text"), str):
            texts.append(memory["text"])
    return texts


async def validate(args: argparse.Namespace) -> dict[str, Any]:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    settings = PowerContextSettings(
        mcp_url=args.mcp_url,
        scope_id=args.scope_id,
        timeout_seconds=args.timeout,
    )

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    async with PowerContextMcpClient(settings) as client:
        tools = await client.tool_names()
        missing = sorted(REQUIRED_TOOLS - tools)
        check(
            "native PowerContext MCP tools discovered",
            not missing,
            "all required tools available" if not missing else f"missing={missing}",
        )

        scope_id = args.scope_id
        created_scope: dict[str, Any] | None = None
        if not scope_id:
            created_scope = await client.create_scope(
                title="Qoder MCP acceptance",
                summary="Independent acceptance scope for the Qoder native MCP integration.",
                idempotency_key=f"qoder-mcp-{stamp}",
            )
            scope_id = str(created_scope["scope_id"])
        check(
            "scope selected for the Qoder session",
            bool(scope_id),
            f"scope_id={scope_id}",
        )

        writes: list[dict[str, Any]] = []
        for kind, text in DEFAULT_MEMORIES:
            result = await client.remember(
                scope_id=scope_id,
                kind=kind,
                text=text,
                reason="Qoder MCP acceptance seed",
            )
            writes.append(result)

        records = [
            record
            for result in writes
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]
        artifact_refs = [_artifact_reference(record) for record in records]
        check(
            "explicit memories persisted through MCP",
            len(records) == len(DEFAULT_MEMORIES)
            and all(ref.get("family") == "atomic-memory" for ref in artifact_refs),
            f"records={len(records)}, artifacts={artifact_refs}",
        )

        search = await client.search(
            scope_id=scope_id,
            query="Qoder workflow API contract coding convention",
            limit=8,
        )
        recalled_texts = _memory_texts(search)
        expected_fragments = ("targeted tests", "API contract", "focused edits")
        check(
            "cross-session memory search returns project guidance",
            all(any(fragment in text for text in recalled_texts) for fragment in expected_fragments),
            f"hits={len(recalled_texts)}",
        )

        first_ref = artifact_refs[0] if artifact_refs else {}
        artifact_result = await client.get_artifact(
            scope_id=scope_id,
            family=str(first_ref.get("family", "atomic-memory")),
            artifact_id=str(first_ref.get("artifact_id", "")),
        )
        artifact = artifact_result.get("artifact")
        artifact_json = json.dumps(artifact, ensure_ascii=False)
        check(
            "exact Atomic Memory Artifact can be inspected",
            artifact_result.get("status_code") == 200
            and bool(artifact_result.get("etag"))
            and DEFAULT_MEMORIES[0][1] in artifact_json,
            f"status={artifact_result.get('status_code')}, etag={artifact_result.get('etag')}",
        )

    report = {
        "generated_at": stamp,
        "mcp_url": args.mcp_url,
        "scope_id": scope_id,
        "created_scope": created_scope,
        "tool_count": len(tools),
        "required_tools": sorted(REQUIRED_TOOLS),
        "writes": writes,
        "search": search,
        "artifact_read": artifact_result,
        "checks": checks,
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
    }
    return report


def write_report(report: dict[str, Any], out_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_at"]
    json_path = out_dir / f"validation-{stamp}.json"
    markdown_path = out_dir / f"validation-{stamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        f"# Qoder × PowerContext MCP validation {stamp}",
        "",
        f"- MCP endpoint: `{report['mcp_url']}`",
        f"- Scope: `{report['scope_id']}`",
        f"- Result: **{report['passed']}/{report['total']} checks passed**",
        "",
        "## Checks",
        "",
    ]
    for item in report["checks"]:
        mark = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- [{mark}] {item['check']} — {item['detail']}")
    lines += [
        "",
        "## Recalled memory",
        "",
        "```json",
        json.dumps(report["search"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Exact artifact read",
        "",
        "```json",
        json.dumps(report["artifact_read"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8000/mcp/",
        help="PowerContext Streamable HTTP MCP endpoint.",
    )
    parser.add_argument(
        "--scope-id",
        help="Reuse an existing PowerContext Scope. A validation Scope is created if omitted.",
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", default="artifacts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(validate(args))
    except Exception as error:
        print(f"validation failed before report generation: {error}", file=sys.stderr)
        return 2

    json_path, markdown_path = write_report(report, pathlib.Path(args.out))
    for item in report["checks"]:
        print(("PASS " if item["ok"] else "FAIL ") + item["check"] + " — " + item["detail"])
    print(
        f"{report['passed']}/{report['total']} checks passed; "
        f"wrote {json_path} and {markdown_path}"
    )
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
