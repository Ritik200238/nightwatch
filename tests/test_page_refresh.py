"""Old pages are refreshed one at a time, whoever reads them.

Measured on the box at 10:52 on 11 Oct, during the web deploy's build: its snapshot step reads every
page in turn, each old page was served from the cache and set off a background refresh in a thread
of its own, so they recomputed together - /stop-benchmark queued 26.6 s and /lenses 34.9 s for the
analysis lock. Refreshes now go through one worker, one page at a time, each page queued once.
"""

import io
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture

KEYS = [f"/anchors?limit={i}" for i in range(1, 8)]  # seven pages, as the build reads seven


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


class SlowPage:
    """A page whose computation holds the analysis lock for a while, as /misses does."""

    def __init__(self, client, hold_s: float = 0.2) -> None:
        self.state = client.app.state.nw
        self.hold_s = hold_s
        self.calls = 0
        self.fail_once: set[int] = set()
        self._mu = threading.Lock()

    def __call__(self, *_a, **_k):
        with self._mu:
            self.calls += 1
            n = self.calls
        with self.state.lock:
            time.sleep(self.hold_s)
        if n in self.fail_once:
            raise RuntimeError("database disk image is malformed")
        return [{"name": f"computed-{n}"}]


class ToTheApp:
    """The worker's HTTP call to the box, delivered to the test app; records overlap."""

    def __init__(self, client) -> None:
        self.client = client
        self.paths: list[str] = []
        self.running = 0
        self.most = 0
        self._mu = threading.Lock()

    def __call__(self, req, timeout=None):  # noqa: ANN001
        path = req.full_url.split(":8000", 1)[1]
        with self._mu:
            self.running += 1
            self.most = max(self.most, self.running)
        try:
            r = self.client.get(path, headers=dict(req.header_items()))
        finally:
            with self._mu:
                self.running -= 1
                self.paths.append(path)
        return io.BytesIO(r.content)


def settle(client, timeout: float = 30) -> None:
    pending = getattr(client.app.state, "page_refresh_pending", None)
    if pending is None:  # the code before this change had no count: wait out the burst instead
        time.sleep(3.0)
        return
    deadline = time.monotonic() + timeout
    while pending() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pending() == 0, "the refreshes never finished"


@pytest.fixture
def pages(client, monkeypatch):
    page = SlowPage(client)
    monkeypatch.setattr("nightwatch.journal.anchor.listing", page)
    for k in KEYS:  # the saved copies, then old
        client.get(k)
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 0.0)
    to_app = ToTheApp(client)
    monkeypatch.setattr("urllib.request.urlopen", to_app)
    monkeypatch.setenv("PORT", "8000")
    return page, to_app


def test_a_reader_of_every_old_page_sets_off_their_refreshes_one_at_a_time(client, pages):
    page, to_app = pages
    for k in KEYS:  # the build's snapshot step: one read after another, each answered at once
        r = client.get(k)
        assert r.headers["x-nightwatch-cache"] == "stale"
    settle(client)
    assert to_app.most == 1, "never two refreshes at once"
    assert sorted(to_app.paths) == sorted(KEYS), "each page refreshed exactly once"
    assert page.calls == 2 * len(KEYS)


def test_many_reads_of_one_old_page_refresh_it_once(client, pages):
    page, to_app = pages
    for _ in range(10):
        client.get(KEYS[0])
    settle(client)
    assert to_app.paths == [KEYS[0]]


def test_one_failed_refresh_does_not_stop_the_others_and_keeps_its_old_copy(client, pages, monkeypatch):
    page, to_app = pages
    page.fail_once = {len(KEYS) + 1}  # the first refresh breaks
    for k in KEYS:
        client.get(k)
    settle(client)
    assert sorted(to_app.paths) == sorted(KEYS)
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 3600.0)
    first = client.get(KEYS[0])
    assert first.status_code == 200 and b"computed-1" in first.content, "the failed one kept its old page"


def test_the_worker_starts_again_after_it_has_gone_quiet(client, pages):
    page, to_app = pages
    client.get(KEYS[0])
    settle(client)
    client.get(KEYS[1])
    settle(client)
    assert to_app.paths == [KEYS[0], KEYS[1]]


def test_benchmark_a_chat_during_the_build_burst_waits_for_at_most_one_page(client, pages, capsys):
    """Seven old pages each holding the lock for 0.2 s are read in a row; 0.25 s later a chat asks
    for the lock. Before this change the seven recomputed together and the chat queued behind them."""
    page, to_app = pages
    lock = client.app.state.nw.lock
    for k in KEYS:
        client.get(k)
    time.sleep(0.25)
    t0 = time.monotonic()
    with lock:
        waited = time.monotonic() - t0
    settle(client)
    with capsys.disabled():
        print(f"\nchat waited {waited * 1000:.0f} ms for the lock during the build burst (pages hold it 200 ms each)")
    assert waited < 0.45, "at most the one page being refreshed, not the queue of them"
