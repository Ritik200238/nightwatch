"use client";

import { AlertTriangle, Clock, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { OpenPositions, useOpenPositions } from "@/components/desk/open-positions";
import { Figure as Stat, OpenSection as Section, Tag as Pill } from "@/components/proof-page";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, peek, type TonightReport, type UniverseEntry } from "@/lib/api";
import { presetName, stateWord } from "@/lib/i18n-terms";
import { useLang } from "@/lib/lang";
import { fmtBps, fmtPct, fmtUsd } from "@/lib/format";
import { fmtTimeL } from "@/lib/i18n";

/** What each flag is, in the words a person would use. Order is the order they are read. */
const FLAG_LABEL_ZH: Record<string, string> = {
  earnings_in_window: "今晚有财报",
  fomc_in_window: "今晚有美联储会议",
  fresh_filing: "刚有新披露",
  cannot_exit: "现在无法平仓",
  thin_book: "盘口常常太薄",
  hostile_regime: "不利的市场状态",
  wide_tail: "隔夜区间很宽",
};

const FLAG_LABEL: Record<string, string> = {
  earnings_in_window: "earnings tonight",
  fomc_in_window: "FOMC tonight",
  fresh_filing: "filing just landed",
  cannot_exit: "cannot exit now",
  thin_book: "book often too thin",
  hostile_regime: "hostile regime",
  wide_tail: "wide overnight band",
};

const FLAG_TONE: Record<string, "critical" | "warning" | "muted"> = {
  earnings_in_window: "critical",
  fomc_in_window: "critical",
  cannot_exit: "critical",
  fresh_filing: "warning",
  thin_book: "warning",
  hostile_regime: "warning",
  wide_tail: "muted",
};

