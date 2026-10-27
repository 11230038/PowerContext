"""Runtime settings, all overridable through environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


@dataclass(frozen=True, slots=True)
class Settings:
    seekdb_host: str = field(default_factory=lambda: os.environ.get("SEEKDB_HOST", "127.0.0.1"))
    seekdb_port: int = field(default_factory=lambda: int(os.environ.get("SEEKDB_PORT", "2881")))
    seekdb_user: str = field(default_factory=lambda: os.environ.get("SEEKDB_USER", "root"))
    seekdb_password: str = field(default_factory=lambda: os.environ.get("SEEKDB_PASSWORD", ""))
    seekdb_database: str = field(default_factory=lambda: os.environ.get("SEEKDB_DATABASE", "sdd_context"))
    state_db: Path = field(
        default_factory=lambda: _path_from_env(
            "POWERCONTEXT_STATE_DB",
            PACKAGE_ROOT / ".state" / "powercontext.db",
        )
    )
    minimax_api_key: str = field(default_factory=lambda: os.environ.get("MINIMAX_API_KEY", ""))
    minimax_base_url: str = field(
        default_factory=lambda: os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
    )
    minimax_model: str = field(default_factory=lambda: os.environ.get("MINIMAX_MODEL", "MiniMax-M3"))
    artifacts_dir: Path = field(
        default_factory=lambda: _path_from_env("SDD_ARTIFACTS_DIR", PACKAGE_ROOT / "artifacts")
    )

    def state_pointer(self) -> Path:
        return self.state_db.with_name("state-pointer.json")
