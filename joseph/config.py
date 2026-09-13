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
    # optional self-hosted compreface face-recognition backend (operator-controlled corpus)
    compreface_url: str = ""
    compreface_recognition_key: str = ""
    compreface_detection_key: str = ""
    compreface_det_prob_threshold: float = 0.8
    compreface_prediction_count: int = 3

    @classmethod
    def load(cls) -> "Config":
        try:
            det_prob = float(os.environ.get("COMPREFACE_DET_PROB_THRESHOLD", "0.8"))
        except (TypeError, ValueError):
            det_prob = 0.8
        return cls(
            discord_token=os.environ.get("DISCORD_TOKEN", "").strip(),
            guild_id=(_as_int(os.environ.get("GUILD_ID"), 0) or None),
            live_search=_as_bool(os.environ.get("JOSEPH_LIVE_SEARCH"), False),
            max_live_queries=_as_int(os.environ.get("JOSEPH_MAX_LIVE_QUERIES"), 8),
            http_timeout=_as_int(os.environ.get("JOSEPH_HTTP_TIMEOUT"), 12),
            compreface_url=os.environ.get("COMPREFACE_URL", "").strip().rstrip("/"),
            compreface_recognition_key=os.environ.get("COMPREFACE_RECOGNITION_KEY", "").strip(),
            compreface_detection_key=os.environ.get("COMPREFACE_DETECTION_KEY", "").strip(),
            compreface_det_prob_threshold=det_prob,
            compreface_prediction_count=_as_int(os.environ.get("COMPREFACE_PREDICTION_COUNT"), 3),
        )

    @property
    def has_token(self) -> bool:
        return bool(self.discord_token)

    @property
    def has_compreface_recognition(self) -> bool:
        return bool(self.compreface_url and self.compreface_recognition_key)

    @property
    def has_compreface_detection(self) -> bool:
        return bool(self.compreface_url and self.compreface_detection_key)
