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
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from math import log
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
    "after",
    "all",
    "also",
    "an",
    "and",
    "annual",
    "answer",
    "any",
    "address",
    "approximately",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "between",
    "both",
    "but",
    "by",
    "calculate",
    "can",
    "company",
    "compute",
    "could",
    "define",
    "detail",
    "details",
    "did",
    "do",
    "does",
    "during",
    "each",
    "either",
    "explain",
    "explanation",
    "fiscal",
    "for",
    "from",
    "fy",
    "give",
    "given",
    "has",
    "have",
    "having",
    "how",
    "if",
    "in",
    "include",
    "including",
    "into",
    "is",
    "it",
    "its",
    "like",
    "may",
    "more",
    "most",
    "much",
    "must",
    "not",
    "of",
    "on",
    "only",
    "or",
    "other",
    "our",
    "over",
    "per",
    "perspective",
    "please",
    "provide",
    "provided",
    "question",
    "relying",
    "report",
    "reported",
    "respond",
    "response",
    "round",
    "say",
    "show",
    "shown",
    "state",
    "statement",
    "statements",
    "such",
    "tell",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "this",
    "those",
    "to",
    "under",
    "use",
    "used",
    "using",
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
    "within",
    "would",
    "year",
    "years",
    "your",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "decimal",
    "decimals",
    "place",
    "places",
    "line",
    "lines",
    "item",
    "items",
    "information",
    "data",
    "following",
    "respective",
    "respectively",
    "defined",
    "definition",
    "percent",
    "percentage",
    "unit",
    "units",
    "yoy",
})

# Finance questions often name a metric differently from the filing.  These are
# domain vocabulary expansions, not document- or question-specific answers.
_FINANCIAL_SYNONYMS: dict[str, tuple[str, ...]] = {
    # Income statement
    "revenue": ("revenues", "sales", "turnover"),
    "revenues": ("revenue", "sales", "turnover"),
    "sales": ("revenue", "revenues", "turnover"),
    "turnover": ("revenue", "revenues", "sales"),
    "income": ("earnings", "profit", "profits"),
    "earnings": ("income", "profit"),
    "profit": ("income", "earnings"),
    "margin": ("profit", "income", "sales", "revenue"),
    "margins": ("profit", "income", "sales", "revenue"),
    "ebitda": ("operating", "income", "depreciation", "amortization"),
    "ebit": ("operating", "income"),
    "eps": ("earnings", "share", "diluted"),
    "cogs": ("cost", "sales", "goods", "sold"),
    # Balance sheet
    "asset": ("assets",),
    "assets": ("asset",),
    "liability": ("liabilities", "obligations"),
    "liabilities": ("liability", "obligations"),
    "equity": ("equities", "stockholders", "shareholders"),
    "inventory": ("inventories",),
    "inventories": ("inventory",),
    "receivable": ("receivables", "accounts"),
    "receivables": ("receivable", "accounts"),
    "payable": ("payables", "accounts"),
    "payables": ("payable", "accounts"),
    "debt": ("borrowings", "notes", "obligations"),
    "borrowings": ("debt", "notes"),
    "liquidity": ("quick", "current", "ratio", "cash"),
    "quick": ("liquidity", "current", "assets", "liabilities"),
    "cash": ("cashflow", "equivalents", "marketable", "securities"),
    # Cash flow
    "capex": ("capital", "expenditures", "property", "plant", "equipment"),
    "capital": ("capex", "expenditures", "property", "plant", "equipment"),
    "expenditure": ("capex", "capital", "spending"),
    "expenditures": ("capex", "capital", "spending"),
    "depreciation": ("amortization", "depletion"),
    "amortization": ("depreciation",),
    "repurchase": ("buyback", "repurchases", "shares"),
    "buyback": ("repurchase", "repurchases", "shares"),
    # Segment, geography, and business descriptions
    "geography": ("geographic", "geographies", "regions", "countries", "international", "global", "worldwide"),
    "geographies": ("geographic", "geography", "regions", "countries", "international", "global", "worldwide"),
    "geographic": ("geography", "geographies", "regions", "countries", "international", "global", "worldwide"),
    "region": ("regions", "geographic", "international"),
    "regions": ("region", "geographic", "international"),
    "segment": ("segments", "division", "divisions", "business"),
    "segments": ("segment", "division", "divisions", "business"),
    "division": ("segment", "segments", "business"),
    "divisions": ("segment", "segments", "business"),
    "acquisition": ("acquired", "acquisitions", "merger", "mergers", "divestiture", "divestitures"),
    "acquisitions": ("acquisition", "acquired", "merger", "mergers", "divestiture", "divestitures"),
    "merger": ("acquisition", "acquisitions", "divestiture"),
    "divestiture": ("divestitures", "acquisition", "acquisitions"),
    "product": ("products", "offering", "offerings"),
    "products": ("product", "offering", "offerings"),
    "service": ("services", "offering", "offerings"),
    "services": ("service", "offering", "offerings"),
    "customer": (
        "customers",
        "client",
        "clients",
        "purchasers",
        "airlines",
        "airline",
        "government",
        "contract",
        "contracts",
        "defense",
        "commercial",
    ),
    "customers": (
        "customer",
        "client",
        "clients",
        "purchasers",
        "airlines",
        "airline",
        "government",
        "contract",
        "contracts",
        "defense",
        "commercial",
    ),
    "client": ("customers", "customer"),
    "clients": ("customers", "customer"),
    "cyclical": ("cyclicality", "cycle", "economic"),
    "cyclicality": ("cyclical", "cycle", "economic"),
    "production": ("manufacturing", "output", "deliveries"),
    "employee": ("employees", "headcount", "personnel"),
    "employees": ("employee", "headcount", "personnel"),
    # Legal and risk
    "lawsuit": ("litigation", "legal", "proceedings", "claim"),
    "lawsuits": ("litigation", "legal", "proceedings", "claims"),
    "litigation": ("lawsuit", "lawsuits", "legal", "proceedings"),
    "legal": ("litigation", "lawsuit", "proceedings", "regulatory"),
    "risk": ("risks", "uncertainty", "uncertainties"),
    "risks": ("risk", "uncertainty", "uncertainties"),
    "restructuring": ("impairment", "charges", "severance"),
    "impairment": ("restructuring", "charges", "write"),
}

