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

"""Event-loop-local embedding coalescing, cancellation isolation, and bounded LRU."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel, QueryEmbeddingModel, embed_query

_TextKey = tuple[bool, str]


@dataclass(frozen=True, slots=True, eq=False)
class _BatchUsage:
    # Identity, rather than equal token counts, distinguishes provider batches.
    usage: InferenceUsage


@dataclass(frozen=True, slots=True)
class _CompletedVector:
    vector: EmbeddingVector
    batch: _BatchUsage


def _observe_completion(future: asyncio.Future[_CompletedVector]) -> None:
    # All callers may have been cancelled. Consume orphaned errors without
    # changing the result seen by current or future shared waiters.
    if not future.cancelled():
        future.exception()


def _total_usage(batches: set[_BatchUsage]) -> InferenceUsage:
    if not batches:
        return InferenceUsage(requests=0)
    inputs = [batch.usage.input_tokens for batch in batches]
    outputs = [batch.usage.output_tokens for batch in batches]
    return InferenceUsage(
        requests=sum(batch.usage.requests for batch in batches),
        input_tokens=None if None in inputs else sum(value for value in inputs if value is not None),
        output_tokens=None if None in outputs else sum(value for value in outputs if value is not None),
    )


class CoalescingEmbeddingModel:
    """Share pending text work and cache successful vectors in one event loop.

    Cache entries contain vectors only: a cache hit never inherits the usage of
    the request that originally computed it. An asymmetric provider's query
    embeddings use a separate key space within the same bounded cache.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a nonnegative integer")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be finite and nonnegative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[_TextKey, EmbeddingVector] = OrderedDict()
        self._pending: dict[_TextKey, asyncio.Future[_CompletedVector]] = {}
        self._queued: dict[_TextKey, asyncio.Future[_CompletedVector]] = {}
        self._dispatch_task: asyncio.Task[None] | None = None
        self._batches: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return await self._embed(texts, query=False)

    async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        # Symmetric providers share document/query work and cached vectors.
        return await self._embed(texts, query=isinstance(self._model, QueryEmbeddingModel))

    async def _embed(self, texts: tuple[str, ...], *, query: bool) -> EmbeddingResult:
        loop = asyncio.get_running_loop()
        keys = tuple((query, text) for text in texts)
        vectors: dict[_TextKey, EmbeddingVector] = {}
        waiting: dict[_TextKey, asyncio.Future[_CompletedVector]] = {}
        # No suspension until the whole call has joined shared work. Other
        # callers cannot observe a partially registered input batch.
        for key in dict.fromkeys(keys):
            if key in self._cache:
                vectors[key] = self._cache[key]
                self._cache.move_to_end(key)
            else:
                future = self._pending.get(key)
                if future is None:
                    future = loop.create_future()
                    future.add_done_callback(_observe_completion)
                    self._pending[key] = self._queued[key] = future
                waiting[key] = future
        if self._queued and self._dispatch_task is None:
            self._dispatch_task = loop.create_task(self._dispatch())

        # Shield each shared future: cancelling this gather only cancels this
        # caller's awaitables, never the shared provider work or another caller.
        completed = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
        batches: set[_BatchUsage] = set()
        for key, result in zip(waiting, completed, strict=True):
            vectors[key] = result.vector
            batches.add(result.batch)
        return EmbeddingResult(vectors=tuple(vectors[key] for key in keys), usage=_total_usage(batches))

    async def _dispatch(self) -> None:
        try:
            # Even zero yields once so callers starting together can join.
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            for key, future in self._queued.items():
                future.cancel()
                self._pending.pop(key, None)
            self._queued.clear()
            self._dispatch_task = None
            raise
        queued = tuple(self._queued.items())
        self._queued.clear()
        self._dispatch_task = None
        for query in (False, True):
            items = tuple(item for item in queued if item[0][0] is query)
            for start in range(0, len(items), self._max_batch_size):
                batch = items[start : start + self._max_batch_size]
                task = asyncio.create_task(self._run_batch(batch, query=query))
                self._batches.add(task)
                task.add_done_callback(self._batches.discard)

    async def _run_batch(
        self,
        batch: tuple[tuple[_TextKey, asyncio.Future[_CompletedVector]], ...],
        *,
        query: bool,
    ) -> None:
        texts = tuple(key[1] for key, _ in batch)
        try:
            result = await embed_query(self._model, texts) if query else await self._model.embed(texts)
            if len(result.vectors) != len(batch):
                raise ValueError("Embedding vector count does not match the requested text count")  # noqa: TRY003, TRY301
            usage = _BatchUsage(result.usage.model_copy(deep=True))
            for (key, future), vector in zip(batch, result.vectors, strict=True):
                self._cache_vector(key, vector)
                future.set_result(_CompletedVector(vector, usage))
        except asyncio.CancelledError:
            for _, future in batch:
                future.cancel()
            raise
        except Exception as error:
            for _, future in batch:
                if not future.done():
                    future.set_exception(error)
        finally:
            for key, _ in batch:
                self._pending.pop(key, None)

    def _cache_vector(self, key: _TextKey, vector: EmbeddingVector) -> None:
        if self._cache_size:
            self._cache[key] = vector
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)


__all__ = ["CoalescingEmbeddingModel"]
