"""Task-state persistence through PowerContext Atomic Memory."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from powercontext.builtin.artifacts.atomic_memory.models import AtomicMemoryContent
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_runtime

from .config import Settings

STATE_KIND = "sdd-task-state"
_UTC = timezone.utc


def _config(settings: Settings) -> BuiltinConfig:
    settings.state_db.parent.mkdir(parents=True, exist_ok=True)
    return BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{settings.state_db.as_posix()}")
    )


async def save_state(
    settings: Settings,
    *,
    task_id: str,
    done: list[str],
    todo: list[str],
    verifications: list[str],
    task_hash: str | None = None,
) -> dict[str, Any]:
    payload = {
        "task_id": task_id,
        "done": list(done),
        "todo": list(todo),
        "verifications": list(verifications),
        "task_hash": task_hash,
        "recorded_at": datetime.now(_UTC).isoformat(),
    }
    content = AtomicMemoryContent(
        kind=STATE_KIND,
        text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )
    async with open_builtin_runtime(_config(settings)) as runtime:
        scope = await runtime.scopes.bootstrap_default()
        memory = runtime.atomic_memory.for_scope(scope.scope_id)
        result = await memory.create((content,))
        artifact_id = result.primary_artifact_id

    pointer = {
        "scope_id": scope.scope_id,
        "artifact_id": artifact_id,
        "task_id": task_id,
        "updated_at": payload["recorded_at"],
    }
    _write_pointer(settings.state_pointer(), pointer)
    return {"artifact_id": artifact_id, "scope_id": scope.scope_id, **payload}


async def load_state(settings: Settings, *, task_id: str) -> dict[str, Any] | None:
    if not settings.state_db.exists():
        return None

    async with open_builtin_runtime(_config(settings)) as runtime:
        scope = await runtime.scopes.bootstrap_default()
        memory = runtime.atomic_memory.for_scope(scope.scope_id)

        pointer = _read_pointer(settings.state_pointer())
        if pointer and pointer.get("task_id") == task_id:
            try:
                record = await memory.get(str(pointer["artifact_id"]))
                payload = _payload(record.artifact.content.text, task_id)
                if payload is not None:
                    payload["artifact_id"] = record.artifact.artifact_id
                    payload["scope_id"] = scope.scope_id
                    return payload
            except Exception:
                pass

        page = await memory.search(STATE_KIND, limit=50)
        candidates = []
        for hit in page.hits:
            payload = _payload(hit.hit.text, task_id)
            if payload is not None:
                payload["artifact_id"] = hit.hit.artifact_ref.artifact_id
                payload["scope_id"] = scope.scope_id
                candidates.append(payload)
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("recorded_at", "")))


def _payload(text: str, task_id: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("task_id") != task_id:
        return None
    return payload


def _read_pointer(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_pointer(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
