"""Cached pages survive a restart.

Measured after restarts on the box: with the page cache empty, the first visitors' pages were
recomputed while they waited and under the analysis lock (/misses held it 31 s, a chat queued 24 s
behind it; /sources took 117-126 s). Saved pages are now read back at start-up.
"""

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from nightwatch.api import page_store as ps
from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture


class Wall:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


def store(tmp_path, wall=None, **kw) -> ps.PageStore:
    return ps.PageStore(tmp_path / "pages", version=kw.pop("version", "1.0"), max_age_s=kw.pop("max_age_s", 3600.0), wall=wall or Wall(), **kw)


def anything(_k: str) -> bool:
    return True


def test_a_saved_page_reads_back_with_its_age(tmp_path):
    wall = Wall()
    s = store(tmp_path, wall)
    assert s.save("/misses?", b'{"a":1}', "application/json")
    wall.t += 90
    got = store(tmp_path, wall).load(anything)
    assert got == {"/misses?": (90.0, b'{"a":1}', "application/json")}


def test_a_page_too_old_is_not_used_and_is_deleted(tmp_path):
    wall = Wall()
    s = store(tmp_path, wall, max_age_s=600)
    s.save("/misses?", b"x", "application/json")
    wall.t += 601
    assert s.load(anything) == {}
    assert list((tmp_path / "pages").iterdir()) == []


def test_a_page_from_another_version_is_not_used(tmp_path):
    store(tmp_path, version="1.0").save("/misses?", b"x", "application/json")
    assert store(tmp_path, version="1.1").load(anything) == {}


def test_a_page_whose_key_is_not_allowed_is_not_used(tmp_path):
    s = store(tmp_path)
    s.save("/health?", b"x", "application/json")
    assert s.load(lambda k: k.startswith("/misses")) == {}


@pytest.mark.parametrize("damage", ["truncate", "garbage", "rename"])
def test_a_damaged_file_is_ignored_and_deleted(tmp_path, damage):
    s = store(tmp_path)
    s.save("/misses?", b'{"rows":[1,2,3]}', "application/json")
    (f,) = list((tmp_path / "pages").iterdir())
    if damage == "truncate":
        f.write_bytes(f.read_bytes()[:-3])  # body shorter than its header says
    elif damage == "garbage":
        f.write_bytes(b"not json\n{}")
    else:
        f.rename(f.with_name("0" * 32 + ".page"))  # not where its key says it lives
    assert s.load(anything) == {}
    assert list((tmp_path / "pages").iterdir()) == []


def test_an_interrupted_save_leaves_the_previous_page(tmp_path):
    s = store(tmp_path)
    s.save("/misses?", b"old", "application/json")
    (final,) = list((tmp_path / "pages").iterdir())
    (tmp_path / "pages" / (final.name + ".123.9.tmp")).write_bytes(b"half a pa")  # a crash mid-write
    got = s.load(anything)
    assert got["/misses?"][1] == b"old"
    assert [p.name for p in (tmp_path / "pages").iterdir()] == [final.name], "the leftover is cleared"


def test_a_save_that_cannot_write_says_so_and_does_not_raise(tmp_path):
    (tmp_path / "pages").write_text("a file where the folder should be")
    assert store(tmp_path).save("/misses?", b"x", "application/json") is False


def test_only_the_newest_pages_are_kept_past_the_limit(tmp_path):
    wall = Wall()
    s = store(tmp_path, wall, max_files=2)
    for i in range(4):
        s.save(f"/calibration?ticker=T{i}", b"x", "application/json")
        wall.t += 10
    assert sorted(s.load(anything)) == ["/calibration?ticker=T2", "/calibration?ticker=T3"]


# --- through the API: a restart ------------------------------------------------------------------------


class Listing:
    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay
        self.fail: BaseException | None = None

    def __call__(self, *_a, **_k):
        self.calls += 1
        time.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return [{"name": f"computed-{self.calls}"}]


@pytest.fixture
def settings(seeded_store, monkeypatch):  # noqa: F811
    import shutil

    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setenv("NIGHTWATCH_PAGE_STORE", "1")
    shutil.rmtree(seeded_store.parent / "page_cache", ignore_errors=True)  # the folder is shared by the module's tests
    return Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))


@pytest.fixture
def listing(monkeypatch):
    got = Listing()
    monkeypatch.setattr("nightwatch.journal.anchor.listing", got)
    return got


