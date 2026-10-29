# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at https://www.apache.org/licenses/LICENSE-2.0

"""Offline financial vocabulary and scoped lexical ranking over stored PDF pages."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime.models import (
    MemoryEntriesPage,
    MemoryEntryRecord,
    MemorySearchPage,
    SearchMemoryRequest,
)

_WORD = re.compile(r"[a-z]+|\d+")
_STOP = frozenset([
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "of",
    "on",
    "or",
    "our",
    "reported",
    "reports",
    "report",
    "than",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "year",
    "years",
    "fiscal",
    "fy",
    "company",
    "corporation",
    "inc",
    "annual",
    "form",
    "k",
    "answer",
    "respond",
    "question",
    "assuming",
    "perspective",
    "investment",
    "analyst",
    "only",
    "details",
    "shown",
    "give",
    "response",
    "define",
    "calculate",
    "calculated",
    "using",
    "use",
    "relying",
    "state",
    "explicitly",
    "outlined",
    "unadjusted",
    "primarily",
    "any",
    "material",
    "materially",
    "important",
    "ongoing",
    "directly",
    "asof",
    "usd",
    "millions",
    "million",
    "s",
])
# Generic accounting vocabulary: no company, document, question or evidence identifiers.
_EXPANSIONS = (
    (
        ("geography", "geographies", "geographic", "countries", "regions", "geographical"),
        "geographic geography countries international divisions segments regions global business operations "
        "north south latin america europe asia africa middle east pacific domestic",
    ),
    (
        ("legal", "litigation", "lawsuit", "lawsuits", "battles"),
        "legal proceedings litigation lawsuits contingencies commitments settlement",
    ),
    (("restructuring",), "restructuring charges expenses costs"),
    (
        ("cash", "cashflow", "cashflows", "capex", "ebitda", "depreciation", "amortization"),
        "cash flows operating activities depreciation amortization capital expenditures property plant equipment",
    ),
    (("income", "earnings", "profit", "ebitda", "pnl"), "income operations earnings consolidated revenue sales profit"),
    (
        ("balance", "assets", "liabilities", "equity", "liquidity"),
        "balance sheet assets liabilities equity current total",
    ),
    (("revenue", "revenues", "sales"), "revenue revenues sales net"),
    (("dividend", "dividends", "repurchase", "buyback"), "dividends repurchases stock shares common equity"),
    (("debt", "borrowings", "borrowing"), "debt borrowings interest maturity maturities long term current"),
    (
        ("workingcapital", "currentratio", "quickratio", "liquidityratio"),
        "balance sheets current assets cash equivalents inventory inventories receivables current liabilities",
    ),
    (("grossprofit", "grossmargin", "cogs"), "income statements revenue sales cost goods sold gross profit margin"),
    (("returnonassets", "assetturnover"), "income statements net income revenue total assets balance sheets"),
    (("returnonequity",), "net income earnings stockholders shareholders equity balance sheets"),
    (("interestcoverage",), "income statements operating income earnings interest expense"),
    (("research", "development", "r&d"), "research development expenses income operations"),
)

_REPORT_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_LEGAL_SUFFIXES = frozenset({"inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "plc"})


class PDFMemory(Protocol):
    """The public scoped Memory operations used by this Source extension."""

    async def list(self, *, include_inactive: bool = False) -> MemoryEntriesPage: ...

    async def search(self, request: SearchMemoryRequest, /) -> MemorySearchPage: ...


@dataclass(frozen=True)
class _Page:
    record: MemoryEntryRecord
    identity: tuple[str, str]
    document: str
    body: str
    terms: Counter[str]


def _stem(word: str) -> str:
    if word.endswith("ies") and len(word) > 5:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    return [_stem(word) for word in _WORD.findall(unicodedata.normalize("NFKC", text).casefold()) if word not in _STOP]


def _query(question: str) -> dict[str, float]:
    query = dict.fromkeys(_tokens(question), 1.0)
    original = set(_WORD.findall(question.casefold()))
    words = re.findall(r"[a-z]+", question.casefold())
    original.update("".join(words[i : i + width]) for width in (2, 3) for i in range(len(words) - width + 1))
    for triggers, expansion in _EXPANSIONS:
        if original.intersection(triggers):
            for term in _tokens(expansion):
                query.setdefault(term, 0.35)
    return {term: weight * (0.15 if term.isdigit() else 1.0) for term, weight in query.items()}


def _select_reports(pages: list[_Page], question: str) -> list[_Page]:
    """Resolve only company/year information supplied in the query and document IDs.

    Leave the collection intact when IDs do not identify a named report. In a
    multi-report collection, text in another company's report is not a substitute
    for the report explicitly requested by the caller. No company aliases or
    document/page lists are built into this resolver.
    """
    words = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", question).casefold())
    phrases = {"".join(words[i : i + width]) for width in range(1, 9) for i in range(len(words) - width + 1)}
    named = set()
    for document in {page.document for page in pages}:
        year = _REPORT_YEAR.search(document)
        company = document[: year.start()] if year else document
        parts = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", company).casefold())
        while parts and parts[-1] in _LEGAL_SUFFIXES:
            parts.pop()
        alias = "".join(parts)
        if alias and alias in phrases:
            named.add(document)
    if not named:
        return pages
    years = set(_REPORT_YEAR.findall(question))
    dated = {document for document in named if years.intersection(_REPORT_YEAR.findall(document))}
    selected = dated or named
    return [page for page in pages if page.document in selected]


def _pages(records: tuple[MemoryEntryRecord, ...]) -> list[_Page]:
    pages = []
    seen = set()
    for record in records:
        refs = {(ref.source_type, ref.source_id) for ref in record.entry.sources if ref.source_type == "pdf-page"}
        # One citation must locate one page. Synthesized multi-page memories cannot
        # stand in for an exact page-level original and are intentionally excluded.
        if len(refs) != 1:
            continue
        identity = next(iter(refs))
        if identity in seen:
            continue
        seen.add(identity)
        document, _, body = record.entry.text.partition("\n")
        if body.strip():
            pages.append(_Page(record, identity, document, body, Counter(_tokens(body))))
    return pages


def _heading_bonus(question: str, body: str) -> float:
    question = question.casefold()
    heading = " ".join(body[:1000].casefold().split())
    score = 0.0
    if any(word in question for word in ("cash", "ebitda", "capex", "depreciation", "amortization")):
        score += 1.0 if re.search(r"statements? of cash flows", heading) else 0.0
    if any(word in question for word in ("income", "ebitda", "profit", "p&l", "earnings")):
        score += 1.0 if re.search(r"statements? of (?:income|operations|earnings)", heading) else 0.0
    if any(word in question for word in ("legal", "litigation", "lawsuit", "battles")):
        score += 1.0 if re.search(r"legal proceedings|commitments and contingencies|litigation", heading) else 0.0
    if any(word in question for word in ("geograph", "countries", "regions")):
        score += (
            0.8
            if re.search(r"our (?:divisions|business|operations)|item 1\.? business|geographic|segment", heading)
            else 0.0
        )
    # Derived metrics name a calculation, while the actual evidence consists of
    # line items on a statement. Literal mentions of the metric in an overview
    # must not crowd those source statements out of the candidate limit.
    financial = re.sub(r"[^a-z]+", " ", question)
    if re.search(
        r"working capital|current ratio|quick ratio|liquidity ratio|return on (?:assets|equity)|asset turnover",
        financial,
    ):
        score += 1.5 if re.search(r"balance sheets?|statements? of financial (?:position|condition)", heading) else 0.0
    if re.search(r"gross (?:margin|profit)|interest coverage|return on (?:assets|equity)|asset turnover", financial):
        score += 1.0 if re.search(r"statements? of (?:income|operations|earnings)", heading) else 0.0
    if any(word in question for word in ("balance", "assets", "liabilities", "equity")):
        score += 1.0 if re.search(r"balance sheets?|statements? of financial (?:position|condition)", heading) else 0.0
    return score


def _rank(pages: list[_Page], question: str, native_ranks: dict[str, int]) -> list[_Page]:
    pages = _select_reports(pages, question)
    query = _query(question)
    if not query:
        return []
    frequency: Counter[str] = Counter()
    for page in pages:
        frequency.update(page.terms.keys())
    lengths = [sum(page.terms.values()) for page in pages]
    average = sum(lengths) / max(1, len(lengths))
    idf = {term: math.log1p((len(pages) - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in query}
    total_weight = sum(idf[term] * weight for term, weight in query.items())
    scored = []
    raw_query = set(_tokens(question))
    for page, length in zip(pages, lengths, strict=True):
        score = 0.0
        for term, weight in query.items():
            count = page.terms[term]
            score += weight * idf[term] * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / max(1, average)))
        heading_bonus = _heading_bonus(question, page.body)
        if score <= 0 and heading_bonus <= 0:
            continue
        doc_terms = set(_tokens(page.document)) - {"10", "20"}
        name_match = any(term in raw_query and not term.isdigit() for term in doc_terms)
        score += total_weight * (0.2 if name_match else 0.0)
        score += total_weight * 0.4 * heading_bonus
        rank = native_ranks.get(page.record.entry.entry_id)
        score += 0.25 / (1 + rank) if rank is not None else 0.0
        # A dense list of headings followed by a single short page number is
        # navigation, not the statements themselves. Do not penalize the running
        # "Table of Contents" link that many reports repeat on every physical page.
        navigation_rows = sum(
            bool(re.fullmatch(r"[^\d$]{4,}\s+\d{1,3}", line.strip())) for line in page.body.splitlines()[:80]
        )
        if navigation_rows >= 8:
            score *= 0.35
        scored.append((score, page))
    scored.sort(key=lambda value: (-value[0], value[1].identity))
    return [page for _, page in scored]


async def retrieve_pdf_pages(memory: PDFMemory, question: str, limit: int) -> tuple[MemoryCitation, ...]:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("PDF question must be a nonempty string")  # noqa: TRY003
    if type(limit) is not int or limit < 0:
        raise ValueError("PDF result limit must be a nonnegative integer")  # noqa: TRY003
    if limit == 0:
        return ()
    # Listing is scoped and excludes inactive entries. It supplies exact durable
    # citations after restart and avoids FTS admission dropping natural questions.
    # At the supported report scale this scans the current pages once per query;
    # no process-local cache or hidden/stale corpus survives a Memory change.
    current = await memory.list()
    pages = _pages(current.entries)
    if not pages:
        return ()
    found = await memory.search(
        SearchMemoryRequest(query=question.strip(), mode="fts", limit=min(100, max(20, limit * 2)))
    )
    native_ranks = (
        {hit.entry_id: i for i, hit in enumerate(found.hits)} if found.memory_ref == current.memory_ref else {}
    )
    return tuple(page.record.citation for page in _rank(pages, question, native_ranks)[:limit])
