"use client";

import { useLang } from "@/lib/lang";

export interface Scenario {
  label: string;
  labelZh: string;
  /** Sent in order, as if typed. A question needs a report before it, so it comes second. */
  steps: string[];
}

export const SCENARIOS: Scenario[] = [
  { label: "Hold $20k TSLA through the weekend", labelZh: "持有 2 万美元 TSLA 过周末", steps: ["Hold $20k TSLA through the weekend"] },
  { label: "5x long NVDA overnight", labelZh: "5 倍杠杆做多 NVDA 过夜", steps: ["5x long NVDA overnight"] },
  { label: "Short 10k AAPL, I also hold 30k AAPL", labelZh: "做空 1 万 AAPL，我另外持有 3 万 AAPL", steps: ["Short 10k AAPL, I also hold 30k AAPL"] },
  { label: "周末做多特斯拉 2万U", labelZh: "周末做多特斯拉 2万U", steps: ["周末做多特斯拉 2万U"] },
  { label: "What's the safest way to hold 20k META?", labelZh: "持有 2 万 META，最安全的方式是什么？", steps: ["long 20k META overnight", "What's the safest way to hold 20k META?"] },
];

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
