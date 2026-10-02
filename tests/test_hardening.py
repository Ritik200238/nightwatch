import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwatch.api import guard, providers
from nightwatch.api.app import PAGE_CACHE_MAX, TicketIn, create_app
from nightwatch.config import Settings
from tests.test_api import AS_OF, _frozen_clock, client  # noqa: F401 - fixtures
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture

SECRET_H = {guard.SECRET_HEADER: "s3cret"}


@pytest.fixture(autouse=True)
def _strict_chat_limit(monkeypatch):
    """One chat a minute, two in a burst: a test machine slow enough to refill the real
    12-a-minute bucket between requests made these tests pass or fail by timing."""
    monkeypatch.setattr(guard, "RULES", (("POST", "/chat", 1, 2),) + tuple(r for r in guard.RULES if r[1] != "/chat"))


def test_secret_unset_lets_everything_through(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv(guard.SECRET_ENV, raising=False)
    assert client.get("/universe").status_code == 200


def test_secret_blocks_missing_and_wrong_but_not_health_or_valid(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv(guard.SECRET_ENV, "s3cret")
    assert client.get("/universe").status_code == 403
    assert client.get("/universe", headers={guard.SECRET_HEADER: "nope"}).status_code == 403
    assert client.post("/tonight", json={}).status_code == 403
    assert client.get("/health").status_code == 200
    assert client.get("/universe", headers=SECRET_H).status_code == 200


def test_localhost_skips_the_secret(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setenv(guard.SECRET_ENV, "s3cret")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA",))
    with TestClient(create_app(settings, warm=False), client=("127.0.0.1", 5000)) as c:
        assert c.get("/universe").status_code == 200


def _chat_burst(c, headers, n):  # noqa: ANN001
    return [c.post("/chat", json={"messages": []}, headers=headers).status_code for _ in range(n)]


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv(guard.SECRET_ENV, raising=False)
    codes = _chat_burst(client, {}, 8)
    assert 429 in codes and codes[0] != 429
    r = client.post("/chat", json={"messages": []})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "detail" in r.json()


def test_limits_are_per_forwarded_client_when_secret_validates(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv(guard.SECRET_ENV, "s3cret")
    a = {**SECRET_H, guard.CLIENT_IP_HEADER: "1.1.1.1"}
    b = {**SECRET_H, guard.CLIENT_IP_HEADER: "2.2.2.2"}
    assert 429 in _chat_burst(client, a, 8)
    assert client.post("/chat", json={"messages": []}, headers=b).status_code != 429


def test_the_internal_marker_never_exempts_from_rate_limits(client, monkeypatch):  # noqa: F811
    """The proxy adds the secret to every visitor's request, so a header the visitor can send
    must not lift the limit: anyone could have had unlimited model calls."""
    monkeypatch.setenv(guard.SECRET_ENV, "s3cret")
    spoof = {**SECRET_H, "x-nw-internal": "1", guard.CLIENT_IP_HEADER: "3.3.3.3"}
    assert 429 in _chat_burst(client, spoof, 10)


def test_cached_pages_still_need_the_secret(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv(guard.SECRET_ENV, "s3cret")
    assert client.get("/studies", headers=SECRET_H).status_code == 200  # fills the cache
    assert client.get("/studies", headers={guard.CLIENT_IP_HEADER: "9.9.9.9"}).status_code in (403,)


def test_limiter_is_bounded_and_refills():
    now = [0.0]
    rl = guard.RateLimiter(max_buckets=50, clock=lambda: now[0])
    for i in range(500):
        rl.take("g", f"c{i}", 60, 1)
    assert len(rl) == 50
    assert rl.take("g", "x", 60, 1) == 0 and rl.take("g", "x", 60, 1) > 0
    now[0] += 1.0
    assert rl.take("g", "x", 60, 1) == 0


def test_input_limits(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv(guard.SECRET_ENV, raising=False)
    ticket = {"ticker": "TSLA", "notional_quote": 1000, "as_of": AS_OF.isoformat()}
    assert client.post("/analyze", json={**ticket, "notional_quote": 10_000_001}).status_code == 422
    assert client.post("/analyze", json={**ticket, "notional_quote": 0}).status_code == 422
    too_many = [{"ticker": "TSLA", "notional_quote": 1}] * 21
    assert client.post("/analyze", json={**ticket, "open_positions": too_many}).status_code == 422
    assert client.post("/tonight", json={"positions": too_many}).status_code == 422
    assert client.post("/chat", json={"messages": [{"role": "user", "content": "x" * 2001}]}).status_code == 422
    assert client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}] * 31}).status_code == 422
    TicketIn(**ticket)


def test_page_cache_only_stores_known_params(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv(guard.SECRET_ENV, raising=False)
    assert client.get("/studies", params={"junk": "1"}).headers["x-nightwatch-cache"] == "miss"
    assert client.get("/studies", params={"junk": "1"}).headers["x-nightwatch-cache"] == "miss"  # never cached
    client.get("/studies")
    assert client.get("/studies", params={"nw_client": "abc"}).headers["x-nightwatch-cache"] == "hit"
    assert PAGE_CACHE_MAX == 200


def test_calibration_cache_is_bounded(client):  # noqa: F811
    cache = client.app.state.nw.calibration_cache
    for i in range(300):
        cache[(f"t{i}", "")] = (None, {})
    assert len(cache) == 100


def test_agent_job_table_keeps_300():
    from nightwatch.api.agent import AgentJobs

    assert AgentJobs()._keep == 300


def test_llm_slots_cap_concurrency_and_time_out(monkeypatch):
    monkeypatch.setattr(providers, "_llm_slots", threading.BoundedSemaphore(2))
    with providers.llm_slot() as a, providers.llm_slot() as b:
        assert a and b
        t0 = time.monotonic()
        with providers.llm_slot(wait_s=0.1) as c:
            assert c is False and time.monotonic() - t0 < 2
    with providers.llm_slot(wait_s=0.1) as d:
        assert d


def test_backup_is_consistent_gzipped_and_pruned(tmp_path):
    import gzip
    from datetime import datetime

    from nightwatch.journal import backup

    db = tmp_path / "live.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (7)")
    c.commit()
    c.close()
    out = tmp_path / "backups"
    for day in range(1, 10):
        backup.backup_now(db, out, keep=7, today=datetime(2026, 10, day))
    files = sorted(out.glob("*.gz"))
    assert len(files) == 7 and files[0].name == "nightwatch-20261003.sqlite.gz" and not list(out.glob("*.sqlite"))
    restored = tmp_path / "r.sqlite"
    restored.write_bytes(gzip.decompress(files[-1].read_bytes()))
    assert sqlite3.connect(restored).execute("SELECT x FROM t").fetchone() == (7,)
    assert backup.newest_age_s(out) < 60