class Refreshes:
    """Records the background refreshes a stale page sets off (they go over HTTP to the box)."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, req, timeout=None):  # noqa: ANN001
        self.urls.append(getattr(req, "full_url", str(req)))
        raise OSError("no server in tests")


def test_after_a_restart_the_saved_page_is_served_at_once_without_recomputing(settings, listing, monkeypatch):
    refreshes = Refreshes()
    monkeypatch.setattr("urllib.request.urlopen", refreshes)
    with TestClient(create_app(settings, warm=False)) as before:
        assert b"computed-1" in before.get("/anchors").content
    assert listing.calls == 1
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 0.0)  # what was saved is old by now
    with TestClient(create_app(settings, warm=False)) as after:
        for _ in range(3):
            r = after.get("/anchors")
            assert r.status_code == 200 and b"computed-1" in r.content and r.headers["x-nightwatch-cache"] == "stale"
        time.sleep(0.2)
    assert listing.calls == 1, "nothing was recomputed for the first visitors"
    assert refreshes.urls == [], "and none of them set off a refresh: the warm-up does that, one page at a time"


def test_the_warm_ups_refresh_replaces_the_restored_page_on_disk_too(settings, listing):
    with TestClient(create_app(settings, warm=False)) as before:
        before.get("/anchors")
    with TestClient(create_app(settings, warm=False)) as after:
        r = after.get("/anchors", headers={"x-nw-refresh": "1"})
        assert b"computed-2" in r.content and r.headers["x-nightwatch-cache"] == "miss"
    with TestClient(create_app(settings, warm=False)) as again:
        assert b"computed-2" in again.get("/anchors").content
    assert listing.calls == 2


def test_a_failed_recompute_never_replaces_the_saved_page(settings, listing):
    with TestClient(create_app(settings, warm=False)) as before:
        before.get("/anchors")
    listing.fail = HTTPException(status_code=503, detail="The desk is busy.")
    with TestClient(create_app(settings, warm=False)) as after:
        assert after.get("/anchors", headers={"x-nw-refresh": "1"}).status_code == 503
    listing.fail = None
    with TestClient(create_app(settings, warm=False)) as again:
        assert b"computed-1" in again.get("/anchors").content


def test_once_the_grace_is_over_a_restored_page_refreshes_as_before(settings, listing, monkeypatch):
    refreshes = Refreshes()
    monkeypatch.setattr("urllib.request.urlopen", refreshes)
    with TestClient(create_app(settings, warm=False)) as before:
        before.get("/anchors")
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 0.0)
    monkeypatch.setattr("nightwatch.api.app.PAGE_RESTORED_GRACE_S", 0.0)
    with TestClient(create_app(settings, warm=False)) as after:
        assert after.get("/anchors").headers["x-nightwatch-cache"] == "stale"
        deadline = time.monotonic() + 3
        while not refreshes.urls and time.monotonic() < deadline:
            time.sleep(0.02)
    assert refreshes.urls and refreshes.urls[0].endswith("/anchors?")


def test_a_saved_page_past_the_cap_is_recomputed(settings, listing, monkeypatch):
    with TestClient(create_app(settings, warm=False)) as before:
        before.get("/anchors")
    time.sleep(0.05)
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_STALE_S", 0.01)  # the cap, shrunk: the saved page is past it
    with TestClient(create_app(settings, warm=False)) as after:
        r = after.get("/anchors")
    assert r.headers["x-nightwatch-cache"] == "miss" and b"computed-2" in r.content


def test_cold_start_first_request_benchmark(settings, monkeypatch, capsys):
    """Not a speed test of the machine: the first request after a restart, with and without the
    saved page, for a page that takes 0.5 s to compute."""
    slow = Listing(delay=0.5)
    monkeypatch.setattr("nightwatch.journal.anchor.listing", slow)
    with TestClient(create_app(settings, warm=False)) as before:
        before.get("/anchors")
    with TestClient(create_app(settings, warm=False)) as after:
        t0 = time.perf_counter()
        after.get("/anchors")
        with_saved = time.perf_counter() - t0
    import shutil

    shutil.rmtree(settings.data_dir / "page_cache")
    with TestClient(create_app(settings, warm=False)) as cold:
        t0 = time.perf_counter()
        cold.get("/anchors")
        without = time.perf_counter() - t0
    with capsys.disabled():
        print(f"\nfirst /anchors after a restart: saved page {with_saved * 1000:.0f} ms, none {without * 1000:.0f} ms")
    assert with_saved < 0.25 <= 0.5 <= without


def test_a_page_recomputed_after_the_restart_refreshes_normally_again(settings, listing, monkeypatch):
    """The grace covers the copy read back from disk, not the page the warm-up has since recomputed."""
    refreshes = Refreshes()
    monkeypatch.setattr("urllib.request.urlopen", refreshes)
    with TestClient(create_app(settings, warm=False)) as before:
        before.get("/anchors")
    with TestClient(create_app(settings, warm=False)) as after:
        after.get("/anchors", headers={"x-nw-refresh": "1"})  # the warm-up's recompute
        monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 0.0)
        assert after.get("/anchors").headers["x-nightwatch-cache"] == "stale"
        deadline = time.monotonic() + 3
        while not refreshes.urls and time.monotonic() < deadline:
            time.sleep(0.02)
    assert refreshes.urls, "an old page that is not the restored copy is refreshed as before"
