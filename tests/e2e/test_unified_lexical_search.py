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

# ruff: noqa: RUF001 - actual multilingual question forms.
"""One public recall contract on real SQLite, seekdb and OceanBase databases."""

import asyncio

import httpx

from powercontext.builtin.runtime import RuntimeConfig
from powercontext.server.factory import create_server_app
from powercontext.server.settings import McpConfig, ServerSettings

FACT = "本项目的 PowerContext Server 固定在 127.0.0.1:8000；测试写入。"
QUESTIONS = (
    "PowerContext Server 地址",
    "PowerContext Server 地址是什么？",
    "的 PowerContext Server 地址是什么？",
    "请告诉我 PowerContext Server 地址是什么？",
    "我之前让你记住的 PowerContext Server 地址是什么？",
)


def test_public_word_recall_identifiers_scope_isolation_and_prepare(migration_backend):
    async def scenario():
        app = create_server_app(
            settings=ServerSettings(
                database=migration_backend.config,
                runtime=RuntimeConfig(artifact_processing_families=()),
                mcp=McpConfig(enabled=False),
            ),
            scheduler_path=migration_backend.directory / "scheduler",
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client,
        ):

            async def scope(label):
                response = await client.post(
                    "/v1/scopes",
                    json={
                        "title": label,
                        "summary": "Lexical acceptance",
                        "idempotency_key": label,
                    },
                )
                response.raise_for_status()
                return response.json()["scope_id"]

            async def remember(scope_id, text):
                response = await client.post(
                    "/v1/memory/remember",
                    json={
                        "scope_id": scope_id,
                        "kind": "fact",
                        "text": text,
                    },
                )
                response.raise_for_status()
                return response.json()["records"][0]["artifact"]

            primary, other = await scope("primary"), await scope("other")
            fact_ref = await remember(primary, FACT)
            await remember(other, "PowerContext Server 固定在 10.0.0.9:9000。")
            await remember(primary, "Dinner recipe baking instructions.")
            identifier_ref = await remember(primary, "alpha u_7684")
            long_identifier = "service_" + "a" * 200
            await remember(primary, long_identifier)
            prohibition = await remember(primary, "不要保存密码")
            await remember(primary, "保存密码")
            operators = await remember(primary, "AND and OR operators.")
            negation = await remember(primary, "not store passwords")

            async def search(query):
                response = await client.post(
                    "/v1/memory/search",
                    json={
                        "scope_id": primary,
                        "query": query,
                        "mode": "fts",
                    },
                )
                response.raise_for_status()
                return response.json()["hits"]

            for question in QUESTIONS:
                hits = await search(question)
                assert [hit["memory"]["text"] for hit in hits] == [FACT]
                prepared = await client.post(
                    "/v1/context/prepare",
                    json={
                        "scope_id": primary,
                        "query": question,
                        "max_bytes": 8192,
                    },
                )
                prepared.raise_for_status()
                assert prepared.json()["status"] == "ready"
                assert "127.0.0.1:8000" in prepared.json()["content"]
                assert "10.0.0.9" not in prepared.json()["content"]
            assert [hit["memory"]["artifact"] for hit in await search("alpha u_7684")] == [identifier_ref]
            assert [hit["memory"]["artifact"] for hit in await search("u_7684")] == [identifier_ref]
            assert [hit["memory"]["artifact"] for hit in await search('"的"')] == [fact_ref]
            assert [hit["memory"]["artifact"] for hit in await search("不要")] == [prohibition]
            assert [hit["memory"]["artifact"] for hit in await search('"AND"')] == [operators]
            assert [hit["memory"]["artifact"] for hit in await search('"OR"')] == [operators]
            assert [hit["memory"]["artifact"] for hit in await search("not")] == [negation]
            assert [hit["memory"]["text"] for hit in await search(long_identifier)] == [long_identifier]
            assert await search("的 是 什么") == []
            assert await search("astronomy telescope galaxy") == []
            # Exact history remains readable through its returned authoritative identity.
            exact = await client.get(
                f"/v1/scopes/{primary}/artifacts/{fact_ref['family']}/{fact_ref['artifact_id']}/revisions/{fact_ref['revision']}"
            )
            exact.raise_for_status()
            assert exact.json()["content"]["text"] == FACT

    asyncio.run(scenario())
