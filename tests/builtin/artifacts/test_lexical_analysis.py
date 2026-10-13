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

# ruff: noqa: RUF001 - intentional multilingual and fullwidth input.

"""Shared word retrieval, exact identifiers, quoting and content-safe normalization."""

import pytest

from powercontext.builtin.artifacts.search import (
    AdmissionFloor,
    admits_fts_text,
    analyze_fts_query,
    analyze_text,
    lexical_terms_with_spans,
)

FACT = "本项目的 PowerContext Server 固定在 127.0.0.1:8000；测试写入。"


@pytest.mark.parametrize(
    "query",
    [
        "PowerContext Server 地址",
        "PowerContext Server 地址是什么？",
        "的 PowerContext Server 地址是什么？",
        "请告诉我 PowerContext Server 地址是什么？",
        "我之前让你记住的 PowerContext Server 地址是什么？",
    ],
)
def test_natural_question_forms_recall_the_same_lexical_fact(query):
    assert admits_fts_text(query, FACT)
    assert not admits_fts_text(query, "Dinner recipe baking instructions.")


def test_chinese_words_and_latin_identifiers_remain_distinct():
    assert admits_fts_text("alpha beta gamma u_7684", "alpha u_7684")
    assert admits_fts_text("u_7684", "u_7684")
    assert not admits_fts_text("u_7684", "的")
    assert not admits_fts_text("的", "u_7684")
    assert not admits_fts_text('"的"', "u_7684")


def test_stopwords_are_query_only_and_quoting_can_search_them():
    assert not analyze_fts_query("的 是 什么")
    assert analyze_text("的")
    assert admits_fts_text('"的"', "的")
    assert admits_fts_text('"AND" "OR"', "AND and OR are operators.")


@pytest.mark.parametrize("word", ["不", "没有", "不要", "无", "not", "without", "can't"])
def test_negation_is_searchable_evidence(word):
    assert analyze_text(word) in analyze_fts_query(word)


def test_explicit_admission_still_applies_to_words():
    strict = AdmissionFloor(lexical_coverage=0.5, lexical_min_matched_terms=2)
    assert not admits_fts_text("alpha beta gamma delta", "alpha")
    assert not admits_fts_text("alpha beta gamma delta", "alpha", floor=strict)
    assert admits_fts_text("alpha beta gamma delta", "alpha beta", floor=strict)


def test_word_spans_and_frequencies_preserve_the_normalized_original():
    text = "Ｃafé 地址 地址 u_7684"
    # NFC preserves fullwidth letters; casefold only changes case.
    normalized = "ｃafé 地址 地址 u_7684"
    words = lexical_terms_with_spans(text)
    assert [word for word, _start, _end in words].count("地址") == 2
    assert all(normalized[start:end] == word for word, start, end in words)
    assert analyze_text(text).split().count(analyze_text("地址")) == 2


@pytest.mark.parametrize("identifier", ["x9", "u_7684", "pcue79a84", "pch1234", "A" * 200])
def test_encoded_projection_has_no_literal_identifier_alias(identifier):
    assert admits_fts_text(identifier, identifier)
    assert not admits_fts_text(identifier, analyze_text(identifier))


def test_apostrophe_spelling_preserves_contractions_and_quoted_stopwords():
    assert analyze_fts_query("it’s") == analyze_fts_query("it's") == ""
    assert admits_fts_text("don’t", "don't disclose passwords")
    assert admits_fts_text('"it’s"', "it's documented")
