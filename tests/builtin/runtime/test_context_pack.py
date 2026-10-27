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

"""Pack integrity, independent reconstruction, and ordinary-prepare compatibility."""

from __future__ import annotations

import base64
import json
import subprocess
import sys

import pytest

from powercontext.builtin.runtime import BuiltinConfig, PrepareContextRequest, open_builtin_runtime
from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)
from powercontext.builtin.scope import ScopeDraft


@pytest.mark.parametrize("size", [4, 5, 7, 16, 512])
def test_utf8_boundary_chunks_are_bounded_deterministic_and_lossless(size):
    text = "a海🙂e\u0301\n\x00\u2028尾" * 50
    pack = ContextPack.from_content(text, chunk_bytes=size)
    assert all(len(item) <= size and item.decode("utf-8") for item in pack.items)
    assert b"".join(pack.items) == text.encode()
    assert pack.to_bytes() == ContextPack.from_content(text.encode(), chunk_bytes=size).to_bytes()
    assert ContextPack.from_bytes(pack.to_bytes()) == pack


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_invalid_chunk_limits_fail_even_for_empty_content(size):
    with pytest.raises(ContextPackError):
        ContextPack.from_content(None, chunk_bytes=size)


@pytest.mark.parametrize("items", [[b"a"], ("a",), (b"\xff",), (b"\xe6", b"\xb5\xb7")])
def test_chunks_must_be_immutable_bytes_and_individually_valid_utf8(items):
    with pytest.raises(ContextPackError):
        ContextPack.build(items)


@pytest.mark.parametrize("items", [(), (b"",), (b"x" * 600,), (b"a",) * 1200])
def test_byte_count_includes_its_own_field_across_size_boundaries(items):
    pack = ContextPack.build(items)
    assert pack.byte_count == len(pack.to_bytes())
    assert json.loads(pack.to_bytes())["byte_count"] == len(pack.to_bytes())
    assert ContextPack.from_bytes(pack.to_bytes()) == pack


@pytest.mark.parametrize("count", [True, 1.5, -1, 0])
def test_decoder_rejects_invalid_or_incorrect_pack_byte_counts(count):
    payload = json.loads(ContextPack.build((b"data",)).to_bytes())
    payload["byte_count"] = count
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize("encoded", ["@@", "YQ", "YQ==\n", "YR==", "_w==", "/w==", 1])
def test_decoder_rejects_invalid_base64_or_utf8(encoded):
    payload = json.loads(ContextPack.build((b"a",)).to_bytes())
    payload["items"] = [encoded]
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(json.dumps(payload).encode())


def test_wire_json_rejects_duplicate_fields_and_non_utf8_encoding():
    pack = ContextPack.build((b"a",))
    raw = pack.to_bytes()
    duplicate = raw.replace(b'"byte_count":', b'"byte_count":0,"byte_count":', 1)
    for invalid in (duplicate, raw.decode().encode("utf-16"), b"[]", b"null", b"not json"):
        with pytest.raises(ContextPackError):
            ContextPack.from_bytes(invalid)


@pytest.mark.parametrize("field", ["schema", "base_digest", "target_digest", "prefix_items", "appended"])
def test_delta_requires_every_field(field):
    base = ContextPack.build((b"a",))
    payload = json.loads(ContextPackDelta.between(base, ContextPack.build((b"a", b"b"))).to_bytes())
    payload.pop(field)
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(json.dumps(payload).encode())


def test_extra_fields_wrong_schema_and_reordered_suffix_fail():
    base = ContextPack.build((b"a",))
    delta = ContextPackDelta.between(base, ContextPack.build((b"a", b"b", b"c")))
    payload = json.loads(delta.to_bytes())
    for changed in ({**payload, "extra": 1}, {**payload, "schema": "unknown"}):
        with pytest.raises(ContextPackError):
            ContextPackDelta.from_bytes(json.dumps(changed).encode())
    reordered = ContextPackDelta(
        delta.base_digest, delta.target_digest, delta.prefix_items, tuple(reversed(delta.appended))
    )
    with pytest.raises(ContextPackError):
        apply_context_pack_delta(base, reordered)


@pytest.mark.parametrize("prefix", [0, 1, 2])
def test_receiver_accepts_any_valid_common_prefix(prefix):
    base = ContextPack.build((b"shared", "海洋".encode(), b"old"))
    target = ContextPack.build((b"shared", "海洋".encode(), b"new"))
    delta = ContextPackDelta(base.digest, target.digest, prefix, target.items[prefix:])
    wire = json.dumps(json.loads(delta.to_bytes()), indent=2).encode()
    assert apply_context_pack_delta(base, ContextPackDelta.from_bytes(wire)) == target


def test_receiver_in_another_process_reconstructs_only_from_wire():
    base = ContextPack.from_content("shared evidence\n" * 80)
    target = ContextPack.from_content("shared evidence\n" * 80 + "新证据\n")
    delta = ContextPackDelta.between(base, target)
    payload = json.dumps({
        "base": base64.b64encode(base.to_bytes()).decode(),
        "delta": base64.b64encode(delta.to_bytes()).decode(),
    }).encode()
    program = """
import base64, json, sys
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
wire = json.load(sys.stdin)
base = ContextPack.from_bytes(base64.b64decode(wire['base']))
delta = ContextPackDelta.from_bytes(base64.b64decode(wire['delta']))
sys.stdout.buffer.write(b''.join(apply_context_pack_delta(base, delta).items))
"""
    result = subprocess.run([sys.executable, "-c", program], input=payload, capture_output=True, check=True)
    assert result.stdout == b"".join(target.items)


async def test_native_prepare_empty_results_and_scope_authorization_are_preserved():
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="Empty", summary="Empty", idempotency_key="pack-empty"))
        context = runtime.context.for_scope(scope.scope_id)
        request = PrepareContextRequest(query="absent")
        ordinary = await context.prepare(request)
        assert ordinary.content is None
        first = await context.prepare_incremental(request)
        assert isinstance(first, ContextPack) and first.items == ()
        previous = ContextPack.from_content("old evidence")
        delta = await context.prepare_incremental(request, base_pack=previous)
        assert isinstance(delta, ContextPackDelta)
        assert apply_context_pack_delta(previous, delta).items == ()
        calls = []

        async def deny(scope_ids):
            calls.append(scope_ids)
            raise PermissionError("denied")

        with pytest.raises(PermissionError):
            await context.prepare_incremental(request, authorize_scopes=deny)
        assert calls == [(scope.scope_id,)]
        with pytest.raises(ContextPackError):
            await context.prepare_incremental(request, base_pack=b"not a pack")
