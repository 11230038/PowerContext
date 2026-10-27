"""seekdb persistence: schema, index ingestion and posting lookups."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

import pymysql

from .chunking import Document
from .config import Settings

_UTC = timezone.utc


def connect(settings: Settings) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.seekdb_host,
        port=settings.seekdb_port,
        user=settings.seekdb_user,
        password=settings.seekdb_password,
        database=settings.seekdb_database,
        charset="utf8mb4",
        autocommit=False,
    )


def ensure_schema(settings: Settings) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", settings.seekdb_database):
        raise ValueError("SEEKDB_DATABASE may only contain letters, digits and underscores")
    server = pymysql.connect(
        host=settings.seekdb_host,
        port=settings.seekdb_port,
        user=settings.seekdb_user,
        password=settings.seekdb_password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with server.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.seekdb_database}` "
                "DEFAULT CHARACTER SET utf8mb4"
            )
    finally:
        server.close()

    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS docs (
                    doc_id VARCHAR(64) NOT NULL,
                    kind VARCHAR(16) NOT NULL,
                    path VARCHAR(512) NOT NULL,
                    symbol VARCHAR(255) NULL,
                    title VARCHAR(512) NOT NULL,
                    content MEDIUMTEXT NOT NULL,
                    updated_at DATETIME(6) NOT NULL,
                    PRIMARY KEY (doc_id),
                    KEY idx_docs_kind (kind)
                ) DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS terms (
                    term VARCHAR(191) NOT NULL,
                    doc_id VARCHAR(64) NOT NULL,
                    tf INT NOT NULL,
                    PRIMARY KEY (term, doc_id),
                    KEY idx_terms_doc (doc_id)
                ) DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_runs (
                    run_id VARCHAR(36) NOT NULL,
                    root VARCHAR(512) NOT NULL,
                    label VARCHAR(64) NOT NULL,
                    started_at DATETIME(6) NOT NULL,
                    finished_at DATETIME(6) NULL,
                    doc_count INT NOT NULL DEFAULT 0,
                    status VARCHAR(16) NOT NULL,
                    error TEXT NULL,
                    PRIMARY KEY (run_id)
                ) DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS query_log (
                    log_id BIGINT NOT NULL AUTO_INCREMENT,
                    task_hash CHAR(40) NOT NULL,
                    query_text TEXT NOT NULL,
                    terms TEXT NOT NULL,
                    candidates INT NOT NULL,
                    created_at DATETIME(6) NOT NULL,
                    PRIMARY KEY (log_id)
                ) DEFAULT CHARSET=utf8mb4
                """
            )
        connection.commit()
    finally:
        connection.close()


def replace_index(
    connection: pymysql.connections.Connection,
    documents: Sequence[Document],
    *,
    root: Path,
    label: str,
) -> dict[str, object]:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(_UTC).replace(tzinfo=None)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO ingest_runs (run_id, root, label, started_at, status) VALUES (%s, %s, %s, %s, %s)",
            (run_id, str(root.resolve()), label, started_at, "running"),
        )
    connection.commit()

    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM terms")
            cursor.execute("DELETE FROM docs")
            now = datetime.now(_UTC).replace(tzinfo=None)
            cursor.executemany(
                "INSERT INTO docs (doc_id, kind, path, symbol, title, content, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (doc.doc_id, doc.kind, doc.path, doc.symbol, doc.title, doc.content, now)
                    for doc in documents
                ],
            )
            cursor.executemany(
                "INSERT INTO terms (term, doc_id, tf) VALUES (%s, %s, %s)",
                [
                    (term, doc.doc_id, count)
                    for doc in documents
                    for term, count in doc.terms.items()
                ],
            )
            cursor.execute(
                "UPDATE ingest_runs SET status = %s, doc_count = %s, finished_at = %s WHERE run_id = %s",
                ("succeeded", len(documents), datetime.now(_UTC).replace(tzinfo=None), run_id),
            )
        connection.commit()
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ingest_runs SET status = %s, error = %s, finished_at = %s WHERE run_id = %s",
                ("failed", str(error)[:2000], datetime.now(_UTC).replace(tzinfo=None), run_id),
            )
        connection.commit()
        raise

    return {"run_id": run_id, "doc_count": len(documents), "label": label}


def lookup_postings(
    connection: pymysql.connections.Connection,
    terms: Iterable[str],
) -> tuple[list[tuple[str, str, int]], dict[str, int], int]:
    """Return postings, document frequency per term and total document count."""

    unique_terms = tuple(dict.fromkeys(terms))
    if not unique_terms:
        return [], {}, _document_count(connection)

    placeholders = ", ".join(["%s"] * len(unique_terms))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT doc_id, term, tf FROM terms WHERE term IN ({placeholders})",
            unique_terms,
        )
        postings = [(str(row[0]), str(row[1]), int(row[2])) for row in cursor.fetchall()]

    frequency: dict[str, int] = {}
    for _doc_id, term, _tf in postings:
        frequency[term] = frequency.get(term, 0) + 1
    return postings, frequency, _document_count(connection)


def fetch_documents(
    connection: pymysql.connections.Connection,
    doc_ids: Sequence[str],
) -> dict[str, dict[str, object]]:
    if not doc_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(doc_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT doc_id, kind, path, symbol, title, content FROM docs WHERE doc_id IN ({placeholders})",
            tuple(doc_ids),
        )
        rows = cursor.fetchall()
    return {
        str(row[0]): {
            "doc_id": str(row[0]),
            "kind": str(row[1]),
            "path": str(row[2]),
            "symbol": None if row[3] is None else str(row[3]),
            "title": str(row[4]),
            "content": str(row[5]),
        }
        for row in rows
    }


def log_query(
    connection: pymysql.connections.Connection,
    *,
    task_hash: str,
    query_text: str,
    terms: Sequence[str],
    candidates: int,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO query_log (task_hash, query_text, terms, candidates, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                task_hash,
                query_text[:10000],
                " ".join(terms)[:10000],
                candidates,
                datetime.now(_UTC).replace(tzinfo=None),
            ),
        )
        log_id = int(cursor.lastrowid)
    connection.commit()
    return log_id


def _document_count(connection: pymysql.connections.Connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM docs")
        row = cursor.fetchone()
    return int(row[0]) if row else 0
