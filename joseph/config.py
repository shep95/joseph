"""runtime configuration, read once from the environment.

zero-touch: no secret values are ever logged or echoed. missing optional values fall
back to safe defaults so the bot always starts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional at runtime (railway injects real env vars)
    pass


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: int | None
    live_search: bool
    max_live_queries: int
    http_timeout: int

    @classmethod
    def load(cls) -> "Config":
        return cls(
            discord_token=os.environ.get("DISCORD_TOKEN", "").strip(),
            guild_id=(_as_int(os.environ.get("GUILD_ID"), 0) or None),
            live_search=_as_bool(os.environ.get("JOSEPH_LIVE_SEARCH"), False),
            max_live_queries=_as_int(os.environ.get("JOSEPH_MAX_LIVE_QUERIES"), 8),
            http_timeout=_as_int(os.environ.get("JOSEPH_HTTP_TIMEOUT"), 12),
        )

    @property
    def has_token(self) -> bool:
        return bool(self.discord_token)
