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

"""Complete physical PDF pages as immutable captured Sources and exact citations."""

from __future__ import annotations

import io
import json
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypdf import PdfReader
from pypdf.generic import DictionaryObject

from powercontext.artifacts import MemoryCitation
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)
from powercontext.sources._pdf_retrieval import PDFMemory, retrieve_pdf_pages


class PDFDocumentInput(BaseModel):
    """A complete original PDF, never a pre-extracted page selection."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("PDF document_id must contain non-whitespace content")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    """One physical page, including empty pages, under an original-file digest."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    document_id: str
    document_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    page_number: Annotated[int, Field(gt=0)]
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("PDF document_id must contain non-whitespace content")  # noqa: TRY003
        return value


def pdf_page_source_id(value: PDFPageInput) -> str:
    """Name one page of one file revision; long document IDs stay bounded by hashing.

    The hashed document ID and the physical page number remain separable, so a
    scope holding several revisions of a report still knows which stored pages
    are the same physical page.
    """
    document = sha256(json.dumps(value.document_id, ensure_ascii=True).encode("ascii")).hexdigest()
    return f"pdf:{document}:{value.document_sha256}:{value.page_number}"


def _physical_page(source_id: str) -> tuple[str, str]:
    """Return the (hashed document ID, page number) shared by every revision of a page."""
    _, document, _, page = source_id.split(":")
    return document, page


def _open_pdf(content: bytes) -> PdfReader:
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF requires a nonempty password")  # noqa: TRY003
    page_tree = reader.root_object["/Pages"].get_object()
    if not isinstance(page_tree, DictionaryObject) or page_tree.get("/Count") != len(reader.pages):
        raise ValueError("PDF page tree is incomplete")  # noqa: TRY003
    return reader


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page before returning anything; errors are atomic."""
    if not value.content.startswith(b"%PDF-"):
        raise ValueError("PDF content must be a complete PDF file")  # noqa: TRY003
    try:
        reader = _open_pdf(value.content)
        pages = reader.pages
        digest = sha256(value.content).hexdigest()
        result = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=index + 1,
                text=page.extract_text() or "",
            )
            for index, page in enumerate(pages)
        )
    except MemoryError:
        raise
    except Exception as error:
        raise ValueError(f"Unable to fully parse PDF: {error}") from error  # noqa: TRY003
    return result


class PDFPageSource(Source):
    """An exact captured page; revising the original file creates a new identity."""

    model_config = ConfigDict(frozen=True, strict=True)
    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        value = PDFPageInput(
            document_id=self.document_id,
            document_sha256=self.document_sha256,
            page_number=self.page_number,
            text=self.text,
        )
        expected = pdf_page_source_id(value)
        if self.name != expected or self.source_id != expected:
            raise ValueError("PDF Source identity must match its document, digest and physical page")  # noqa: TRY003
        return self


class _PDFPageAdapter:
    input_class = PDFPageInput
    source_class = PDFPageSource
    name = "pdf-page"

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = pdf_page_source_id(value)
        return PDFPageSource(name=identity, source_id=identity, **value.model_dump())

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class _PDFTextProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    _PDFPageAdapter(), version="1", projections=(_PDFTextProjection(),)
)


async def search_pdf_pages(memory: PDFMemory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Search scoped current Memory and return distinct, exact stored-page citations."""
    return await retrieve_pdf_pages(memory, question, limit, _physical_page)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
