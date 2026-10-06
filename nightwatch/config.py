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


# The names we backfill first and record order books for. Originally 24 tickers
# chosen for liquidity; expanded to the ranked shortlist in UNIVERSE_CANDIDATES.md
# (S&P 500 constituents + well-known ETFs, cross-referenced against Bitget's live
# R-token list and spot-checked against Yahoo Finance). Override with the
# NIGHTWATCH_CORE_TICKERS env var (comma-separated) instead of editing this tuple
# if you want a different set without a code change — Settings.core_tickers already
# reads that env var first. A 100+-entry tuple is kept here, not split into a JSON/
# YAML file, because it is small, rarely edited, and type-checked at import time;
# revisit if this grows past a few hundred entries.
DEFAULT_CORE_TICKERS: tuple[str, ...] = (
    "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NFLX", "AMD", "PLTR",
    "MSTR", "HOOD", "COIN", "BABA", "CRCL", "AVGO", "TSM", "INTC", "MU", "SMCI",
    "SPY", "QQQ", "TQQQ", "SQQQ", "ABBV", "ABNB", "ABT", "ADBE", "ADSK", "AMGN",
    "ANET", "ARKK", "AXP", "BA", "BAC", "BKNG", "BLK", "BMY", "C", "CHTR",
    "CMCSA", "CMG", "COP", "COST", "CRM", "CSCO", "CVS", "CVX", "DE", "DELL",
    "DHR", "DIA", "DIS", "DUK", "EOG", "F", "FTNT", "GE", "GILD", "GLD",
    "GM", "GS", "HD", "HON", "HPQ", "IBM", "INTU", "IWM", "JNJ", "JPM",
    "KO", "LLY", "LMT", "LOW", "MA", "MCD", "MDLZ", "MDT", "MO", "MRK",
    "MS", "NEE", "NKE", "NOW", "NSC", "ORCL", "PANW", "PEP", "PFE", "PG",
    "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SLB", "SLV", "SMH", "T",
    "TGT", "TLT", "TMO", "TMUS", "TXN", "UBER", "UNH", "V", "VZ", "WFC",
    "WMT", "XOM",
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