# Suffix stripping makes question vocabulary meet the inflected forms used in
# filings ("geographies"/"geographic", "operates"/"operations").  It is applied
# identically to questions and pages, so only consistency matters.
_STEM_SUFFIXES = (
    "ational",
    "ization",
    "ation",
    "ition",
    "tion",
    "sion",
    "ment",
    "ness",
    "ical",
    "ity",
    "ies",
    "ing",
    "edly",
    "ed",
    "izing",
    "izes",
    "ized",
    "ize",
    "ly",
    "es",
    "er",
    "al",
    "ive",
    "ous",
    "ic",
    "y",
    "at",
    "e",
    "s",
)
_STEM_ALIASES = {
    "acqui": "acquir",
    "acquis": "acquir",
    "distribu": "distrib",
    "divestit": "divest",
    "divestitur": "divest",
    "percentag": "percent",
    "produc": "product",
    "regulator": "regul",
    "reten": "retain",
    "uncertaint": "uncertain",
}

# Generic filing-section vocabulary used to widen retrieval for an intent.
_INTENT_QUERIES: dict[str, tuple[str, ...]] = {
    "income": (
        "consolidated statements of income",
        "consolidated statements of operations",
        "statements of operations",
        "total revenues",
        "net sales",
        "gross profit",
        "operating income",
        "cost of sales",
        "cost of goods sold",
        "income before income taxes",
        "income tax expense",
        "net income",
        "earnings per share",
    ),
    "balance": (
        "consolidated balance sheets",
        "balance sheet",
        "total current assets",
        "total current liabilities",
        "cash and cash equivalents",
        "marketable securities",
        "accounts receivable",
        "accounts payable",
        "inventories",
        "total assets",
        "total liabilities",
        "stockholders equity",
        "working capital",
    ),
    "cashflow": (
        "consolidated statements of cash flows",
        "cash flows from operating activities",
        "cash flows from investing activities",
        "cash flows from financing activities",
        "capital expenditures",
        "depreciation and amortization",
        "property plant and equipment",
    ),
    "segment": (
        "business segment",
        "business segments",
        "reportable segments",
        "segment data",
        "segment information",
        "summary of business segment data",
        "sales and operating income",
        "revenues by segment",
        "sales by segment",
        "geographic markets",
        "geographic regions",
        "international operations",
    ),
    "business": (
        "item 1 business",
        "company overview",
        "products and services",
        "our products",
        "our services",
        "our customers",
        "significant customers",
        "customer concentration",
        "one customer accounted",
        "limited number of customers",
        "significant portion of our revenues",
        "substantial portion of our revenue",
        "government contracts",
    ),
    "legal": (
        "legal proceedings",
        "item 3 legal proceedings",
        "litigation",
        "claims and litigation",
    ),
    "risk": (
        "risk factors",
        "item 1a risk factors",
        "risks related to our business",
    ),
}

