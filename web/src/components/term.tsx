"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLang } from "@/lib/lang";

/** Plain-language meanings for the words the proof pages cannot avoid. Each entry is
 *  English then Chinese, so a reader in either language gets the same explanation. */
const GLOSSARY = {
  p5: {
    label: ["p5 (one-in-twenty loss)", "p5（二十分之一的亏损）"],
    def: [
      "The bad case: out of 20 similar situations, 19 end better than this and 1 ends worse. It is the 5th percentile of the outcomes.",
      "坏情形：在 20 个相似情形里，19 个结果比它好，1 个比它差。也就是结果分布的第 5 百分位。",
    ],
  },
  p95: {
    label: ["p95", "p95"],
    def: [
      "The good case at the other end: only 1 situation in 20 ends better than this. Between p5 and p95 sit 90% of outcomes.",
      "另一端的好情形：二十个情形里只有一个比它更好。p5 与 p95 之间包含 90% 的结果。",
    ],
  },
  analog: {
    label: ["analog (past moment)", "相似时刻（历史上的类似时点）"],
    def: [
      "A past moment whose market conditions looked like the ones in front of you. The desk reports what happened after each of them.",
      "历史上市场状况与眼前相似的某个时点。交易台会报告在每个这样的时点之后发生了什么。",
    ],
  },
  pinball: {
    label: ["pinball loss", "弹球损失"],
    def: [
      "A score for a forecast that states percentile lines (p5, p50, p95) instead of one number. The further the real outcome lands from a line, the bigger the penalty, weighted by what that line promised (a p5 line is penalised far more when the outcome falls below it). Lower is better.",
      "给“分位线预测”（p5、p50、p95 等，而不是单个数字）打分的方法：真实结果离某条线越远，扣分越多，并按这条线的承诺加权（p5 线在结果跌到它下方时扣分要重得多）。越低越好。",
    ],
  },
  klo: {
    label: ["k_lo (tail widening factor)", "k_lo（尾部放宽系数）"],
    def: [
      "The number the bad-case line is multiplied by to correct it. Above 1 the line is pushed further out; below 1 it is pulled in.",
      "用来修正坏情形线的乘数。大于 1 表示把线往外推得更远；小于 1 表示往里收。",
    ],
  },
  margin: {
    label: ["margin", "边际"],
    def: [
      "A fixed number of percentage points added under narrow forecasts, because a multiplier alone leaves them too tight.",
      "给较窄的预测额外加上的固定百分点，因为只用乘数时，它们仍然偏窄。",
    ],
  },
  coverage: {
    label: ["coverage / breach", "覆盖率 / 突破"],
    def: [
      "Coverage is how often reality stayed inside a stated line. A breach is one time it did not, for example a loss past the p5 line.",
      "覆盖率是现实留在所述线以内的频率。突破是指没有留在线内的那一次，例如亏损超过 p5 线。",
    ],
  },
  calibrated: {
    label: ["calibrated", "校准良好"],
    def: [
      "The stated odds match what really happened: a 1-in-20 line is crossed about 1 time in 20, not 1 in 12.",
      "所说的概率与实际发生的相符：“二十分之一”的线大约二十次被越过一次，而不是十二次一次。",
    ],
  },
  fdr: {
    label: ["FDR / q-value", "FDR / q 值"],
    def: [
      "When many questions are tested at once, some look like wins by luck. The false discovery rate caps the share of such lucky wins, and the q-value is the p-value after that correction.",
      "同时检验很多问题时，总会有一些碰巧显得成立。假发现率限制这类碰巧成立的比例，q 值就是经过这种校正之后的 p 值。",
    ],
  },
  bh: {
    label: ["Benjamini–Hochberg", "Benjamini–Hochberg（BH 校正）"],
    def: [
      "A standard way to correct a batch of p-values at once. It ranks them and keeps only the ones small enough that, on average, no more than the chosen share (here 5%) of the results declared real are lucky flukes.",
      "同时校正一批 p 值的标准方法。它把 p 值排序，只保留足够小的那些，使被判定为“成立”的结果里，平均而言碰巧成立的比例不超过所设的份额（这里是 5%）。",
    ],
  },
  khi: {
    label: ["k_hi (upper tail factor)", "k_hi（上尾系数）"],
    def: [
      "The same correction as k_lo, applied to the good-case line (p95) instead of the bad-case line. Above 1 pushes it further out; below 1 pulls it in.",
      "与 k_lo 相同的修正，但作用于好情形线（p95），而不是坏情形线。大于 1 表示往外推；小于 1 表示往里收。",
    ],
  },
  clustered: {
    label: ["clustered t", "聚类 t 值"],
    def: [
      "A t-statistic that treats all the nights of one token as a single group, because they are not independent. It is stricter than counting every night as a separate test.",
      "把同一个代币的所有夜晚当作一组来计算的 t 值，因为它们并不彼此独立。比把每个夜晚当作单独检验更严格。",
    ],
  },
  pit: {
    label: ["PIT", "PIT（概率积分变换）"],
    def: [
      "Where each real outcome fell inside the forecast range, from the very bottom to the very top. If the forecasts are honest the bars come out flat.",
      "每个真实结果落在预测区间里的哪个位置，从最低端到最高端。如果预测是诚实的，各个柱子应当一样高。",
    ],
  },
  regime: {
    label: ["regime", "市场状态"],
    def: [
      "A kind of market period, such as calm nights or volatile ones, where prices behave differently.",
      "一类市场时期，例如平静的夜晚或剧烈波动的夜晚，价格在其中的表现不同。",
    ],
  },
  basis: {
    label: ["basis", "基差"],
    def: [
      "The gap between the tokenized stock's price and the real stock's price. It can widen when the stock market is closed.",
      "代币化股票的价格与真实股票价格之间的差距。股市休市时，这个差距可能拉大。",
    ],
  },
} as const;

