"""Split specs, code and tests into source-addressable documents."""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .text import tokenize

_SPEC_HEADING = re.compile(r"^##\s+(SPEC-[A-Za-z]+-\d+)\s+(.+)$", re.MULTILINE)
_SKIP_DIRS = frozenset({".git", ".venv", "__pycache__", ".pytest_cache", ".state", "runs", "artifacts"})


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    kind: str
    path: str
    symbol: str | None
    title: str
    content: str
    terms: Counter[str]

    @property
    def source(self) -> str:
        if self.symbol:
            return f"{self.path}#{self.symbol}"
        return self.path


def build_terms(title: str, symbol: str | None, path: str, content: str) -> Counter[str]:
    terms: Counter[str] = Counter()
    _add(terms, title, 3)
    _add(terms, symbol or "", 2)
    _add(terms, path, 1)
    _add(terms, content, 1)
    return terms


def _add(terms: Counter[str], text: str, weight: int) -> None:
    for term, count in tokenize(text).items():
        terms[term] += count * weight


def _document(kind: str, path: str, symbol: str | None, title: str, content: str) -> Document:
    digest = hashlib.sha1(f"{kind}|{path}|{symbol or ''}|{content}".encode()).hexdigest()[:32]
    return Document(
        doc_id=f"doc_{digest}",
        kind=kind,
        path=path,
        symbol=symbol,
        title=title,
        content=content,
        terms=build_terms(title, symbol, path, content),
    )


def load_documents(root: Path) -> list[Document]:
    root = root.resolve()
    documents: list[Document] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(root)
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        suffix = file_path.suffix.lower()
        if suffix == ".md" and _is_spec(relative):
            documents.extend(_spec_documents(file_path, relative))
        elif suffix == ".py":
            documents.extend(_python_documents(file_path, relative))
    return documents


def _is_spec(relative: Path) -> bool:
    return "specs" in relative.parts or relative.name.lower().startswith("spec")


def _spec_documents(file_path: Path, relative: Path) -> list[Document]:
    text = file_path.read_text(encoding="utf-8")
    path = relative.as_posix()
    matches = list(_SPEC_HEADING.finditer(text))
    if not matches:
        return [_document("spec", path, None, file_path.stem, text.strip())]

    documents: list[Document] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        clause = text[match.start() : end].strip()
        documents.append(
            _document(
                "spec",
                path,
                match.group(1).upper(),
                match.group(2).strip(),
                clause,
            )
        )
    return documents


def _python_documents(file_path: Path, relative: Path) -> list[Document]:
    text = file_path.read_text(encoding="utf-8")
    path = relative.as_posix()
    is_test = "tests" in relative.parts or relative.name.startswith("test_")
    kind = "test" if is_test else "code"
    documents: list[Document] = [_document(kind, path, None, file_path.stem, text)]

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return documents

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if is_test and not node.name.startswith("test_"):
                continue
            documents.append(_symbol_document(kind, path, node.name, node, text))
        elif isinstance(node, ast.ClassDef):
            if is_test and not node.name.startswith("Test"):
                continue
            if is_test:
                continue
            documents.append(_symbol_document(kind, path, node.name, node, text))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    documents.append(
                        _symbol_document(kind, path, f"{node.name}.{child.name}", child, text)
                    )
    return documents


def _symbol_document(kind: str, path: str, symbol: str, node: ast.AST, text: str) -> Document:
    content = ast.get_source_segment(text, node) or ""
    return _document(kind, path, symbol, symbol, content)
