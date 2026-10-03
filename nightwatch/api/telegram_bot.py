"""The desk in a Telegram chat.

Same engine, same conversation code as the web chat: a message goes through
``app._chat`` (rules or model intake, the missing-field questions, follow-ups, what-ifs),
so "long 20k NVDA over the weekend" gets the same sized verdict here that it gets on the
site, and "halve it" or "short instead" is answered by the same routing. What is
different is only the last step: a finished report is written as a short plain-text
message whose every number is copied out of the report, with the /r/<id> link to the full
page.

It runs as a background thread inside the API process (which already owns the desk, the
analysis lock and the model-slot cap; a second container will not fit on the box). It
long-polls the Bot API, so nothing needs to be reachable from outside, and it is a no-op
unless ``TELEGRAM_BOT_TOKEN`` is set. Tripwires and watches armed from a chat are
*delivered* by the recorder (``journal.telegram``), which runs those checks.

Limits that keep it safe on a small box: a per-chat rate limit before any analysis runs,
three worker threads, one request at a time per chat, a bounded number of remembered
chats that expire, and a poll loop that backs off on any failure and never raises.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from nightwatch.api import guard
from nightwatch.journal import engagement, telegram, tripwires, watches
from nightwatch.journal.telegram import PUBLIC_URL, BotApi, TelegramError

log = logging.getLogger("nightwatch.telegram")

MAX_SESSIONS = 1000
SESSION_TTL_S = 6 * 3600.0
MAX_HISTORY = 28          # the chat endpoint accepts at most 30 messages
MAX_INPUT = 1000          # characters of one user message that reach the desk
WORKERS = 3
MAX_PENDING = 30          # updates waiting for a worker; beyond this the chat is told to retry
# Messages that run the desk: a burst of 3, then one every 10 s. Commands are cheaper.
DESK_RATE = (6.0, 3)
CMD_RATE = (30.0, 10)

# chat(messages, context_forecast_id) -> the /chat response dict.
ChatFn = Callable[[list[dict[str, str]], int | None], dict[str, Any]]


@dataclass
class Session:
    messages: list[dict[str, str]] = field(default_factory=list)
    context_id: int | None = None
    lang: str = "en"
    touched: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


# --- words ------------------------------------------------------------------------------

HELP = {
    "en": (
        "Nightwatch stress-tests a trade in US stocks (as Bitget tokens) and gives a sized verdict from real history, not a guess.\n\n"
        "Tell me the trade in plain words:\n  long 20k NVDA over the weekend\nIf something is missing (token, side, size) I will ask.\n\n"
        "Then follow up: halve it - short instead - what about 5x? - why?\n\n"
        "/tripwire <price> - message me if the price crosses it (or /tripwire stop)\n"
        "/watch - re-check this trade after the next US close\n"
        "/new - start over\n\n"
        "Full reports: " + PUBLIC_URL + ". Not financial advice."
    ),
    "zh": (
        "Nightwatch 对美股交易（Bitget 代币）做压力测试，用真实历史给出带仓位的结论，不是猜的。\n\n"
        "直接用平常的话描述交易：\n  周末做多特斯拉 2万U\n缺少代币、方向或金额时我会问你。\n\n"
        "然后可以接着问：仓位减半 - 改成做空 - 5倍杠杆呢？ - 为什么？\n\n"
        "/tripwire <价格> - 价格触及时通知我（或 /tripwire stop）\n"
        "/watch - 下一个美股收盘后复查这笔交易\n"
        "/new - 重新开始\n\n"
        "完整报告：" + PUBLIC_URL + "。不构成投资建议。"
    ),
}

T = {
    "slow": ("Slow down a little - try again in {s} s.", "请稍等一下，{s} 秒后再试。"),
    "busy": ("The desk is busy right now. Try again in a minute.", "现在比较忙，请一分钟后再试。"),
    "fail": ("I could not do that: {why}", "没能完成：{why}"),
    "fail_generic": ("Something went wrong on my side. Try again in a minute.", "出错了，请一分钟后再试。"),
    "no_report": ("Tell me a trade first, e.g. \"long 20k NVDA over the weekend\".", "先告诉我一笔交易，比如“周末做多特斯拉 2万U”。"),
    "fresh": ("Started over. Tell me a trade.", "已重新开始。请描述一笔交易。"),
    "tw_usage": ("Send /tripwire <price> to be messaged when it trades through that price.", "发送 /tripwire <价格>，价格触及时我会通知你。"),
    "tw_none": ("This report has no ready-made lines. Send /tripwire <price>.", "这份报告没有现成的价位。请发送 /tripwire <价格>。"),
    "tw_bad": ("I need a price, like /tripwire 295.5 - or one of: {names}.", "需要一个价格，如 /tripwire 295.5，或其中之一：{names}。"),
    "tw_armed": ("Armed: {ticker} {dir} {level}. I will message this chat once if it trades through, with the verdict re-run then. Expires in 30 days.",
                 "已设置：{ticker} {dir} {level}。触及时我会在此通知一次，并重新评估结论。30 天后失效。"),
    "tw_many": ("That is too many tripwires for now (10 an hour, 20 armed). Try later.", "警报太多了（每小时 10 个，同时 20 个），请稍后再试。"),
    "w_nogo": ("A re-check needs a saved report. Ask for a fresh verdict first.", "复查需要已保存的报告，请先重新要一份结论。"),
    "w_armed": ("Done. I will re-run this trade after the next US close (about {when} UTC) and message you the verdict, moved or not.",
                "好的。下一个美股收盘后（约 {when} UTC）我会重新评估这笔交易并通知你结论。"),
    "w_many": ("Too many re-checks for now. Try later.", "复查太多了，请稍后再试。"),
}


def _t(key: str, lang: str, **kw: Any) -> str:  # noqa: ANN401
    en, zh = T[key]
    return (zh if lang == "zh" else en).format(**kw)


# --- the verdict message ----------------------------------------------------------------

def _n(v: Any, digits: int = 0) -> str:  # noqa: ANN401
    return f"{v:,.{digits}f}"


def _signed_pct(v: float) -> str:
    s = f"{v:+.1f}%"
    return "0.0%" if s in ("+0.0%", "-0.0%") else s


def _signed_money(v: float) -> str:
    s = f"{v:+,.0f}"
    return "0" if s in ("+0", "-0") else s


def format_verdict(report: dict[str, Any], lang: str = "en") -> str:
    """A finished report as a short plain-text message. Nothing is computed that the report
    does not already hold, apart from picking the worst of its stress rows."""
    zh = lang == "zh"
    t = report.get("ticket") or {}
    v = report.get("verdict") or {}
    fid = report.get("forecast_id")
    side = t.get("side") or "long"
    label = (t.get("extra") or {}).get("horizon_label") if isinstance(t.get("extra"), dict) else None
    hours = report.get("horizon_h")
    when = label or (f"{hours:.0f}h" if isinstance(hours, int | float) else "")
    side_txt = {"long": "做多", "short": "做空"}.get(side, side) if zh else side
    head = f"{t.get('ticker', '?')} {side_txt} {_n(t.get('notional_quote') or 0)} USDT" + (f", {when}" if when else "")
    lines = [head]

    rec, req = v.get("recommended_notional"), v.get("requested_notional")
    verdict = v.get("verdict") or "?"
    if rec is not None and req is not None and abs(rec - req) > 1:
        lines.append(f"{'结论' if zh else 'Verdict'}: {verdict} - {'建议仓位' if zh else 'size'} {_n(rec)} USDT ({'你想做' if zh else 'you asked'} {_n(req)})")
    elif rec is not None:
        lines.append(f"{'结论' if zh else 'Verdict'}: {verdict} - {'仓位' if zh else 'size'} {_n(rec)} USDT")
    else:
        lines.append(f"{'结论' if zh else 'Verdict'}: {verdict}")

    hz = ((report.get("analog") or {}).get("horizons") or {}).get(report.get("primary_horizon") or "")
    p5 = hz.get("loss_p5_pct") if isinstance(hz, dict) else None
    if isinstance(p5, int | float):
        gate = report.get("gate") or {}
        q = gate.get("risk_quote") if "5th" in str(gate.get("risk_basis") or "") else None
        extra = f" ({'约' if zh else 'about'} {_n(q)} USDT)" if isinstance(q, int | float) else ""
        lines.append(f"{'二十次里有一次亏得比这更多' if zh else 'One-in-twenty loss'}: {_signed_pct(p5)}{extra}")

    st = report.get("stress") or {}
    names = {p.get("id"): (p.get("name_zh") if zh and p.get("name_zh") else p.get("name")) for p in st.get("presets") or []}
    rows = [i for i in st.get("impacts") or [] if isinstance(i.get("total_pnl_quote"), int | float)]
    if rows:
        w = min(rows, key=lambda i: i["total_pnl_quote"])
        pct = w.get("total_pct_of_notional")
        lines.append(f"{'最坏压力情景' if zh else 'Worst stress'}: {names.get(w.get('scenario_id'), w.get('scenario_id'))} {_signed_money(w['total_pnl_quote'])} USDT"
                     + (f" ({_signed_pct(pct)})" if isinstance(pct, int | float) else ""))

    ex = (report.get("execution") or {}).get("exit_quote")
    if isinstance(ex, dict) and isinstance(ex.get("total_cost_bps"), int | float):
        cost = f"{ex['total_cost_bps']:.1f} bps" + (f" ({_n(ex['total_cost_quote'])} USDT)" if isinstance(ex.get("total_cost_quote"), int | float) else "")
        part = "" if ex.get("fully_filled", True) else (" - 盘口吃不下全部仓位" if zh else " - the book cannot take all of it")
        lines.append(f"{'平仓成本' if zh else 'Exit cost'}: {cost}{part}")
    else:
        lines.append(f"{'平仓成本' if zh else 'Exit cost'}: {'暂无实时盘口' if zh else 'no live book to price it'}")

    lev = report.get("leverage")
    if isinstance(lev, dict) and isinstance(lev.get("liquidation_price"), int | float):
        hit = ""
        if lev.get("analog_of"):
            hit = f"; {lev.get('analog_hits', 0)}/{lev['analog_of']} " + ("个历史相似时刻触及" if zh else "past moments reached it")
        dist = lev.get("liquidation_distance_pct")
        lines.append(f"{'爆仓价' if zh else 'Liquidation'} ({lev.get('leverage'):g}x): {_n(lev['liquidation_price'], 2)}"
                     + (f", {dist:.1f}% {'之外' if zh else 'away'}" if isinstance(dist, int | float) else "") + hit)

    reasons = [str(r)[:160] for r in (v.get("reasons") or [])[:2]]
    if reasons and verdict != "GO":
        lines.append(("原因: " if zh else "Why: ") + "; ".join(reasons))
    if t.get("account_equity_quote") is None:
        lines.append("想要明确的 GO / NO-GO，请告诉我账户规模，如“账户 20万”。" if zh else 'For a firm GO / NO-GO tell me your account size, e.g. "account 200k".')
    if isinstance(fid, int) and fid > 0:
        lines.append(f"{'完整报告' if zh else 'Full report'}: {PUBLIC_URL}/r/{fid}")
    lines.append("接着问：仓位减半 · 改成做空 · 5倍杠杆呢？ · /tripwire stop · /watch" if zh else "Ask on: halve it - short instead - what about 5x? - /tripwire stop - /watch")
    return "\n".join(lines)


# --- the bot ----------------------------------------------------------------------------

class TelegramBot:
    def __init__(
        self, api: BotApi, state: Any, chat_fn: ChatFn, *, limiter: guard.RateLimiter | None = None, workers: int = WORKERS,  # noqa: ANN401
        clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] | None = None,
    ):
        self.api = api
        self.state = state
        self.chat_fn = chat_fn
        self.limiter = limiter or guard.RateLimiter()
        self._clock = clock
        self._sessions: OrderedDict[int, Session] = OrderedDict()
        self._guard = threading.Lock()
        self._offset: int | None = None
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="telegram") if workers > 0 else None
        self._pending = 0
        self._thread: threading.Thread | None = None
        self.failures = 0

    # -- sessions
    def session(self, chat_id: int, lang_code: str | None = None) -> Session:
        now = self._clock()
        with self._guard:
            for cid in [c for c, s in self._sessions.items() if now - s.touched > SESSION_TTL_S]:
                del self._sessions[cid]
            s = self._sessions.pop(chat_id, None)
            if s is None:
                s = Session(lang=engagement.norm_lang(lang_code))
            s.touched = now
            self._sessions[chat_id] = s
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
            return s

    @staticmethod
    def client_of(chat_id: int) -> str:
        """The chat as a salted hash, like every other client: the raw id is not what the
        rate limiter or the engagement counts see."""
        return engagement.hash_client(f"telegram-{chat_id}", None)

    # -- updates
    def handle_update(self, update: dict[str, Any]) -> None:
        """One update, start to finish. Never raises."""
        try:
            msg = update.get("message")
            if not isinstance(msg, dict):
                return  # edits, channel posts, member changes: not for us
            text, chat = msg.get("text"), msg.get("chat") or {}
            sender = msg.get("from") or {}
            if not isinstance(text, str) or not text.strip() or sender.get("is_bot") or not isinstance(chat.get("id"), int):
                return  # stickers, photos, voice, bots
            self._handle_text(chat["id"], text.strip(), sender.get("language_code"))
        except Exception as exc:  # noqa: BLE001 - one bad update must not stop the next
            log.warning("update failed: %s: %s", type(exc).__name__, telegram.scrub(str(exc))[:200])

    def _say(self, chat_id: int, text: str) -> None:
        try:
            self.api.send_message(chat_id, text)
        except TelegramError as exc:
            log.warning("could not send: %s", exc)

    def _handle_text(self, chat_id: int, text: str, lang_code: str | None) -> None:
        sess = self.session(chat_id, lang_code)
        is_cmd = text.startswith("/")
        if is_cmd:
            cmd, _, arg = text.partition(" ")
            cmd = cmd.split("@", 1)[0].lower()
            arg = arg.strip()
        client = self.client_of(chat_id)
        group, (rate, burst) = ("telegram-cmd", CMD_RATE) if is_cmd else ("telegram", DESK_RATE)
        wait = self.limiter.take(group, client, rate, burst)
        lang = self._lang(sess, text)
        if wait > 0:
            self._say(chat_id, _t("slow", lang, s=max(1, int(wait + 0.999))))
            return
        with sess.lock:  # one request at a time per chat, so history stays in order
            if is_cmd:
                self._command(chat_id, sess, cmd, arg, lang, client)
            else:
                self._desk(chat_id, sess, text, lang, client)

    @staticmethod
    def _lang(sess: Session, text: str) -> str:
        from nightwatch.api.intake import language_of

        if language_of(text) == "zh":
            sess.lang = "zh"
        return sess.lang

    # -- commands
    def _command(self, chat_id: int, sess: Session, cmd: str, arg: str, lang: str, client: str) -> None:
        if cmd in ("/start", "/help"):
            self._say(chat_id, HELP[lang])
        elif cmd == "/new":
            sess.messages, sess.context_id = [], None
            self._say(chat_id, _t("fresh", lang))
        elif cmd == "/tripwire":
            self._say(chat_id, self._tripwire(chat_id, sess, arg, lang, client))
        elif cmd == "/watch":
            self._say(chat_id, self._watch(chat_id, sess, lang, client))
        else:
            self._say(chat_id, HELP[lang])

    def _report_of(self, sess: Session) -> dict[str, Any] | None:
        return self.state.reports.get(sess.context_id) if sess.context_id is not None else None

    def _tripwire(self, chat_id: int, sess: Session, arg: str, lang: str, client: str) -> str:
        report = self._report_of(sess)
        if report is None:
            return _t("no_report", lang)
        suggestions = tripwires.suggest(report)
        if not arg:
            if not suggestions:
                return _t("tw_none", lang)
            lines = [f"{s['label']}: {s['level']:,.2f} ({s['direction']})" for s in suggestions]
            return _t("tw_usage", lang) + "\n" + "\n".join(lines) + "\n" + ("例如 /tripwire stop" if lang == "zh" else "e.g. /tripwire " + suggestions[0]["label"])
        word = arg.split()[0].lower()
        level: float | None = None
        label = "custom"
        by_label = {s["label"]: s for s in suggestions}
        if word in by_label:
            level, label = by_label[word]["level"], word
        else:
            try:
                level = float(word.replace(",", "").lstrip("$"))
            except ValueError:
                return _t("tw_bad", lang, names=", ".join(by_label) or "-")
        try:
            row = tripwires.create(
                self.state.store._conn, forecast_id=int(report.get("forecast_id") or sess.context_id), report=report,
                level=level, label=label, webhook=telegram.target(chat_id), lang=lang, client=client,
            )
        except tripwires.BadLevel as exc:
            return str(exc)
        except tripwires.TooMany:
            return _t("tw_many", lang)
        word_dir = row.get("direction", "")
        if lang == "zh":
            word_dir = "跌破" if word_dir == "below" else "突破"
        return _t("tw_armed", lang, ticker=row.get("ticker"), dir=word_dir, level=f"{row.get('level'):,.2f}")

    def _watch(self, chat_id: int, sess: Session, lang: str, client: str) -> str:
        report = self._report_of(sess)
        fid = sess.context_id
        if report is None:
            return _t("no_report", lang)
        if fid is None or fid <= 0:
            return _t("w_nogo", lang)  # a what-if was never journalled; same rule as POST /watch
        try:
            row = watches.create(self.state.store._conn, forecast_id=fid, report=report, webhook=telegram.target(chat_id), lang=lang, client=client)
        except watches.TooMany:
            return _t("w_many", lang)
        due = str(row.get("due_at") or "")
        return _t("w_armed", lang, when=due[:16].replace("T", " "))

    # -- the desk
    def _desk(self, chat_id: int, sess: Session, text: str, lang: str, client: str) -> None:
        self.api.typing(chat_id)
        messages = [*sess.messages, {"role": "user", "content": text[:MAX_INPUT]}][-MAX_HISTORY:]
        try:
            out = self.chat_fn(messages, sess.context_id)
        except Exception as exc:  # noqa: BLE001 - HTTPException from the shared chat code carries a safe message
            detail = getattr(exc, "detail", None)
            if isinstance(detail, str) and detail:
                self._say(chat_id, _t("fail", lang, why=detail[:300]))
            else:
                log.warning("desk failed: %s: %s", type(exc).__name__, telegram.scrub(str(exc))[:200])
                self._say(chat_id, _t("fail_generic", lang))
            return
        report = out.get("report") if isinstance(out.get("report"), dict) else None
        fresh = report is not None and not out.get("answered_about") and out.get("mode") != "what_if"
        reply = format_verdict(report, lang) if fresh else str(out.get("reply") or "")
        if not reply.strip():
            reply = _t("fail_generic", lang)
        spoken = str(out.get("reply") or reply)[:2000]
        sess.messages = [*messages, {"role": "assistant", "content": spoken}][-MAX_HISTORY:]
        if report is not None:
            fid = report.get("forecast_id")
            sess.context_id = fid if isinstance(fid, int) else None
            if fresh and isinstance(fid, int) and fid > 0:
                try:
                    engagement.mark_verdict(self.state.store._conn, fid, lang=lang, client=client, internal=False)
                except Exception as exc:  # noqa: BLE001 - counting is never worth a failed answer
                    log.warning("could not count verdict: %s", exc)
        self._say(chat_id, reply)

    # -- the loop
    def _dispatch(self, update: dict[str, Any]) -> None:
        if self._pool is None:
            self.handle_update(update)
            return
        with self._guard:
            if self._pending >= MAX_PENDING:
                chat = ((update.get("message") or {}).get("chat") or {}).get("id")
                busy = isinstance(chat, int)
            else:
                busy = False
                self._pending += 1
        if busy:
            self._say(chat, _t("busy", "en"))
            return

        def work() -> None:
            try:
                self.handle_update(update)
            finally:
                with self._guard:
                    self._pending -= 1

        self._pool.submit(work)

    def poll_once(self) -> int:
        """One getUpdates round; returns how many updates it dispatched. Raises TelegramError."""
        updates = self.api.get_updates(self._offset)
        for u in updates:
            if isinstance(u, dict) and isinstance(u.get("update_id"), int):
                self._offset = u["update_id"] + 1
                self._dispatch(u)
        return len(updates)

    def run(self) -> None:
        """Poll until stopped. Every failure is a backoff, never an exit - except a token
        Telegram says is wrong, which no retry will fix."""
        log.info("telegram bot polling")
        while not self._stop.is_set():
            try:
                self.poll_once()
                self.failures = 0
            except TelegramError as exc:
                if exc.status in (401, 404):
                    log.error("telegram rejected the bot token (http %s); the bot is off", exc.status)
                    return
                self._fail(str(exc), exc.retry_after, conflict=exc.status == 409)
            except Exception as exc:  # noqa: BLE001 - the host process must outlive anything in here
                self._fail(f"{type(exc).__name__}: {telegram.scrub(str(exc))[:120]}", None)

    def _fail(self, why: str, retry_after: float | None, conflict: bool = False) -> None:
        self.failures += 1
        delay = float(retry_after) if retry_after else min(60.0, 2.0 ** min(self.failures, 6))
        if conflict:
            delay = max(delay, 30.0)  # another poller holds this token
        if self.failures in (1, 5) or self.failures % 20 == 0:
            log.warning("telegram poll failed (%d in a row): %s; retrying in %.0fs", self.failures, telegram.scrub(why), delay)
        self._sleep(delay + random.uniform(0, 1))

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="telegram-bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)


def start_if_configured(state: Any, chat_fn: ChatFn, limiter: guard.RateLimiter | None = None) -> TelegramBot | None:  # noqa: ANN401
    """Start the bot when TELEGRAM_BOT_TOKEN is set; otherwise do nothing at all."""
    tok = telegram.token()
    if not tok:
        return None
    try:
        bot = TelegramBot(BotApi(tok), state, chat_fn, limiter=limiter)
        bot.start()
        return bot
    except Exception as exc:  # noqa: BLE001 - a broken bot must not stop the API
        log.error("telegram bot did not start: %s", telegram.scrub(f"{type(exc).__name__}: {exc}"))
        return None
