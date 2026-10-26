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

"""Capture offline CSV records as one stable Source per data row."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

CSV_ROW_SOURCE_NAME = "csv-row"
CSV_ROW_SOURCE_VERSION = "1"


class CSVDocumentInput(BaseModel):
    """A complete offline CSV document and the primary key column it uses."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One data row identified by its document and primary key value."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """A captured CSV row that can be used as Artifact evidence."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate a complete CSV document before returning any row.

    Header names, field values and primary key values are preserved exactly as
    written; only a leading UTF-8 BOM is removed.
    """

    document_id = _validate_document_id(value.document_id)
    _validate_primary_key(value.primary_key)
    text = _decode_document(value.content)
    records = _read_records(text)
    if not records:
        raise ValueError("CSV document must contain a header record")  # noqa: TRY003
    header = records[0]
    _validate_header(header)
    if value.primary_key not in header:
        raise ValueError(f"primary key {value.primary_key!r} is not a header column")  # noqa: TRY003
    key_index = header.index(value.primary_key)
    columns = tuple(header)
    rows: list[CSVRowInput] = []
    seen: set[str] = set()
    for record in records[1:]:
        if not record:
            continue
        if len(record) != len(header):
            raise ValueError("CSV record width does not match the header")  # noqa: TRY003
        primary_key_value = record[key_index]
        if not primary_key_value.strip():
            raise ValueError("primary key value must not be blank")  # noqa: TRY003
        if primary_key_value in seen:
            raise ValueError(f"duplicate primary key value {primary_key_value!r}")  # noqa: TRY003
        seen.add(primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=document_id,
                primary_key=value.primary_key,
                primary_key_value=primary_key_value,
                columns=columns,
                values=tuple(record),
            )
        )
    return tuple(rows)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the delimiter-safe identity of one CSV row Source."""

    document_id = _validate_document_id(document_id)
    if not primary_key_value.strip():
        raise ValueError("primary key value must not be blank")  # noqa: TRY003
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


class CSVRowSourceAdapter:
    """Resolve and read captured CSV row Sources."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Expose one CSV row through the standard text-evidence projection."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


def _validate_document_id(document_id: str) -> str:
    if not document_id:
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    if document_id != document_id.strip():
        raise ValueError("document_id must not contain leading or trailing whitespace")  # noqa: TRY003
    return document_id


def _validate_primary_key(primary_key: str) -> None:
    if not primary_key.strip():
        raise ValueError("primary_key must be a non-empty string")  # noqa: TRY003


def _decode_document(content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error  # noqa: TRY003
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def _read_records(text: str) -> list[list[str]]:
    try:
        return list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise ValueError(f"malformed CSV content: {error}") from error  # noqa: TRY003


def _validate_header(header: list[str]) -> None:
    if not header:
        raise ValueError("CSV header must contain at least one column")  # noqa: TRY003
    seen: set[str] = set()
    for name in header:
        if not name.strip():
            raise ValueError("CSV header columns must not be blank")  # noqa: TRY003
        if name in seen:
            raise ValueError(f"duplicate CSV header column {name!r}")  # noqa: TRY003
        seen.add(name)


CSV_ROW_SOURCE_ADAPTER = CSVRowSourceAdapter()
CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSV_ROW_SOURCE_ADAPTER,
    version=CSV_ROW_SOURCE_VERSION,
    projections=(CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