# Metric names imply where in the filing their inputs live.
_METRIC_QUERIES: dict[str, tuple[str, ...]] = {
    "quick ratio": (
        "cash and cash equivalents",
        "marketable securities",
        "accounts receivable",
        "total current assets",
        "total current liabilities",
    ),
    "current ratio": (
        "total current assets",
        "total current liabilities",
    ),
    "days payable outstanding": (
        "accounts payable",
        "cost of sales",
        "cost of goods sold",
        "inventories",
        "days payable outstanding",
    ),
    "dpo": (
        "accounts payable",
        "cost of sales",
        "cost of goods sold",
        "inventories",
        "days payable outstanding",
    ),
    "days sales outstanding": (
        "accounts receivable",
        "net sales",
        "days sales outstanding",
    ),
    "days inventory outstanding": (
        "inventories",
        "cost of sales",
        "days inventory outstanding",
    ),
    "gross margin": (
        "gross profit",
        "net sales",
        "cost of sales",
    ),
    "operating margin": (
        "operating income",
        "total revenues",
        "net sales",
    ),
    "effective tax rate": (
        "income before income taxes",
        "income tax expense",
        "effective tax rate",
    ),
    "capital expenditures": (
        "capital expenditures",
        "property plant and equipment",
        "cash flows from investing activities",
    ),
    "working capital": (
        "total current assets",
        "total current liabilities",
        "inventories",
        "accounts receivable",
        "accounts payable",
    ),
    "customer concentration": (
        "significant customers",
        "one customer accounted",
        "customer accounted",
        "limited number of customers",
    ),
    "primary customers": (
        "significant customers",
        "major customers",
        "limited number of customers",
        "commercial airlines",
        "government contracts",
        "u.s. government",
        "united states government",
        "defense contracts",
    ),
    "major customers": (
        "significant customers",
        "primary customers",
        "limited number of customers",
        "commercial airlines",
        "government contracts",
        "u.s. government",
        "united states government",
        "defense contracts",
    ),
    "capital intensive": (
        "property plant and equipment",
        "capital expenditures",
        "total assets",
        "net sales",
        "cost of sales",
        "cash flows from operating activities",
    ),
}

_INCOME_HINTS = frozenset({
    "cost",
    "earn",
    "ebit",
    "ebitda",
    "eps",
    "expens",
    "gross",
    "income",
    "incom",
    "margin",
    "net",
    "profit",
    "revenu",
    "sale",
    "tax",
})
_BALANCE_HINTS = frozenset({
    "asset",
    "borrow",
    "capit",
    "cash",
    "current",
    "debt",
    "equit",
    "inventor",
    "liabil",
    "liquid",
    "payabl",
    "propert",
    "quick",
    "receivabl",
})
_CASHFLOW_HINTS = frozenset({
    "amort",
    "buyback",
    "capex",
    "capit",
    "cashflow",
    "depreci",
    "dividend",
    "expenditur",
    "financ",
    "invest",
    "repurchas",
})
_SEGMENT_HINTS = frozenset({
    "acquir",
    "categor",
    "countr",
    "divest",
    "division",
    "geograph",
    "intern",
    "merg",
    "region",
    "segment",
})
_BUSINESS_HINTS = frozenset({
    "busi",
    "client",
    "compet",
    "competit",
    "custom",
    "cycl",
    "emplo",
    "oper",
    "product",
    "serv",
    "suppli",
})
_LEGAL_HINTS = frozenset({"claim", "legal", "litig", "proc", "regul"})
_RISK_HINTS = frozenset({"cybersecur", "infl", "risk", "uncertain", "volatil"})

# Section intents lift a page type; business sections partly satisfy a segment
# question because geography is usually described alongside the business.
_TYPE_INTENT: dict[str, tuple[tuple[str, float], ...]] = {
    "income": (("income", 1.0),),
    "balance": (("balance", 1.0),),
    "cashflow": (("cashflow", 1.0),),
    "segment": (("segment", 1.0), ("geography", 0.8), ("business", 0.4)),
    "business": (("business", 1.0), ("geography", 0.5), ("risk", 0.5), ("segment", 0.3)),
    "legal": (("legal", 1.0),),
    "risk": (("risk", 1.0),),
}

