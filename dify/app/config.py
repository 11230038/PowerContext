"""Runtime configuration for the Cat Tavern backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    seekdb_host: str = field(default_factory=lambda: _env("SEEKDB_HOST", "127.0.0.1"))
    seekdb_port: int = field(default_factory=lambda: int(_env("SEEKDB_PORT", "2881")))
    seekdb_user: str = field(default_factory=lambda: _env("SEEKDB_USER", "root"))
    seekdb_password: str = field(default_factory=lambda: _env("SEEKDB_PASSWORD", ""))
    seekdb_database: str = field(default_factory=lambda: _env("TAVERN_DB", "tavern"))
    state_db: Path = field(
        default_factory=lambda: Path(
            _env("TAVERN_STATE_DB", str(ROOT / ".state" / "tavern-powercontext.db"))
        )
    )

    def pointer_path(self) -> Path:
        return self.state_db.with_name("tavern-memory-pointer.json")
