"""Small JSON-RPC client for the PowerContext Streamable HTTP MCP endpoint."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class PowerContextMcpError(RuntimeError):
    """Raised when the PowerContext MCP endpoint returns an invalid or failed tool result."""


@dataclass(frozen=True)
class PowerContextSettings:
    """Connection and scope settings shared by the demo and Qoder MCP config."""

    mcp_url: str = "http://127.0.0.1:8000/mcp/"
    scope_id: str | None = None
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "PowerContextSettings":
        return cls(
            mcp_url=os.getenv("POWERCONTEXT_MCP_URL", cls.mcp_url),
            scope_id=os.getenv("POWERCONTEXT_SCOPE_ID") or None,
            timeout_seconds=float(os.getenv("POWERCONTEXT_MCP_TIMEOUT", "30")),
        )


class PowerContextMcpClient:
    """Typed convenience wrapper over PowerContext's native MCP tools."""

    def __init__(self, settings: PowerContextSettings | None = None) -> None:
        self.settings = settings or PowerContextSettings.from_env()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "PowerContextMcpClient":
        self._stack = AsyncExitStack()
        read_stream, write_stream, _ = await self._stack.enter_async_context(
            streamable_http_client(self.settings.mcp_url)
        )
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await asyncio.wait_for(
            self._session.initialize(), timeout=self.settings.timeout_seconds
        )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def tool_names(self) -> set[str]:
        result = await self._require_session().list_tools()
        return {tool.name for tool in result.tools}

    async def create_scope(
        self,
        *,
        title: str,
        summary: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._call_tool(
            "create_scope",
            {
                "title": title,
                "summary": summary,
                "idempotency_key": idempotency_key,
            },
        )

    async def remember(
        self,
        *,
        scope_id: str,
        kind: str,
        text: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "scope_id": scope_id,
            "kind": kind,
            "text": text,
        }
        if reason:
            arguments["reason"] = reason
        return await self._call_tool("remember_memory", arguments)

    async def search(
        self,
        *,
        scope_id: str,
        query: str,
        limit: int = 8,
    ) -> dict[str, Any]:
        return await self._call_tool(
            "search_memory",
            {
                "scope_id": scope_id,
                "query": query,
                "limit": limit,
                "mode": "fts",
            },
        )

    async def get_artifact(
        self,
        *,
        scope_id: str,
        family: str,
        artifact_id: str,
    ) -> dict[str, Any]:
        return await self._call_tool(
            "get_artifact",
            {
                "scope_id": scope_id,
                "family": family,
                "artifact_id": artifact_id,
            },
        )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.wait_for(
            self._require_session().call_tool(name, arguments),
            timeout=self.settings.timeout_seconds,
        )
        if result.isError:
            detail = "\n".join(
                item.text for item in result.content if hasattr(item, "text")
            )
            raise PowerContextMcpError(f"{name} failed: {detail or 'unknown error'}")
        if isinstance(result.structuredContent, dict):
            return result.structuredContent
        for item in result.content:
            text = getattr(item, "text", None)
            if not text:
                continue
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
        raise PowerContextMcpError(f"{name} returned no structured JSON object")

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise PowerContextMcpError("PowerContext MCP client is not connected")
        return self._session