_INCOME_HEADINGS = (
    ("consolidated", "statement", "of", "income"),
    ("consolidated", "statements", "of", "income"),
    ("consolidated", "statement", "of", "operations"),
    ("consolidated", "statements", "of", "operations"),
    ("consolidated", "statements", "of", "earnings"),
    ("statement", "of", "income"),
    ("statements", "of", "income"),
    ("statement", "of", "operations"),
    ("statements", "of", "operations"),
    ("statement", "of", "earnings"),
    ("statements", "of", "earnings"),
)
_BALANCE_HEADINGS = (
    ("consolidated", "balance", "sheet"),
    ("consolidated", "balance", "sheets"),
    ("balance", "sheet"),
    ("balance", "sheets"),
)
_CASHFLOW_HEADINGS = (
    ("consolidated", "statement", "of", "cash", "flows"),
    ("consolidated", "statements", "of", "cash", "flows"),
    ("statement", "of", "cash", "flows"),
    ("statements", "of", "cash", "flows"),
)
_SEGMENT_HEADINGS = (
    ("business", "segment"),
    ("business", "segments"),
    ("segment", "data"),
    ("segment", "information"),
    ("reportable", "segments"),
    ("sales", "and", "operating", "income"),
)
_BUSINESS_HEADINGS = (
    ("item", "1", "business"),
    ("company", "overview"),
)
_RISK_HEADINGS = (
    ("risk", "factors"),
    ("risk", "factor"),
    ("item", "1a", "risk", "factors"),
    ("risks", "related", "to"),
)
_LEGAL_HEADINGS = (
    ("legal", "proceedings"),
    ("legal", "proceeding"),
    ("item", "3", "legal", "proceedings"),
)

# A heading alone is not enough: notes and MD&A pages mention the statement
# names in prose.  Primary statements also carry several signature line items.
_INCOME_SIGNATURES = (
    ("net", "sales"),
    ("net", "revenue"),
    ("total", "revenues"),
    ("total", "sales"),
    ("sales", "of", "products"),
    ("sales", "of", "services"),
    ("cost", "of", "sales"),
    ("cost", "of", "products"),
    ("cost", "of", "services"),
    ("gross", "profit"),
    ("operating", "income"),
    ("operating", "profit"),
    ("loss", "from", "operations"),
    ("income", "from", "operations"),
    ("income", "before", "income", "taxes"),
    ("loss", "before", "income", "taxes"),
    ("net", "income"),
    ("net", "loss"),
    ("earnings", "per", "share"),
    ("loss", "per", "share"),
)
_BALANCE_SIGNATURES = (
    ("total", "current", "assets"),
    ("total", "current", "liabilities"),
    ("total", "assets"),
    ("total", "liabilities"),
    ("total", "stockholders", "equity"),
    ("total", "shareholders", "equity"),
    ("total", "equity"),
    ("cash", "and", "cash", "equivalents"),
    ("accounts", "payable"),
    ("retained", "earnings"),
)
_CASHFLOW_SIGNATURES = (
    ("cash", "flows", "from", "operating", "activities"),
    ("cash", "flows", "from", "investing", "activities"),
    ("cash", "flows", "from", "financing", "activities"),
    ("net", "cash", "provided", "by", "operating", "activities"),
    ("net", "cash", "used", "in", "operating", "activities"),
    ("net", "cash", "provided", "by", "investing", "activities"),
    ("net", "cash", "used", "in", "investing", "activities"),
    ("net", "cash", "provided", "by", "financing", "activities"),
    ("net", "cash", "used", "in", "financing", "activities"),
    ("net", "change", "in", "cash"),
    ("capital", "expenditures"),
    ("depreciation", "and", "amortization"),
    ("cash", "and", "cash", "equivalents"),
)

_GEOGRAPHY_TOKENS = frozenset({
    "africa",
    "african",
    "america",
    "american",
    "asia",
    "asian",
    "australia",
    "australian",
    "brazil",
    "brazilian",
    "canada",
    "canadian",
    "china",
    "chinese",
    "countr",
    "europ",
    "european",
    "glob",
    "india",
    "indian",
    "intern",
    "japan",
    "japanese",
    "mexico",
    "mexican",
    "middl",
    "pacif",
    "region",
    "worldwid",
})


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


_CANDIDATE_LIMIT = 200
_MAX_QUERIES = 72


@dataclass(slots=True)
class _PageView:
    citation: MemoryCitation
    document_id: str
    tokens: tuple[str, ...]
    counts: Counter[str]
    types: frozenset[str]
    geography_count: int
    reciprocal_rank: float


