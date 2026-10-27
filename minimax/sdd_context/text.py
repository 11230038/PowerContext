"""Tokenization shared by indexing and query analysis."""

from __future__ import annotations

import re
from collections import Counter

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?")
_CJK = re.compile(r"[一-鿿]+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
SPEC_ID = re.compile(r"SPEC-[A-Za-z]+-\d+")

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "class",
        "def",
        "false",
        "for",
        "from",
        "if",
        "import",
        "in",
        "is",
        "it",
        "none",
        "not",
        "of",
        "on",
        "or",
        "return",
        "self",
        "that",
        "the",
        "this",
        "to",
        "true",
        "with",
    }
)


def _word_terms(word: str) -> set[str]:
    lowered = word.lower()
    terms = {lowered}
    terms.update(part.lower() for part in lowered.split("_") if part)
    terms.update(match.lower() for match in _CAMEL.findall(word))
    return {term for term in terms if term and term not in STOP_WORDS}


def tokenize(text: str) -> Counter[str]:
    """Return weighted term frequencies for a document fragment."""

    terms: Counter[str] = Counter()
    for match in _WORD.finditer(text):
        for term in _word_terms(match.group()):
            terms[term] += 1
    for run in _CJK.findall(text):
        if len(run) == 1:
            terms[run] += 1
            continue
        if len(run) <= 6:
            terms[run] += 1
        for index in range(len(run) - 1):
            terms[run[index : index + 2]] += 1
    return terms


def query_terms(text: str) -> tuple[str, ...]:
    """Deterministic, deduplicated terms used for a seekdb lookup."""

    return tuple(sorted(tokenize(text)))


def spec_ids(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.upper() for match in SPEC_ID.findall(text)))
