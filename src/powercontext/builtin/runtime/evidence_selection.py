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

"""Choose literal, query-relevant sentence spans inside recalled Memory text.

The selector is pure: it reads candidate text, splits it into sentences that
keep their original character offsets, and asks the caller whether a candidate
set still fits the output budget. It never rewrites evidence; every chosen span
addresses ``text[start:end]`` of the entry it came from.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

__all__ = ["EvidenceSpan", "choose_evidence_spans", "sentence_spans"]

_WORD = re.compile(r"[a-z]+|\d+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_TOKEN_LIMIT = 12
_SUFFIXES = ("ing", "ed", "es", "s")


@dataclass(frozen=True)
class EvidenceSpan:
    """One selected interval in the source at ``source`` index."""

    source: int
    start: int
    end: int


@dataclass(frozen=True)
class _Sentence:
    document: int
    index: int
    start: int
    end: int
    score: int


_Document = tuple[int, str, tuple[tuple[int, int], ...], tuple[_Sentence, ...]]


def choose_evidence_spans(
    query: str,
    texts: Sequence[str],
    fits: Callable[[tuple[EvidenceSpan, ...]], bool],
) -> tuple[EvidenceSpan, ...]:
    """Return ranked literal spans whose merged rendering satisfies ``fits``.

    Every document first contributes its best matching sentence, remaining
    matching sentences follow in global score order, and any budget left over
    extends the strongest documents sentence by sentence. A sentence is only
    admitted whole, so a returned interval always ends at an original sentence
    boundary.
    """

    terms = _terms(query)
    if not terms or not texts:
        return ()
    documents: list[_Document] = [
        (index, text, sentence_spans(text), _scored_sentences(index, text, terms)) for index, text in enumerate(texts)
    ]
    ranked = [document for document in documents if any(sentence.score > 0 for sentence in document[3])]
    if not ranked:
        return ()
    document_rank = sorted(
        ranked,
        key=lambda document: (-max(sentence.score for sentence in document[3]), document[0]),
    )
    selected: dict[int, set[int]] = {document[0]: set() for document in documents}
    attempts = _Attempts(documents, selected, fits)
    _seed_best_per_document(document_rank, attempts)
    _seed_matching_sentences(ranked, selected, attempts)
    _fill_documents(document_rank, selected, attempts)
    return _merged_spans(documents, selected)


class _Attempts:
    """Admit one sentence at a time, keeping it only while the whole output fits."""

    def __init__(
        self,
        documents: Sequence[_Document],
        selected: dict[int, set[int]],
        fits: Callable[[tuple[EvidenceSpan, ...]], bool],
    ) -> None:
        self._documents = documents
        self._selected = selected
        self._fits = fits

    def add(self, document: int, sentence: int) -> bool:
        self._selected[document].add(sentence)
        if self._fits(_merged_spans(self._documents, self._selected)):
            return True
        self._selected[document].discard(sentence)
        return False


def _seed_best_per_document(document_rank: Sequence[_Document], attempts: _Attempts) -> None:
    for document in document_rank:
        best = max(document[3], key=lambda sentence: (sentence.score, -sentence.index))
        attempts.add(document[0], best.index)


def _seed_matching_sentences(
    ranked: Sequence[_Document],
    selected: dict[int, set[int]],
    attempts: _Attempts,
) -> None:
    scored = sorted(
        (sentence for document in ranked for sentence in document[3] if sentence.score > 0),
        key=lambda sentence: (-sentence.score, sentence.document, sentence.index),
    )
    for sentence in scored:
        if sentence.index not in selected[sentence.document]:
            attempts.add(sentence.document, sentence.index)


def _fill_documents(
    document_rank: Sequence[_Document],
    selected: dict[int, set[int]],
    attempts: _Attempts,
) -> None:
    for document in document_rank:
        for sentence in document[3]:
            if sentence.index not in selected[document[0]]:
                attempts.add(document[0], sentence.index)


def sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Split ``text`` after sentence punctuation while preserving offsets."""

    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        end = match.start()
        if text[start:end].strip():
            spans.append((start, end))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return tuple(spans)


def _scored_sentences(source: int, text: str, terms: frozenset[str]) -> tuple[_Sentence, ...]:
    sentences: list[_Sentence] = []
    for index, (start, end) in enumerate(sentence_spans(text)):
        counts = Counter(_stem(token) for token in _WORD.findall(text[start:end].lower()))
        matched = sum(1 for term in terms if term in counts)
        occurrences = sum(counts[term] for term in terms)
        sentences.append(_Sentence(document=source, index=index, start=start, end=end, score=matched * 3 + occurrences))
    return tuple(sentences)


def _terms(query: str) -> frozenset[str]:
    tokens = [_stem(token) for token in _WORD.findall(query.lower())]
    return frozenset(tokens[:_TOKEN_LIMIT])


def _stem(token: str) -> str:
    if len(token) <= 4 or token.isdigit():
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def _merged_spans(
    documents: Sequence[tuple[int, str, tuple[tuple[int, int], ...], tuple[_Sentence, ...]]],
    selected: dict[int, set[int]],
) -> tuple[EvidenceSpan, ...]:
    spans: list[EvidenceSpan] = []
    for document_index, text, sentences, _ in documents:
        ranges: list[list[int]] = []
        for sentence_index in sorted(selected[document_index]):
            start, end = sentences[sentence_index]
            if ranges and not text[ranges[-1][1] : start].strip():
                ranges[-1][1] = end
            else:
                ranges.append([start, end])
        spans.extend(EvidenceSpan(document_index, start, end) for start, end in ranges)
    return tuple(spans)
