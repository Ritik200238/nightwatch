"use client";

import type { OpenInterestView, OptionsView, Report } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import { fmtDateL, fmtTimeL, type Lang, tr } from "@/lib/i18n";

/** "Open interest 38,322 contracts (about $14.2M), up 3.4% in 24h." Built here from the
 *  server's numbers so it reads in either language; the 24 h change is left out, and said
 *  to be, until the recorder holds a reading that old. */
export function oiLine(oi: OpenInterestView, lang: Lang): string {
  const L = tr(lang);
  const n = oi.contracts >= 100 ? Math.round(oi.contracts).toLocaleString("en-US") : oi.contracts.toFixed(2);
  const usd = oi.usd != null ? (oi.usd >= 1e6 ? `$${(oi.usd / 1e6).toFixed(1)}M` : `$${Math.round(oi.usd / 1e3)}k`) : null;
  const now = L(`Open interest ${n} contracts${usd ? ` (about ${usd})` : ""}`, `未平仓合约 ${n} 张${usd ? `（约 ${usd}）` : ""}`);
  const ch = oi.change_24h_pct;
  if (ch == null) return L(`${now} on Bitget's perp; no reading from a day ago to compare with yet.`, `${now}（Bitget 永续）；还没有一天前的记录可供对比。`);
  if (Math.abs(ch) < 1) return L(`${now}, about the same as 24 h ago (${ch >= 0 ? "+" : "−"}${Math.abs(ch).toFixed(1)}%).`, `${now}，与 24 小时前基本持平（${ch >= 0 ? "+" : "−"}${Math.abs(ch).toFixed(1)}%）。`);
  return L(`${now}, ${ch > 0 ? "up" : "down"} ${Math.abs(ch).toFixed(1)}% in 24h.`, `${now}，24 小时内${ch > 0 ? "上升" : "下降"} ${Math.abs(ch).toFixed(1)}%。`);
}

/** The implied move beside the desk's own one-in-twenty loss, in one sentence. */
export function optionsLine(o: OptionsView, lang: Lang): string {
  const L = tr(lang);
  const move = o.implied_move_pct.toFixed(1);
  if (o.desk_p5_pct != null && o.desk_p5_pct < 0) {
    const p5 = Math.abs(o.desk_p5_pct).toFixed(1);
    return L(`Options market implies about ±${move}% over this hold; history says one in twenty worse than −${p5}%.`, `期权市场隐含本次持有期内约 ±${move}%；历史上二十次里有一次比 −${p5}% 更差。`);
  }
  return L(`Options market implies about ±${move}% over this hold.`, `期权市场隐含本次持有期内约 ±${move}%。`);
}

/** When the options market expects more than history, said plainly. */
export function optionsSizingLine(o: OptionsView, lang: Lang): string | null {
  const L = tr(lang);
  if (!o.sizing_binding) return null;
  const move = o.implied_move_pct.toFixed(1);
  if (o.history_severe_pct != null) {
    const h = o.history_severe_pct.toFixed(1);
    return L(`The options market expects more than history: the stress limit is sized on ±${move}% (history's worst severe move for this side is ${h}%).`, `期权市场预期的波动超过历史：压力上限按 ±${move}% 设定（历史上该方向最严重的情景为 ${h}%）。`);
  }
  return L(`The options market expects ±${move}% and the stress limit is sized on it.`, `期权市场预期 ±${move}%，压力上限按此设定。`);
}

/** Two plain lines of market context beside the stress and history cards: what the options
 *  market expects this hold to move, and how much leverage is open on the perp. Both are
 *  context, said to be, and neither reaches the size. Renders nothing when neither exists. */
export function MarketContext({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const o = report.options;
  // With a leverage ladder on the page the open-interest line lives in that section instead.
  const oi = report.leverage?.ladder?.length ? null : report.open_interest;
  if (!o && !oi) return null;
  return (
    <div className="mt-3 border-l-2 border-border pl-3 text-sm">
      <p className="font-medium text-foreground">{L("What the markets around it say", "周边市场的信号")}</p>
      {o ? (
        <p className="mt-1 text-foreground">
          {optionsLine(o, lang)}
          {optionsSizingLine(o, lang) ? <span className="block font-medium text-status-warning">{optionsSizingLine(o, lang)}</span> : null}
          <span className="block text-[13px] text-muted-foreground">
            {L(
              `One standard deviation, from the ${fmtDateL(o.expiry, lang)} option at the ${fmtUsd(o.atm_strike, 0)} strike (implied volatility ${o.atm_iv_pct.toFixed(0)}%). Cboe delayed quotes${o.quote_ts ? `, priced as of ${fmtTimeL(o.quote_ts, lang)}` : ""}.`,
              `一个标准差，取自 ${fmtDateL(o.expiry, lang)} 到期、行权价 ${fmtUsd(o.atm_strike, 0)} 的期权（隐含波动率 ${o.atm_iv_pct.toFixed(0)}%）。Cboe 延迟行情${o.quote_ts ? `，报价时间 ${fmtTimeL(o.quote_ts, lang)}` : ""}。`,
            )}
          </span>
        </p>
      ) : null}
      {oi ? (
        <p className="mt-1 text-foreground">
          {oiLine(oi, lang)}
          {oi.crowded ? <span className="block font-medium text-status-warning">{L(`Crowded: open interest +${(oi.change_24h_pct ?? 0).toFixed(0)}% in 24h, in its own top decile. A caution; the size is unchanged.`, `拥挤：未平仓量 24 小时 +${(oi.change_24h_pct ?? 0).toFixed(0)}%，处于自身历史前 10%。仅作提示，仓位未变。`)}</span> : null}
          <span className="block text-[13px] text-muted-foreground">{L("Bitget perpetual, read live. It did not move the size.", "Bitget 永续合约，实时读取。没有影响仓位。")}</span>
        </p>
      ) : null}
    </div>
  );
}
