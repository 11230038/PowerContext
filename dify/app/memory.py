"""Cross-session player memory backed by PowerContext Atomic Memory."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from powercontext.builtin.artifacts.atomic_memory.models import AtomicMemoryContent
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_runtime

from config import Settings

MEMORY_KIND = "tavern-player-memory"
MAX_DEEDS = 20
_UTC = timezone.utc
_LOCK = asyncio.Lock()

_NEGATIVE = ("偷", "骗", "砸", "骂", "踢", "烧", "抢", "嫁祸", "恶作剧", "打", "咬", "掀")
_POSITIVE = ("喂", "夸", "摸", "请", "帮", "道歉", "赔", "送", "抱", "谢谢", "原谅")


def _config(settings: Settings) -> BuiltinConfig:
    settings.state_db.parent.mkdir(parents=True, exist_ok=True)
    return BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{settings.state_db.as_posix()}")
    )


def empty_state(player_id: str) -> dict[str, Any]:
    return {
        "player_id": player_id,
        "deeds": [],
        "affinity": 0,
        "updated_at": None,
        "artifact_id": None,
        "scope_id": None,
        "source": "PowerContext (empty)",
    }


async def load_memory(settings: Settings, player_id: str) -> dict[str, Any]:
    async with open_builtin_runtime(_config(settings)) as runtime:
        scope = await runtime.scopes.bootstrap_default()
        memory = runtime.atomic_memory.for_scope(scope.scope_id)
        state = await _load_with_memory(settings, memory, player_id, scope.scope_id)
    state["memory_text"] = memory_text(state)
    state["affinity_label"] = affinity_label(int(state["affinity"]))
    return state


async def save_memory(
    settings: Settings,
    player_id: str,
    *,
    deed: str,
    reply: str,
    session_id: str,
) -> dict[str, Any]:
    del reply, session_id  # the deed is the durable fact; the reply stays in turn_log
    async with _LOCK:
        async with open_builtin_runtime(_config(settings)) as runtime:
            scope = await runtime.scopes.bootstrap_default()
            memory = runtime.atomic_memory.for_scope(scope.scope_id)
            state = await _load_with_memory(settings, memory, player_id, scope.scope_id)
            delta = affinity_delta(deed)
            deeds = list(state["deeds"])
            deeds.append(
                {
                    "text": deed[:500],
                    "at": datetime.now(_UTC).isoformat(),
                    "delta": delta,
                }
            )
            deeds = deeds[-MAX_DEEDS:]
            affinity = max(-5, min(5, int(state["affinity"]) + delta))
            payload = {
                "player_id": player_id,
                "deeds": deeds,
                "affinity": affinity,
                "updated_at": datetime.now(_UTC).isoformat(),
            }
            content = AtomicMemoryContent(
                kind=MEMORY_KIND,
                text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            )
            result = await memory.create((content,))
            artifact_id = result.primary_artifact_id

        pointer = _read_pointer(settings.pointer_path())
        players = pointer.setdefault("players", {})
        players[player_id] = {
            "artifact_id": artifact_id,
            "updated_at": payload["updated_at"],
        }
        _write_pointer(settings.pointer_path(), pointer)

    state = {
        **payload,
        "artifact_id": artifact_id,
        "scope_id": scope.scope_id,
        "source": "PowerContext",
    }
    state["memory_text"] = memory_text(state)
    state["affinity_label"] = affinity_label(affinity)
    return state


async def reset_memory(settings: Settings, player_id: str) -> dict[str, Any]:
    """Forget a player by appending an empty memory artifact.

    Atomic Memory is append-only, so a reset writes a fresh empty payload and
    points the player at it; deleting the pointer alone would let the fallback
    search in :func:`_load_with_memory` resurrect the old deeds.
    """
    async with _LOCK:
        async with open_builtin_runtime(_config(settings)) as runtime:
            scope = await runtime.scopes.bootstrap_default()
            memory = runtime.atomic_memory.for_scope(scope.scope_id)
            payload = {
                "player_id": player_id,
                "deeds": [],
                "affinity": 0,
                "updated_at": datetime.now(_UTC).isoformat(),
            }
            content = AtomicMemoryContent(
                kind=MEMORY_KIND,
                text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            )
            result = await memory.create((content,))
            artifact_id = result.primary_artifact_id

        pointer = _read_pointer(settings.pointer_path())
        pointer.setdefault("players", {})[player_id] = {
            "artifact_id": artifact_id,
            "updated_at": payload["updated_at"],
        }
        _write_pointer(settings.pointer_path(), pointer)

    return {
        "player_id": player_id,
        "artifact_id": artifact_id,
        "scope_id": scope.scope_id,
        "reset": True,
    }


async def _load_with_memory(
    settings: Settings,
    memory: Any,
    player_id: str,
    scope_id: str,
) -> dict[str, Any]:
    pointer = _read_pointer(settings.pointer_path())
    entry = pointer.get("players", {}).get(player_id)
    if isinstance(entry, dict) and entry.get("artifact_id"):
        try:
            record = await memory.get(str(entry["artifact_id"]))
            payload = _payload(record.artifact.content.text, player_id)
            if payload is not None:
                return {
                    **payload,
                    "artifact_id": record.artifact.artifact_id,
                    "scope_id": scope_id,
                    "source": "PowerContext",
                }
        except Exception:
            pass

    page = await memory.search(MEMORY_KIND, limit=100)
    candidates = []
    for hit in page.hits:
        payload = _payload(hit.hit.text, player_id)
        if payload is not None:
            payload["artifact_id"] = hit.hit.artifact_ref.artifact_id
            payload["scope_id"] = scope_id
            payload["source"] = "PowerContext"
            candidates.append(payload)
    if not candidates:
        return empty_state(player_id)
    return max(candidates, key=lambda item: str(item.get("updated_at", "")))


def affinity_delta(text: str) -> int:
    negative = sum(1 for word in _NEGATIVE if word in text)
    positive = sum(1 for word in _POSITIVE if word in text)
    return max(-2, min(2, positive - negative))


def affinity_label(affinity: int) -> str:
    if affinity <= -3:
        return "记仇"
    if affinity <= -1:
        return "警惕"
    if affinity == 0:
        return "陌生"
    if affinity <= 2:
        return "熟客"
    return "自己人"


def memory_text(state: dict[str, Any]) -> str:
    deeds = state.get("deeds", [])
    if not deeds:
        return "（老白第一次见你，还没记住你的任何事。）"
    lines = [
        f"玩家 {state['player_id']}，好感度 {int(state['affinity']):+d}"
        f"（{affinity_label(int(state['affinity']))}）。老白记得这些旧事："
    ]
    for deed in deeds[-6:]:
        lines.append(f"- {deed['text']}")
    return "\n".join(lines)


def _payload(text: str, player_id: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("player_id") != player_id:
        return None
    if not isinstance(payload.get("deeds"), list):
        return None
    return payload


def _read_pointer(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"players": {}}
    if not isinstance(value, dict):
        return {"players": {}}
    value.setdefault("players", {})
    return value


def _write_pointer(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)
