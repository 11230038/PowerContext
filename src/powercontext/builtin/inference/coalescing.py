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

"""Cross-call request coalescing and bounded vector caching for embeddings."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Iterable
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

__all__ = ["CoalescingEmbeddingModel"]


@dataclass(slots=True)
class _Batch:
    """Identity and provider usage of one dispatched underlying request.

    Every text that shares this batch receives the same instance, so a caller can
    attribute the batch's usage exactly once no matter how many of its inputs joined it.
    """

    usage: InferenceUsage


@dataclass(slots=True)
class _Pending:
    """One text's shared in-flight computation."""

    future: asyncio.Future[tuple[EmbeddingVector, _Batch]]


class CoalescingEmbeddingModel:
    """Join identical in-flight embedding texts and cache successful vectors.

    The wrapper is bound to one event loop. Callers requesting the same text while a
    batch is queued or running await that one computation; cancelling a caller only
    cancels that caller's wait, never the shared request. The cache is a bounded LRU
    of successful vectors, refreshed on every hit.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int:
            raise TypeError("max_batch_size must be an integer")  # noqa: TRY003
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")  # noqa: TRY003
        if coalesce_ms < 0:
            raise ValueError("coalesce_ms must not be negative")  # noqa: TRY003
        if type(cache_size) is not int:
            raise TypeError("cache_size must be an integer")  # noqa: TRY003
        if cache_size < 0:
            raise ValueError("cache_size must not be negative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_ms = coalesce_ms
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, _Pending] = {}
        self._queue: deque[str] = deque()
        self._scheduled = False
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return one ordered vector per input text, sharing and caching provider work."""

        ordered = tuple(texts)
        if not ordered:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        vectors: dict[str, EmbeddingVector] = {}
        pending: list[tuple[str, _Pending]] = []
        seen: set[str] = set()
        for text in ordered:
            if text in seen:
                continue
            seen.add(text)
            cached = self._cached(text)
            if cached is not None:
                vectors[text] = cached
                continue
            entry = self._inflight.get(text)
            if entry is None:
                entry = self._start(text)
            pending.append((text, entry))

        batches: dict[int, _Batch] = {}
        if pending:
            awaited = await asyncio.gather(*(asyncio.shield(entry.future) for _, entry in pending))
            for (text, _), (vector, batch) in zip(pending, awaited, strict=True):
                vectors[text] = vector
                batches[id(batch)] = batch

        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in ordered),
            usage=_sum_usage(tuple(batches.values())),
        )

    def _cached(self, text: str) -> EmbeddingVector | None:
        if not self._cache_size:
            return None
        vector = self._cache.get(text)
        if vector is None:
            return None
        self._cache.move_to_end(text)
        return vector

    def _start(self, text: str) -> _Pending:
        future: asyncio.Future[tuple[EmbeddingVector, _Batch]] = asyncio.get_running_loop().create_future()
        future.add_done_callback(_consume_exception)
        entry = _Pending(future=future)
        self._inflight[text] = entry
        self._queue.append(text)
        self._schedule()
        return entry

    def _schedule(self) -> None:
        if self._scheduled:
            return
        self._scheduled = True
        loop = asyncio.get_running_loop()
        if self._coalesce_ms > 0:
            loop.call_later(self._coalesce_ms / 1000.0, self._dispatch)
        else:
            # Still let every coroutine run this instant register its texts first.
            loop.call_soon(self._dispatch)

    def _dispatch(self) -> None:
        self._scheduled = False
        while self._queue:
            texts = self._next_batch()
            if not texts:
                break
            task = asyncio.get_running_loop().create_task(self._run_batch(texts))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _next_batch(self) -> tuple[str, ...]:
        texts: list[str] = []
        while self._queue and len(texts) < self._max_batch_size:
            text = self._queue.popleft()
            if text in self._inflight:
                texts.append(text)
        return tuple(texts)

    async def _run_batch(self, texts: tuple[str, ...]) -> None:
        try:
            result = await self._model.embed(texts)
        except asyncio.CancelledError:
            self._discard(texts, cancelled=True)
            raise
        except Exception as error:
            self._discard(texts, error=error)
            return

        if len(result.vectors) != len(texts):
            self._discard(texts, error=ValueError("embedding provider returned a mismatched vector count"))
            return

        batch = _Batch(usage=result.usage)
        for text, vector in zip(texts, result.vectors, strict=True):
            self._remember(text, vector)
            entry = self._inflight.pop(text, None)
            if entry is not None and not entry.future.done():
                entry.future.set_result((vector, batch))

    def _remember(self, text: str, vector: EmbeddingVector) -> None:
        if not self._cache_size:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _discard(
        self,
        texts: tuple[str, ...],
        *,
        error: BaseException | None = None,
        cancelled: bool = False,
    ) -> None:
        for text in texts:
            entry = self._inflight.pop(text, None)
            if entry is None or entry.future.done():
                continue
            if cancelled:
                entry.future.cancel()
            elif error is not None:
                entry.future.set_exception(error)


def _consume_exception(future: asyncio.Future[object]) -> None:
    """Mark a shared future's failure retrieved even when every waiter was cancelled."""

    if not future.cancelled():
        future.exception()


def _sum_usage(batches: tuple[_Batch, ...]) -> InferenceUsage:
    if not batches:
        return InferenceUsage(requests=0)
    return InferenceUsage(
        requests=sum(batch.usage.requests for batch in batches),
        input_tokens=_sum_tokens(batch.usage.input_tokens for batch in batches),
        output_tokens=_sum_tokens(batch.usage.output_tokens for batch in batches),
    )


def _sum_tokens(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None
