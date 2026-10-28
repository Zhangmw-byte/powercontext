# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Shared batches retain per-caller ordering, failure, usage, and cancellation."""

from __future__ import annotations

import asyncio

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage, embed_query
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel
from powercontext.builtin.inference.usage import UsageReportingEmbeddingModel, bind_usage_reporter
from powercontext.builtin.statistics import ModelUsagePurpose


class _Metered:
    profile = EmbeddingProfile(profile_id="coalescing-regression", model="offline", dimension=1)

    def __init__(self):
        self.calls = []

    async def embed(self, texts):
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((float(len(text)),) for text in texts),
            usage=InferenceUsage(requests=2, input_tokens=7, output_tokens=3),
        )


class _Gated(_Metered):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def embed(self, texts):
        self.started.set()
        await self.release.wait()
        return await super().embed(texts)


@pytest.mark.parametrize(
    "settings",
    [
        {"max_batch_size": 0},
        {"max_batch_size": -1},
        {"max_batch_size": True},
        {"max_batch_size": 1.0},
        {"cache_size": -1},
        {"cache_size": True},
        {"cache_size": 1.0},
        {"coalesce_ms": -1},
        {"coalesce_ms": True},
        {"coalesce_ms": float("nan")},
        {"coalesce_ms": float("inf")},
        {"coalesce_ms": "5"},
    ],
)
def test_invalid_budgets_are_rejected(settings):
    with pytest.raises(ValueError):
        CoalescingEmbeddingModel(_Metered(), **settings)


@pytest.mark.parametrize("cache_size", [0, 4])
async def test_late_waiter_shares_running_work_and_cache_zero_only_disables_completed_reuse(cache_size):
    base = _Gated()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=cache_size)
    assert model.profile is base.profile
    first = asyncio.create_task(model.embed(("alpha", "beta", "alpha")))
    await asyncio.wait_for(base.started.wait(), timeout=3)
    entered = asyncio.Event()

    async def join_late():
        entered.set()
        return await model.embed(("beta", "alpha", "beta"))

    late = asyncio.create_task(join_late())
    await entered.wait()
    base.release.set()
    left, right = await asyncio.wait_for(asyncio.gather(first, late), timeout=3)
    assert left.vectors == ((5.0,), (4.0,), (5.0,))
    assert right.vectors == ((4.0,), (5.0,), (4.0,))
    assert base.calls == [("alpha", "beta")]
    assert left.usage == right.usage == InferenceUsage(requests=2, input_tokens=7, output_tokens=3)
    again = await model.embed(("alpha",))
    assert len(base.calls) == (2 if cache_size == 0 else 1)
    assert again.usage.requests == (2 if cache_size == 0 else 0)


async def test_overlapping_calls_count_each_shared_batch_once_even_with_identical_usage():
    base = _Metered()
    model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=5)
    first, second, third = await asyncio.gather(
        model.embed(("a", "bb", "ccc", "a")),
        model.embed(("bb", "dddd")),
        model.embed(("a", "bb", "a")),
    )
    assert base.calls == [("a", "bb"), ("ccc", "dddd")]
    assert first.vectors == ((1.0,), (2.0,), (3.0,), (1.0,))
    assert second.vectors == ((2.0,), (4.0,))
    assert first.usage == second.usage == InferenceUsage(requests=4, input_tokens=14, output_tokens=6)
    assert third.usage == InferenceUsage(requests=2, input_tokens=7, output_tokens=3)
    mixed = await model.embed(("a", "new", "new", "bb"))
    assert mixed.usage == InferenceUsage(requests=2, input_tokens=7, output_tokens=3)


async def test_unknown_token_counts_are_not_replaced_with_invented_zeroes():
    class Partial(_Metered):
        async def embed(self, texts):
            return EmbeddingResult(
                vectors=((1.0,),),
                usage=InferenceUsage(requests=3, input_tokens=7 if texts == ("known",) else None, output_tokens=None),
            )

    result = await CoalescingEmbeddingModel(Partial(), max_batch_size=1, coalesce_ms=0).embed(("known", "unknown"))
    assert result.usage == InferenceUsage(requests=6, input_tokens=None, output_tokens=None)


async def test_provider_exception_only_fails_its_batch_and_failed_text_can_retry():
    class Flaky(_Metered):
        async def embed(self, texts):
            if texts == ("bad",) and texts not in self.calls:
                self.calls.append(texts)
                raise RuntimeError("transient provider failure")  # noqa: TRY003
            return await super().embed(texts)

    base = Flaky()
    model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=5)
    failed, shared, independent = await asyncio.gather(
        model.embed(("bad", "good")), model.embed(("bad",)), model.embed(("good",)), return_exceptions=True
    )
    assert isinstance(failed, RuntimeError) and isinstance(shared, RuntimeError)
    assert isinstance(independent, EmbeddingResult) and independent.vectors == ((4.0,),)
    assert (await model.embed(("bad",))).vectors == ((3.0,),)
    assert (await model.embed(("good",))).usage.requests == 0
    assert base.calls.count(("bad",)) == 2
    assert base.calls.count(("good",)) == 1


