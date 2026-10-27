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

"""HTTP scoring with global, identity-preserving Memory candidate selection."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Rerank JSON contains a duplicate field")  # noqa: TRY003
        value[key] = item
    return value


def _batch_scores(payload: object, expected: set[int]) -> dict[int, int | float]:
    if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
        raise ValueError("Rerank response must contain only a scores array")  # noqa: TRY003
    scores: dict[int, int | float] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("Each rerank score must contain only rank and score")  # noqa: TRY003
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in expected or rank in scores:
            raise ValueError("Rerank response has a duplicate or unexpected rank")  # noqa: TRY003
        # bool is not a score. Integers are finite without a lossy float conversion.
        if not (type(score) is int or (type(score) is float and math.isfinite(score))):
            raise ValueError("Rerank score must be a finite number")  # noqa: TRY003
        scores[rank] = score
    if set(scores) != expected:
        raise ValueError("Rerank response does not cover every candidate in the batch")  # noqa: TRY003
    return scores


class HTTPMemoryReranker:
    """Score all candidates in bounded batches using a caller-owned client."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("Rerank batch_size must be a positive integer")  # noqa: TRY003
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
        if not candidates or type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("Rerank requires candidates and a valid integer limit")  # noqa: TRY003
        scores: dict[int, int | float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = [
                {"rank": index + 1, "text": candidates[index].text}
                for index in range(start, min(start + self._batch_size, len(candidates)))
            ]
            response = await self._client.post(
                self._endpoint,
                json={"query": query, "candidates": batch},
                # Every non-2xx response is an error, including redirects.
                follow_redirects=False,
            )
            requests += 1
            response.raise_for_status()
            payload = response.json(object_pairs_hook=_unique_object)
            scores.update(_batch_scores(payload, set(range(start + 1, start + len(batch) + 1))))
        selected = sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]
        return MemoryRerankDecision(selected_ranks=tuple(selected), usage=InferenceUsage(requests=requests))


__all__ = ["HTTPMemoryReranker"]
