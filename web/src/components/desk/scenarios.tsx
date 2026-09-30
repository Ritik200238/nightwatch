"use client";

import { useLang } from "@/lib/lang";

export interface Scenario {
  label: string;
  labelZh: string;
  /** Sent in order, as if typed. A question needs a report before it, so it comes second. */
  steps: string[];
}

export const SCENARIOS: Scenario[] = [
  chip("Long 20k TSLA overnight, account 200k, because of the strong close, wrong if it opens below 340", "做多 2 万美元 TSLA 过夜，账户 20 万，理由是收盘强势，如果开盘低于 340 就算错"),
  chip("5x long 10k NVDA overnight, account 200k, because momentum into earnings, wrong if it loses 120", "5 倍杠杆做多 1 万美元 NVDA 过夜，账户 20 万，理由是财报前动能强，如果跌破 120 就算错"),
  chip("Short 10k AAPL overnight, I also hold 30k AAPL, account 200k, because it looks stretched, wrong if it makes a new high", "做空 1 万美元 AAPL 过夜，我另外持有 3 万美元 AAPL，账户 20 万，理由是涨幅过大，如果创新高就算错"),
  chip("周末做多特斯拉 2万U，账户 20万U，理由是收盘强势，如果开盘跌破 340 就算错", "周末做多特斯拉 2万U，账户 20万U，理由是收盘强势，如果开盘跌破 340 就算错"),
  { label: "What's the safest way to hold 20k META? (long 20k META overnight, account 200k, because earnings beat, wrong if it opens below 600)", labelZh: "持有 2 万 META，最安全的方式是什么？（账户 20 万，理由是财报超预期，如果开盘低于 600 就算错）", steps: ["Long 20k META overnight, account 200k, because earnings beat, wrong if it opens below 600", "What's the safest way to hold 20k META?"] },
];

function chip(label: string, labelZh: string): Scenario {
  return { label, labelZh, steps: [label] };
}

/** One-click starts. Each runs through the chat, so what you see is what typing it would give. */
export function ScenarioChips({ disabled, onPick }: { disabled: boolean; onPick: (steps: string[]) => void }) {
  const { lang, tx } = useLang();
  return (
    <div>
      <p className="mb-1.5 text-xs font-medium text-muted-foreground">{tx("Try one, no typing:", "点一个，不用打字：")}</p>
      <div className="flex flex-wrap gap-1.5">
        {SCENARIOS.map((s) => (
          <button
            key={s.label}
            type="button"
            disabled={disabled}
            onClick={() => onPick(s.steps)}
            className="rounded-full border border-border px-2.5 py-1 text-left text-xs hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50"
          >
            {lang === "zh" ? s.labelZh : s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
