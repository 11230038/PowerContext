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

"""聊天编排：召回 -> 拼 prompt -> 流式调 LLM -> 捕获与提取。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from powercontext.client import PowerContextClient
from powercontext.http import (
    CreateSourceRequest,
    FlushMemoryRequest,
    FlushMemoryResponse,
    ListMemoryEntriesRequest,
    SearchMemoryHit,
    SearchMemoryRequest,
)

from .config import DemoConfig

# 持有在途写入任务的引用, 防止事件循环只握弱引用时任务被垃圾回收
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _log_background_failure(task: asyncio.Task) -> None:
    # 访客在 done 后刷新页面会取消 SSE 生成器, shield 里的写入任务若失败,
    # 异常无人认领, GC 时 asyncio 会打 "Task exception was never retrieved";
    # 这里在任务完成时取走异常并留下一条干净日志 (SSE 已断, 无法再报给前端)
    if not task.cancelled() and (exc := task.exception()):
        logging.getLogger(__name__).warning("后台记忆写入失败: %s", exc)


PERSONA = (
    "你是「小O」，一个温暖健谈的中文 AI 助手，正在一个线下的记忆能力体验活动中陪用户聊天。"
    "保持自然口语化的中文，每次回答不超过三句话，并对用户透露的偏好、习惯、事实表现出兴趣。"
)


def build_system_prompt(hits: list[SearchMemoryHit]) -> str:
    if not hits:
        return PERSONA
    lines = "\n".join(f"- {hit.text}" for hit in hits)
    return (
        f"{PERSONA}\n\n"
        "以下是你记住的关于这位用户的长期记忆（由 PowerContext 召回）：\n"
        f"{lines}\n\n"
        "回答时自然地运用这些记忆；除非用户问起，不要逐条复述记忆列表。"
    )


async def stream_llm_reply(
    http: httpx.AsyncClient,
    cfg: DemoConfig,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    payload = {
        "model": cfg.llm_model,
        "stream": True,
        "temperature": 0.7,
        "messages": [{"role": "system", "content": system_prompt}, *messages],
    } | cfg.llm_extra_body
    async with http.stream(
        "POST",
        f"{cfg.llm_base_url}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {cfg.llm_api_key}"},
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ").strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            choices = chunk.get("choices") or []
            if not choices:
                # Some OpenAI-compatible providers (e.g. DashScope) end the
                # stream with a usage-only chunk carrying an empty choices list.
                continue
            delta = choices[0].get("delta", {}).get("content")
            if delta:
                yield delta


_REWRITE_SYSTEM = (
    "你是检索查询改写器。把用户的最新发言改写成一个适合检索长期记忆的独立查询："
    '保留实体、偏好、事实等关键词；把"我是谁""上次说的"等指代结合上下文展开成具体对象；'
    "只输出查询词本身（不超过30字），不要解释、不要引号、不要句号。"
)


async def _rewrite_query(
    http: httpx.AsyncClient,
    cfg: DemoConfig,
    messages: list[dict[str, str]],
    last_user: str,
) -> str:
    """Rewrite the latest message (with conversation context) into a retrieval query.

    Any failure returns the original message: rewriting must never break the chat.
    """
    context = "\n".join(f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:200]}" for m in messages[-6:-1])
    user_content = (
        f"对话上下文：\n{context}\n\n最新发言：{last_user}\n\n检索查询："
        if context
        else f"最新发言：{last_user}\n\n检索查询："
    )
    payload = {
        "model": cfg.llm_model,
        "stream": False,
        "temperature": 0.0,
        "max_tokens": 64,
        "messages": [
            {"role": "system", "content": _REWRITE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
    } | cfg.llm_extra_body
    resp = await http.post(
        f"{cfg.llm_base_url}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {cfg.llm_api_key}"},
    )
    resp.raise_for_status()
    choices = resp.json().get("choices") or []
    text = str(choices[0].get("message", {}).get("content", "") if choices else "").strip()
    text = text.strip("\"'“”«»").strip()
    return text or last_user


async def _recall_for_query(
    client: PowerContextClient,
    http: httpx.AsyncClient,
    cfg: DemoConfig,
    scope_id: str,
    messages: list[dict[str, str]],
    last_user: str,
) -> tuple[list[SearchMemoryHit], bool, dict[str, Any] | None, str]:
    """Rewrite the query, search memories; on miss, fall back to the most recent entries.

    Returns (hits, fallback, error_event, effective_query). Identity-style questions
    ("你知道我是谁吗") share no tokens with the stored text, so the rewrite expands
    pronouns into entities first and the fallback keeps the agent oriented on a miss.
    """
    try:
        query = await _rewrite_query(http, cfg, messages, last_user)
    except Exception:  # rewrite failure must not block recall or the chat
        query = last_user
    try:
        resp = await client.search_memory(SearchMemoryRequest(scope_id=scope_id, query=query, limit=5))
        if resp.hits:
            return resp.hits, False, None, query
    except Exception as exc:  # recall failure must not block the chat
        return [], False, {"type": "recall_error", "message": str(exc)}, query
    try:
        listed = await client.list_memory_entries(ListMemoryEntriesRequest(scope_id=scope_id))
        return (
            [
                SearchMemoryHit(citation=entry.citation, text=entry.text, score=0.0, matched_by=[])
                for entry in listed.entries[:8]
            ],
            True,
            None,
            query,
        )
    except Exception as exc:
        return [], False, {"type": "recall_error", "message": str(exc)}, query


async def run_chat_turn(
    client: PowerContextClient,
    http: httpx.AsyncClient,
    cfg: DemoConfig,
    scope_id: str,
    messages: list[dict[str, str]],
    memory_on: bool,
) -> AsyncIterator[dict[str, Any]]:
    """One chat turn, yielding SSE event dicts."""
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

    hits: list[SearchMemoryHit] = []
    if memory_on and last_user:
        hits, fallback, error_event, effective_query = await _recall_for_query(
            client, http, cfg, scope_id, messages, last_user
        )
        if error_event:
            yield error_event
        if hits:
            yield {
                "type": "recall",
                "fallback": fallback,
                "query": effective_query,
                "hits": [{"text": hit.text, "score": hit.score} for hit in hits],
            }

    reply: list[str] = []
    try:
        async for delta in stream_llm_reply(http, cfg, build_system_prompt(hits), messages):
            reply.append(delta)
            yield {"type": "delta", "text": delta}
    except Exception as exc:
        yield {"type": "error", "message": f"模型调用失败：{exc}"}
        return
    yield {"type": "done", "reply": "".join(reply)}

    # After the turn: with memory on, capture the exchange and trigger extraction.
    if memory_on and last_user and reply:
        # 写入放进独立任务并 shield: 访客在 done 后立刻刷新页面会取消本生成器,
        # 但这轮对话的记忆不能丢, 让写入在后台继续跑完
        write_task = asyncio.create_task(_capture_and_flush(client, scope_id, last_user, "".join(reply)))
        write_task.add_done_callback(_log_background_failure)
        _BACKGROUND_TASKS.add(write_task)
        write_task.add_done_callback(_BACKGROUND_TASKS.discard)
        try:
            flush = await asyncio.shield(write_task)
            yield {"type": "flushed", "processed_source_count": flush.processed_source_count}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield {"type": "write_error", "message": str(exc)}


async def _capture_and_flush(
    client: PowerContextClient,
    scope_id: str,
    last_user: str,
    reply: str,
) -> FlushMemoryResponse:
    await client.create_source(scope_id, CreateSourceRequest(content=f"用户：{last_user}\n助手：{reply}"))
    return await client.flush_memory(FlushMemoryRequest(scope_id=scope_id))
