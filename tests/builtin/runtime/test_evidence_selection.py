# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at https://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput, MemoryHit
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    ContextAssembly,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource

MEMORY = ArtifactRef(family="memory", artifact_id="memory", revision=3)


def _group(*texts: str, scope: str = "scope", memory_ref: ArtifactRef = MEMORY) -> PreparedMemoryCandidates:
    return PreparedMemoryCandidates(
        scope_id=scope,
        memory_ref=memory_ref,
        hits=tuple(
            MemoryHit(
                memory_ref=memory_ref,
                entry_id=f"e{i}",
                entry_version_id=f"v{i}",
                text=text,
                score=1.0,
                matched_by=("fts",),
            )
            for i, text in enumerate(texts)
        ),
    )


def _build(*groups: PreparedMemoryCandidates, query: str = "cobalt sensor", budget: int = 1400, **options):
    return PreparedContextBuilder().build_scopes_result(
        current_scope_id="scope",
        memory_candidates=groups,
        request=PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True, **options),
    )


def _assert_literals(result, groups, budget):
    assert result.context.content_bytes == len((result.context.content or "").encode("utf-8")) <= budget
    assert result.origins == tuple(fragment.address for fragment in result.fragments)
    if not result.fragments:
        assert result.context.status == "empty" and result.context.content is None
        return
    assert result.context.content.startswith(TRUST_POLICY + "\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n")
    assert result.context.content.endswith("\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1")
    envelope = json.loads(result.context.content.splitlines()[-2])
    assert envelope["trust"] == "untrusted_history"
    assert len(envelope["items"]) == len(result.fragments)
    for fragment, item in zip(result.fragments, envelope["items"], strict=True):
        group = next(
            group
            for group in groups
            if group.scope_id == fragment.address.memory.scope_id
            and group.memory_ref == fragment.address.memory.artifact
        )
        hit = next(hit for hit in group.hits if hit.entry_id == fragment.address.entry_id)
        assert type(fragment.start) is int and type(fragment.end) is int
        assert 0 <= fragment.start < fragment.end <= len(hit.text)
        assert fragment.text == hit.text[fragment.start : fragment.end]
        assert item == {
            "citation": {
                "scope_id": group.scope_id,
                "memory_ref": group.memory_ref.model_dump(mode="json"),
                "entry_id": hit.entry_id,
                "entry_version_id": hit.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }


@pytest.mark.parametrize("bad", [None, 1, 0, "true", "false", [], {}])
def test_selection_flag_is_a_strict_opt_in(bad):
    assert not PrepareContextRequest(query="sensor").evidence_selection
    with pytest.raises(ValidationError):
        PrepareContextRequest(query="sensor", evidence_selection=bad)


def test_query_switches_evidence_and_can_return_separated_ranges():
    text = "Cobalt sensors require calibration at 37 degrees. " + "Administrative notes. " * 100
    text += "Cobalt sensors require annual inspection. " + "Unrelated notes. " * 100
    text += "Amber valves open at 19 degrees."
    group = _group(text)
    cobalt = _build(group, query="cobalt sensors calibration inspection", budget=1200)
    amber = _build(group, query="amber valves open", budget=1200)
    assert len(cobalt.fragments) >= 2
    assert any("37" in f.text for f in cobalt.fragments)
    assert any("inspection" in f.text for f in cobalt.fragments)
    assert any("19" in f.text for f in amber.fragments)
    assert cobalt.fragments != amber.fragments
    for result in (cobalt, amber):
        _assert_literals(result, (group,), 1200)


@pytest.mark.parametrize("budget", [512, 600, 700, 999, 1200, 1400, 1800, 32768])
def test_complete_utf8_budget_includes_escaped_json_citations_and_markers(budget):
    group = _group('Sensor "海洋观测" measures \\temperature.\r\nCobalt sensor λ has range 0.5 μm. ' * 12)
    result = _build(group, query="sensor 海洋观测 temperature", budget=budget)
    _assert_literals(result, (group,), budget)


def test_exact_fit_and_one_byte_less():
    group = _group("Cobalt sensor calibration preserves literal evidence.")
    full = _build(group)
    required = full.context.content_bytes
    assert required > 512
    exact = _build(group, budget=required)
    smaller = _build(group, budget=required - 1)
    assert exact.context == full.context
    assert not smaller.fragments
    _assert_literals(exact, (group,), required)
    _assert_literals(smaller, (group,), required - 1)


def test_adjacent_sentences_merge_without_altering_intervening_whitespace():
    text = "Cobalt sensor calibration is exact.\r\n  Sensor inspection follows.\t"
    group = _group(text)
    result = _build(group, query="sensor calibration inspection")
    assert len(result.fragments) == 1
    assert result.fragments[0].text == text.rstrip()
    _assert_literals(result, (group,), 1400)


def test_same_text_in_different_scopes_keeps_both_identities():
    groups = (_group("Cobalt sensor is calibrated.", scope="one"), _group("Cobalt sensor is calibrated.", scope="two"))
    result = _build(*groups, budget=1800)
    assert {f.address.memory.scope_id for f in result.fragments} == {"one", "two"}
    _assert_literals(result, groups, 1800)


def test_duplicate_candidate_identity_is_deduplicated_but_conflicting_text_is_rejected():
    group = _group("Cobalt sensor is calibrated.")
    result = _build(group, group)
    assert len(result.fragments) == 1
    different = replace(group, hits=(group.hits[0].model_copy(update={"text": "Different contents."}),))
    with pytest.raises(PreparedContextInvariantError, match="memory-entry-text-mismatch"):
        _build(group, different)


@pytest.mark.parametrize(
    "group, error",
    [
        (replace(_group("Sensor evidence."), memory_ref=None), "memory-ref-missing"),
        (replace(_group("Sensor evidence."), scope_id=""), "evidence-scope-missing"),
        (
            replace(_group("Sensor evidence."), memory_ref=MEMORY.model_copy(update={"revision": 4})),
            "memory-ref-mismatch",
        ),
        (_group(*["Sensor evidence."] * 17), "memory-candidate-limit"),
    ],
)
def test_candidate_invariants_are_retained(group, error):
    with pytest.raises(PreparedContextInvariantError, match=error):
        _build(group)


@pytest.mark.parametrize(
    "groups, query", [((), "sensor"), ((_group(" \n\t"),), "sensor"), ((_group("Literal evidence."),), "!!!")]
)
def test_empty_inputs_and_unmatchable_queries_are_safe(groups, query):
    result = _build(*groups, query=query)
    _assert_literals(result, groups, 1400)


def test_oversized_sentence_can_select_a_late_interior_without_prefix_truncation():
    group = _group("filler " * 800 + "cobalt sensor calibrated " * 4 + "filler " * 800)
    result = _build(group, budget=1200)
    assert any("calibrated" in f.text for f in result.fragments)
    assert all(f.start > 1000 for f in result.fragments)
    _assert_literals(result, (group,), 1200)


def test_cjk_without_spaces_remains_literal_and_query_driven():
    group = _group("普通记录。" * 200 + "海洋观测设备已经校准并正常运行。" + "一般说明。" * 200)
    result = _build(group, query="海洋观测设备校准", budget=1200)
    assert any("设备已经校准" in f.text for f in result.fragments)
    _assert_literals(result, (group,), 1200)


def test_default_and_explicitly_disabled_selection_keep_ordinary_prepare():
    group = _group("Ordinary sensor evidence.")
    builder = PreparedContextBuilder()
    for assembly in (None, ContextAssembly()):
        options = {} if assembly is None else {"assembly": assembly}
        request = PrepareContextRequest(query="sensor", **options)
        default = builder.build_scopes_result(request=request, current_scope_id="scope", memory_candidates=(group,))
        explicit = builder.build_scopes_result(
            request=request.model_copy(update={"evidence_selection": False}),
            current_scope_id="scope",
            memory_candidates=(group,),
        )
        assert default == explicit and not default.fragments
        assert "Ordinary sensor evidence." in default.context.content


def test_selection_uses_memory_envelope_even_if_other_presentation_options_are_set():
    group = _group("Cobalt sensor has exact evidence.")
    result = _build(group, include_code=True, assembly=ContextAssembly())
    _assert_literals(result, (group,), 1400)
    assert result.fragments and not result.code_origins


def test_budget_probe_describes_the_actual_selected_output():
    group = _group("Cobalt sensor is calibrated. " * 100)
    request = PrepareContextRequest(query="sensor", max_bytes=1200, evidence_selection=True)
    builder = PreparedContextBuilder()
    result = builder.build_scopes_result(request=request, current_scope_id="scope", memory_candidates=(group,))
    probe = builder.probe_budget(request=request, current_scope_id="scope", memory_candidates=(group,))
    assert probe.delivered_items == len(result.fragments)
    assert probe.unused_bytes == 1200 - result.context.content_bytes


def test_many_budget_boundaries_preserve_literals_for_adversarial_unicode_and_json():
    group = _group('Cobalt sensor "\\\n😀 is calibrated.\n' * 8, "Cobalt sensor 海洋观测 19 degrees. " * 8)
    for budget in range(512, 1801, 17):
        result = _build(group, budget=budget)
        _assert_literals(result, (group,), budget)


def test_result_is_deterministic_at_different_budgets():
    group = _group("Cobalt sensor is calibrated. " + "Plain notes. " * 30 + "Cobalt sensor inspection is complete.")
    for budget in (800, 1200, 1800):
        assert _build(group, budget=budget) == _build(group, budget=budget)


class _LiteralPipeline:
    async def extract(self, request: MemoryCandidateRequest, /):
        return tuple(
            MemoryEntryInput(kind="document", text=s.content, sources=(s,))
            for s in request.sources
            if isinstance(s, ContentSource)
        )


@pytest.mark.asyncio
async def test_real_runtime_prepare_and_citation_readback():
    async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=_LiteralPipeline()) as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(title="Evidence", summary="Literal evidence", idempotency_key="evidence")
        )
        source = "Unrelated records. " * 90 + "The cobalt sensor is calibrated at 37 degrees."
        await runtime.sources.for_scope(scope.scope_id).capture(
            CaptureSource(source_id="doc", content=source, metadata={})
        )
        memory = runtime.memory.for_scope(scope.scope_id)
        while (await memory.flush()).processed:
            pass
        page = await memory.search(SearchMemoryRequest(query="cobalt sensor calibrated", mode="fts"))
        group = PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits)
        result = _build(group, query="cobalt sensor calibrated", budget=1200)
        from powercontext.artifacts import MemoryCitation

        for fragment in result.fragments:
            entry = await memory.get(
                GetMemoryEntryRequest(
                    citation=MemoryCitation(
                        memory_ref=fragment.address.memory.artifact,
                        entry_id=fragment.address.entry_id,
                        entry_version_id=fragment.address.entry_version_id,
                    )
                )
            )
            assert fragment.text == entry.entry.text[fragment.start : fragment.end]
        prepared = await runtime.context.for_scope(scope.scope_id).prepare(
            PrepareContextRequest(query="cobalt sensor calibrated", max_bytes=1200, evidence_selection=True)
        )
        assert prepared.content is not None and "37 degrees" in prepared.content
        assert prepared.content_bytes <= 1200
