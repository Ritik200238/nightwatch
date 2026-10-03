"use client";

import { Crosshair } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { engagement, EngagementError, type Tripwire, type TripwireSuggestion } from "@/lib/engagement";
import { fmtPrice } from "@/lib/format";
import { actionName } from "@/components/report/plan-card";
import { type Lang, fmtTimeL, tr } from "@/lib/i18n";

export function labelWord(lang: Lang, label: string): string {
  const L = tr(lang);
  switch (label) {
    case "stop":
      return L("your stop", "你的止损");
    case "invalidation":
      return L("your invalidation", "你的失效位");
    case "liquidation":
      return L("liquidation", "强平价");
    case "p5":
      return L("the 1-in-20 loss price", "二十分之一亏损价");
    default:
      return L("your price", "你设的价格");
  }
}

/** One tripwire as a sentence: armed, or fired at what price and when. */
export function TripwireLine({ t, lang }: { t: Tripwire; lang: Lang }) {
  const L = tr(lang);
  const dir = t.direction === "below" ? L("below", "跌破") : L("above", "涨破");
  const what = `${t.ticker} ${dir} ${fmtPrice(t.level)} (${labelWord(lang, t.label)})`;
  if (t.status === "fired") {
    return (
      <li className="text-sm">
        <span className="font-medium text-status-critical">{L("Fired", "已触发")}</span> · {what} ·{" "}
        {L(`traded at ${fmtPrice(t.fired_price)} on ${fmtTimeL(t.fired_at, lang)}`, `于 ${fmtTimeL(t.fired_at, lang)} 成交于 ${fmtPrice(t.fired_price)}`)}
        {t.after?.verdict ? <> · {L(`verdict then: ${t.after.verdict.replace(/_/g, " ")}`, `当时结论：${t.after.verdict}`)}</> : null}
        {t.webhook_status ? <> · webhook {t.webhook_status}</> : null}
        {t.plan ? <> · <span className="font-medium">{L(t.plan.reminder, `你事先决定：${actionName(lang, t.plan.action)}。`)}</span></> : null}
      </li>
    );
  }
  return (
    <li className="text-sm">
      <span className="font-medium">{t.status === "armed" ? L("Armed", "已布防") : L("Expired", "已过期")}</span> · {what} ·{" "}
      {L(`since ${fmtTimeL(t.created_at, lang)}`, `自 ${fmtTimeL(t.created_at, lang)}`)}
    </li>
  );
}

/** The tripwires this visitor armed on a report, as a list. Shared by the report and the watch page. */
export function TripwireList({ forecastId, lang = "en", reloadKey = 0 }: { forecastId: number; lang?: Lang; reloadKey?: number }) {
  const [items, setItems] = useState<Tripwire[]>([]);
  useEffect(() => {
    let off = false;
    engagement
      .tripwiresFor(forecastId)
      .then((r) => !off && setItems(r.tripwires))
      .catch(() => undefined);
    return () => {
      off = true;
    };
  }, [forecastId, reloadKey]);
  if (!items.length) return null;
  return (
    <ul className="space-y-1" aria-label={tr(lang)("Tripwires", "价格警报")}>
      {items.map((t) => (
        <TripwireLine key={t.id} t={t} lang={lang} />
      ))}
    </ul>
  );
}

/** "Tell me if it trades through ..." with one click: the lines the report already holds
 *  (stop, written invalidation, liquidation, the 1-in-20 loss price) are offered ready to arm. */
export function TripwireButton({ forecastId, ticker, lang = "en" }: { forecastId: number; ticker: string; lang?: Lang }) {
  const L = tr(lang);
  const [sugg, setSugg] = useState<TripwireSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const [hook, setHook] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let off = false;
    engagement
      .tripwireSuggest(forecastId)
      .then((r) => !off && setSugg(r.suggestions))
      .catch(() => undefined);
    return () => {
      off = true;
    };
  }, [forecastId]);

  const arm = useCallback(
    async (level: number, label: string) => {
      setBusy(true);
      setError(null);
      try {
        await engagement.tripwireArm({ forecast_id: forecastId, level, label, webhook: hook.trim() || null, lang });
        setTick((n) => n + 1);
        setOpen(false);
      } catch (e) {
        setError(e instanceof EngagementError ? e.message : tr(lang)("Could not arm that.", "无法设置。"));
      } finally {
        setBusy(false);
      }
    },
    [forecastId, hook, lang],
  );

  const customLevel = Number(custom);
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <Crosshair aria-hidden /> {L(`Tell me if ${ticker} trades through a price`, `${ticker} 触及某价位时通知我`)}
        </Button>
      </div>
      {open ? (
        <div className="space-y-2 rounded-lg border border-border p-3">
          <p className="text-[13px] text-muted-foreground">
            {L(
              "Checked every minute against Bitget highs and lows. It fires once, records the price and time, re-runs the desk on this trade, and can post to a webhook.",
              "每分钟对照 Bitget 的最高/最低价检查。只触发一次，记录价格与时间，对这笔交易重新运行，并可发送到 webhook。",
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            {sugg.map((s) => (
              <Button key={s.label} variant="outline" size="sm" disabled={busy} onClick={() => void arm(s.level, s.label)}>
                {labelWord(lang, s.label)} · {s.direction === "below" ? L("below", "跌破") : L("above", "涨破")} {fmtPrice(s.level)}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              inputMode="decimal"
              aria-label={L("Your own price", "自定义价格")}
              placeholder={L("or your own price", "或自定义价格")}
              className="w-40 rounded-lg border border-border bg-background p-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            />
            <Button size="sm" disabled={busy || !(customLevel > 0)} onClick={() => void arm(customLevel, "custom")}>
              {L("Arm", "设置")}
            </Button>
          </div>
          <input
            value={hook}
            onChange={(e) => setHook(e.target.value)}
            inputMode="url"
            aria-label={L("Webhook URL (https only)", "Webhook 地址（仅 https）")}
            placeholder={L("optional webhook, https://...", "可选 webhook，https://...")}
            className="w-full max-w-md rounded-lg border border-border bg-background p-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          />
        </div>
      ) : null}
      {error ? <p className="text-xs text-status-critical">{error}</p> : null}
      <TripwireList forecastId={forecastId} lang={lang} reloadKey={tick} />
    </div>
  );
}
