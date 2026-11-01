from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from powercontext_client import PowerContextMcpClient, PowerContextSettings
from validate_qoder_mcp import _memory_texts


def test_settings_read_environment(monkeypatch) -> None:
    monkeypatch.setenv("POWERCONTEXT_MCP_URL", "http://example.test/mcp/")
    monkeypatch.setenv("POWERCONTEXT_SCOPE_ID", "scope-demo")
    monkeypatch.setenv("POWERCONTEXT_MCP_TIMEOUT", "12.5")

    settings = PowerContextSettings.from_env()

    assert settings.mcp_url == "http://example.test/mcp/"
    assert settings.scope_id == "scope-demo"
    assert settings.timeout_seconds == 12.5


def test_memory_texts_ignores_malformed_hits() -> None:
    result = {
        "hits": [
            {"memory": {"text": "first"}},
            {"memory": {"text": 12}},
            {"other": "value"},
            "not-a-dict",
            {"memory": {"text": "second"}},
        ]
    }

    assert _memory_texts(result) == ["first", "second"]


def test_structured_content_is_preferred() -> None:
    client = PowerContextMcpClient()
    result = SimpleNamespace(
        isError=False,
        structuredContent={"status": "ready"},
        content=[],
    )

    class Session:
        async def call_tool(self, name, arguments):
            assert name == "get_artifact"
            assert arguments["scope_id"] == "scope-demo"
            return result

    client._session = Session()  # type: ignore[assignment]

    import asyncio

    value = asyncio.run(
        client.get_artifact(
            scope_id="scope-demo",
            family="atomic-memory",
            artifact_id="memory-1",
        )
    )
    assert value == {"status": "ready"}