async def test_wrong_vector_count_is_not_cached_and_does_not_block_other_batches():
    class WrongCount(_Metered):
        async def embed(self, texts):
            if texts == ("broken",) and texts not in self.calls:
                self.calls.append(texts)
                return EmbeddingResult(vectors=((1.0,), (2.0,)))
            return await super().embed(texts)

    base = WrongCount()
    model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
    bad, good = await asyncio.gather(model.embed(("broken",)), model.embed(("ok",)), return_exceptions=True)
    assert isinstance(bad, ValueError)
    assert isinstance(good, EmbeddingResult) and good.vectors == ((2.0,),)
    assert (await model.embed(("broken",))).vectors == ((6.0,),)
    assert base.calls.count(("broken",)) == 2


async def test_call_timeout_and_all_waiters_cancelling_leave_shared_work_available():
    base = _Gated()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=0)
    timed = asyncio.create_task(asyncio.wait_for(model.embed(("shared",)), timeout=0.02))
    await asyncio.wait_for(base.started.wait(), timeout=3)
    with pytest.raises(TimeoutError):
        await timed
    # The timed-out call was the only waiter. A new call must still join the
    # live provider request rather than find a cancelled shared future.
    survivor = asyncio.create_task(model.embed(("shared",)))
    base.release.set()
    result = await asyncio.wait_for(survivor, timeout=3)
    assert result.vectors == ((6.0,),)
    assert base.calls == [("shared",)]


async def test_provider_cancellation_releases_the_identity_for_retry():
    class CancelOnce(_Metered):
        async def embed(self, texts):
            if not self.calls:
                self.calls.append(texts)
                raise asyncio.CancelledError
            return await super().embed(texts)

    base = CancelOnce()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0)
    with pytest.raises(asyncio.CancelledError):
        await model.embed(("retry",))
    assert (await model.embed(("retry",))).vectors == ((5.0,),)
    assert len(base.calls) == 2


async def test_failure_after_every_waiter_cancelled_is_consumed_and_can_retry():
    class FailAfterRelease(_Gated):
        def __init__(self):
            super().__init__()
            self.failed = asyncio.Event()

        async def embed(self, texts):
            self.started.set()
            await self.release.wait()
            if not self.calls:
                self.calls.append(texts)
                self.failed.set()
                raise RuntimeError("orphaned provider failure")  # noqa: TRY003
            return await _Metered.embed(self, texts)

    base = FailAfterRelease()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0)
    abandoned = asyncio.create_task(model.embed(("retry",)))
    await asyncio.wait_for(base.started.wait(), timeout=3)
    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandoned
    base.release.set()
    await asyncio.wait_for(base.failed.wait(), timeout=3)
    assert (await model.embed(("retry",))).vectors == ((5.0,),)
    assert len(base.calls) == 2


@pytest.mark.parametrize("cache_size", [0, 1, 2])
async def test_active_results_survive_cache_eviction_before_the_call_returns(cache_size):
    class Numbered(_Metered):
        async def embed(self, texts):
            self.calls.append(texts)
            return EmbeddingResult(vectors=tuple((float(text),) for text in texts))

    base = Numbered()
    model = CoalescingEmbeddingModel(base, max_batch_size=3, coalesce_ms=0, cache_size=cache_size)
    values = ("8", "3", "4", "1", "6", "2", "7", "5", "3")
    result = await model.embed(values)
    assert result.vectors == tuple((float(text),) for text in values)
    assert len(base.calls) == 3


async def test_query_and_document_embeddings_share_only_when_provider_is_symmetric():
    class Asymmetric(_Metered):
        async def embed_query(self, texts):
            self.calls.append(("query", *texts))
            return EmbeddingResult(vectors=tuple((-float(len(text)),) for text in texts))

    base = Asymmetric()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=1)
    assert (await model.embed(("same",))).vectors == ((4.0,),)
    assert (await embed_query(model, ("same",))).vectors == ((-4.0,),)
    assert (await embed_query(model, ("same",))).usage.requests == 0
    assert (await model.embed(("same",))).vectors == ((4.0,),)
    assert base.calls == [("same",), ("query", "same"), ("same",)]


async def test_usage_reporting_remains_bound_to_each_waiting_caller():
    base = _Metered()
    model = UsageReportingEmbeddingModel(CoalescingEmbeddingModel(base, coalesce_ms=5))
    reports = {}

    async def invoke(scope):
        async def report(purpose, operation, usage):
            reports[scope] = usage

        with bind_usage_reporter(report, embedding_purpose=ModelUsagePurpose.MEMORY_INDEXING):
            return await model.embed(("shared", "shared"))

    left, right = await asyncio.gather(invoke("left"), invoke("right"))
    assert base.calls == [("shared",)]
    assert reports["left"] == reports["right"] == left.usage == right.usage


async def test_waiter_population_does_not_change_unique_text_request_budget():
    base = _Metered()
    model = CoalescingEmbeddingModel(base, max_batch_size=5, coalesce_ms=0, cache_size=100)
    texts = tuple(str(number) for number in range(37))
    results = await asyncio.gather(*(model.embed(texts[::-1] if index % 2 else texts) for index in range(40)))
    assert len(base.calls) == 8
    assert all(len(batch) <= 5 for batch in base.calls)
    assert sorted(text for batch in base.calls for text in batch) == sorted(texts)
    for index, result in enumerate(results):
        expected = texts[::-1] if index % 2 else texts
        assert result.vectors == tuple((float(len(text)),) for text in expected)
        assert result.usage.requests == 16
