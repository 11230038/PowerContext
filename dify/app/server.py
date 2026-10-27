"""HTTP API used by the Dify Cat Tavern chatflow.

Dify calls three endpoints:

* ``GET  /memory/{player_id}``  - load the player's cross-session memory;
* ``GET  /lore``                 - retrieve lore cards from seekdb;
* ``POST /memory/{player_id}``  - append the current deed to PowerContext.

``GET /debug/state/{player_id}`` exists only for validation evidence.
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import memory
import seekdb_store
from config import Settings

logger = logging.getLogger("cat-tavern")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

settings = Settings()
_PLAYER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class MemoryWrite(BaseModel):
    deed: str = Field(min_length=1, max_length=500)
    reply: str = Field(default="", max_length=4000)
    session_id: str = Field(default="default", max_length=64)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seekdb_store.ensure_schema(settings)
    seeded = seekdb_store.seed_cards(settings)
    logger.info("seekdb ready: %s lore cards", seeded)
    yield


app = FastAPI(title="Cat Tavern Memory API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "猫酒馆记忆 API",
        "endpoints": [
            "GET /memory/{player_id}",
            "POST /memory/{player_id}",
            "GET /lore?q=...",
            "GET /debug/state/{player_id}",
        ],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        details = seekdb_store.stats(settings)
    except Exception as error:  # pragma: no cover - surfaced to the operator
        raise HTTPException(status_code=503, detail=f"seekdb unavailable: {error}") from error
    return {
        "status": "ok",
        **details,
        "memory_backend": "PowerContext Atomic Memory",
        "state_db": str(settings.state_db),
    }


@app.get("/memory/{player_id}")
async def read_memory(player_id: str) -> dict[str, Any]:
    _validate_player(player_id)
    return await memory.load_memory(settings, player_id)


@app.post("/memory/{player_id}")
async def write_memory(player_id: str, body: MemoryWrite) -> dict[str, Any]:
    _validate_player(player_id)
    state = await memory.save_memory(
        settings,
        player_id,
        deed=body.deed.strip(),
        reply=body.reply,
        session_id=body.session_id,
    )
    turn_id = seekdb_store.log_turn(
        settings,
        player_id=player_id,
        session_id=body.session_id,
        deed=body.deed.strip(),
        reply=body.reply,
        artifact_id=state.get("artifact_id"),
    )
    logger.info("memory saved player=%s artifact=%s turn=%s", player_id, state["artifact_id"], turn_id)
    return {**state, "turn_id": turn_id}


@app.get("/lore")
async def lore(
    q: str = Query(min_length=1, max_length=500),
    player_id: str = Query(default="anonymous", max_length=64),
    session_id: str = Query(default="default", max_length=64),
    limit: int = Query(default=3, ge=1, le=5),
) -> dict[str, Any]:
    _validate_player(player_id)
    result = seekdb_store.search_lore(
        settings,
        query=q,
        player_id=player_id,
        session_id=session_id,
        limit=limit,
    )
    logger.info(
        "lore query player=%s log=%s hits=%s",
        player_id,
        result["query_log_id"],
        [hit["card_id"] for hit in result["hits"]],
    )
    return result


@app.get("/debug/state/{player_id}")
async def debug_state(player_id: str) -> dict[str, Any]:
    _validate_player(player_id)
    state = await memory.load_memory(settings, player_id)
    return {
        "player_id": player_id,
        "memory": state,
        "recent_turns": seekdb_store.recent_turns(settings, player_id=player_id),
        "recent_lore_queries": seekdb_store.recent_queries(settings, player_id=player_id),
        "seekdb": seekdb_store.stats(settings),
    }


@app.post("/debug/reset/{player_id}")
async def debug_reset(player_id: str) -> dict[str, Any]:
    _validate_player(player_id)
    return await memory.reset_memory(settings, player_id)


def _validate_player(player_id: str) -> None:
    if not _PLAYER_ID.fullmatch(player_id):
        raise HTTPException(
            status_code=400,
            detail="player_id must be 1-64 characters: letters, digits, _ or -",
        )
