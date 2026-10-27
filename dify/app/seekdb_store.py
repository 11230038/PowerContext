"""seekdb storage and retrieval for the Cat Tavern lore cards."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pymysql

from config import Settings
from lore_data import LORE_CARDS

_UTC = timezone.utc
_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_CJK = re.compile(r"[一-鿿]+")
_STOP_BIGRAMS = {
    "我把",
    "你还",
    "今天",
    "怎么",
    "什么",
    "一个",
    "这个",
    "那个",
    "就是",
    "可以",
    "我们",
    "他们",
    "自己",
    "没有",
    "不是",
    "知道",
    "觉得",
    "现在",
    "然后",
    "还是",
    "已经",
}


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
    if not _DB_NAME.fullmatch(settings.seekdb_database):
        raise ValueError("TAVERN_DB may only contain letters, digits and underscores")
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
                CREATE TABLE IF NOT EXISTS lore_cards (
                    card_id VARCHAR(64) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    tags VARCHAR(255) NOT NULL,
                    weight INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (card_id)
                ) DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS lore_query_log (
                    log_id BIGINT NOT NULL AUTO_INCREMENT,
                    player_id VARCHAR(64) NOT NULL,
                    session_id VARCHAR(64) NOT NULL,
                    query_text TEXT NOT NULL,
                    terms TEXT NOT NULL,
                    hit_ids TEXT NOT NULL,
                    created_at DATETIME(6) NOT NULL,
                    PRIMARY KEY (log_id)
                ) DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS turn_log (
                    turn_id BIGINT NOT NULL AUTO_INCREMENT,
                    player_id VARCHAR(64) NOT NULL,
                    session_id VARCHAR(64) NOT NULL,
                    deed TEXT NOT NULL,
                    reply TEXT NOT NULL,
                    artifact_id VARCHAR(64) NULL,
                    created_at DATETIME(6) NOT NULL,
                    PRIMARY KEY (turn_id)
                ) DEFAULT CHARSET=utf8mb4
                """
            )
        connection.commit()
    finally:
        connection.close()


def seed_cards(settings: Settings) -> int:
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.executemany(
                "REPLACE INTO lore_cards (card_id, title, content, tags, weight) "
                "VALUES (%s, %s, %s, %s, %s)",
                [
                    (
                        card["card_id"],
                        card["title"],
                        card["content"],
                        card["tags"],
                        card["weight"],
                    )
                    for card in LORE_CARDS
                ],
            )
        connection.commit()
    finally:
        connection.close()
    return len(LORE_CARDS)


def query_terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        if len(term) >= 2 and term not in _STOP_BIGRAMS and term not in seen:
            seen.add(term)
            terms.append(term)

    for word in _WORD.findall(text):
        add(word.lower())
    for run in _CJK.findall(text):
        if len(run) == 1:
            continue
        for index in range(len(run) - 1):
            add(run[index : index + 2])
    return terms[:24]


def search_lore(
    settings: Settings,
    *,
    query: str,
    player_id: str,
    session_id: str,
    limit: int = 3,
) -> dict[str, Any]:
    terms = query_terms(query)
    connection = connect(settings)
    try:
        rows: list[tuple[str, str, str, str, int]] = []
        if terms:
            clause = " OR ".join(
                "(title LIKE %s OR tags LIKE %s OR content LIKE %s)" for _ in terms
            )
            parameters: list[Any] = []
            for term in terms:
                like = f"%{term}%"
                parameters.extend([like, like, like])
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT card_id, title, content, tags, weight FROM lore_cards "
                    f"WHERE {clause} LIMIT 100",
                    parameters,
                )
                rows = [tuple(row) for row in cursor.fetchall()]
        if not rows:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT card_id, title, content, tags, weight FROM lore_cards "
                    "ORDER BY weight DESC, card_id LIMIT %s",
                    (limit,),
                )
                rows = [tuple(row) for row in cursor.fetchall()]

        ranked = sorted(
            rows,
            key=lambda row: (-_score(row, terms), str(row[0])),
        )[:limit]
        hits = [
            {
                "card_id": str(row[0]),
                "title": str(row[1]),
                "content": str(row[2]),
                "tags": str(row[3]),
                "score": _score(row, terms),
            }
            for row in ranked
        ]
        log_id = _log_query(
            connection,
            player_id=player_id,
            session_id=session_id,
            query=query,
            terms=terms,
            hit_ids=[hit["card_id"] for hit in hits],
        )
    finally:
        connection.close()

    return {
        "query": query,
        "terms": terms,
        "hits": hits,
        "lore_text": "\n\n".join(f"【{hit['title']}】{hit['content']}" for hit in hits),
        "query_log_id": log_id,
        "source": f"seekdb://{settings.seekdb_database}/lore_cards",
    }


def log_turn(
    settings: Settings,
    *,
    player_id: str,
    session_id: str,
    deed: str,
    reply: str,
    artifact_id: str | None,
) -> int:
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO turn_log (player_id, session_id, deed, reply, artifact_id, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    player_id,
                    session_id,
                    deed[:4000],
                    reply[:4000],
                    artifact_id,
                    datetime.now(_UTC).replace(tzinfo=None),
                ),
            )
            turn_id = int(cursor.lastrowid)
        connection.commit()
    finally:
        connection.close()
    return turn_id


def recent_queries(settings: Settings, *, player_id: str, limit: int = 5) -> list[dict[str, Any]]:
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT log_id, session_id, query_text, terms, hit_ids, created_at "
                "FROM lore_query_log WHERE player_id = %s ORDER BY log_id DESC LIMIT %s",
                (player_id, limit),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    return [
        {
            "log_id": int(row[0]),
            "session_id": str(row[1]),
            "query": str(row[2]),
            "terms": str(row[3]),
            "hits": str(row[4]),
            "created_at": str(row[5]),
        }
        for row in rows
    ]


def recent_turns(settings: Settings, *, player_id: str, limit: int = 5) -> list[dict[str, Any]]:
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT turn_id, session_id, deed, reply, artifact_id, created_at "
                "FROM turn_log WHERE player_id = %s ORDER BY turn_id DESC LIMIT %s",
                (player_id, limit),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    return [
        {
            "turn_id": int(row[0]),
            "session_id": str(row[1]),
            "deed": str(row[2]),
            "reply": str(row[3]),
            "artifact_id": None if row[4] is None else str(row[4]),
            "created_at": str(row[5]),
        }
        for row in rows
    ]


def stats(settings: Settings) -> dict[str, Any]:
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = str(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM lore_cards")
            cards = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM lore_query_log")
            queries = int(cursor.fetchone()[0])
    finally:
        connection.close()
    return {"engine_version": version, "lore_cards": cards, "lore_queries": queries}


def _score(row: tuple[str, str, str, str, int], terms: list[str]) -> int:
    _card_id, title, content, tags, weight = row
    score = int(weight)
    for term in terms:
        if term in tags:
            score += 8
        if term in title:
            score += 5
        if term in content:
            score += 1
    return score


def _log_query(
    connection: pymysql.connections.Connection,
    *,
    player_id: str,
    session_id: str,
    query: str,
    terms: list[str],
    hit_ids: list[str],
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lore_query_log "
            "(player_id, session_id, query_text, terms, hit_ids, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                player_id,
                session_id,
                query[:4000],
                " ".join(terms),
                ",".join(str(item) for item in hit_ids),
                datetime.now(_UTC).replace(tzinfo=None),
            ),
        )
        log_id = int(cursor.lastrowid)
    connection.commit()
    return log_id