export default function TonightPage() {
  const { tx, lang } = useLang();
  const { positions, setPositions } = useOpenPositions();
  const [universe, setUniverse] = useState<UniverseEntry[] | null>(null);
  const [report, setReport] = useState<TonightReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [equity, setEquity] = useState<number | null>(200000);

  const [universeFailed, setUniverseFailed] = useState(false);
  const loadUniverse = useCallback(() => {
    setUniverseFailed(false);
    void api.universe(true).then(setUniverse).catch(() => setUniverseFailed(true));
  }, []);

  useEffect(() => {
    const cached = peek<UniverseEntry[]>("/universe?core=true");
    if (cached) setUniverse(cached);
    loadUniverse();
    try {
      const raw = window.localStorage.getItem("nightwatch.equity");
      if (raw) setEquity(Number(raw) || null);
    } catch {
      /* a blocked store just means the default */
    }
  }, []);

  const run = useCallback(async () => {
    if (!positions.length) {
      setReport(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setReport(await api.tonight(positions, equity));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : tx("Could not read the book tonight.", "无法读取今晚的持仓。"));
    } finally {
      setBusy(false);
    }
  }, [positions, equity]);

  const worst = report?.items?.[0] ?? null;
  const needAttention = (report?.items ?? []).filter((i) => i.flags.some((f) => f !== "wide_tail"));

  return (
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      <aside className="min-w-0 space-y-6 lg:sticky lg:top-6 lg:self-start">
        <div>
          <h1 className="t-title flex items-center gap-2">
            <Moon className="h-4 w-4" aria-hidden /> {tx("Tonight", "今晚")}
          </h1>
          <p className="t-body mt-2 text-muted-foreground">
            {tx("The desk answers what you ask it. This is the question you would not have thought to ask: of what you are already holding, which position needs you before the market opens again.", "交易台只回答你问到的问题。这是你可能想不到要问的一个：在你已有的持仓里，哪一个在市场再次开盘之前需要你处理。")}
          </p>
        </div>
        {universe ? (
          <OpenPositions universe={universe} positions={positions} onChange={setPositions} />
        ) : universeFailed ? (
          <div role="alert" className="rounded-lg border border-border p-4 text-sm">
            <p>{tx("The token list did not load. The desk may be busy.", "代币列表没有加载出来，交易台可能正忙。")}</p>
            <Button variant="secondary" size="sm" className="mt-2" onClick={loadUniverse}>
              {tx("Try again", "重试")}
            </Button>
          </div>
        ) : (
          <div role="status" className="flex h-32 w-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            {tx("Loading the token list…", "正在加载代币列表…")}
          </div>
        )}
        <Button onClick={() => void run()} disabled={busy || !positions.length} variant={positions.length || busy ? "default" : "outline"} className="w-full">
          {busy ? tx("Reading the book…", "正在读取持仓…") : positions.length ? tx(`Watch these ${positions.length}`, `盯住这 ${positions.length} 个`) : tx("Add what you hold", "添加你的持仓")}
        </Button>
        <p className="t-caption">
          {tx("Every position gets the same full analysis the desk would give if you asked about it directly — the analogs over tonight's window, the presets at the size you hold, and the live book walked for that size. That takes a couple of seconds each.", "每个持仓都会得到与你直接询问时相同的完整分析——今晚这个时间窗口内的相似时刻、按你持有仓位计算的压力预设，以及按该仓位在实时盘口上的成交推演。每个大约需要几秒钟。")}
        </p>
      </aside>

      <section aria-live="polite" aria-busy={busy} className="min-w-0 space-y-8">
        {error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p className="font-medium">{tx("Couldn't read the book", "无法读取持仓")}</p>
            <p className="text-[13px] text-muted-foreground">{error}</p>
          </div>
        ) : null}

        {busy && !report ? (
          <>
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </>
        ) : null}

        {!report && !busy && !error ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-8 text-center">
            <Moon className="h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="font-medium">{tx("Nothing on the watch yet", "还没有盯任何持仓")}</p>
            <p className="max-w-md text-sm text-muted-foreground">
              {tx("Add the positions you are carrying and this page will tell you which of them has earnings landing overnight, which one the book will not absorb at three in the morning, and which one carries the widest tail between now and the open.", "添加你持有的仓位，这个页面会告诉你：哪个有财报在夜间发布，哪个在凌晨三点盘口接不住，哪个从现在到开盘之间的尾部风险最大。")}
            </p>
            <p className="text-sm text-muted-foreground">
              {tx("Or", "或者在交易台")}{" "}
              <Link href="/" className="underline underline-offset-2">
                {tx("stress-test something new", "测试一笔新的交易")}
              </Link>{" "}
              {tx("on the desk.", "。")}
            </p>
          </div>
        ) : null}

        {report ? (
          <>
            <Section
              title={report.market_is_open ? tx("Until the close", "到收盘为止") : tx("Until the next open", "到下次开盘为止")}
              subtitle={
                report.window_end
                  ? tx(`${Math.round(report.hours)} ${Math.round(report.hours) === 1 ? "hour" : "hours"}, to ${fmtTimeL(report.window_end, lang)}. ${report.market_is_open ? "The regular session is open, so this is what you would be carrying into the close." : "Everything below is measured over exactly this window."}`, `${report.hours.toFixed(0)} 小时，到 ${fmtTimeL(report.window_end, lang)}。${report.market_is_open ? "常规交易时段正在进行，所以这是你带到收盘的仓位。" : "下面的一切都恰好按这个时间窗口计算。"}`)
                  : undefined
              }
              action={
                <Pill tone={needAttention.length ? "warning" : "good"}>
                  {report.market_is_open ? <Sun className="mr-1 h-3 w-3" aria-hidden /> : <Clock className="mr-1 h-3 w-3" aria-hidden />}
                  {needAttention.length ? tx(`${needAttention.length} want a look`, `${needAttention.length} 个需要看一眼`) : tx("nothing pressing", "没有紧急事项")}
                </Pill>
              }
            >
              <p className="text-lg font-medium leading-snug">{report.summary}</p>
              <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-6 lg:grid-cols-4">
                <Stat label={tx("Positions", "持仓数")} value={String(report.items.length)} hint={report.note || tx("all judged", "全部已评估")} />
                <Stat label={tx("Gross held", "总持仓")} value={fmtUsd(report.gross_quote)} hint={tx("USDT across the book", "整个组合合计 USDT")} />
                <Stat
                  label={tx("Worst tonight", "今晚最坏")}
                  value={worst?.p5_quote != null ? `−${fmtUsd(Math.abs(worst.p5_quote))}` : "—"}
                  hint={worst ? tx(`${worst.ticker}, at the calibrated 5th percentile`, `${worst.ticker}，校准后的第 5 百分位`) : undefined}
                  tone="warning"
                />
                <Stat
                  label={tx("Added up", "合计")}
                  value={`−${fmtUsd(report.items.reduce((a, i) => a + Math.abs(i.p5_quote ?? 0), 0))}`}
                  hint={tx("if every bad case landed at once, which they would not", "假如所有坏情形同时发生（实际不会）")}
                />
              </div>
            </Section>

            {report.items.map((item) => (
              <Section
                key={`${item.ticker}-${item.side}`}
                collapsible
                summary={`${item.headline}`}
                title={`${item.ticker} ${lang === "zh" ? (item.side === "long" ? "做多" : item.side === "short" ? "做空" : item.side) : item.side} · ${fmtUsd(item.notional_quote)} USDT`}
                subtitle={tx("What this position looks like over tonight's window.", "这个持仓在今晚时间窗口内的情况。")}
                action={
                  item.flags.length ? (
                    <span className="flex flex-wrap gap-x-3 gap-y-1">
                      {item.flags.map((f) => (
                        <Pill key={f} tone={FLAG_TONE[f] ?? "muted"}>
                          {(lang === "zh" ? FLAG_LABEL_ZH : FLAG_LABEL)[f] ?? f.replace(/_/g, " ")}
                        </Pill>
                      ))}
                    </span>
                  ) : (
                    <Pill tone="good">{tx("quiet", "平静")}</Pill>
                  )
                }
              >
                <div className="grid grid-cols-2 gap-x-6 gap-y-6 lg:grid-cols-4">
                  <Stat
                    label={tx("Bad case tonight", "今晚的坏情形")}
                    value={item.p5_quote != null ? `−${fmtUsd(Math.abs(item.p5_quote))}` : "—"}
                    hint={item.p5_pct != null ? tx(`${fmtPct(item.p5_pct, 1)} of the position, calibrated`, `占仓位的 ${fmtPct(item.p5_pct, 1)}，已校准`) : tx("no distribution", "没有预测分布")}
                    tone="warning"
                  />
                  <Stat
                    label={tx("Worst preset", "最坏的预设情景")}
                    value={item.worst_preset_quote != null ? `−${fmtUsd(Math.abs(item.worst_preset_quote))}` : "—"}
                    hint={item.worst_preset ? presetName(lang, item.worst_preset) : undefined}
                    tone="critical"
                  />
                  <Stat
                    label={tx("Getting out now", "现在平仓")}
                    value={item.exit_cost_bps != null ? fmtBps(item.exit_cost_bps) : item.exit_fills ? "—" : tx("will not fill", "无法成交")}
                    hint={item.exit_fills ? tx("on the live book", "按实时盘口") : tx("the book cannot absorb this size", "盘口接不住这个仓位")}
                    tone={item.exit_fills ? undefined : "critical"}
                  />
                  <Stat
                    label={tx("Book at these hours", "这些时段的盘口")}
                    value={item.thin_share != null ? tx(`${(item.thin_share * 100).toFixed(0)}% too thin`, `${(item.thin_share * 100).toFixed(0)}% 太薄`) : "—"}
                    hint={tx("share of recorded snapshots that could not take this size", "记录的快照中接不住这个仓位的占比")}
                    tone={item.thin_share != null && item.thin_share >= 0.2 ? "warning" : undefined}
                  />
                </div>
                {item.events.length ? (
                  <div className="t-body mt-6 border-l-2 border-status-warning pl-4">
                    <p className="mb-1 flex items-center gap-2 font-medium">
                      <AlertTriangle className="h-4 w-4 text-status-warning" aria-hidden /> {tx("Landing inside the window", "落在这个时间窗口内")}
                    </p>
                    <ul className="space-y-1 text-muted-foreground">
                      {item.events.map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <p className="t-caption mt-6">
                  {tx("Regime: ", "市场状态：")}{stateWord(lang, item.regime_label ?? "unknown")}.{" "}
                  <Link href="/" className="underline underline-offset-2">
                    {tx("Stress-test a change to this position", "测试对这个持仓的改动")}
                  </Link>{" "}
                  {tx("on the desk.", "（在交易台）。")}
                </p>
              </Section>
            ))}
          </>
        ) : null}
      </section>
    </div>
  );
}
