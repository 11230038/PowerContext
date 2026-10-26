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

"""HTTP cross-encoder Memory reranking with bounded request batches."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

DEFAULT_HTTP_RERANK_BATCH_SIZE = 32
DEFAULT_HTTP_RERANK_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score candidate batches over HTTP and select from the whole candidate pool."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = DEFAULT_HTTP_RERANK_BATCH_SIZE,
        policy_id: str = DEFAULT_HTTP_RERANK_POLICY_ID,
    ) -> None:
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate exactly once and rank the complete pool globally."""

        _validate_bounds(len(candidates), limit)
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            ranks = tuple(range(start + 1, start + 1 + len(batch)))
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [{"rank": rank, "text": candidates[rank - 1].text} for rank in ranks],
                },
            )
            requests += 1
            response.raise_for_status()
            scores.update(_validated_batch_scores(_decode_response(response), ranks))
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _ in ordered),
            usage=InferenceUsage(requests=requests),
        )


def _decode_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise ValueError("rerank response must be valid JSON") from error  # noqa: TRY003


def _validated_batch_scores(body: Any, ranks: tuple[int, ...]) -> dict[int, float]:
    if not isinstance(body, dict) or set(body) != {"scores"}:
        raise ValueError("rerank response must contain exactly the scores field")  # noqa: TRY003
    raw_scores = body["scores"]
    if not isinstance(raw_scores, list):
        raise ValueError("rerank scores must be a list")  # noqa: TRY003, TRY004
    validated: dict[int, float] = {}
    for item in raw_scores:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("each rerank score must contain exactly rank and score")  # noqa: TRY003
        rank = item["rank"]
        if type(rank) is not int:
            raise ValueError("rerank score rank must be an integer")  # noqa: TRY003
        if rank in validated or rank not in ranks:
            raise ValueError("rerank scores must cover each batch rank exactly once")  # noqa: TRY003
        validated[rank] = _finite_score(item["score"])
    if set(validated) != set(ranks):
        raise ValueError("rerank scores must cover each batch rank exactly once")  # noqa: TRY003
    return validated


def _finite_score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("rerank score must be a finite number")  # noqa: TRY003, TRY004
    try:
        score = float(value)
    except OverflowError as error:
        raise ValueError("rerank score must be a finite number") from error  # noqa: TRY003
    if not math.isfinite(score):
        raise ValueError("rerank score must be a finite number")  # noqa: TRY003
    return score


def _validate_bounds(candidate_count: int, limit: int) -> None:
    if candidate_count < 1:
        raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
    if limit < 1 or limit > candidate_count:
        raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003


__all__ = [
    "DEFAULT_HTTP_RERANK_BATCH_SIZE",
    "DEFAULT_HTTP_RERANK_POLICY_ID",
    "HTTPMemoryReranker",
]
