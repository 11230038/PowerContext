"""Command line entry point for the SDD context module."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from . import minimax_client, prompts
from .chunking import load_documents
from .config import Settings
from .db import connect, ensure_schema, replace_index
from .retrieval import build_context
from .state import load_state, save_state


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="sdd-context", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="create the seekdb database and tables")

    ingest = subparsers.add_parser("ingest", help="index specs, code and tests in seekdb")
    ingest.add_argument("--root", type=Path, required=True)
    ingest.add_argument("--label", default="app")

    context = subparsers.add_parser("context", help="build the development context for a task")
    context.add_argument("--task", type=Path, required=True)
    context.add_argument("--task-id", default=None)
    context.add_argument("--label", default="app")
    context.add_argument("--out", type=Path, default=None)

    record = subparsers.add_parser("record", help="store task progress in PowerContext")
    record.add_argument("--task-id", required=True)
    record.add_argument("--task-hash", default=None)
    record.add_argument("--done", action="append", default=[])
    record.add_argument("--todo", action="append", default=[])
    record.add_argument("--verification", action="append", default=[])

    status = subparsers.add_parser("status", help="read a stored task state from PowerContext")
    status.add_argument("--task-id", required=True)

    ask = subparsers.add_parser("ask-minimax", help="send the context to MiniMax for a code change")
    ask.add_argument("--task", type=Path, required=True)
    ask.add_argument("--context", type=Path, required=True)
    ask.add_argument("--target", type=Path, required=True)
    ask.add_argument("--out", type=Path, required=True)
    ask.add_argument("--task-id", required=True)

    args = parser.parse_args(argv)
    settings = Settings()

    if args.command == "init":
        ensure_schema(settings)
        print(json.dumps({"database": settings.seekdb_database, "host": settings.seekdb_host}, indent=2))
        return 0

    if args.command == "ingest":
        documents = load_documents(args.root)
        ensure_schema(settings)
        connection = connect(settings)
        try:
            result = replace_index(connection, documents, root=args.root, label=args.label)
        finally:
            connection.close()
        counts = Counter(document.kind for document in documents)
        print(json.dumps({**result, "kinds": dict(counts)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "context":
        task_text = args.task.read_text(encoding="utf-8")
        connection = connect(settings)
        try:
            context_payload = build_context(connection, task_text, label=args.label)
        finally:
            connection.close()
        task_id = args.task_id or f"task-{context_payload['task_hash'][:8]}"
        stored = asyncio.run(load_state(settings, task_id=task_id))
        context_payload["state"] = _state_view(task_id, stored)
        rendered = json.dumps(context_payload, ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered, encoding="utf-8")
        print(rendered)
        return 0

    if args.command == "record":
        result = asyncio.run(
            save_state(
                settings,
                task_id=args.task_id,
                done=args.done,
                todo=args.todo,
                verifications=args.verification,
                task_hash=args.task_hash,
            )
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        stored = asyncio.run(load_state(settings, task_id=args.task_id))
        print(json.dumps(_state_view(args.task_id, stored), ensure_ascii=False, indent=2))
        return 0

    if args.command == "ask-minimax":
        task_text = args.task.read_text(encoding="utf-8")
        context_payload = json.loads(args.context.read_text(encoding="utf-8"))
        target_source = args.target.read_text(encoding="utf-8")
        messages = prompts.implementation_messages(
            task_text=task_text,
            context=context_payload,
            target_path=str(args.target),
            target_source=target_source,
        )
        result = minimax_client.chat(messages, settings)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result["content"] + "\n", encoding="utf-8")
        record_path = minimax_client.record(
            settings,
            task_id=args.task_id,
            messages=messages,
            result=result,
            extra={
                "target": str(args.target),
                "context_task_hash": context_payload.get("task_hash"),
                "output": str(args.out),
            },
        )
        print(json.dumps({"output": str(args.out), "record": str(record_path)}, indent=2))
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


def _state_view(task_id: str, stored: dict[str, object] | None) -> dict[str, object]:
    if stored is None:
        return {
            "task_id": task_id,
            "done": [],
            "todo": [],
            "verifications": [],
            "source": "PowerContext (empty)",
        }
    return {
        "task_id": task_id,
        "done": stored.get("done", []),
        "todo": stored.get("todo", []),
        "verifications": stored.get("verifications", []),
        "recorded_at": stored.get("recorded_at"),
        "artifact_id": stored.get("artifact_id"),
        "source": "PowerContext",
    }
