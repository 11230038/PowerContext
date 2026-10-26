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

"""Capture every physical page of an offline PDF as exact Source evidence."""

from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from itertools import pairwise
from urllib.parse import quote

from pydantic import BaseModel
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime import SearchMemoryRequest
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"

_WORD = re.compile(r"[a-z]+|\d+", re.IGNORECASE)
_QUESTION_STOP_WORDS = frozenset({
    "a",
    "about",
    "according",
    "an",
    "and",
    "answer",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "calculate",
    "can",
    "company",
    "define",
    "details",
    "did",
    "do",
    "does",
    "for",
    "from",
    "fy",
    "give",
    "has",
    "have",
    "how",
    "if",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "only",
    "or",
    "perspective",
    "question",
    "relying",
    "report",
    "reported",
    "respond",
    "shown",
    "state",
    "statement",
    "statements",
    "that",
    "the",
    "then",
    "to",
    "use",
    "using",
    "was",
    "were",
    "what",
    "when",
    "which",
    "who",
    "why",
    "with",
    "within",
    "would",
    "year",
})

# Finance questions often name a metric differently from the filing.  These are
# domain vocabulary expansions, not document- or question-specific answers.
_FINANCIAL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "capex": ("capital", "expenditures", "property", "plant", "equipment"),
    "ebitda": ("operating", "income", "depreciation", "amortization"),
    "geographies": ("geographic", "regions", "countries", "international"),
    "geography": ("geographic", "regions", "countries", "international"),
    "lawsuit": ("litigation", "legal", "proceedings"),
    "lawsuits": ("litigation", "legal", "proceedings"),
    "battles": ("litigation", "legal", "proceedings"),
    "restructuring": ("restructuring", "impairment", "charges"),
    "revenue": ("revenues", "sales"),
    "revenues": ("revenue", "sales"),
    "margin": ("income", "revenue", "sales"),
    "cashflow": ("cash", "flows"),
    "debt": ("borrowings", "notes"),
    "inventory": ("inventories",),
    "inventories": ("inventory",),
}


class PDFDocumentInput(BaseModel):
    """A complete offline PDF and its caller-assigned document identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """The extractable text of one one-based physical PDF page."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured page that remains tied to one exact PDF revision."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


def parse_pdf_document(value: PDFDocumentInput, /) -> tuple[PDFPageInput, ...]:
    """Parse all physical pages, failing atomically when any page is unreadable."""

    document_id = _validate_document_id(value.document_id)
    content = bytes(value.content)
    if not content:
        raise ValueError("PDF content must not be empty")  # noqa: TRY003
    digest = hashlib.sha256(content).hexdigest()
    try:
        extracted = _extract_pages(content)
    except Exception as error:
        raise ValueError("PDF could not be parsed completely") from error  # noqa: TRY003
    if not extracted:
        raise ValueError("PDF must contain at least one physical page")  # noqa: TRY003
    return tuple(
        PDFPageInput(
            document_id=document_id,
            document_sha256=digest,
            page_number=page_number,
            text=text,
        )
        for page_number, text in enumerate(extracted, start=1)
    )


