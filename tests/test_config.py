"""The universe size is config-driven, not a number baked into the UI or API.

These tests exist because the product shipped with exactly 24 hardcoded core
tickers for a while, and several places (docs, a stale UI badge) quoted "24"
as if it were permanent. The fix is that the *count* is never hardcoded
anywhere except this one tuple, which the env var below can override; these
tests pin that behaviour down so a future change can't silently reintroduce
a hardcoded number in a component instead of reading Settings.
"""

from __future__ import annotations

from nightwatch.config import DEFAULT_CORE_TICKERS, Settings, load_settings


def test_default_core_tickers_is_not_the_old_24():
    # This is intentionally >24: the universe was expanded from the original
    # 24-ticker list. If this regresses back to 24 (or fewer), something
    # reverted the expansion.
    assert len(DEFAULT_CORE_TICKERS) > 24
    assert len(set(DEFAULT_CORE_TICKERS)) == len(DEFAULT_CORE_TICKERS), "no duplicate tickers"


def test_core_tickers_env_override_changes_the_count(monkeypatch):
    monkeypatch.setenv("NIGHTWATCH_CORE_TICKERS", "TSLA,NVDA,AAPL")
    settings = load_settings()
    assert settings.core_tickers == ("TSLA", "NVDA", "AAPL")
    assert len(settings.core_tickers) == 3


def test_settings_core_tickers_defaults_to_the_shared_tuple(monkeypatch):
    monkeypatch.delenv("NIGHTWATCH_CORE_TICKERS", raising=False)
    settings = Settings()
    assert settings.core_tickers == DEFAULT_CORE_TICKERS
