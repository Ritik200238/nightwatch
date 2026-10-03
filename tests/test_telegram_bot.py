"""The Telegram bot against a fake Bot API: no network, the real desk behind it."""

import json
from datetime import timedelta

import httpx
import pytest

from nightwatch.api import guard, telegram_bot
from nightwatch.api.telegram_bot import TelegramBot
from nightwatch.journal import telegram, tripwires
from nightwatch.time_utils import to_epoch_ms, utc_now
from tests import test_api
from tests.test_api import _frozen_clock  # noqa: F401 - autouse: the chat analyses "now"
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture the client fixture depends on

client = test_api.client
CHAT = 4242


class FakeApi:
    """Stands in for BotApi: records what the bot says, serves queued updates."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.batches: list = []
        self.typing_calls = 0

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    def typing(self, chat_id):
        self.typing_calls += 1

    def get_updates(self, offset, timeout_s=50):
        item = self.batches.pop(0) if self.batches else []
        if isinstance(item, Exception):
            raise item
        return item


def msg(text, chat=CHAT, **kw):
    return {"update_id": kw.pop("update_id", 1), "message": {"chat": {"id": chat}, "from": {"id": chat, "language_code": kw.pop("lang", "en")}, "text": text, **kw}}


@pytest.fixture
def desk(client, monkeypatch):
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    calls = []

    def chat_fn(messages, context_id):
        calls.append((messages, context_id))
        r = client.post("/chat", json={"messages": messages, "context_forecast_id": context_id})
        if r.status_code != 200:
            err = Exception(r.text)
            err.detail = r.json().get("detail")
            raise err
        return r.json()

    api = FakeApi()
    bot = TelegramBot(api, client.app.state.nw, chat_fn, limiter=guard.RateLimiter(), workers=0)
    conn = client.app.state.nw.store._conn
    with conn:
        conn.execute("DELETE FROM tripwires")
        conn.execute("DELETE FROM watches")
    bot.calls, bot.fake = calls, api
    return bot


def last(bot) -> str:
    return bot.fake.sent[-1][1]


def test_without_a_token_the_bot_is_off(client, monkeypatch):
    monkeypatch.delenv(telegram.TOKEN_ENV, raising=False)
    assert client.app.state.telegram is None
    assert telegram_bot.start_if_configured(client.app.state.nw, lambda m, c: {}) is None


def test_a_trade_in_plain_words_gets_the_sized_verdict_from_the_report(desk, client):
    desk.handle_update(msg("long 20k TSLA overnight, stop 300, because momentum"))
    text = last(desk)
    fid = desk.session(CHAT).context_id
    rep = client.app.state.nw.reports.get(fid)
    hz = rep["analog"]["horizons"][rep["primary_horizon"]]
    v = rep["verdict"]
    assert f"Verdict: {v['verdict']}" in text and f"{v['recommended_notional']:,.0f} USDT" in text
    assert f"One-in-twenty loss: {hz['loss_p5_pct']:+.1f}%" in text
    assert "Worst stress: " in text and "Exit cost: " in text
    ex = rep["execution"]["exit_quote"]
    assert f"{ex['total_cost_bps']:.1f} bps" in text
    worst = min(i["total_pnl_quote"] for i in rep["stress"]["impacts"])
    assert f"{worst:+,.0f} USDT" in text
    assert text.count(f"https://nightwatch-gules.vercel.app/r/{fid}") == 1
    assert "Liquidation" not in text  # not leveraged
    assert desk.fake.typing_calls == 1 and len(text) < 1500


def test_a_leveraged_trade_shows_the_liquidation_price(desk, client):
    desk.handle_update(msg("long 20k TSLA 5x leverage over the weekend"))
    rep = client.app.state.nw.reports.get(desk.session(CHAT).context_id)
    assert f"Liquidation (5x): {rep['leverage']['liquidation_price']:,.2f}" in last(desk)


def test_a_missing_field_is_asked_for_and_the_answer_completes_it(desk):
    desk.handle_update(msg("what about tesla?"))
    assert "long or short" in last(desk) and "Verdict:" not in last(desk)
    assert desk.session(CHAT).context_id is None
    desk.handle_update(msg("long 20k"))
    assert "Verdict:" in last(desk) and "TSLA" in last(desk)


def test_follow_ups_use_the_report_in_this_chat_only(desk):
    desk.handle_update(msg("long 20k TSLA overnight"))
    before = desk.session(CHAT).context_id
    desk.handle_update(msg("why was it sized like that?"))
    assert desk.calls[-1][1] == before and "Verdict:" not in last(desk)
    desk.handle_update(msg("hello?", chat=99))
    assert desk.calls[-1][1] is None  # another chat does not inherit the report
    desk.handle_update(msg("/new"))
    assert desk.session(CHAT).context_id is None


def test_chinese_is_answered_in_chinese(desk):
    desk.handle_update(msg("周末做多特斯拉 2万U", lang="zh-hans"))
    assert "结论" in last(desk) and "TSLA" in last(desk)


def test_rate_limit_stops_a_flood_before_the_desk_runs(desk):
    for i in range(6):
        desk.handle_update(msg("what about tesla?", update_id=i))
    assert len(desk.calls) == 3  # the burst
    assert "Slow down" in last(desk)
    desk.handle_update(msg("hello", chat=7))
    assert len(desk.calls) == 4  # another chat is unaffected


def test_edits_stickers_bots_and_empty_text_are_ignored(desk):
    desk.handle_update({"update_id": 1, "edited_message": {"chat": {"id": CHAT}, "text": "long 5k TSLA"}})
    desk.handle_update({"update_id": 2, "message": {"chat": {"id": CHAT}, "sticker": {}}})
    desk.handle_update({"update_id": 3, "message": {"chat": {"id": CHAT}, "from": {"is_bot": True}, "text": "hi"}})
    desk.handle_update(msg("   "))
    desk.handle_update({"update_id": 5})
    assert desk.fake.sent == [] and desk.calls == []


def test_a_desk_error_becomes_a_message_not_a_crash(desk):
    desk.chat_fn = lambda m, c: (_ for _ in ()).throw(RuntimeError("secret 123:abc"))
    desk.handle_update(msg("long 20k TSLA"))
    assert "went wrong" in last(desk) and "secret" not in last(desk)


def test_help_in_both_languages(desk):
    desk.handle_update(msg("/start"))
    assert "/tripwire" in last(desk) and "Nightwatch" in last(desk)
    desk.handle_update(msg("/help@my_bot", chat=5, lang="zh"))
    assert "压力测试" in last(desk)


def test_tripwire_needs_a_report_then_arms_for_this_chat_and_delivers(desk, client, monkeypatch):
    desk.handle_update(msg("/tripwire 295"))
    assert "Tell me a trade first" in last(desk)
    desk.handle_update(msg("long 20k TSLA overnight, stop 300, because momentum, wrong if it closes below 290"))
    fid = desk.session(CHAT).context_id
    desk.handle_update(msg("/tripwire"))
    assert "stop: 300.00" in last(desk)
    desk.handle_update(msg("/tripwire stop"))
    assert last(desk).startswith("Armed: TSLA below 300.00")
    desk.handle_update(msg("/tripwire nonsense"))
    assert "I need a price" in last(desk)
    conn = client.app.state.nw.store._conn
    row = conn.execute("SELECT webhook, client, status FROM tripwires WHERE forecast_id=?", (fid,)).fetchone()
    assert row[0] == f"tg:{CHAT}" and row[2] == "armed" and str(CHAT) not in row[1]  # the client column is the hash

    sent = []
    monkeypatch.setattr(telegram, "send_message", lambda chat, text, **k: sent.append((chat, text)) or "telegram ok")
    bar = (to_epoch_ms(utc_now() + timedelta(minutes=1)), 298.5, 310.0)
    s = client.app.state.nw
    n = tripwires.run_armed(conn, lambda t, since: [bar], lambda rep: rep, s.reports.get)
    assert n == 1 and len(sent) == 1
    chat, text = sent[0]
    assert chat == CHAT and "TSLA traded below 300.00" in text and f"/r/{fid}" in text
    armed = tripwires.for_report(conn, fid, desk.client_of(CHAT))[0]
    assert armed["status"] == "fired" and armed["webhook_status"] == "telegram ok"
    n = tripwires.run_armed(conn, lambda t, since: [bar], lambda rep: rep, s.reports.get)
    assert n == 0 and len(sent) == 1  # fires once


def test_a_bad_price_is_refused_in_words(desk):
    desk.handle_update(msg("long 20k TSLA overnight"))
    desk.handle_update(msg("/tripwire -5"))
    assert "positive" in last(desk)


def test_watch_arms_a_recheck_delivered_to_this_chat(desk, client):
    desk.handle_update(msg("/watch"))
    assert "Tell me a trade first" in last(desk)
    desk.handle_update(msg("long 20k TSLA overnight"))
    desk.handle_update(msg("/watch"))
    assert last(desk).startswith("Done. I will re-run this trade after the next US close")
    row = client.app.state.nw.store._conn.execute("SELECT webhook, status FROM watches").fetchone()
    assert row == (f"tg:{CHAT}", "pending")


def test_the_poll_loop_backs_off_survives_and_stops_on_a_bad_token(client):
    api = FakeApi()
    delays = []
    bot = TelegramBot(api, client.app.state.nw, lambda m, c: {"reply": "ok"}, workers=0, sleep=delays.append)
    api.batches = [
        telegram.TelegramError("net", None), telegram.TelegramError("net", None), RuntimeError("weird"),
        [msg("hi", update_id=10), {"update_id": 11, "edited_message": {}}],
        telegram.TelegramError("limit", 429, retry_after=7),
        telegram.TelegramError("bad token", 401),
    ]
    bot.run()  # returns, instead of looping, once Telegram says the token is wrong
    assert [round(d) for d in delays[:2]] == [2, 4] and 4 < delays[2] < 10 and 7 <= delays[3] < 9
    assert api.sent == [(CHAT, "ok")] and bot._offset == 12


def test_conflict_waits_long(client):
    api, delays = FakeApi(), []
    bot = TelegramBot(api, client.app.state.nw, lambda m, c: {}, workers=0, sleep=delays.append)
    api.batches = [telegram.TelegramError("conflict", 409), telegram.TelegramError("x", 401)]
    bot.run()
    assert delays[0] >= 30


def test_sessions_are_capped_and_expire(client, monkeypatch):
    now = [0.0]
    bot = TelegramBot(FakeApi(), client.app.state.nw, lambda m, c: {}, workers=0, clock=lambda: now[0])
    monkeypatch.setattr(telegram_bot, "MAX_SESSIONS", 5)
    for i in range(9):
        bot.session(i).context_id = i
    assert len(bot._sessions) == 5 and list(bot._sessions) == [4, 5, 6, 7, 8]
    now[0] = telegram_bot.SESSION_TTL_S + 1
    assert bot.session(8).context_id is None and len(bot._sessions) == 1  # the expired one is forgotten


def test_a_long_message_is_cut_into_allowed_pieces():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["text"])
        return httpx.Response(200, json={"ok": True, "result": {}})

    api = telegram.BotApi("1:abc", httpx.Client(transport=httpx.MockTransport(handler)))
    api.send_message(1, ("word " * 20) * 120)
    assert len(seen) == 3 and all(len(p) <= 4096 for p in seen)


def test_bot_api_get_updates_asks_for_messages_only():
    got = {}

    def handler(request):
        got.update(json.loads(request.content))
        got["path"] = request.url.path
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 1}]})

    api = telegram.BotApi("1:abc", httpx.Client(transport=httpx.MockTransport(handler)))
    assert api.get_updates(5) == [{"update_id": 1}]
    assert got["allowed_updates"] == ["message"] and got["offset"] == 5 and got["path"].endswith("/getUpdates")
