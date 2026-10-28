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

"""Captured CSV rows with stable document/key identities and exact text evidence."""

from __future__ import annotations

import csv
import io
import json
from typing import Literal, Self
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)


def _validate_document_id(document_id: str) -> None:
    if not document_id or document_id != document_id.strip():
        raise ValueError("CSV document_id must be nonempty and have no surrounding whitespace")  # noqa: TRY003


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Encode each identity component separately without normalizing either."""

    _validate_document_id(document_id)
    if not primary_key_value.strip():
        raise ValueError("CSV primary key value must not be empty or whitespace only")  # noqa: TRY003
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("CSV Source identity exceeds the Source ID length limit")  # noqa: TRY003
    return identity


def _validate_header(columns: tuple[str, ...], primary_key: str) -> None:
    if not columns or any(not column.strip() for column in columns) or len(set(columns)) != len(columns):
        raise ValueError("CSV header must contain unique nonblank column names")  # noqa: TRY003
    if not primary_key or primary_key not in columns:
        raise ValueError("CSV primary_key must exactly match a column name")  # noqa: TRY003


class CSVDocumentInput(BaseModel):
    """One complete offline UTF-8 CSV document."""

    model_config = ConfigDict(frozen=True, strict=True)

    document_id: str
    primary_key: str
    content: bytes

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        _validate_document_id(self.document_id)
        if not self.primary_key:
            raise ValueError("CSV primary_key must not be empty")  # noqa: TRY003
        return self


class CSVRowInput(BaseModel):
    """One validated row, retaining column order and every original string value."""

    model_config = ConfigDict(frozen=True, strict=True)

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        csv_row_source_id(self.document_id, self.primary_key_value)
        _validate_header(self.columns, self.primary_key)
        if len(self.values) != len(self.columns):
            raise ValueError("CSV row width must match its header")  # noqa: TRY003
        if self.values[self.columns.index(self.primary_key)] != self.primary_key_value:
            raise ValueError("CSV primary key value does not match the row")  # noqa: TRY003
        return self


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Validate the entire document before returning any row.

    ``newline=''`` preserves CR, LF, and CRLF inside quoted fields. Only empty
    records following the header are skipped; quoted empty cells remain data.
    """

    reader = csv.reader(io.StringIO(value.content.decode("utf-8-sig"), newline=""), strict=True)
    rows: list[CSVRowInput] = []
    seen: set[str] = set()
    try:
        columns = tuple(next(reader, ()))
        _validate_header(columns, value.primary_key)
        key_index = columns.index(value.primary_key)
        for fields in reader:
            if not fields:
                continue
            if len(fields) != len(columns):
                raise ValueError("CSV row width must match its header")  # noqa: TRY003
            row = CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=fields[key_index],
                columns=columns,
                values=tuple(fields),
            )
            if row.primary_key_value in seen:
                raise ValueError("CSV primary key values must be unique within a document")  # noqa: TRY003
            seen.add(row.primary_key_value)
            rows.append(row)
    except csv.Error as error:
        raise ValueError(f"Malformed CSV: {error}") from error  # noqa: TRY003
    return tuple(rows)


class CSVRowSource(Source):
    """A captured, immutable original row under its stable Source identity."""

    model_config = ConfigDict(frozen=True, strict=True)

    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_captured_row(self) -> Self:
        row = CSVRowInput(
            document_id=self.document_id,
            primary_key=self.primary_key,
            primary_key_value=self.primary_key_value,
            columns=self.columns,
            values=self.values,
        )
        identity = csv_row_source_id(row.document_id, row.primary_key_value)
        if self.name != identity or self.source_id != identity:
            raise ValueError("CSV Source name and source_id must match its document/key identity")  # noqa: TRY003
        return self


class _CSVRowAdapter:
    input_class: type[CSVRowInput] = CSVRowInput
    name = "csv-row"
    source_class: type[CSVRowSource] = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(name=identity, source_id=identity, **value.model_dump())

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class _CSVRowTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[CSVRowSource] = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
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


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = AdapterSourceDefinition(
    _CSVRowAdapter(), version="1", projections=(_CSVRowTextEvidenceProjection(),)
)

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
