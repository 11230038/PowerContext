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

"""Capture the raw visible events of one Pi session branch as Sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.models import Source, SourceMaterialization

PI_EVENT_SOURCE_NAME = "pi-event"
PI_EVENT_SOURCE_VERSION = "1"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_CONNECTOR_VERSION = "1"
_PI_SESSION_VERSION = 3
_CHECKPOINT_VERSION = 1

_VISIBLE_EVENT_TYPES = frozenset({"message", "compaction", "branch_summary", "custom_message"})


class PiSessionInput(BaseModel):
    """A complete Pi v3 session archive and the branch leaf to follow."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected Pi session branch."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """A captured Pi event that can be used as Artifact evidence."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def parse_pi_session(value: PiSessionInput, /) -> tuple[PiEventInput, ...]:
    """Parse the complete archive and return the selected branch's visible events.

    The archive is validated atomically: any invalid encoding, JSON, identity or
    parent relationship raises ``ValueError`` without returning partial results.
    """

    _, events = _parse_document(value.content, value.leaf_id)
    return events


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable, bounded identity of one Pi event Source."""

    encoded = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(encoded) <= MAX_SOURCE_ID_LENGTH:
        return encoded
    return f"pi-hash:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


class PiEventSourceAdapter:
    """Resolve and read captured Pi event Sources."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one Pi event through the standard text-evidence projection."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    version=PI_EVENT_SOURCE_VERSION,
    projections=(PiEventTextEvidenceProjection(),),
)


class PiSessionConnector:
    """Import only the not-yet-imported visible events of one Pi session branch."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_SESSION_CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        session_id, events = _parse_document(self._path.read_bytes(), self._leaf_id)
        imported = _checkpoint_events(session.checkpoint, session_id)
        pending: list[tuple[PiEventInput, str]] = []
        for event in events:
            digest = _event_digest(session_id, event.record)
            stored = imported.get(event.event_id)
            if stored is not None:
                if stored != digest:
                    raise ValueError(f"Pi event {event.event_id!r} changed after import")  # noqa: TRY003
                continue
            pending.append((event, digest))
        for event, digest in pending:
            outcome = await session.submit(
                pi_event_source_id(session_id, event.event_id),
                PI_EVENT_SOURCE_NAME,
                event,
            )
            if outcome.status is not ConnectorSubmissionStatus.ACCEPTED:
                return ConnectorRunCompletion(
                    status=ConnectorRunStatus.INCOMPLETE,
                    checkpoint=session.checkpoint,
                )
            imported[event.event_id] = digest
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={
                "version": _CHECKPOINT_VERSION,
                "session_id": session_id,
                "events": dict(sorted(imported.items())),
            },
        )


def _parse_document(content: bytes, leaf_id: str | None) -> tuple[str, tuple[PiEventInput, ...]]:
    records = _decode_records(content)
    session_id = _validate_header(records[0])
    nodes = _validate_graph(records[1:])
    order = list(nodes)
    if leaf_id is None:
        if not order:
            return session_id, ()
        leaf_id = order[-1]
    elif not isinstance(leaf_id, str) or leaf_id not in nodes:
        raise ValueError(f"Pi session leaf {leaf_id!r} does not exist")  # noqa: TRY003
    events: list[PiEventInput] = []
    for event_id in _ancestor_chain(nodes, leaf_id):
        event = _visible_event(session_id, nodes[event_id])
        if event is not None:
            events.append(event)
    return session_id, tuple(events)


