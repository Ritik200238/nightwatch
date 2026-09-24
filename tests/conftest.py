"""Shared test setup.

No test reaches the network. The API builds a client for Bitget's US-stock data service
by default; it is switched off here so a test run neither depends on that service being
up nor sends it traffic.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_external_data_services(monkeypatch):
    monkeypatch.setenv("NIGHTWATCH_BITGET_MCP", "0")
