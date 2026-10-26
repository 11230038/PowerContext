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

"""Chunked context packs and prefix-reusing incremental deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

CONTEXT_PACK_SCHEMA = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CONTEXT_PACK_CHUNK_BYTES = 512

_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})
_DIGEST_PREFIX = "sha256:"
_DIGEST_HEX_LENGTH = 64
_BYTE_COUNT_KEY_BYTES = len(',"byte_count":')


class ContextPackError(ValueError):
    """A context pack or delta violated the wire protocol."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One complete context split into ordered byte chunks with a digest."""

    items: tuple[bytes, ...]
    digest: str

    @classmethod
    def build(cls, items: tuple[bytes, ...], /) -> ContextPack:
        """Build a complete pack from already chunked content."""

        validated = _validate_items(items)
        return cls(items=validated, digest=_pack_digest(validated))

    @classmethod
    def from_content(
        cls, content: str | bytes, /, *, chunk_bytes: int = DEFAULT_CONTEXT_PACK_CHUNK_BYTES
    ) -> ContextPack:
        """Split content into deterministic, bounded, valid UTF-8 chunks."""

        return cls.build(_chunk_utf8(content, chunk_bytes))

    @property
    def byte_count(self) -> int:
        """Exact serialized size, including the byte count field itself."""

        return _pack_byte_count(self.items, self.digest)

    def to_bytes(self) -> bytes:
        payload = {
            "schema": CONTEXT_PACK_SCHEMA,
            "items": _encode_items(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        }
        return _canonical_json(payload)

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> ContextPack:
        """Validate and decode one complete pack."""

        payload = _decode_json_object(raw, _PACK_FIELDS)
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("unsupported context pack schema")  # noqa: TRY003
        items = _decode_items(payload["items"])
        digest = _require_digest(payload["digest"])
        if digest != _pack_digest(items):
            raise ContextPackError("context pack digest does not match its items")  # noqa: TRY003
        byte_count = _require_integer(payload["byte_count"], "byte_count")
        if byte_count != len(raw):
            raise ContextPackError("context pack byte count does not match its payload")  # noqa: TRY003
        return cls(items=items, digest=digest)


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """The reusable prefix of one pack plus the suffix needed for the next."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        """Carry the longest common item prefix and the remaining target items."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta endpoints must be ContextPacks")  # noqa: TRY003
        prefix = 0
        for base_item, target_item in zip(base.items, target.items, strict=False):
            if base_item != target_item:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @property
    def byte_count(self) -> int:
        """Exact serialized size of this delta."""

        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _canonical_json({
            "schema": CONTEXT_PACK_DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> ContextPackDelta:
        """Validate and decode one delta payload."""

        payload = _decode_json_object(raw, _DELTA_FIELDS)
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("unsupported context pack delta schema")  # noqa: TRY003
        return cls(
            base_digest=_require_digest(payload["base_digest"]),
            target_digest=_require_digest(payload["target_digest"]),
            prefix_items=_require_integer(payload["prefix_items"], "prefix_items"),
            appended=_decode_items(payload["appended"]),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Rebuild the target pack from one base pack and one validated delta."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta application requires a ContextPack and a ContextPackDelta")  # noqa: TRY003
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the supplied base pack")  # noqa: TRY003
    if delta.prefix_items < 0 or delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix is outside the base pack")  # noqa: TRY003
    target_items = base.items[: delta.prefix_items] + delta.appended
    try:
        target = ContextPack.build(target_items)
    except ContextPackError as error:
        raise ContextPackError("delta payload is not a valid context pack") from error  # noqa: TRY003
    if target.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")  # noqa: TRY003
    return target


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": CONTEXT_PACK_SCHEMA, "items": _encode_items(items)}
    return _DIGEST_PREFIX + hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def _pack_byte_count(items: tuple[bytes, ...], digest: str) -> int:
    unsigned = {"schema": CONTEXT_PACK_SCHEMA, "items": _encode_items(items), "digest": digest}
    base_length = len(_canonical_json(unsigned)) + _BYTE_COUNT_KEY_BYTES
    digits = 1
    while True:
        total = base_length + digits
        resolved = len(str(total))
        if resolved == digits:
            return total
        digits = resolved


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _validate_items(items: object) -> tuple[bytes, ...]:
    if not isinstance(items, (tuple, list)):
        raise ContextPackError("context pack items must be a sequence of byte chunks")  # noqa: TRY003
    validated = tuple(items)
    if not all(isinstance(item, bytes) for item in validated):
        raise ContextPackError("context pack items must be byte chunks")  # noqa: TRY003
    return validated


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("encoded items must be a list")  # noqa: TRY003
    decoded: list[bytes] = []
    for encoded in value:
        if not isinstance(encoded, str):
            raise ContextPackError("encoded items must be Base64 strings")  # noqa: TRY003
        try:
            chunk = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as error:
            raise ContextPackError("encoded item is not valid Base64") from error  # noqa: TRY003
        if base64.b64encode(chunk).decode("ascii") != encoded:
            raise ContextPackError("encoded item is not canonical Base64")  # noqa: TRY003
        decoded.append(chunk)
    return tuple(decoded)


def _decode_json_object(raw: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, (bytes, bytearray)):
        raise ContextPackError("context pack payload must be bytes")  # noqa: TRY003
    try:
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("context pack payload must be valid UTF-8 JSON") from error  # noqa: TRY003
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ContextPackError("context pack payload must contain exactly the protocol fields")  # noqa: TRY003
    return payload


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX):
        raise ContextPackError("digest must use the sha256:<hex> form")  # noqa: TRY003
    hexadecimal = value.removeprefix(_DIGEST_PREFIX)
    if len(hexadecimal) != _DIGEST_HEX_LENGTH or hexadecimal != hexadecimal.lower():
        raise ContextPackError("digest must use the sha256:<hex> form")  # noqa: TRY003
    try:
        int(hexadecimal, 16)
    except ValueError as error:
        raise ContextPackError("digest must use the sha256:<hex> form") from error  # noqa: TRY003
    return value


def _require_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContextPackError(f"{field} must be a non-negative integer")  # noqa: TRY003
    return value


def _chunk_utf8(content: str | bytes, chunk_bytes: int) -> tuple[bytes, ...]:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("context content must be valid UTF-8") from error  # noqa: TRY003
    if not isinstance(content, str):
        raise ContextPackError("context content must be text")  # noqa: TRY003
    if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes < 1:
        raise ContextPackError("chunk_bytes must be a positive integer")  # noqa: TRY003
    chunks: list[bytes] = []
    buffer: list[str] = []
    size = 0
    for character in content:
        width = len(character.encode("utf-8"))
        if width > chunk_bytes:
            raise ContextPackError("chunk_bytes cannot hold one character")  # noqa: TRY003
        if size + width > chunk_bytes:
            chunks.append("".join(buffer).encode("utf-8"))
            buffer = []
            size = 0
        buffer.append(character)
        size += width
    if buffer:
        chunks.append("".join(buffer).encode("utf-8"))
    return tuple(chunks)


__all__ = [
    "CONTEXT_PACK_DELTA_SCHEMA",
    "CONTEXT_PACK_SCHEMA",
    "DEFAULT_CONTEXT_PACK_CHUNK_BYTES",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
