"""Telegram as a place an alert can be delivered, and the one way this code talks to it.

A tripwire or a watch normally POSTs to a visitor's https webhook. A Telegram chat is a
second kind of target, stored in the same column as the string ``tg:<chat id>`` so no
table changes: ``journal.watches._notify`` sees the prefix and sends here instead of
making an HTTP request to a stranger's address.

Two processes use this. The API runs the bot (``nightwatch.api.telegram_bot``: long
polling, conversation). The recorder runs the tripwire and watch checks, so it is the one
that has to *push* an alert; it needs only ``send_message`` and the same bot token. Both
read ``TELEGRAM_BOT_TOKEN`` from the environment and do nothing without it.

The token is a password: it sits in the URL path of every Bot API call. This module never
logs it, strips it from any error it raises, and turns down the HTTP client's own request
logging, which prints the full URL at INFO.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger("nightwatch.telegram")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
API = "https://api.telegram.org"
TARGET_PREFIX = "tg:"
PUBLIC_URL = "https://nightwatch-gules.vercel.app"
MAX_LEN = 4000  # the Bot API refuses more than 4096 characters; leave room
_CHAT = re.compile(r"^tg:(-?\d{1,20})$")


class TelegramError(Exception):
    """A Bot API call failed. ``status`` is the HTTP status when there was one; the
    message never contains the token."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def quiet_http_logs() -> None:
    """httpx logs every request URL at INFO, and the token is in the URL."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def target(chat_id: int) -> str:
    return f"{TARGET_PREFIX}{int(chat_id)}"


def chat_id_of(delivery: str | None) -> int | None:
    """The chat id in a ``tg:<id>`` target, or None for anything else (a webhook URL)."""
    m = _CHAT.match(delivery or "")
    return int(m.group(1)) if m else None


def scrub(text: str, secret: str | None = None) -> str:
    secret = secret or token()
    out = text.replace(secret, "<token>") if secret else text
    return re.sub(r"/bot\d+:[A-Za-z0-9_-]+", "/bot<token>", out)


def split(text: str, limit: int = MAX_LEN) -> list[str]:
    """Pieces of at most ``limit`` characters, broken at a line, else a space, else hard."""
    text = (text or "").strip()
    if not text:
        return []
    out: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        out.append(text)
    return out


class BotApi:
    """The few Bot API methods this code uses, over httpx. ``client`` can be given so tests
    run against a fake Bot API with no network."""

    def __init__(self, bot_token: str, client: httpx.Client | None = None, *, base: str = API):
        if not bot_token:
            raise ValueError("a bot token is required")
        self._token = bot_token
        self._base = base.rstrip("/")
        self._client = client or httpx.Client()
        quiet_http_logs()

    def call(self, method: str, payload: dict[str, Any] | None = None, *, timeout: float = 15.0) -> Any:  # noqa: ANN401
        url = f"{self._base}/bot{self._token}/{method}"
        try:
            r = self._client.post(url, json=payload or {}, timeout=timeout)
        except httpx.HTTPError as exc:
            raise TelegramError(f"{method}: {type(exc).__name__}") from None  # the message could carry the URL
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code == 200 and body.get("ok"):
            return body.get("result")
        params = body.get("parameters") or {}
        raise TelegramError(
            scrub(f"{method}: http {r.status_code} {str(body.get('description') or '')[:120]}", self._token),
            status=r.status_code, retry_after=params.get("retry_after"),
        )

    def get_updates(self, offset: int | None, timeout_s: int = 50) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout_s, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=timeout_s + 15) or []

    def send_message(self, chat_id: int, text: str) -> None:
        for piece in split(text):
            self.call("sendMessage", {"chat_id": chat_id, "text": piece, "disable_web_page_preview": True})

    def typing(self, chat_id: int) -> None:
        try:
            self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=5.0)
        except TelegramError:
            pass  # a missing typing dot is never worth a failed answer


def send_message(chat_id: int, text: str, *, api: BotApi | None = None) -> str:
    """Push one message. Returns a short status for the alert row ("telegram ok" or
    "failed: ..."); never raises, because a dead chat must not stop the other alerts."""
    try:
        api = api or BotApi(token())
    except ValueError:
        return "failed: no bot token"
    try:
        api.send_message(chat_id, text)
        return "telegram ok"
    except TelegramError as exc:
        return f"failed: {exc.status or 'network'}"


# --- what an alert says -----------------------------------------------------------------

def _money(v: Any) -> str:  # noqa: ANN401
    return f"{v:,.0f}" if isinstance(v, int | float) else "-"


def _state(s: dict[str, Any] | None, zh: bool) -> str:
    if not s:
        return "无" if zh else "n/a"
    verdict = s.get("verdict") or "?"
    rec = s.get("recommended_notional")
    return f"{verdict} {_money(rec)} USDT" if rec is not None else str(verdict)


def _price(v: Any) -> str:  # noqa: ANN401
    return f"{v:,.2f}" if isinstance(v, int | float) and abs(v) < 1000 else _money(v)


def format_tripwire(body: dict[str, Any], lang: str = "en") -> str:
    zh = lang == "zh"
    below = body.get("direction") == "below"
    fid = body.get("forecast_id")
    link = f"{PUBLIC_URL}/r/{fid}" if isinstance(fid, int) and fid > 0 else None
    if zh:
        lines = [f"警报：{body.get('ticker')} 触及 {_price(body.get('level'))}（{'跌破' if below else '突破'}），成交价 {_price(body.get('fired_price'))}。",
                 f"之前的结论：{_state(body.get('before'), True)}", f"现在重新评估：{_state(body.get('after'), True)}"]
    else:
        lines = [f"Tripwire: {body.get('ticker')} traded {'below' if below else 'above'} {_price(body.get('level'))}, at {_price(body.get('fired_price'))}.",
                 f"Verdict then: {_state(body.get('before'), False)}", f"Verdict now: {_state(body.get('after'), False)}"]
    if body.get("after") is None:
        lines[-1] += "（重新评估失败）" if zh else " (the re-run failed)"
    if body.get("reminder"):  # the action the trader chose in advance for this line, already in their language
        lines.insert(1, str(body["reminder"]))
    if link:
        lines.append(("原报告：" if zh else "Original report: ") + link)
    return "\n".join(lines)


def format_watch(body: dict[str, Any], lang: str = "en") -> str:
    zh = lang == "zh"
    fid = body.get("forecast_id")
    link = f"{PUBLIC_URL}/r/{fid}" if isinstance(fid, int) and fid > 0 else None
    moved = body.get("moved")
    if zh:
        lines = ["美股收盘后的复查：" + ("结论变了。" if moved else "结论没变。"), f"之前：{_state(body.get('before'), True)}", f"现在：{_state(body.get('after'), True)}"]
    else:
        lines = ["Re-check after the US close: " + ("the verdict moved." if moved else "the verdict held."), f"Before: {_state(body.get('before'), False)}", f"Now: {_state(body.get('after'), False)}"]
    if link:
        lines.append(("原报告：" if zh else "Original report: ") + link)
    return "\n".join(lines)
