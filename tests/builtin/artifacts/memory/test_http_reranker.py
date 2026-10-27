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

"""HTTP reranking validation, global ordering, accounting, and native identity."""

from __future__ import annotations

import json

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.http_reranker import HTTPMemoryReranker
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts


def hit(index):
    return MemoryHit(
        memory_ref=ArtifactRef(family="memory", artifact_id="memory", revision=2),
        entry_id=f"entry-{index}",
        entry_version_id=f"version-{index}",
        text=f"候选 {index}\n完整原文",
        score=1 / index,
        matched_by=("fts",),
    )


async def test_global_top_k_includes_final_batch_and_ties_use_original_rank():
    candidates = tuple(hit(index) for index in range(1, 10))
    before = tuple(candidate.model_dump() for candidate in candidates)
    seen = []
    scores = {1: 0, 2: 0.9, 3: 0.8, 4: -1, 5: 0.4, 6: 0.9, 7: 0.1, 8: 0.2, 9: 1}

    def handler(request):
        body = json.loads(request.content)
        assert set(body) == {"query", "candidates"}
        assert body["query"] == "原始查询"
        seen.append(body["candidates"])
        return httpx.Response(
            200,
            json={
                "scores": [
                    {"rank": item["rank"], "score": scores[item["rank"]]} for item in reversed(body["candidates"])
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = HTTPMemoryReranker("https://score.invalid", client=client, batch_size=2)
        decision = await reranker.rerank("原始查询", candidates, 4)
        assert decision.selected_ranks == (9, 2, 6, 3)
        assert decision.usage.requests == len(seen) == 5
        assert [item for batch in seen for item in batch] == [
            {"rank": index, "text": candidate.text} for index, candidate in enumerate(candidates, 1)
        ]
        assert tuple(candidate.model_dump() for candidate in candidates) == before
        assert not client.is_closed


async def test_full_pool_with_batch_size_seven_reports_twenty_five_requests():
    calls = []

    def handler(request):
        items = json.loads(request.content)["candidates"]
        assert 1 <= len(items) <= 7
        calls.extend(item["rank"] for item in items)
        return httpx.Response(200, json={"scores": [{"rank": item["rank"], "score": -item["rank"]} for item in items]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = HTTPMemoryReranker("https://score.invalid", client=client, batch_size=7)
        decision = await reranker.rerank("query", tuple(hit(index) for index in range(1, 174)), 10)
    assert decision.selected_ranks == tuple(range(1, 11))
    assert decision.usage.requests == 25
    assert calls == list(range(1, 174))


@pytest.mark.parametrize("batch_size", [True, -1, 1.5, "2"])
async def test_batch_size_must_be_a_positive_integer(batch_size):
    transport = httpx.MockTransport(lambda request: pytest.fail("invalid batch_size must not send HTTP requests"))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            HTTPMemoryReranker("https://score.invalid", client=client, batch_size=batch_size)


@pytest.mark.parametrize("limit", [True, 0, -1, 1.0, "1"])
async def test_invalid_limit_fails_before_sending_http(limit):
    def unexpected(request):
        pytest.fail("invalid input must not make HTTP requests")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        reranker = HTTPMemoryReranker("https://score.invalid", client=client)
        with pytest.raises(ValueError):
            await reranker.rerank("query", (hit(1),), limit)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"scores": None},
        {"scores": {}},
        {"scores": [{"rank": True, "score": 0.5}]},
        {"scores": [{"rank": 1.0, "score": 0.5}]},
        {"scores": [{"rank": "1", "score": 0.5}]},
        {"scores": [{"rank": 1, "score": True}]},
        {"scores": [{"rank": 1, "score": "0.5"}]},
        {"scores": [{"rank": 1, "score": None}]},
        {"scores": [{"rank": 1}]},
    ],
)
async def test_schema_rejects_coercions_and_missing_fields(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", (hit(1),), 1)


@pytest.mark.parametrize(
    "raw",
    [
        b"not JSON",
        b'{"scores":[],"scores":[{"rank":1,"score":0.5}]}',
        b'{"scores":[{"rank":1,"score":0.2,"score":0.5}]}',
    ],
)
async def test_malformed_json_and_duplicate_fields_are_rejected(raw):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=raw))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", (hit(1),), 1)


@pytest.mark.parametrize("status", [302, 429, 503])
async def test_non_success_preserves_httpx_error_without_following_redirects(status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={"Location": "/redirected"}, content=b"failure")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", (hit(1),), 1)
        assert error.value.response.status_code == status
    assert len(seen) == 1


async def test_native_memory_search_preserves_each_selected_hit_and_usage():
    seen = []

    def handler(request):
        items = json.loads(request.content)["candidates"]
        seen.append(items)
        return httpx.Response(200, json={"scores": [{"rank": item["rank"], "score": item["rank"]} for item in items]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = HTTPMemoryReranker("https://score.invalid", client=client, batch_size=2, policy_id="test.http")
        async with open_builtin_contexts(BuiltinConfig(database=SQLiteConfig()), memory_reranker=reranker) as contexts:
            service = (await contexts.get("http-ranking")).artifacts.memory
            memory = await service.remember(
                memory=None,
                entries=tuple(MemoryEntryInput(kind="fact", text=f"Project evidence {index}.") for index in range(3)),
                mode="append",
            )
            assert memory is not None
            result = await service.search("project", memories=(memory,), limit=2, mode="fts")
            assert result.rerank is not None
            original = result.rerank.candidate_hits
            assert result.rerank.selected_ranks == (3, 2)
            assert result.hits == (original[2], original[1])
            assert result.rerank.policy_id == "test.http"
            assert result.rerank.usage.requests == len(seen) == 2
