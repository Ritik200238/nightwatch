"""The hourly warm-up refreshes the seven cached pages one at a time.

Measured on the box at 06:00:57: the warm-up asked for each page with a plain request, found it an
hour old, was answered from the saved copy at once and set off a background refresh - so the pages
recomputed together, four of them starting inside one second, and /stop-benchmark queued 22 s for
the analysis lock behind /misses. Each warm-up request now asks for a refresh and waits for it.
"""

import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from nightwatch.api.app import CACHED_PAGES, create_app
from nightwatch.config import Settings
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


class FakeUrlopen:
    """Stands in for the warm-up's HTTP calls: records each one's headers and when it ran."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, str], float, float]] = []
        self.running = 0
        self.most = 0
        self.fail_on = fail_on
        self._mu = threading.Lock()

    def __call__(self, req, timeout=None):  # noqa: ANN001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        headers = {k.lower(): v for k, v in (req.header_items() if hasattr(req, "header_items") else [])}
        with self._mu:
            self.running += 1
            self.most = max(self.most, self.running)
        t0 = time.monotonic()
        try:
            time.sleep(0.02)
            if self.fail_on and url.endswith(self.fail_on):
                raise OSError("connection reset")
            return self
        finally:
            with self._mu:
                self.running -= 1
                self.calls.append((url.split("8000", 1)[-1] if "8000" in url else url, headers, t0, time.monotonic()))

    def read(self) -> bytes:
        return b"{}"


def test_the_warm_up_asks_for_every_page_in_turn_as_a_refresh(client, monkeypatch):
    fake = FakeUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setenv("PORT", "8000")
    client.app.state.nw.warm_pages()
    assert [c[0] for c in fake.calls] == list(CACHED_PAGES)
    assert all(c[1].get("x-nw-refresh") == "1" for c in fake.calls), "each one waits for its own recompute"
    assert fake.most == 1, "never two at once"
    assert all(a[3] <= b[2] for a, b in zip(fake.calls, fake.calls[1:], strict=False)), "each starts after the last has finished"


def test_one_page_failing_does_not_stop_the_rest(client, monkeypatch):
    fake = FakeUrlopen(fail_on="/misses")
    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setenv("PORT", "8000")
    client.app.state.nw.warm_pages()
    assert [c[0] for c in fake.calls] == list(CACHED_PAGES)


class Listing:
    def __init__(self) -> None:
        self.calls = 0
        self.fail: BaseException | None = None

    def __call__(self, *_a, **_k):
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        return [{"name": f"computed-{self.calls}"}]


@pytest.fixture
def listing(monkeypatch):
    got = Listing()
    monkeypatch.setattr("nightwatch.journal.anchor.listing", got)
    return got


def test_a_refresh_request_recomputes_an_old_page_and_replaces_the_saved_copy(client, listing, monkeypatch):
    first = client.get("/anchors")
    assert b"computed-1" in first.content
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 0.0)  # the saved copy is now old
    refreshed = client.get("/anchors", headers={"x-nw-refresh": "1"})
    assert refreshed.headers["x-nightwatch-cache"] == "miss" and b"computed-2" in refreshed.content
    assert listing.calls == 2, "recomputed by the request itself, once"
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 60.0)
    after = client.get("/anchors")
    assert after.headers["x-nightwatch-cache"] == "hit" and b"computed-2" in after.content
    assert listing.calls == 2


def test_a_refresh_that_fails_keeps_the_saved_copy_for_visitors(client, listing, monkeypatch):
    client.get("/anchors")
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 0.0)
    listing.fail = HTTPException(status_code=503, detail="The desk is busy.")
    assert client.get("/anchors", headers={"x-nw-refresh": "1"}).status_code == 503
    listing.fail = None
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 60.0)
    visitor = client.get("/anchors")
    assert visitor.status_code == 200 and b"computed-1" in visitor.content, "the old page, not an error"
