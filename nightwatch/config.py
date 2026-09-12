"""Runtime configuration from environment variables with safe defaults.

Nothing here is secret except optional API keys; all data sources work without keys.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


# The names we backfill first and record order books for. Chosen for liquidity and
# because they are the tokens a retail trader is most likely to hold overnight.
DEFAULT_CORE_TICKERS: tuple[str, ...] = (
    "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NFLX", "AMD", "PLTR",
    "MSTR", "HOOD", "COIN", "BABA", "CRCL", "AVGO", "TSM", "INTC", "MU", "SMCI",
    "SPY", "QQQ", "TQQQ", "SQQQ",
)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _env_path("NIGHTWATCH_DATA_DIR", PROJECT_ROOT / "data"))
    db_filename: str = field(default_factory=lambda: os.environ.get("NIGHTWATCH_DB", "nightwatch.sqlite"))
    fred_api_key: str | None = field(default_factory=lambda: os.environ.get("FRED_API_KEY") or None)
    core_tickers: tuple[str, ...] = field(default_factory=lambda: _env_list("NIGHTWATCH_CORE_TICKERS", DEFAULT_CORE_TICKERS))
    recorder_interval_sec: int = field(default_factory=lambda: int(os.environ.get("NIGHTWATCH_RECORDER_INTERVAL", "60")))
    recorder_retention_days: int = field(default_factory=lambda: int(os.environ.get("NIGHTWATCH_RECORDER_RETENTION_DAYS", "120")))
    bitget_rate_per_sec: float = field(default_factory=lambda: float(os.environ.get("NIGHTWATCH_BITGET_RPS", "8")))
    # Feature frames are a few MB each. On a small box, cap the cache at one frame per
    # token rather than the default, which allows several hours of history per token.
    frame_cache_size: int = field(default_factory=lambda: int(os.environ.get("NIGHTWATCH_FRAME_CACHE", "64")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename


def load_settings() -> Settings:
    return Settings()
