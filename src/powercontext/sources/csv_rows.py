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

"""Row-level Source capture for offline CSV documents.

Each data record of a CSV document becomes one ``CAPTURED`` Source.  The row
identity is derived from the document identity and the primary key value, so a
row keeps its identity when the document is re-ordered or unrelated fields are
edited.  The standard ``powercontext.text-evidence`` projection exposes the
row as a JSON object that keeps the original header order and field values.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Annotated
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

CSV_ROW_SOURCE_NAME = "csv-row"
CSV_ROW_DEFINITION_VERSION = "1"

_UTF8_BOM = b"\xef\xbb\xbf"
_NonEmptyText = Annotated[str, Field(min_length=1)]


def _reject_blank(field: str, value: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")  # noqa: TRY003
    return value


def _require_document_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    if value != value.strip():
        raise ValueError("document_id must not contain leading or trailing whitespace")  # noqa: TRY003
    return value


def _require_primary_key(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("primary_key must be a non-empty string")  # noqa: TRY003
    return value


def _require_primary_key_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("primary_key_value must be a string")  # noqa: TRY003, TRY004
    return _reject_blank("primary_key_value", value)


def _require_columns_and_values(columns: tuple[str, ...], values: tuple[str, ...]) -> None:
    if not columns:
        raise ValueError("columns must not be empty")  # noqa: TRY003
    if len(columns) != len(values):
        raise ValueError("values must contain one value per column")  # noqa: TRY003
    seen: set[str] = set()
    for column in columns:
        if not isinstance(column, str) or not column or not column.strip():
            raise ValueError("column names must be non-empty and not blank")  # noqa: TRY003
        if column in seen:
            raise ValueError(f"duplicate column name {column!r}")  # noqa: TRY003
        seen.add(column)


class CSVDocumentInput(BaseModel):
    """A complete offline CSV document to capture row by row."""

    document_id: _NonEmptyText
    primary_key: _NonEmptyText
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        return _require_document_id(value)

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, value: str) -> str:
        return _require_primary_key(value)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: bytes) -> bytes:
        if not isinstance(value, (bytes, bytearray)):
            raise ValueError("content must be bytes")  # noqa: TRY003, TRY004
        return bytes(value)


class CSVRowInput(BaseModel):
    """One CSV data record expressed with the original header order."""

    document_id: _NonEmptyText
    primary_key: _NonEmptyText
    primary_key_value: _NonEmptyText
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        return _require_document_id(value)

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, value: str) -> str:
        return _require_primary_key(value)

    @field_validator("primary_key_value")
    @classmethod
    def validate_primary_key_value(cls, value: str) -> str:
        return _require_primary_key_value(value)

    @model_validator(mode="after")
    def validate_row_shape(self) -> CSVRowInput:
        _require_columns_and_values(self.columns, self.values)
        if self.primary_key not in self.columns:
            raise ValueError(f"primary_key {self.primary_key!r} is not a column")  # noqa: TRY003
        return self


class CSVRowSource(Source):
    """Durable identity and original fields of one captured CSV record."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_source_identity(self) -> CSVRowSource:
        _require_document_id(self.document_id)
        _require_primary_key(self.primary_key)
        _require_primary_key_value(self.primary_key_value)
        _require_columns_and_values(self.columns, self.values)
        if self.primary_key not in self.columns:
            raise ValueError(f"primary_key {self.primary_key!r} is not a column")  # noqa: TRY003
        expected_id = csv_row_source_id(self.document_id, self.primary_key_value)
        if self.source_id != expected_id or self.name != expected_id:
            raise ValueError("source identity must match csv_row_source_id(document_id, primary_key_value)")  # noqa: TRY003
        return self


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the stable ``csv:<document>:<primary key value>`` Source identity."""

    document_id = _require_document_id(document_id)
    primary_key_value = _require_primary_key_value(primary_key_value)
    source_id = f"csv:{quote_component(document_id)}:{quote_component(primary_key_value)}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def quote_component(value: str) -> str:
    """Percent-encode one identity component without keeping any delimiter."""

    return quote(value, safe="")


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate a complete CSV document into row inputs.

    The whole document is validated before anything is returned; any encoding,
    CSV syntax or data validation error surfaces as :class:`ValueError`.
    """

    document_id = _require_document_id(value.document_id)
    primary_key = _require_primary_key(value.primary_key)
    content = bytes(value.content)
    if content.startswith(_UTF8_BOM):
        content = content[len(_UTF8_BOM) :]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error  # noqa: TRY003

    records = _read_csv_records(text)
    header = records[0] if records else ()
    _validate_header(header)
    if not primary_key:
        raise ValueError("primary_key must be non-empty")  # noqa: TRY003
    try:
        primary_key_index = header.index(primary_key)
    except ValueError:
        raise ValueError(f"primary_key {primary_key!r} is not a column") from None  # noqa: TRY003

    rows: list[CSVRowInput] = []
    seen_keys: set[str] = set()
    for record in records[1:]:
        if not record:
            # A completely empty physical record is not a data record.
            continue
        if len(record) != len(header):
            raise ValueError("every record must contain exactly one field per column")  # noqa: TRY003
        primary_key_value = record[primary_key_index]
        if not primary_key_value.strip():
            raise ValueError("primary_key_value must not be empty or blank")  # noqa: TRY003
        if primary_key_value in seen_keys:
            raise ValueError(f"duplicate primary_key_value {primary_key_value!r}")  # noqa: TRY003
        seen_keys.add(primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=document_id,
                primary_key=primary_key,
                primary_key_value=primary_key_value,
                columns=tuple(header),
                values=tuple(record),
            )
        )
    return tuple(rows)


def _read_csv_records(text: str) -> list[list[str]]:
    previous_field_limit = csv.field_size_limit(sys.maxsize)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        return list(reader)
    except csv.Error as error:
        raise ValueError(f"CSV content is malformed: {error}") from error  # noqa: TRY003
    finally:
        csv.field_size_limit(previous_field_limit)


def _validate_header(header: list[str]) -> None:
    if not header:
        raise ValueError("CSV content must start with a non-empty header record")  # noqa: TRY003
    seen: set[str] = set()
    for column in header:
        if not column or not column.strip():
            raise ValueError("header column names must be non-empty and not blank")  # noqa: TRY003
        if column in seen:
            raise ValueError(f"duplicate header column name {column!r}")  # noqa: TRY003
        seen.add(column)


def _row_mapping(source: CSVRowSource | CSVRowInput) -> dict[str, str]:
    return dict(zip(source.columns, source.values, strict=True))


class CSVRowTextEvidenceProjection:
    """Expose one CSV row through the standard text-evidence projection."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = _row_mapping(source)
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


class CSVRowSourceAdapter:
    """Resolve and read row-level CSV Source values."""

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


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSVRowSourceAdapter(),
    version=CSV_ROW_DEFINITION_VERSION,
    projections=(CSVRowTextEvidenceProjection(),),
)


__all__ = [
    "CSV_ROW_DEFINITION_VERSION",
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "CSVRowTextEvidenceProjection",
    "csv_row_source_id",
    "parse_csv_document",
]
