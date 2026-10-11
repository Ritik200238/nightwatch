"""Shared test setup.

No test reaches the network. The API builds a client for Bitget's US-stock data service
by default; it is switched off here so a test run neither depends on that service being
up nor sends it traffic.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_external_data_services(monkeypatch):
    monkeypatch.setenv("NIGHTWATCH_BITGET_MCP", "0")
    monkeypatch.setenv("NIGHTWATCH_BITGET_SIGNAL", "0")
    monkeypatch.setenv("NIGHTWATCH_CBOE_OPTIONS", "0")
    monkeypatch.setenv("NIGHTWATCH_BITGET_RWA", "0")
    # Saved pages would carry over between tests that share a module's data folder; the tests of
    # the page store turn it back on with a folder of their own (tests/test_page_store.py).
    monkeypatch.setenv("NIGHTWATCH_PAGE_STORE", "0")