def _decode_records(content: bytes) -> list[dict[str, JsonValue]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error  # noqa: TRY003
    if text.startswith("\ufeff"):
        text = text[1:]
    records: list[dict[str, JsonValue]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"malformed Pi session JSON: {error}") from error  # noqa: TRY003
        if not isinstance(value, dict):
            raise ValueError("each Pi session record must be a JSON object")  # noqa: TRY003, TRY004
        records.append(value)
    if not records:
        raise ValueError("Pi session archive must start with a session record")  # noqa: TRY003
    return records


def _validate_header(header: dict[str, JsonValue]) -> str:
    if header.get("type") != "session":
        raise ValueError("Pi session archive must start with a session record")  # noqa: TRY003
    version = header.get("version")
    if isinstance(version, bool) or version != _PI_SESSION_VERSION:
        raise ValueError(f"Pi session version must be {_PI_SESSION_VERSION}")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session id must be a non-empty string")  # noqa: TRY003
    return session_id


def _validate_graph(records: list[dict[str, JsonValue]]) -> dict[str, dict[str, JsonValue]]:
    nodes: dict[str, dict[str, JsonValue]] = {}
    for record in records:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("every Pi session record must have a non-empty id")  # noqa: TRY003
        if event_id in nodes:
            raise ValueError(f"duplicate Pi session record id {event_id!r}")  # noqa: TRY003
        if "parentId" not in record:
            raise ValueError(f"Pi session record {event_id!r} must declare parentId")  # noqa: TRY003
        parent_id = record["parentId"]
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in nodes):
            raise ValueError(f"Pi session record {event_id!r} has a missing parent {parent_id!r}")  # noqa: TRY003
        nodes[event_id] = record
    return nodes


def _ancestor_chain(nodes: dict[str, dict[str, JsonValue]], leaf_id: str) -> list[str]:
    chain: list[str] = []
    current: str | None = leaf_id
    while current is not None:
        chain.append(current)
        parent = nodes[current]["parentId"]
        current = parent if isinstance(parent, str) else None
    chain.reverse()
    return chain


def _visible_event(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    event_type = record.get("type")
    if not isinstance(event_type, str) or event_type not in _VISIBLE_EVENT_TYPES:
        return None
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role.strip():
            return None
        body = _message_body(role, message)
    elif event_type == "custom_message":
        role = "custom"
        body = _visible_text(record.get("content"))
    else:
        role = event_type
        summary = record.get("summary")
        body = summary if isinstance(summary, str) else None
    if body is None or not body.strip():
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=str(record["id"]),
        parent_id=record.get("parentId") if isinstance(record.get("parentId"), str) else None,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _message_body(role: str, message: dict[str, JsonValue]) -> str | None:
    if role == "bashExecution":
        command = message.get("command")
        if not isinstance(command, str):
            return None
        output = message.get("output")
        return f"$ {command}\n{output if isinstance(output, str) else ''}"
    if role == "toolResult":
        tool_name = _non_empty_text(message.get("toolName")) or "unknown"
        call_id = _non_empty_text(message.get("toolCallId")) or ""
        text = _visible_text(message.get("content"))
        if text is None:
            return None
        return f"[tool_result {tool_name} {call_id}] {text}"
    return _visible_text(message.get("content"), include_tool_calls=True)


def _visible_text(content: JsonValue, *, include_tool_calls: bool = False) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif include_tool_calls and block_type == "toolCall":
            name = _non_empty_text(block.get("name")) or "unknown"
            call_id = _non_empty_text(block.get("id")) or ""
            arguments = json.dumps(
                block.get("arguments"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            parts.append(f"[tool_call {name} {call_id}] {arguments}")
    if not parts:
        return None
    return "\n".join(parts)


def _non_empty_text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _event_digest(session_id: str, record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(
        {"session_id": session_id, "record": record},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _checkpoint_events(checkpoint: JsonValue, session_id: str) -> dict[str, str]:
    if not isinstance(checkpoint, dict):
        return {}
    if checkpoint.get("version") != _CHECKPOINT_VERSION or checkpoint.get("session_id") != session_id:
        return {}
    events = checkpoint.get("events")
    if not isinstance(events, dict):
        return {}
    return {key: value for key, value in events.items() if isinstance(key, str) and isinstance(value, str)}


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PI_SESSION_CONNECTOR_VERSION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
