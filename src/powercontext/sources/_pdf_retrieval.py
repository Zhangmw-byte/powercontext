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
    (
        ("customer", "customers", "client", "clients"),
        "customer customers accounted significant portion revenues sales government contracts major",
    ),
    (("cyclical", "cyclicality", "seasonal", "seasonality"), "cyclical cycles economic conditions demand downturn"),
    (
        ("acquisition", "acquisitions", "acquired", "acquire", "acquires"),
        "acquisitions acquisition acquired divestitures business combinations purchase price",
    ),
    (("tax", "taxes"), "effective tax rate provision income taxes before"),
    (("segment", "segments", "categories", "category"), "segment segments revenues business data total"),
    (("products", "product", "services", "sells", "sell"), "products services segments offerings"),
    (("industry", "industries"), "industry business markets products segments"),
    (("growth", "grow", "grew"), "increase decrease change compared prior year percent"),
    (("drove", "drive", "driven", "drivers"), "primarily due increase decrease compared prior year"),
)

_REPORT_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_LEGAL_SUFFIXES = frozenset({"inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "plc"})

# Primary financial statements are recognized by a heading near the top of the
# page plus the line items that define the statement. Headings are matched on
# letters only, because PDF text extraction can split words ("incom e").
_STATEMENT_HEADINGS = (
    ("income", re.compile(r"statements?of(?:consolidated)?(?:income|operations|earnings)|incomestatements?")),
    ("balance", re.compile(r"balancesheets?|statements?of(?:consolidated)?financial(?:position|condition)")),
    ("cash", re.compile(r"statements?of(?:consolidated)?cashflows?|cashflows?statements?")),
)
_STATEMENT_LINE_ITEMS = {
    "income": ((("revenue", "sales", "interestincome"), ("pershare", "netincome", "netearnings", "netloss")), 2),
    "balance": ((("totalassets", "totalcurrentassets", "totalliabilities", "totalcurrentliabilities"),), 1),
    "cash": (
        (
            ("operatingactivities", "netcashfromoperations"),
            ("investingactivities", "netcashusedininvesting"),
            ("financingactivities", "netcashusedinfinancing", "netcashfromfinancing"),
        ),
        2,
    ),
}
_STATEMENT_HEADING_LETTERS = 240
_STATEMENT_NUMERIC_SHARE = 0.25
_STATEMENT_PAGES_PER_KIND = 2
_BUSINESS_HEADING = re.compile(r"^\s*item\s*1\s*[.:]?\s*[-\u2013\u2014]?\s*business\b", re.IGNORECASE | re.MULTILINE)
_ITEM_HEADING = re.compile(r"^\s*item\s*\d+[a-c]?\b", re.IGNORECASE | re.MULTILINE)
_NAVIGATION_ITEMS = 4
_BUSINESS_QUESTION = re.compile(
    r"\b(?:products?|services?|sells?|geograph\w*|regions?|countries|operates?|industry|industries|customers?)\b"
)


class PDFMemory(Protocol):
    """The public scoped Memory operations used by this Source extension."""

    async def list(self, *, include_inactive: bool = False) -> MemoryEntriesPage: ...

    async def search(self, request: SearchMemoryRequest, /) -> MemorySearchPage: ...


@dataclass(frozen=True)
class _Statement:
    kind: str
    heading_position: int
    numeric_share: float


@dataclass(frozen=True)
class _Page:
    record: MemoryEntryRecord
    identity: tuple[str, str]
    document: str
    body: str
    terms: Counter[str]
    statement: _Statement | None
    overview: bool

    @classmethod
    def of(cls, record: MemoryEntryRecord, identity: tuple[str, str], document: str, body: str) -> _Page:
        return cls(record, identity, document, body, Counter(_tokens(body)), _statement(body), _overview(body))


def _stem(word: str) -> str:
    if word.endswith("ies") and len(word) > 5:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    return [_stem(word) for word in _WORD.findall(unicodedata.normalize("NFKC", text).casefold()) if word not in _STOP]


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]+", "", unicodedata.normalize("NFKC", text).casefold())


def _statement(body: str) -> _Statement | None:
    """Recognize an income statement, balance sheet or cash flow statement page."""
    heading = _letters(body[:1500])[:_STATEMENT_HEADING_LETTERS]
    found = [(match.start(), kind) for kind, pattern in _STATEMENT_HEADINGS if (match := pattern.search(heading))]
    if not found:
        return None
    position, kind = min(found)
    words = _WORD.findall(unicodedata.normalize("NFKC", body).casefold())
    numeric_share = sum(word.isdigit() for word in words) / max(1, len(words))
    if numeric_share < _STATEMENT_NUMERIC_SHARE:
        return None
    compact = _letters(body)
    groups, required = _STATEMENT_LINE_ITEMS[kind]
    if sum(any(item in compact for item in group) for group in groups) < required:
        return None
    return _Statement(kind, position, numeric_share)


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
            pages.append(_Page.of(record, identity, document, body))
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


def _primary_statements(pages: list[_Page], documents: list[str]) -> list[_Page]:
    """Return the best-recognized statement pages of each kind for the given reports."""
    candidates: dict[tuple[str, str], list[_Page]] = {}
    for page in pages:
        if page.statement is not None and page.document in documents:
            candidates.setdefault((page.document, page.statement.kind), []).append(page)
    chosen = []
    for document in documents:
        for kind, _ in _STATEMENT_HEADINGS:
            ranked = sorted(
                candidates.get((document, kind), ()),
                key=lambda page: (page.statement.heading_position, -page.statement.numeric_share, page.identity),
            )
            chosen.extend(ranked[:_STATEMENT_PAGES_PER_KIND])
    return chosen


def _overview(body: str) -> bool:
    """Recognize the opening page of a report's business description, not a table of contents."""
    return bool(_BUSINESS_HEADING.search(body)) and len(_ITEM_HEADING.findall(body)) < _NAVIGATION_ITEMS


def _bm25(count: int, length: int, average: float) -> float:
    return count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / max(1.0, average)))