export type TermKey = keyof typeof GLOSSARY;

/** An inline word with a dotted underline that explains itself. It opens on hover, on
 *  keyboard focus and on tap; Escape or a tap elsewhere closes it. */
export function Term({ k, children }: { k: TermKey; children?: ReactNode }) {
  const { lang } = useLang();
  const i = lang === "zh" ? 1 : 0;
  const entry = GLOSSARY[k];
  const id = useId();
  const [open, setOpen] = useState(false);
  const [shift, setShift] = useState(0);
  const root = useRef<HTMLSpanElement>(null);
  const pop = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (root.current && e.target instanceof Node && !root.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // Keep the bubble inside the viewport on a narrow screen.
  useLayoutEffect(() => {
    if (!open) {
      setShift(0);
      return;
    }
    if (!pop.current) return;
    const r = pop.current.getBoundingClientRect();
    const margin = 8;
    const over = r.right - (window.innerWidth - margin);
    const under = margin - r.left;
    if (over > 0) setShift((s) => s - over);
    else if (under > 0) setShift((s) => s + under);
  }, [open]);

  return (
    <span ref={root} className="relative inline" onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
        className="relative cursor-help rounded-sm after:absolute after:-inset-x-3 after:-inset-y-2 after:content-[''] underline decoration-muted-foreground/70 decoration-dotted underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {children ?? entry.label[i]}
      </button>
      {open ? (
        <span
          ref={pop}
          id={id}
          role="tooltip"
          style={{ transform: `translateX(${shift}px)` }}
          className="absolute top-full left-0 z-50 mt-1 block w-64 max-w-[calc(100vw-1rem)] rounded-md border border-border bg-popover p-3 text-left text-[13px] leading-snug font-normal tracking-normal text-popover-foreground normal-case shadow-lg"
        >
          <span className="block font-medium">{entry.label[i]}</span>
          <span className="mt-1 block text-muted-foreground">{entry.def[i]}</span>
        </span>
      ) : null}
    </span>
  );
}
