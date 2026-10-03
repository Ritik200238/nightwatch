"""Telegram as an alert target: the transport, the token's safety, and tripwire delivery."""

import json
import logging

import httpx
import pytest

from nightwatch.journal import telegram, tripwires, watches

TOKEN = "123456:ABC-secret_token"


def fake_api(handler):
    return telegram.BotApi(TOKEN, httpx.Client(transport=httpx.MockTransport(handler)))


def test_target_round_trip_and_webhooks_are_not_chats():
    assert telegram.chat_id_of(telegram.target(42)) == 42 and telegram.chat_id_of("tg:-100123") == -100123
    for bad in (None, "", "https://x.io/h", "tg:abc", "tg:", "xtg:5"):
        assert telegram.chat_id_of(bad) is None


def test_split_keeps_every_piece_under_the_limit_and_loses_nothing():
    text = "\n".join(f"line {i} " + "x" * 90 for i in range(200))
    pieces = telegram.split(text, 1000)
    assert all(len(p) <= 1000 for p in pieces) and len(pieces) > 1
    assert "".join("".join(p.split()) for p in pieces) == "".join(text.split())
    assert telegram.split("   ") == [] and telegram.split("a" * 50, 20) == ["a" * 20, "a" * 20, "a" * 10]


def test_an_error_never_carries_the_token(caplog):
    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    api = fake_api(boom)
    with caplog.at_level(logging.DEBUG), pytest.raises(telegram.TelegramError) as e:
        api.call("getMe")
    assert TOKEN not in str(e.value) and "secret_token" not in str(e.value)
    assert TOKEN not in caplog.text

    def rejected(request):
        return httpx.Response(401, json={"ok": False, "description": f"Unauthorized {TOKEN}"})

    with pytest.raises(telegram.TelegramError) as e2:
        fake_api(rejected).call("getMe")
    assert e2.value.status == 401 and TOKEN not in str(e2.value)


def test_the_http_client_is_told_to_stop_logging_urls():
    fake_api(lambda r: httpx.Response(200, json={"ok": True, "result": []}))
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_send_message_posts_to_the_chat_and_reports_status(monkeypatch):
    sent = []

    def ok(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    assert telegram.send_message(7, "hello", api=fake_api(ok)) == "telegram ok"
    assert sent == [{"chat_id": 7, "text": "hello", "disable_web_page_preview": True}]
    assert telegram.send_message(7, "x", api=fake_api(lambda r: httpx.Response(403, json={"ok": False, "description": "blocked"}))) == "failed: 403"
    monkeypatch.delenv(telegram.TOKEN_ENV, raising=False)
    assert telegram.send_message(7, "x") == "failed: no bot token"


def test_a_telegram_target_is_delivered_not_posted(monkeypatch):
    got = []
    monkeypatch.setattr(telegram, "send_message", lambda chat, text, **k: got.append((chat, text)) or "telegram ok")
    body = {"tripwire_id": "t", "forecast_id": 5, "ticker": "TSLA", "level": 300.0, "direction": "below", "fired_price": 298.5,
            "before": {"verdict": "GO", "recommended_notional": 20000}, "after": {"verdict": "REDUCE_TO", "recommended_notional": 8000}}
    assert watches._notify("tg:99", body, "en") == "telegram ok"
    chat, text = got[0]
    assert chat == 99 and "TSLA traded below 300.00" in text and "GO 20,000 USDT" in text and "REDUCE_TO 8,000 USDT" in text
    assert text.endswith("https://nightwatch-gules.vercel.app/r/5")
    zh = telegram.format_watch({"forecast_id": 5, "before": {"verdict": "GO"}, "after": {"verdict": "NO_GO"}, "moved": True}, "zh")
    assert "结论变了" in zh and "NO_GO" in zh