def _rank(pages: list[_Page], question: str, native_ranks: dict[str, int], limit: int) -> list[_Page]:
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
            score += weight * idf[term] * _bm25(page.terms[term], length, average)
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
    ranked = [page for _, page in scored]
    scores = {page.identity: value for value, page in scored}
    reserved = _reserved_pages(pages, ranked, scores, question, limit)
    lexical = [page for page in ranked if page.identity not in reserved][: limit - len(reserved)]
    return sorted([*lexical, *reserved.values()], key=lambda page: (-scores.get(page.identity, 0.0), page.identity))


def _reserved_pages(
    pages: list[_Page], ranked: list[_Page], scores: dict[tuple[str, str], float], question: str, limit: int
) -> dict[tuple[str, str], _Page]:
    """Choose structural pages of the targeted reports that lexical overlap tends to miss.

    FinanceBench-style questions about a report are most often answered from its
    primary statements, even when the question names a derived metric or a
    qualitative property instead of a statement line item. Questions about what a
    company sells, where and to whom are answered in its business description,
    whose opening page names few query terms. Both take a bounded share of the result.
    """
    documents = sorted({page.document for page in pages})
    if len(documents) > 2:
        documents = [ranked[0].document] if ranked else []
    reserved = {page.identity: page for page in _primary_statements(pages, documents)[: limit // 3]}
    if not _BUSINESS_QUESTION.search(question.casefold()):
        return reserved
    for document in documents:
        candidates = [page for page in pages if page.overview and page.document == document]
        if candidates and len(reserved) < limit // 2:
            best = min(candidates, key=lambda page: (-scores.get(page.identity, 0.0), page.identity))
            reserved.setdefault(best.identity, best)
    return reserved


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
    return tuple(page.record.citation for page in _rank(pages, question, native_ranks, limit))
