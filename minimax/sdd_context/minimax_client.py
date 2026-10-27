"""Minimal MiniMax chat-completions client with an auditable request record."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE = re.compile(r"^```[a-zA-Z0-9_+-]*\s*\n(.*?)\n```\s*$", re.DOTALL)


class MiniMaxError(RuntimeError):
    """Raised when the MiniMax API rejects the request."""


def chat(
    messages: list[dict[str, str]],
    settings: Settings,
    *,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    if not settings.minimax_api_key:
        raise MiniMaxError("MINIMAX_API_KEY is not set")

    url = f"{settings.minimax_base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": settings.minimax_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.minimax_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    latency = time.monotonic() - started

    base = payload.get("base_resp") or {}
    if base.get("status_code") not in (0, None):
        raise MiniMaxError(f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}")

    choice = (payload.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    cleaned = _FENCE.sub(r"\1", _THINK.sub("", content)).strip()
    return {
        "model": payload.get("model", settings.minimax_model),
        "content": cleaned,
        "raw_content": content,
        "usage": payload.get("usage") or {},
        "latency_seconds": round(latency, 3),
        "request_id": payload.get("id"),
        "created": payload.get("created"),
    }


def record(
    settings: Settings,
    *,
    task_id: str,
    messages: list[dict[str, str]],
    result: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> Path:
    directory = settings.artifacts_dir / "minimax"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-{task_id}.json"
    payload = {
        "task_id": task_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "provider": "MiniMax",
        "base_url": settings.minimax_base_url,
        "model": result.get("model"),
        "request_id": result.get("request_id"),
        "usage": result.get("usage"),
        "latency_seconds": result.get("latency_seconds"),
        "messages": _redact(messages),
        "response": result.get("content"),
        **(extra or {}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _redact(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"role": item["role"], "content": item["content"]} for item in messages]
