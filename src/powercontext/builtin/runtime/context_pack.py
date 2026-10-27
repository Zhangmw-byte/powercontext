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

"""Self-contained v1 context packs and verified prefix-reuse deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """A context pack, delta, or UTF-8 boundary violates the v1 protocol."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _check_items(items: tuple[bytes, ...]) -> None:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("Context chunks must be a tuple of bytes")  # noqa: TRY003
    try:
        for item in items:
            item.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContextPackError("Each context chunk must be valid UTF-8") from error  # noqa: TRY003


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ContextPackError("Wire chunks must be an array of Base64 strings")  # noqa: TRY003
    items = []
    for value in values:
        try:
            item = base64.b64decode(value.encode("ascii"), validate=True)
        except (ValueError, binascii.Error) as error:
            raise ContextPackError("Invalid Base64 context chunk") from error  # noqa: TRY003
        if base64.b64encode(item).decode("ascii") != value:
            raise ContextPackError("Context chunks require canonical standard Base64")  # noqa: TRY003
        items.append(item)
    result = tuple(items)
    _check_items(result)
    return result


def _check_digest(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ContextPackError("Invalid sha256 context digest")  # noqa: TRY003


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("Duplicate context wire field")  # noqa: TRY003
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ContextPackError(f"Non-JSON constant: {value}")  # noqa: TRY003


def _read_payload(data: bytes, schema: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise ContextPackError("Context wire input must be bytes")  # noqa: TRY003
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ContextPackError("Invalid UTF-8 context JSON") from error  # noqa: TRY003
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != schema:
        raise ContextPackError("Invalid context wire fields or schema")  # noqa: TRY003
    return value


@dataclass(frozen=True, slots=True)
class ContextPack:
    """An immutable, independently serializable sequence of UTF-8 chunks."""

    items: tuple[bytes, ...]
    digest: str = field(init=False)
    byte_count: int = field(init=False)

    def __post_init__(self) -> None:
        _check_items(self.items)
        unsigned = {"schema": _PACK_SCHEMA, "items": _encode_items(self.items)}
        digest = "sha256:" + hashlib.sha256(_json_bytes(unsigned)).hexdigest()
        count = 0
        while True:
            measured = len(_json_bytes({**unsigned, "digest": digest, "byte_count": count}))
            if measured == count:
                break
            count = measured
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "byte_count", count)

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        return cls(items)

    @classmethod
    def from_content(cls, content: str | bytes | None, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")  # noqa: TRY003
        try:
            if content is None:
                raw = b""
            elif isinstance(content, str):
                raw = content.encode("utf-8")
            elif isinstance(content, bytes):
                raw = content
            else:
                raise ContextPackError("Context content must be text, bytes, or None")  # noqa: TRY003
            raw.decode("utf-8")
        except UnicodeError as error:
            raise ContextPackError("Context content must be valid UTF-8") from error  # noqa: TRY003
        chunks = []
        offset = 0
        while offset < len(raw):
            end = min(offset + chunk_bytes, len(raw))
            while end < len(raw) and end > offset and raw[end] & 0xC0 == 0x80:
                end -= 1
            if end == offset:
                raise ContextPackError("A UTF-8 character exceeds chunk_bytes")  # noqa: TRY003
            chunks.append(raw[offset:end])
            offset = end
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        return _json_bytes({
            "schema": _PACK_SCHEMA,
            "items": _encode_items(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        value = _read_payload(data, _PACK_SCHEMA, {"schema", "items", "digest", "byte_count"})
        _check_digest(value["digest"])
        if type(value["byte_count"]) is not int or value["byte_count"] < 0:
            raise ContextPackError("Pack byte_count must be a non-negative integer")  # noqa: TRY003
        pack = cls.build(_decode_items(value["items"]))
        if value["digest"] != pack.digest or value["byte_count"] != pack.byte_count:
            raise ContextPackError("Context pack digest or byte_count mismatch")  # noqa: TRY003
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A verified base identity, retained chunk prefix, and target suffix."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _check_digest(self.base_digest)
        _check_digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("Delta prefix_items must be a non-negative integer")  # noqa: TRY003
        _check_items(self.appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("Delta requires complete base and target packs")  # noqa: TRY003
        prefix = 0
        for old, new in zip(base.items, target.items, strict=False):
            if old != new:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _json_bytes({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        value = _read_payload(
            data, _DELTA_SCHEMA, {"schema", "base_digest", "target_digest", "prefix_items", "appended"}
        )
        return cls(
            value["base_digest"], value["target_digest"], value["prefix_items"], _decode_items(value["appended"])
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild exclusively from the supplied base and delta, verifying both IDs."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("Applying a delta requires a full base pack and delta")  # noqa: TRY003
    if base.digest != delta.base_digest:
        raise ContextPackError("Context delta base digest mismatch")  # noqa: TRY003
    if delta.prefix_items > len(base.items):
        raise ContextPackError("Context delta prefix exceeds the base")  # noqa: TRY003
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("Context delta target digest mismatch")  # noqa: TRY003
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
