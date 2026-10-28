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

"""Offline lexical evidence selection with exact serialized-output accounting."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.models import PrepareContextRequest, PreparedContext
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    MemoryEvidenceFragment,
    PreparedContextBuild,
    PreparedMemoryCandidates,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_BOUNDARY = re.compile(r"[。！？][\"'”’\)\]]*|[.!?][\"'”’\)\]]*(?=\s|$)|\n+")  # noqa: RUF001
_STOP = frozenset([
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "which",
    "with",
    "would",
    "we",
    "they",
    "than",
    "through",
    "using",
    "used",
    "use",
    "also",
    "such",
    "not",
    "no",
])


@dataclass(frozen=True)
class _Sentence:
    fragment: MemoryEvidenceFragment
    # Whitespace between consecutive ranges is retained when they are joined.
    previous_end: int | None
    gap: str
    terms: Counter[str]
    rank: int


@dataclass(frozen=True)
class _Choice:
    previous: _Choice | None
    sentence: _Sentence
    joined: bool


@dataclass(frozen=True)
class _State:
    value: float = 0.0
    choice: _Choice | None = None


def _terms(text: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for match in _WORD.finditer(text.casefold()):
        word = match.group()
        if word in _STOP:
            continue
        if any("\u3400" <= char <= "\u9fff" for char in word):
            result.update(word[i : i + 2] for i in range(max(1, len(word) - 1)))
        else:
            # Conservative inflection normalization, without a model or corpus dependency.
            if word.endswith("ies") and len(word) > 5:
                word = word[:-3] + "y"
            elif word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
                word = word[:-1]
            result[word] += 1
    return result


def _long_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    result = []
    remaining_bytes = len(text[start:end].encode("utf-8"))
    # Split oversized sentences at whitespace when possible, keeping literal offsets.
    while remaining_bytes > 512:
        stop = start
        size = 0
        space = None
        while stop < end and size + len(text[stop].encode("utf-8")) <= 256:
            size += len(text[stop].encode("utf-8"))
            stop += 1
            if text[stop - 1].isspace() and size >= 128:
                space = stop
        stop = space or stop
        trimmed = stop
        while trimmed > start and text[trimmed - 1].isspace():
            trimmed -= 1
        if trimmed > start:
            result.append((start, trimmed))
        while stop < end and text[stop].isspace():
            stop += 1
        remaining_bytes -= len(text[start:stop].encode("utf-8"))
        start = stop
    if start < end:
        result.append((start, end))
    return result


def _spans(text: str) -> list[tuple[int, int]]:
    boundaries = [0, *(match.end() for match in _BOUNDARY.finditer(text)), len(text)]
    result: list[tuple[int, int]] = []
    for start, end in pairwise(boundaries):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        result.extend(_long_spans(text, start, end))
    return result


def _sentences(groups: Sequence[PreparedMemoryCandidates]) -> list[list[_Sentence]]:
    documents: list[list[_Sentence]] = []
    seen: dict[tuple[str, str, str, int, str, str], str] = {}
    for group in groups:
        if group.hits and group.memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        if group.hits and not group.scope_id.strip():
            raise PreparedContextInvariantError("evidence-scope-missing")
        for hit in group.hits:
            if hit.memory_ref != group.memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            address = MemoryEntryAddress(
                memory=ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref),
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            identity = (
                group.scope_id,
                hit.memory_ref.family,
                hit.memory_ref.artifact_id,
                hit.memory_ref.revision,
                hit.entry_id,
                hit.entry_version_id,
            )
            if identity in seen:
                if seen[identity] != hit.text:
                    raise PreparedContextInvariantError("memory-entry-text-mismatch")
                continue
            seen[identity] = hit.text
            sentences: list[_Sentence] = []
            previous_end = None
            for start, end in _spans(hit.text):
                fragment = MemoryEvidenceFragment(address, start, end, hit.text[start:end])
                gap = "" if previous_end is None else hit.text[previous_end:start]
                sentences.append(_Sentence(fragment, previous_end, gap, _terms(fragment.text), len(documents)))
                previous_end = end
            documents.append(sentences)
    return documents


def _weights(documents: list[list[_Sentence]], query: str) -> list[list[float]]:
    query_terms = _terms(query)
    sentences = [sentence for document in documents for sentence in document]
    frequency: Counter[str] = Counter()
    for sentence in sentences:
        frequency.update(sentence.terms.keys())
    average_length = sum(sum(sentence.terms.values()) for sentence in sentences) / max(1, len(sentences))
    idf = {term: math.log1p((len(sentences) - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in query_terms}
    weights = []
    for document in documents:
        raw = []
        repeated: set[str] = set()
        unique = []
        for sentence in document:
            score = 0.0
            unique.append(sentence.fragment.text not in repeated)
            if unique[-1]:
                length = sum(sentence.terms.values())
                for term in query_terms:
                    count = sentence.terms[term]
                    score += idf[term] * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / max(1, average_length)))
            repeated.add(sentence.fragment.text)
            raw.append(score)
        # Nearby explanatory sentences have value even when their vocabulary differs.
        # This also favors contiguous evidence, whose citation cost can be shared.
        weights.append([
            value
            + 0.12 * max((raw[j] / (1 + abs(i - j)) for j in range(max(0, i - 2), min(len(raw), i + 3))), default=0)
            if unique[i]
            else 0.0
            for i, (sentence, value) in enumerate(zip(document, raw, strict=True))
        ])
    if not any(value > 0 for document in weights for value in document):
        return [[1.0 / (1 + sentence.rank) for sentence in document] for document in documents]
    return weights


def _item(fragment: MemoryEvidenceFragment) -> dict[str, object]:
    address = fragment.address
    return {
        "citation": {
            "scope_id": address.memory.scope_id,
            "memory_ref": address.memory.artifact.model_dump(mode="json"),
            "entry_id": address.entry_id,
            "entry_version_id": address.entry_version_id,
        },
        "content": fragment.text,
        "start": fragment.start,
        "end": fragment.end,
    }


def _json_bytes(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _render(fragments: Sequence[MemoryEvidenceFragment]) -> str:
    envelope = json.dumps(
        {"trust": "untrusted_history", "items": [_item(f) for f in fragments]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{TRUST_POLICY}\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n{envelope}\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"


def _prune(states: dict[int, _State]) -> dict[int, _State]:
    # For the same open/closed run, a cheaper state with at least as much utility
    # dominates every future continuation. Keep only the cost/value frontier.
    best = -1.0
    frontier = {}
    for cost, state in sorted(states.items()):
        if state.value > best:
            frontier[cost] = state
            best = state.value
    return frontier


def _put(states: dict[int, _State], cost: int, state: _State) -> None:
    if cost not in states or state.value > states[cost].value:
        states[cost] = state


def _advance(
    closed: dict[int, _State], opened: dict[int, _State], sentence: _Sentence, value: float, capacity: int
) -> tuple[dict[int, _State], dict[int, _State]]:
    new_closed = dict(closed)
    for cost, state in opened.items():
        _put(new_closed, cost, state)
    new_opened: dict[int, _State] = {}
    new_cost = _json_bytes(_item(sentence.fragment)) + 1
    for cost, state in closed.items():
        if value > 0 and cost + new_cost <= capacity:
            _put(new_opened, cost + new_cost, _State(state.value + value, _Choice(state.choice, sentence, False)))
    if sentence.previous_end is not None:
        delta = (
            _json_bytes(sentence.gap + sentence.fragment.text)
            - 2
            + len(str(sentence.fragment.end))
            - len(str(sentence.previous_end))
        )
        for cost, state in opened.items():
            if cost + delta <= capacity:
                _put(new_opened, cost + delta, _State(state.value + value, _Choice(state.choice, sentence, True)))
    return _prune(new_closed), _prune(new_opened)


def _fragments(choice: _Choice | None) -> list[MemoryEvidenceFragment]:
    choices = []
    while choice is not None:
        choices.append(choice)
        choice = choice.previous
    fragments: list[MemoryEvidenceFragment] = []
    for choice in reversed(choices):
        fragment = choice.sentence.fragment
        if choice.joined:
            previous = fragments.pop()
            fragment = MemoryEvidenceFragment(
                fragment.address, previous.start, fragment.end, previous.text + choice.sentence.gap + fragment.text
            )
        fragments.append(fragment)
    return fragments


def select_evidence(request: PrepareContextRequest, groups: Sequence[PreparedMemoryCandidates]) -> PreparedContextBuild:
    """Choose literal sentence ranges by lexical relevance under the complete wire budget."""
    documents = _sentences(groups)
    weights = _weights(documents, request.query)
    # Each new JSON item costs its encoding plus one comma. Subtracting one here
    # accounts for the absent comma before the first item, including end/start digits.
    base_bytes = len(_render(()).encode("utf-8")) - 1
    capacity = request.max_bytes - base_bytes
    closed = {0: _State()}
    opened: dict[int, _State] = {}
    for document, scores in zip(documents, weights, strict=True):
        for cost, state in opened.items():
            _put(closed, cost, state)
        closed = _prune(closed)
        opened = {}
        for sentence, value in zip(document, scores, strict=True):
            closed, opened = _advance(closed, opened, sentence, value, capacity)
    best = max((*closed.values(), *opened.values()), key=lambda state: state.value)
    fragments = _fragments(best.choice)
    if not fragments:
        return PreparedContextBuild(context=PreparedContext(status="empty", content=None, content_bytes=0), origins=())
    content = _render(fragments)
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > request.max_bytes:
        raise PreparedContextInvariantError("output-budget")
    return PreparedContextBuild(
        context=PreparedContext(status="ready", content=content, content_bytes=content_bytes),
        origins=tuple(fragment.address for fragment in fragments),
        fragments=tuple(fragments),
    )