def _extract_pages(content: bytes) -> tuple[str, ...]:
    # Real regulatory filings commonly contain harmless cross-reference and
    # metadata defects.  pypdf's tolerant reader still rejects files whose
    # page tree cannot be read, while accepting those real-world documents.
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise ValueError("PDF requires a password")  # noqa: TRY003
    return tuple("" if text is None else text for text in (page.extract_text() for page in reader.pages))


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build a delimiter-safe identity for one page of one exact PDF revision."""

    document_id = _validate_document_id(document_id)
    if not re.fullmatch(r"[0-9a-f]{64}", document_sha256):
        raise ValueError("document_sha256 must be a lowercase SHA-256 digest")  # noqa: TRY003
    if page_number < 1:
        raise ValueError("page_number must be positive")  # noqa: TRY003
    source_id = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(source_id) <= MAX_SOURCE_ID_LENGTH:
        return source_id
    identity = f"{document_id}\0{document_sha256}\0{page_number}".encode()
    return f"pdf-hash:{hashlib.sha256(identity).hexdigest()}"


class PDFPageSourceAdapter:
    """Resolve and read captured PDF page Sources."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose a PDF page through the standard text-evidence projection."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    version=PDF_PAGE_SOURCE_VERSION,
    projections=(PDFPageTextEvidenceProjection(),),
)


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve distinct page citations using deterministic, offline lexical expansion."""

    if limit <= 0 or not question.strip():
        return ()
    query_terms = _query_terms(question)
    focus_queries = _focus_queries(question)
    queries = tuple(dict.fromkeys((*focus_queries, *_search_queries(question, query_terms))))
    candidate_limit = max(32, limit * 4)
    candidates, focused = await _collect_candidates(memory, queries, focus_queries, candidate_limit)
    ranked = sorted(
        candidates.values(),
        key=lambda candidate: (
            -_page_score(question, query_terms, candidate[1], candidate[2]),
            candidate[0].entry_id.encode(),
            candidate[0].entry_version_id.encode(),
        ),
    )
    return _select_citations(ranked, candidates, focused, len(focus_queries), limit)


async def _collect_candidates(memory, queries, focus_queries, candidate_limit):
    candidates: dict[tuple[str, int, str, str], tuple[MemoryCitation, str, float]] = {}
    focused: list[tuple[str, int, str, str]] = []
    for query_rank, query in enumerate(queries, start=1):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=candidate_limit))
        focus_best: tuple[float, tuple[str, int, str, str]] | None = None
        for hit_rank, hit in enumerate(page.hits, start=1):
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            identity = (
                citation.memory_ref.artifact_id,
                citation.memory_ref.revision,
                citation.entry_id,
                citation.entry_version_id,
            )
            reciprocal_rank = 1.0 / (20 + query_rank + hit_rank)
            previous = candidates.get(identity)
            if previous is None:
                candidates[identity] = (citation, hit.text, reciprocal_rank)
            else:
                candidates[identity] = (previous[0], previous[1], previous[2] + reciprocal_rank)
            if query in focus_queries:
                score = _focus_score(query, hit.text, hit_rank)
                if focus_best is None or score > focus_best[0]:
                    focus_best = (score, identity)
        if focus_best is not None:
            focused.append(focus_best[1])
    return candidates, focused


def _select_citations(ranked, candidates, focused, focus_query_count: int, limit: int) -> tuple[MemoryCitation, ...]:
    # A compound financial question can require evidence from two different
    # statements.  Reserve a bounded part of the result for the best hit from
    # each filing-section query, then fill the remainder with the fused rank.
    ordered: list[MemoryCitation] = []
    selected: set[tuple[str, int, str, str]] = set()
    focus_budget = min(focus_query_count, max(1, limit // 3))
    for identity in focused:
        if identity in selected or len(ordered) >= focus_budget:
            continue
        selected.add(identity)
        ordered.append(candidates[identity][0])
    for citation, _text, _score in ranked:
        identity = (
            citation.memory_ref.artifact_id,
            citation.memory_ref.revision,
            citation.entry_id,
            citation.entry_version_id,
        )
        if identity in selected:
            continue
        selected.add(identity)
        ordered.append(citation)
        if len(ordered) == limit:
            break
    return tuple(ordered)


def _validate_document_id(document_id: str) -> str:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    return document_id


def _words(value: str) -> tuple[str, ...]:
    return tuple(match.group(0).lower() for match in _WORD.finditer(value))


def _query_terms(question: str) -> tuple[str, ...]:
    words = _words(question)
    company_terms = {word for word in words if word.endswith("co") or word.endswith("corp")}
    terms = [word for word in words if word not in _QUESTION_STOP_WORDS and word not in company_terms]
    expanded = list(terms)
    for term in terms:
        expanded.extend(_FINANCIAL_SYNONYMS.get(term, ()))
        if term.endswith("ies") and len(term) > 4:
            expanded.append(f"{term[:-3]}y")
        elif term.endswith("s") and len(term) > 4:
            expanded.append(term[:-1])
    return tuple(dict.fromkeys(expanded))


def _search_queries(question: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    original_words = _words(question)
    years = tuple(dict.fromkeys(word for word in original_words if len(word) == 4 and word.isdigit()))
    core = tuple(term for term in terms if term not in years)
    queries: list[str] = [question]
    if terms:
        queries.append(" ".join(terms))
    if core:
        queries.append(" ".join(core))
    for term in core:
        queries.append(term)
    for left, right in pairwise(core):
        queries.append(f"{left} {right}")
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def _focus_queries(question: str) -> tuple[str, ...]:
    """Translate common filing vocabulary into likely section-heading queries."""

    normalized = " ".join(_words(question))
    words = set(normalized.split())
    queries: list[str] = []
    income_terms = {
        "ebit",
        "ebitda",
        "earnings",
        "income",
        "margin",
        "profit",
        "revenue",
        "revenues",
        "sales",
    }
    balance_terms = {
        "assets",
        "equity",
        "inventories",
        "inventory",
        "liabilities",
        "receivables",
    }
    cash_flow_terms = {"capex", "cashflow", "financing", "investing"}
    if (
        "income statement" in normalized
        or "income statements" in normalized
        or "p l" in normalized
        or words.intersection(income_terms)
    ):
        queries.extend(("consolidated statement of income", "operating profit net revenue"))
    if "cash flow" in normalized or "cash flows" in normalized or words.intersection(cash_flow_terms):
        queries.append("consolidated statement of cash flows")
    if "balance sheet" in normalized or words.intersection(balance_terms):
        queries.append("consolidated balance sheet")
    if words.intersection({"legal", "litigation", "lawsuit", "lawsuits", "battles"}):
        queries.append("legal proceedings")
    if words.intersection({"geographies", "geography", "geographic"}):
        queries.extend(("our divisions", "geographic markets operations"))
    if "restructuring" in words:
        queries.append("restructuring and impairment charges")
    if "capex" in words or "capital expenditure" in normalized or "capital expenditures" in normalized:
        queries.append("capital spending")
    return tuple(dict.fromkeys(queries))


def _focus_score(query: str, text: str, hit_rank: int) -> float:
    query_words = _words(query)
    page_words = _words(text)
    normalized_query = " ".join(query_words)
    normalized_page = " ".join(page_words)
    phrase_position = normalized_page.find(normalized_query)
    phrase_score = 100.0 if phrase_position >= 0 else 0.0
    heading_score = 20.0 if 0 <= phrase_position < 250 else 0.0
    coverage = len(set(query_words).intersection(page_words))
    return phrase_score + heading_score + coverage * 5.0 - hit_rank / 100.0


def _page_score(question: str, query_terms: tuple[str, ...], text: str, reciprocal_rank: float) -> float:
    page_words = _words(text)
    if not page_words:
        return reciprocal_rank
    page_counts = Counter(page_words)
    query_counts = Counter(query_terms)
    overlap = sum(min(count, page_counts[term]) for term, count in query_counts.items())
    covered = sum(term in page_counts for term in query_counts)
    density = overlap / (len(page_words) ** 0.5)
    phrase = " ".join(_words(question))
    normalized_text = " ".join(page_words)
    phrase_bonus = 2.0 if phrase and phrase in normalized_text else 0.0
    return covered * 3.0 + overlap + density + phrase_bonus + reciprocal_rank * 8.0


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