@dataclass(frozen=True, slots=True)
class _Profile:
    weights: tuple[tuple[str, float], ...]
    phrases: tuple[tuple[tuple[str, ...], float], ...]
    pairs: tuple[tuple[str, str], ...]
    intent_bonuses: tuple[tuple[str, float], ...]
    queries: tuple[str, ...]
    affinity_keys: tuple[str, ...]
    years: tuple[str, ...]


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve distinct page citations using deterministic, offline lexical expansion."""

    if limit <= 0 or not question.strip():
        return ()
    profile = _question_profile(question)
    candidates = await _collect_candidates(memory, profile.queries, _CANDIDATE_LIMIT)
    if not candidates:
        return ()
    views = [_page_view(citation, text, reciprocal_rank) for citation, text, reciprocal_rank in candidates.values()]
    inverse_frequency = _inverse_document_frequency(views)
    bonuses = dict(profile.intent_bonuses)
    ranked = sorted(
        views,
        key=lambda view: (
            -_view_score(view, profile, inverse_frequency, bonuses),
            view.citation.entry_id.encode(),
            view.citation.entry_version_id.encode(),
        ),
    )
    return tuple(view.citation for view in ranked[:limit])


async def _collect_candidates(memory, queries, candidate_limit):
    candidates: dict[tuple[str, int, str, str], tuple[MemoryCitation, str, float]] = {}
    for query_rank, query in enumerate(queries, start=1):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=candidate_limit))
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
            reciprocal_rank = 1.0 / (10 + query_rank + hit_rank)
            previous = candidates.get(identity)
            if previous is None:
                candidates[identity] = (citation, hit.text, reciprocal_rank)
            else:
                candidates[identity] = (previous[0], previous[1], previous[2] + reciprocal_rank)
    return candidates


def _question_profile(question: str) -> _Profile:
    raw_words = _words(question)
    raw_weight: dict[str, float] = {}
    years: list[str] = []
    for position, word in enumerate(raw_words):
        if len(word) < 2:
            continue
        if word.isdigit():
            if len(word) == 4 and 1900 <= int(word) <= 2100:
                years.append(word)
            continue
        if word in _QUESTION_STOP_WORDS or word in _COMPANY_SUFFIXES:
            continue
        weight = 1.0 if position < 30 else 0.55
        raw_weight[word] = max(raw_weight.get(word, 0.0), weight)

    weights: dict[str, float] = {}
    for word, weight in raw_weight.items():
        term = _stem(word)
        weights[term] = max(weights.get(term, 0.0), weight)
        for synonym in _FINANCIAL_SYNONYMS.get(word, ()):
            if len(synonym) >= 2 and synonym not in _QUESTION_STOP_WORDS:
                synonym_term = _stem(synonym)
                weights[synonym_term] = max(weights.get(synonym_term, 0.0), weight * 0.55)

    normalized_question = " ".join(raw_words)
    lowered_question = question.lower()
    intents = _detect_intents(raw_words, normalized_question, lowered_question, set(weights))
    intent_bonuses = _intent_bonuses(intents)

    core_words = _ordered_unique(word for word in raw_words if word in raw_weight)
    metric_queries = _metric_queries(normalized_question, set(weights))
    intent_queries = _intent_queries(intents)
    pairs = tuple(dict.fromkeys((_stem(left), _stem(right)) for left, right in pairwise(core_words[:16])))
    phrases = _phrases(metric_queries, intent_queries)
    queries = _queries(
        question,
        core_words,
        metric_queries,
        intent_queries,
        pairs,
        _synonym_queries(core_words),
    )
    return _Profile(
        weights=tuple(weights.items()),
        phrases=phrases,
        pairs=pairs,
        intent_bonuses=intent_bonuses,
        queries=queries,
        affinity_keys=_affinity_keys(raw_words),
        years=tuple(dict.fromkeys(years)),
    )


def _raise_intent(intents: dict[str, float], name: str, weight: float) -> None:
    intents[name] = max(intents.get(name, 0.0), weight)


def _hint_intents(stems: set[str]) -> dict[str, float]:
    intents: dict[str, float] = {}
    for name, hints, weight in (
        ("income", _INCOME_HINTS, 10.0),
        ("balance", _BALANCE_HINTS, 10.0),
        ("cashflow", _CASHFLOW_HINTS, 10.0),
        ("segment", _SEGMENT_HINTS, 12.0),
        ("business", _BUSINESS_HINTS, 5.0),
        ("legal", _LEGAL_HINTS, 10.0),
        ("risk", _RISK_HINTS, 5.0),
    ):
        if stems.intersection(hints):
            _raise_intent(intents, name, weight)
    return intents


def _apply_statement_intents(
    intents: dict[str, float],
    normalized_question: str,
    lowered_question: str,
    stems: set[str],
) -> None:
    if "income statement" in normalized_question or "p&l" in lowered_question or "p l" in normalized_question:
        _raise_intent(intents, "income", 14.0)
    if "balance sheet" in normalized_question:
        _raise_intent(intents, "balance", 14.0)
    if "cash flow" in normalized_question or "cash flows" in normalized_question:
        _raise_intent(intents, "cashflow", 14.0)
    if "working capital" in normalized_question:
        _raise_intent(intents, "balance", 12.0)
    if "quick ratio" in normalized_question or "current ratio" in normalized_question:
        _raise_intent(intents, "balance", 14.0)
    for phrase, token in (
        ("days payable", "dpo"),
        ("days sales", "dso"),
        ("days inventory", "dio"),
    ):
        if phrase in normalized_question or token in stems:
            _raise_intent(intents, "income", 8.0)
            _raise_intent(intents, "balance", 10.0)
    if "capital intensive" in normalized_question or "capital-intensive" in lowered_question:
        # Capital intensity is answered by the income statement (sales/costs),
        # the balance sheet (assets), and the cash flow statement (capex).
        _raise_intent(intents, "income", 14.0)
        _raise_intent(intents, "balance", 14.0)
        _raise_intent(intents, "cashflow", 14.0)


def _apply_narrative_intents(
    intents: dict[str, float],
    lowered_question: str,
    stems: set[str],
) -> None:
    if "customer" in stems and {"primary", "major", "significant", "largest"}.intersection(stems):
        _raise_intent(intents, "business", 8.0)
    if "m&a" in lowered_question or "merger" in stems or "acquisition" in stems:
        _raise_intent(intents, "segment", 8.0)
    if "legal" in stems or "litigation" in stems or "lawsuit" in stems:
        _raise_intent(intents, "legal", 12.0)
    if "risk" in stems:
        _raise_intent(intents, "risk", 6.0)


def _detect_intents(
    raw_words: tuple[str, ...],
    normalized_question: str,
    lowered_question: str,
    stems: set[str],
) -> dict[str, float]:
    intents = _hint_intents(stems)
    _apply_statement_intents(intents, normalized_question, lowered_question, stems)
    _apply_narrative_intents(intents, lowered_question, stems)
    return intents


def _intent_bonuses(intents: dict[str, float]) -> tuple[tuple[str, float], ...]:
    bonuses: dict[str, float] = {}
    for intent, weight in intents.items():
        for page_type, factor in _TYPE_INTENT[intent]:
            bonuses[page_type] = max(bonuses.get(page_type, 0.0), weight * factor)
    return tuple(bonuses.items())


def _metric_queries(normalized_question: str, stems: set[str]) -> tuple[str, ...]:
    queries: list[str] = []
    for phrase, expansions in _METRIC_QUERIES.items():
        if (" " in phrase and phrase in normalized_question) or (" " not in phrase and _stem(phrase) in stems):
            queries.extend(expansions)
    if "m&a" in normalized_question:
        queries.extend(("acquisitions divestitures", "merger acquisition", "business segment"))
    if {"geograph", "region", "countr"}.intersection(stems):
        queries.extend((
            "north america",
            "latin america",
            "asia pacific",
            "middle east",
            "europe",
            "africa",
            "international operations",
        ))
    return tuple(dict.fromkeys(queries))


def _intent_queries(intents: dict[str, float]) -> tuple[str, ...]:
    ordered = [
        list(_INTENT_QUERIES[intent][:13]) for intent in sorted(intents, key=lambda name: (-intents[name], name))
    ]
    queries: list[str] = []
    for index in range(13):
        for section in ordered:
            if index < len(section):
                queries.append(section[index])
            if len(queries) >= 30:
                return tuple(queries)
    return tuple(queries)


def _phrases(
    metric_queries: tuple[str, ...], intent_queries: tuple[str, ...]
) -> tuple[tuple[tuple[str, ...], float], ...]:
    weighted: dict[tuple[str, ...], float] = {}
    for query in (*metric_queries[:12], *intent_queries):
        pattern = tuple(_stem(word) for word in _words(query))
        if len(pattern) >= 2:
            weighted[pattern] = max(weighted.get(pattern, 0.0), 1.6)
    return tuple(weighted.items())


def _synonym_queries(core_words: list[str]) -> tuple[str, ...]:
    preferred: list[str] = []
    fallback: list[str] = []
    for word in core_words:
        for synonym in _FINANCIAL_SYNONYMS.get(word, ()):
            if " " in synonym:
                preferred.append(synonym)
            elif len(synonym) >= 4:
                fallback.append(synonym)
    return tuple(list(dict.fromkeys((*preferred, *fallback)))[:10])


def _queries(
    question: str,
    core_words: list[str],
    metric_queries: tuple[str, ...],
    intent_queries: tuple[str, ...],
    pairs: tuple[tuple[str, str], ...],
    synonym_queries: tuple[str, ...],
) -> tuple[str, ...]:
    queries: list[str] = [question, " ".join(core_words[:24])]
    queries.extend(metric_queries[:12])
    queries.extend(intent_queries)
    queries.extend(core_words[:12])
    queries.extend(f"{left} {right}" for left, right in pairs[:8])
    queries.extend(synonym_queries[:8])
    ordered = tuple(dict.fromkeys(query for query in queries if query.strip()))
    return ordered[:_MAX_QUERIES]


def _affinity_keys(raw_words: tuple[str, ...]) -> tuple[str, ...]:
    keys: list[str] = []
    for word in raw_words:
        if len(word) >= 3 and word not in _QUESTION_STOP_WORDS:
            keys.append(word)
    for size in (2, 3):
        for index in range(len(raw_words) - size + 1):
            parts = raw_words[index : index + size]
            if any(part in _QUESTION_STOP_WORDS for part in parts):
                continue
            joined = "".join(parts)
            if 2 <= len(joined) <= 40:
                keys.append(joined)
    return tuple(dict.fromkeys(keys))[:32]


def _page_view(citation: MemoryCitation, text: str, reciprocal_rank: float) -> _PageView:
    document_id, _, body = text.partition("\n")
    raw_tokens = _words(body)
    tokens = tuple(_stem(token) for token in raw_tokens)
    geography_count = len(set(tokens).intersection(_GEOGRAPHY_TOKENS))
    return _PageView(
        citation=citation,
        document_id=document_id,
        tokens=tokens,
        counts=Counter(tokens),
        types=_page_types(tokens, geography_count),
        geography_count=geography_count,
        reciprocal_rank=reciprocal_rank,
    )


def _page_types(tokens: tuple[str, ...], geography_count: int) -> frozenset[str]:
    head = tokens[:80]
    types: set[str] = set()
    if _matches_any(head, _INCOME_HEADINGS) and _signature_count(tokens, _INCOME_SIGNATURES) >= 3:
        types.add("income")
    if _matches_any(head, _BALANCE_HEADINGS) and _signature_count(tokens, _BALANCE_SIGNATURES) >= 3:
        types.add("balance")
    if _matches_any(head, _CASHFLOW_HEADINGS) and _signature_count(tokens, _CASHFLOW_SIGNATURES) >= 3:
        types.add("cashflow")
    if _matches_any(head, _SEGMENT_HEADINGS):
        types.add("segment")
    if _matches_any(head, _BUSINESS_HEADINGS):
        types.add("business")
    if _matches_any(head, _RISK_HEADINGS):
        types.add("risk")
    if _matches_any(head, _LEGAL_HEADINGS):
        types.add("legal")
    if geography_count >= 5:
        types.add("geography")
    return frozenset(types)


def _matches_any(tokens: tuple[str, ...], headings: tuple[tuple[str, ...], ...]) -> bool:
    return any(_contains_sequence(tokens, _phrase(*heading)) for heading in headings)


def _signature_count(
    tokens: tuple[str, ...],
    signatures: tuple[tuple[str, ...], ...],
) -> int:
    return sum(1 for signature in signatures if _contains_sequence(tokens, _phrase(*signature)))


def _inverse_document_frequency(views: list[_PageView]) -> dict[str, float]:
    frequency: Counter[str] = Counter()
    for view in views:
        frequency.update(view.counts.keys())
    total = max(len(views), 1)
    return {term: log(1.0 + (total + 1.0) / (count + 0.5)) for term, count in frequency.items()}


def _term_score(
    view: _PageView,
    profile: _Profile,
    inverse_frequency: dict[str, float],
) -> float:
    counts = view.counts
    score = 0.0
    matched = 0.0
    for term, weight in profile.weights:
        term_frequency = counts.get(term, 0)
        if not term_frequency:
            continue
        term_idf = inverse_frequency.get(term, 1.0)
        matched += weight * term_idf
        score += 2.0 * weight * term_idf * (term_frequency / (term_frequency + 1.2))
    return score + 1.6 * matched


def _phrase_score(
    view: _PageView,
    profile: _Profile,
    inverse_frequency: dict[str, float],
) -> float:
    score = 0.0
    for pattern, weight in profile.phrases:
        positions = _sequence_positions(view.tokens, pattern)
        if not positions:
            continue
        strength = sum(inverse_frequency.get(term, 0.5) for term in set(pattern))
        bonus = weight * (0.8 + 0.25 * min(len(positions), 4)) * (0.5 + strength / max(len(pattern), 1))
        if positions[0] < 80:
            bonus *= 1.3
        score += bonus
    return score


def _pair_score(
    view: _PageView,
    profile: _Profile,
    inverse_frequency: dict[str, float],
) -> float:
    score = 0.0
    for left, right in profile.pairs:
        if _near(view.tokens, left, right, 4):
            score += 0.3 * (inverse_frequency.get(left, 1.0) + inverse_frequency.get(right, 1.0))
    return score


def _intent_score(view: _PageView, intent_bonuses: dict[str, float]) -> float:
    score = 0.0
    for page_type, bonus in intent_bonuses.items():
        if page_type in view.types:
            score += bonus
    if "geography" in intent_bonuses:
        score += 0.7 * min(view.geography_count, 8)
    return score


def _affinity_score(view: _PageView, profile: _Profile) -> float:
    document_key = re.sub(r"[^a-z0-9]+", "", view.document_id.lower())
    score = 0.0
    if any(key in document_key for key in profile.affinity_keys):
        score += 3.0
    for year in profile.years:
        if year in document_key:
            score += 0.8
    return score


def _view_score(
    view: _PageView,
    profile: _Profile,
    inverse_frequency: dict[str, float],
    intent_bonuses: dict[str, float],
) -> float:
    score = _term_score(view, profile, inverse_frequency)
    score += _phrase_score(view, profile, inverse_frequency)
    score += _pair_score(view, profile, inverse_frequency)
    score += _intent_score(view, intent_bonuses)
    score += _affinity_score(view, profile)
    score += min(4.0, view.reciprocal_rank * 40.0)
    return score


def _sequence_positions(tokens: tuple[str, ...], pattern: tuple[str, ...]) -> list[int]:
    if not pattern or len(pattern) > len(tokens):
        return []
    width = len(pattern)
    first = pattern[0]
    positions: list[int] = []
    for index, token in enumerate(tokens):
        if token == first and tokens[index : index + width] == pattern:
            positions.append(index)
    return positions


def _contains_sequence(tokens: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern or len(pattern) > len(tokens):
        return False
    width = len(pattern)
    first = pattern[0]
    return any(token == first and tokens[index : index + width] == pattern for index, token in enumerate(tokens))


def _near(tokens: tuple[str, ...], left: str, right: str, window: int) -> bool:
    last_left = last_right = -(10**9)
    for index, token in enumerate(tokens):
        if token == left:
            if index - last_right <= window:
                return True
            last_left = index
        elif token == right:
            if index - last_left <= window:
                return True
            last_right = index
    return False


def _validate_document_id(document_id: str) -> str:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    return document_id


def _words(value: str) -> tuple[str, ...]:
    return tuple(match.group(0).lower() for match in _WORD.finditer(value))


_COMPANY_SUFFIXES = frozenset({
    "ag",
    "co",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "ltd",
    "nv",
    "plc",
    "sa",
})


def _stem(word: str) -> str:
    value = word.lower()
    if len(value) <= 3:
        return value
    if value.endswith("ies") and len(value) > 4:
        value = f"{value[:-3]}y"
    if (value.endswith("es") and len(value) >= 5 and value[-3] in "sxz") or value.endswith(("ches", "shes")):
        value = value[:-2]
    changed = True
    while changed and len(value) > 4:
        changed = False
        for suffix in _STEM_SUFFIXES:
            if value.endswith(suffix) and len(value) - len(suffix) >= 4:
                value = value[: -len(suffix)]
                changed = True
                break
    return _STEM_ALIASES.get(value, value)


@cache
def _phrase(*words: str) -> tuple[str, ...]:
    return tuple(_stem(word) for word in words)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


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
