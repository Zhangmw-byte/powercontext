# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""CSV field fidelity, identity boundaries, and native Source readback."""

from __future__ import annotations

import csv
import io
import json

import pytest

from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.tables import SHARED_TABLES
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    SourceDefinitionRegistry,
    SourceMaterialization,
    SourceRef,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowInput,
    CSVRowSource,
    csv_row_source_id,
    parse_csv_document,
)


def _document(content, **kwargs):
    return CSVDocumentInput(document_id="表:one", primary_key=" id ", content=content, **kwargs)


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
async def test_all_csv_newlines_preserve_quoted_content_and_column_order(line_ending, bom):
    columns = ("z", " id ", "a", "empty", "unicode")
    values = ('雪, "quoted"\r\nnext\rfinal\n', " 001 ", "000.00", "", "A\u2028B\u2029C\0D")
    output = io.StringIO(newline="")
    # Quote every field: embedded newlines must be protected even when a writer
    # is configured with a different record terminator.
    writer = csv.writer(output, lineterminator=line_ending, quoting=csv.QUOTE_ALL)
    writer.writerow(columns)
    writer.writerow(values)
    (row,) = parse_csv_document(_document(bom + output.getvalue().encode()))
    assert row.columns == columns
    assert row.values == values
    assert row.primary_key_value == " 001 "

    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    source = await registry.resolve(row)
    assert source.materialization is SourceMaterialization.CAPTURED
    assert await registry.read(source) == row
    projection = registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY)
    assert projection["content"] == json.dumps(
        dict(zip(columns, values, strict=True)), ensure_ascii=False, separators=(",", ":")
    )
    assert list(json.loads(projection["content"])) == list(columns)
    assert projection["metadata"]["columns"] == list(columns)


@pytest.mark.parametrize(
    "content",
    [
        b' id ,name\n001,valid\n002,"unterminated',
        b' id ,name\n001,valid\n002,"closed"junk\n',
        b" id ,name\n001,valid\n001,duplicate\n",
        b" id ,name\n001,valid\n002,extra,column\n",
        b" id ,name\n001,valid\n\xff,invalid-encoding\n",
    ],
)
def test_late_document_errors_never_return_a_partial_result(content):
    with pytest.raises(ValueError):
        parse_csv_document(_document(content))


@pytest.mark.parametrize("record", [b'""\n', b" \t\n", b",\n"])
def test_empty_field_records_are_not_treated_as_empty_physical_lines(record):
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="d", primary_key="id", content=b"id\n" + record))
    assert parse_csv_document(CSVDocumentInput(document_id="d", primary_key="id", content=b"id\n\r\n\n")) == ()


def test_header_and_keys_are_exact_strings_not_normalized():
    rows = parse_csv_document(
        CSVDocumentInput(document_id="d", primary_key="id ", content=b"id,id ,value\nx, k,1\ny,k ,true\n")
    )
    assert [row.primary_key_value for row in rows] == [" k", "k "]
    assert rows[0].values == ("x", " k", "1")
    assert rows[1].values == ("y", "k ", "true")


def test_identity_length_is_measured_after_percent_encoding():
    assert len(csv_row_source_id("d", "x" * 250)) == 256
    assert len(csv_row_source_id("d", "中" * 27)) == 249
    for key in ("x" * 251, "中" * 28):
        with pytest.raises(ValueError):
            csv_row_source_id("d", key)
    assert csv_row_source_id("a:b", "c") != csv_row_source_id("a", "b:c")
    assert csv_row_source_id("a%3Ab", "c") != csv_row_source_id("a:b", "c")
    assert csv_row_source_id("a/b", " c ") == "csv:a%2Fb:%20c%20"


@pytest.mark.parametrize(
    "changes",
    [
        {"columns": ("id", "id")},
        {"columns": ("id", " ")},
        {"primary_key": "missing"},
        {"primary_key_value": "different"},
        {"values": ("01",)},
        {"document_id": " d"},
        {"primary_key_value": " ", "values": (" ", "value")},
    ],
)
def test_direct_row_inputs_validate_the_same_row_invariants(changes):
    fields = {
        "document_id": "d",
        "primary_key": "id",
        "primary_key_value": "01",
        "columns": ("id", "value"),
        "values": ("01", "value"),
    }
    with pytest.raises(ValueError):
        CSVRowInput(**(fields | changes))


async def test_captured_source_json_roundtrip_rejects_identity_mismatch():
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    (row,) = parse_csv_document(_document(b" id ,n\n001,value\n"))
    source = await registry.resolve(row)
    assert CSVRowSource.model_validate_json(source.model_dump_json()) == source
    for field in ("name", "source_id"):
        payload = json.loads(source.model_dump_json())
        payload[field] = "csv:wrong:identity"
        with pytest.raises(ValueError):
            CSVRowSource.model_validate_json(json.dumps(payload))


async def test_native_source_persistence_reads_every_original_field_after_reopen(tmp_path):
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    rows = parse_csv_document(_document(' id ,z,a\n001,"机场, east",\n002,"line one\r\nline two",000\n'.encode()))
    originals = [await registry.resolve(row) for row in rows]
    config = SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'csv.db'}")
    repository = SourceRepository(registry)
    async with (
        SQLiteProfile.open(config, tables=SHARED_TABLES) as profile,
        profile.database.transaction() as connection,
    ):
        for source in originals:
            await repository.add(connection, "scope", source)
        replay = await repository.add(connection, "scope", originals[0])
        assert replay.journal_position == 1
        assert await repository.journal_position(connection, "scope") == 2
    async with (
        SQLiteProfile.open(config, tables=SHARED_TABLES) as profile,
        profile.database.transaction() as connection,
    ):
        for row, original in zip(rows, originals, strict=True):
            saved = await repository.get(connection, "scope", SourceRef(source_type="csv-row", source_id=original.name))
            assert isinstance(saved.value, CSVRowSource)
            assert saved.value == original
            assert await registry.read(saved.value) == row
            assert registry.project(saved.value, TEXT_EVIDENCE_PROJECTION_KEY) == registry.project(
                original, TEXT_EVIDENCE_PROJECTION_KEY
            )
