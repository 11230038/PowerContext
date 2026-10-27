"""Turn a task description plus seekdb postings into a development context."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from math import log

import pymysql

from .db import fetch_documents, log_query, lookup_postings
from .text import query_terms, spec_ids

_KIND_WEIGHT = {"spec": 1.15, "code": 1.0, "test": 0.9}


@dataclass(frozen=True, slots=True)
class Hit:
    doc: dict[str, object]
    score: float

    @property
    def kind(self) -> str:
        return str(self.doc["kind"])

    @property
    def path(self) -> str:
        return str(self.doc["path"])

    @property
    def symbol(self) -> str | None:
        symbol = self.doc["symbol"]
        return None if symbol is None else str(symbol)

    @property
    def source(self) -> str:
        return f"{self.path}#{self.symbol}" if self.symbol else self.path


def build_context(
    connection: pymysql.connections.Connection,
    task_text: str,
    *,
    label: str = "app",
    spec_limit: int = 5,
    code_limit: int = 4,
    test_limit: int = 4,
) -> dict[str, object]:
    terms = query_terms(task_text)
    mentioned_specs = set(spec_ids(task_text))
    postings, frequency, total_documents = lookup_postings(connection, terms)

    scores: dict[str, float] = defaultdict(float)
    for doc_id, term, term_frequency in postings:
        document_frequency = frequency.get(term, 1)
        inverse_frequency = log(
            1.0 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        scores[doc_id] += (1.0 + log(term_frequency)) * inverse_frequency

    ranked_ids = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))[:250]
    documents = fetch_documents(connection, ranked_ids)

    hits: list[Hit] = []
    lowered_task = task_text.lower()
    for doc_id, doc in documents.items():
        score = scores[doc_id]
        score *= _KIND_WEIGHT.get(str(doc["kind"]), 1.0)
        symbol = doc["symbol"]
        if symbol is not None:
            symbol_text = str(symbol)
            if symbol_text.upper() in mentioned_specs:
                score *= 4.0
            if symbol_text.lower() in lowered_task:
                score *= 1.8
        hits.append(Hit(doc=doc, score=score))

    hits.sort(key=lambda hit: (-hit.score, hit.source))

    specs = _select_specs(hits, mentioned_specs, spec_limit)
    code = _select_by_kind(hits, "code", code_limit)
    tests = _select_tests(hits, test_limit)
    candidate_count = len(hits)
    task_hash = hashlib.sha1(task_text.strip().encode()).hexdigest()
    log_id = log_query(
        connection,
        task_hash=task_hash,
        query_text=task_text,
        terms=terms,
        candidates=candidate_count,
    )

    return {
        "task": task_text.strip(),
        "task_hash": task_hash,
        "label": label,
        "specs": [_spec_entry(hit, label) for hit in specs],
        "code": [_code_entry(hit, label) for hit in code],
        "tests": [_test_entry(hit, label) for hit in tests],
        "database": {
            "engine": "seekdb",
            "documents": total_documents,
            "postings": len(postings),
            "query_terms": list(terms[:60]),
            "query_log_id": log_id,
        },
    }


def _select_specs(hits: list[Hit], mentioned: set[str], limit: int) -> list[Hit]:
    spec_hits = [hit for hit in hits if hit.kind == "spec" and hit.symbol]
    selected: list[Hit] = []
    mentioned_hits = [hit for hit in spec_hits if hit.symbol in mentioned]
    for hit in sorted(mentioned_hits, key=lambda hit: (-hit.score, str(hit.symbol))):
        if hit not in selected:
            selected.append(hit)
    for hit in spec_hits:
        if len(selected) >= limit:
            break
        if hit not in selected:
            selected.append(hit)
    return selected[:limit]


def _select_by_kind(hits: list[Hit], kind: str, limit: int) -> list[Hit]:
    candidates = [hit for hit in hits if hit.kind == kind]
    selected: list[Hit] = []
    per_path: dict[str, int] = defaultdict(int)
    for hit in candidates:
        if hit.symbol is None and any(
            other.kind == kind and other.path == hit.path and other.symbol for other in candidates
        ):
            continue
        if per_path[hit.path] >= 2:
            continue
        selected.append(hit)
        per_path[hit.path] += 1
        if len(selected) >= limit:
            break
    return selected


def _select_tests(hits: list[Hit], limit: int) -> list[Hit]:
    test_hits = [hit for hit in hits if hit.kind == "test" and hit.symbol]
    if not test_hits:
        test_hits = [hit for hit in hits if hit.kind == "test"]
    selected: list[Hit] = []
    per_path: dict[str, int] = defaultdict(int)
    for hit in test_hits:
        if per_path[hit.path] >= 3:
            continue
        selected.append(hit)
        per_path[hit.path] += 1
        if len(selected) >= limit:
            break
    return selected


def _spec_entry(hit: Hit, label: str) -> dict[str, object]:
    return {
        "id": hit.symbol,
        "title": hit.doc["title"],
        "source": f"{label}/{hit.path}#{hit.symbol}",
        "content": hit.doc["content"],
        "score": round(hit.score, 4),
    }


def _code_entry(hit: Hit, label: str) -> dict[str, object]:
    return {
        "path": hit.path,
        "symbol": hit.symbol,
        "source": f"{label}/{hit.source}",
        "score": round(hit.score, 4),
    }


def _test_entry(hit: Hit, label: str) -> dict[str, object]:
    return {
        "path": hit.path,
        "name": hit.symbol or hit.doc["title"],
        "source": f"{label}/{hit.source}",
        "score": round(hit.score, 4),
    }
