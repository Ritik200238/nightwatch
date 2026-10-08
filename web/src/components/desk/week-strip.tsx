"use client";

import { useEffect, useState } from "react";
import { useLang } from "@/lib/lang";

/**
 * The week the desk exists for, drawn once: seven days, Monday to Sunday, in New York time,
 * with the hours the US stock market trades lit and everything else dark. The dark part is
 * where a tokenized stock still trades and the stock behind it does not. A marker shows
 * where "now" is.
 *
 * Regular hours are 09:30-16:00 ET, extended 04:00-09:30 and 16:00-20:00, weekdays only.
 * US market holidays are not drawn; the footnote says so.
 */

const DAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAYS_ZH = ["一", "二", "三", "四", "五", "六", "日"];
const W = 700;
const H = 96;
const PAD_L = 0;
const COL = W / 7;
const ROW_TOP = 6;
const ROW_H = 84;

type Phase = "regular" | "extended" | "shut";
type Now = { day: number; hour: number };

function etNow(): Now {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    minute: "numeric",
    hour12: false,
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
  const day = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(get("weekday"));
  return { day: Math.max(0, day), hour: (Number(get("hour")) % 24) + Number(get("minute")) / 60 };
}

function phaseOf(n: Now): Phase {
  if (n.day >= 5) return "shut";
  if (n.hour >= 9.5 && n.hour < 16) return "regular";
  if ((n.hour >= 4 && n.hour < 9.5) || (n.hour >= 16 && n.hour < 20)) return "extended";
  return "shut";
}

/** Hours until the next 09:30 ET open on a weekday. Holidays are not known here. */
function hoursToOpen(n: Now): number {
  for (let add = 0; add <= 7; add++) {
    const d = (n.day + add) % 7;
    if (d >= 5) continue;
    const h = add * 24 + 9.5 - n.hour;
    if (h > 0) return h;
  }
  return 0;
}

function hoursToClose(n: Now): number {
  return 16 - n.hour;
}

function span(h: number, lang: string): string {
  const total = Math.max(0, Math.round(h * 60));
  const hh = Math.floor(total / 60);
  const mm = total % 60;
  if (hh >= 48) return lang === "zh" ? `${Math.round(h / 24)} 天` : `${Math.round(h / 24)} days`;
  return lang === "zh" ? `${hh} 小时 ${mm} 分` : `${hh}h ${String(mm).padStart(2, "0")}m`;
}

export function WeekStrip() {
  const { lang, tx } = useLang();
  const [now, setNow] = useState<Now | null>(null);

  useEffect(() => {
    setNow(etNow());
    const id = setInterval(() => setNow(etNow()), 60_000);
    return () => clearInterval(id);
  }, []);

  const phase = now ? phaseOf(now) : null;
  const x = (d: number, hour: number) => PAD_L + d * COL + (hour / 24) * COL;
  const days = lang === "zh" ? DAYS_ZH : DAYS_EN;

  let headline = tx("Reading the New York clock…", "正在读取纽约时间…");
  let sub = "";
  if (now && phase) {
    if (phase === "regular") {
      headline = tx("US stock market is open", "美股正在交易");
      sub = tx(`Closes in ${span(hoursToClose(now), "en")}. The token follows the stock now.`, `${span(hoursToClose(now), "zh")}后收盘。此刻代币紧跟股票。`);
    } else if (phase === "extended") {
      headline = tx("US extended hours — thin and jumpy", "美股盘前/盘后 —— 流动性薄、波动大");
      sub = tx(`Regular session opens in ${span(hoursToOpen(now), "en")} (09:30 ET).`, `常规时段 ${span(hoursToOpen(now), "zh")}后开盘（美东 09:30）。`);
    } else {
      headline = tx("US stock market is shut. The token is not.", "美股已休市，代币仍在交易。");
      sub = tx(`Opens in ${span(hoursToOpen(now), "en")} (09:30 ET). This gap is what Nightwatch stress-tests.`, `${span(hoursToOpen(now), "zh")}后开盘（美东 09:30）。Nightwatch 压力测试的正是这段空档。`);
    }
  }

  return (
    <figure className="m-0" aria-label={tx("The week in New York time, with US stock market hours lit", "按纽约时间绘制的一周，亮色为美股交易时段")}>
      <div className="grid grid-cols-7 pb-1 text-center text-[12px] text-slate-400" aria-hidden>
        {days.map((d, i) => (
          <span key={d} className={now && now.day === i ? "font-bold text-slate-50" : ""}>{d}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-hidden={false}>
        <title>{tx("US market hours across the week, New York time", "一周内美股交易时段（纽约时间）")}</title>
        {days.map((d, i) => {
          const weekday = i < 5;
          return (
            <g key={d}>
              <rect x={PAD_L + i * COL + 1} y={ROW_TOP} width={COL - 2} height={ROW_H} rx="3" fill="#0b1226" stroke="#26335a" strokeWidth="1" />
              {weekday ? (
                <>
                  <rect x={x(i, 4) + 1} y={ROW_TOP} width={((9.5 - 4) / 24) * COL} height={ROW_H} fill="#3b4f94" />
                  <rect x={x(i, 9.5) + 1} y={ROW_TOP} width={((16 - 9.5) / 24) * COL} height={ROW_H} fill="#f2c14e" />
                  <rect x={x(i, 16) + 1} y={ROW_TOP} width={((20 - 16) / 24) * COL} height={ROW_H} fill="#3b4f94" />
                </>
              ) : null}
            </g>
          );
        })}
        {now ? (
          <g>
            <line x1={x(now.day, now.hour) + 1} x2={x(now.day, now.hour) + 1} y1={0} y2={H} stroke="#ff6b6b" strokeWidth="2.5" />
          </g>
        ) : null}
      </svg>
      {now ? (
        <div className="relative mt-1 h-5" aria-hidden>
          <span className="absolute -translate-x-1/2 text-[12px] font-bold text-[#ff9d9d]" style={{ left: `${Math.min(Math.max(((now.day + now.hour / 24) / 7) * 100, 4), 96)}%` }}>
            ▲ {tx("now", "现在")}
          </span>
        </div>
      ) : null}
      <figcaption className="mt-3">
        <p className="text-base font-semibold leading-snug text-slate-50 sm:text-lg" aria-live="polite">
          {headline}
        </p>
        {sub ? <p className="mt-1 text-[13px] leading-relaxed text-slate-300 sm:text-sm">{sub}</p> : null}
        <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-slate-400">
          <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: "#f2c14e" }} />{tx("regular 09:30–16:00", "常规 09:30–16:00")}</span>
          <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: "#3b4f94" }} />{tx("extended hours", "盘前盘后")}</span>
          <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-sm border border-slate-600" style={{ background: "#0b1226" }} />{tx("stock shut, token trades", "股票休市，代币交易")}</span>
          <span>{tx("New York time · holidays not drawn", "纽约时间 · 未标出节假日")}</span>
        </p>
      </figcaption>
    </figure>
  );
}
