"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useLang } from "@/lib/lang";
import { holdLabel } from "@/lib/plain";
import { api, type HorizonKind, type Lens, type Side, type TicketInput, type UniverseEntry } from "@/lib/api";

interface Props {
  universe: UniverseEntry[];
  busy: boolean;
  onSubmit: (ticket: TicketInput) => void;
  initial?: Partial<TicketInput>;
}

type Errors = Partial<Record<"ticker" | "notional" | "equity" | "stop" | "hours" | "leverage", string>>;

interface Menu {
  lenses: Lens[];
  counts: Record<string, number>;
  floor: number;
  suggested: string[];
  pooled: Record<string, { hours: number; episodes: number }>;
  minEpisodes: number;
}

/** Which past moments the search is allowed to compare against.
 *
 *  The same seventeen conditions the model picks from when a trader asks for one in
 *  words, offered as a list so the feature is not hidden behind knowing to ask. Each
 *  one carries how many hours of this token's own history it leaves, because that is
 *  the cost: narrow far enough and there is no evidence left to answer from.
 */
function LensPicker({ ticker, chosen, onChange }: { ticker: string; chosen: string[]; onChange: (names: string[]) => void }) {
  const { tx } = useLang();
  const [menu, setMenu] = useState<Menu | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    let live = true;
    void api
      .lenses(ticker)
      .then((r) => {
        if (live)
          setMenu({
            lenses: r.lenses,
            counts: r.counts ?? {},
            floor: r.floor_hours,
            suggested: r.suggested ?? [],
            pooled: r.pooled ?? {},
            minEpisodes: r.min_episodes ?? 15,
          });
      })
      .catch(() => {
        // A missing menu is not worth blocking a ticket over; the chat path still works.
        if (live) setMenu(null);
      });
    return () => {
      live = false;
    };
  }, [ticker]);

  if (!menu) return null;

  const suggested = menu.lenses.filter((x) => menu.suggested.includes(x.name) || chosen.includes(x.name));
  const rest = menu.lenses.filter((x) => !suggested.includes(x));
  const shown = showAll ? [...suggested, ...rest] : suggested;
  const thin = chosen.filter((n) => (menu.counts[n] ?? 0) < menu.floor);

  function toggle(name: string) {
    onChange(chosen.includes(name) ? chosen.filter((x) => x !== name) : [...chosen, name]);
  }

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <Label>{tx("Compare against", "对比的历史条件")}</Label>
        <button
          type="button"
          className="rounded text-[13px] text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? tx("Fewer", "收起") : tx(`All ${menu.lenses.length}`, `全部 ${menu.lenses.length} 个`)}
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {shown.map((x) => {
          const on = chosen.includes(x.name);
          const n = menu.counts[x.name];
          // Hours are not the limit once the search pools across tokens; separate events
          // are. FOMC nights fall on the same dates for every token, so thousands of
          // hours can still be fourteen meetings - too few to answer from.
          const events = menu.pooled[x.name]?.episodes;
          const unanswerable = events != null && events < menu.minEpisodes;
          return (
            <button
              key={x.name}
              type="button"
              aria-pressed={on}
              disabled={unanswerable && !on}
              title={
                unanswerable
                  ? `${x.definition} — ${tx(`only ${events} separate past events across every token, and the search needs ${menu.minEpisodes}. It cannot answer this yet.`, `所有代币合计只有 ${events} 次独立的历史事件，而搜索至少需要 ${menu.minEpisodes} 次，暂时无法回答。`)}`
                  : `${x.definition}${n != null ? ` — ${tx(`${n.toLocaleString()} past hours in ${ticker}`, `${ticker} 有 ${n.toLocaleString()} 个历史小时`)}` : ""}`
              }
              onClick={() => toggle(x.name)}
              className={`rounded-full border px-2 py-0.5 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
                on ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {x.label}
              {unanswerable ? (
                <span className="ml-1 opacity-70">· {tx(`${events} events, too few`, `仅 ${events} 次事件，太少`)}</span>
              ) : n != null ? (
                <span className="ml-1 opacity-60 tabular-nums">{n.toLocaleString()}h</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <p className="text-[13px] text-muted-foreground">
        {chosen.length === 0 ? (
          <>{tx("All past hours ranked by how much they resemble now. Pick a condition to rank inside it instead.", "所有历史小时按与现在的相似度排序。选一个条件，则只在该条件内排序。")}</>
        ) : thin.length > 0 ? (
          <>
            {tx(`Under ${menu.floor.toLocaleString()} hours left in ${ticker}'s own past, so the search widens across tokens — or says it cannot answer.`, `${ticker} 自己的历史里只剩不到 ${menu.floor.toLocaleString()} 个小时，所以搜索会扩展到其他代币，或者直接说明无法回答。`)}
          </>
        ) : (
          <>{tx("Ranked inside that history only, and the report says what it cost.", "只在该历史范围内排序，报告会说明这样做的代价。")}</>
        )}
      </p>
    </div>
  );
}

export function TicketForm({ universe, busy, onSubmit, initial }: Props) {
  const { tx, lang } = useLang();
  const [ticker, setTicker] = useState(initial?.ticker ?? "TSLA");
  const [side, setSide] = useState<Side>(initial?.side ?? "long");
  const [notional, setNotional] = useState(String(initial?.notional_quote ?? 20000));
  const [equity, setEquity] = useState(initial?.account_equity_quote ? String(initial.account_equity_quote) : "200000");
  const [horizon, setHorizon] = useState<HorizonKind>(initial?.horizon_kind ?? "next_open");
  const [hours, setHours] = useState("");
  const [stop, setStop] = useState(initial?.stop_price ? String(initial.stop_price) : "");
  const [leverage, setLeverage] = useState(initial?.leverage ? String(initial.leverage) : "");
  const [thesis, setThesis] = useState(initial?.thesis ?? "");
  const [invalidation, setInvalidation] = useState(initial?.invalidation ?? "");
  const [lenses, setLenses] = useState<string[]>(initial?.lenses ?? []);
  const [errors, setErrors] = useState<Errors>({});

  const available = universe.filter((u) => u.has_data);

  function validate(): TicketInput | null {
    const e: Errors = {};
    const n = Number(notional);
    const eq = equity.trim() ? Number(equity) : null;
    const st = stop.trim() ? Number(stop) : null;
    const hrs = hours.trim() ? Number(hours) : null;
    const lev = leverage.trim() ? Number(leverage) : null;
    if (!ticker) e.ticker = tx("Pick a token.", "请选择代币。");
    if (!(n > 0)) e.notional = tx("Enter a size in USDT.", "请输入 USDT 金额。");
    if (eq != null && !(eq > 0)) e.equity = tx("Equity must be positive.", "账户资金必须大于 0。");
    if (st != null && !(st > 0)) e.stop = tx("Stop must be a price.", "止损必须是一个价格。");
    if (horizon === "hours" && !(hrs && hrs > 0)) e.hours = tx("Enter how many hours.", "请输入小时数。");
    if (lev != null && !(lev >= 1 && lev <= 125)) e.leverage = tx("Leverage is between 1x and 125x.", "杠杆范围是 1 到 125 倍。");
    setErrors(e);
    if (Object.keys(e).length) return null;
    return {
      ticker,
      side,
      notional_quote: n,
      account_equity_quote: eq,
      horizon_kind: horizon,
      horizon_hours: horizon === "hours" ? hrs : null,
      stop_price: st,
      leverage: lev != null && lev > 1 ? lev : null,
      thesis,
      invalidation,
      lenses,
    };
  }

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(ev) => {
        ev.preventDefault();
        const t = validate();
        if (t) onSubmit(t);
      }}
    >
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="ticker">{tx("Token", "代币")}</Label>
          <Select value={ticker} onValueChange={(v) => setTicker(v ?? "")}>
            <SelectTrigger id="ticker" className="w-full" aria-invalid={!!errors.ticker}>
              <SelectValue placeholder={tx("Pick a token", "选择代币")} />
            </SelectTrigger>
            <SelectContent>
              {available.map((u) => (
                <SelectItem key={u.ticker} value={u.ticker}>
                  {u.ticker} <span className="text-muted-foreground">· {u.spot_symbol}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {errors.ticker ? <p className="text-xs text-destructive">{errors.ticker}</p> : null}
        </div>
        <div className="space-y-1">
          <Label htmlFor="side">{tx("Direction", "方向")}</Label>
          <Select value={side} onValueChange={(v) => setSide(v as Side)}>
            <SelectTrigger id="side" className="w-full">
              <SelectValue>{side === "short" ? tx("Short", "做空") : tx("Long", "做多")}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="long">{tx("Long", "做多")}</SelectItem>
              <SelectItem value="short">{tx("Short", "做空")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="notional">{tx("Size (USDT)", "仓位 (USDT)")}</Label>
          <Input id="notional" type="number" inputMode="decimal" min={1} step="any" value={notional} onChange={(e) => setNotional(e.target.value)} aria-invalid={!!errors.notional} autoComplete="off" />
          {errors.notional ? <p className="text-xs text-destructive">{errors.notional}</p> : null}
        </div>
        <div className="space-y-1">
          <Label htmlFor="equity">{tx("Account equity (USDT)", "账户资金 (USDT)")}</Label>
          <Input id="equity" type="number" inputMode="decimal" min={1} step="any" value={equity} onChange={(e) => setEquity(e.target.value)} aria-invalid={!!errors.equity} autoComplete="off" />
          {errors.equity ? <p className="text-xs text-destructive">{errors.equity}</p> : null}
        </div>
        <div className="space-y-1">
          <Label htmlFor="horizon">{tx("Hold until", "持有到")}</Label>
          <Select value={horizon} onValueChange={(v) => setHorizon(v as HorizonKind)}>
            <SelectTrigger id="horizon" className="w-full">
              <SelectValue>{holdLabel(horizon, lang)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="next_open">{holdLabel("next_open", lang)}</SelectItem>
              <SelectItem value="window_end">{holdLabel("window_end", lang)}</SelectItem>
              <SelectItem value="hours">{holdLabel("hours", lang)}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {horizon === "hours" ? (
          <div className="space-y-1">
            <Label htmlFor="hours">{tx("Hours", "小时数")}</Label>
            <Input id="hours" type="number" inputMode="numeric" min={1} value={hours} onChange={(e) => setHours(e.target.value)} aria-invalid={!!errors.hours} autoComplete="off" />
            {errors.hours ? <p className="text-xs text-destructive">{errors.hours}</p> : null}
          </div>
        ) : (
          <div className="space-y-1">
            <Label htmlFor="stop">{tx("Stop price (optional)", "止损价（可选）")}</Label>
            <Input id="stop" type="number" inputMode="decimal" min={0} step="any" value={stop} onChange={(e) => setStop(e.target.value)} aria-invalid={!!errors.stop} autoComplete="off" placeholder={tx("e.g. 350", "例如 350")} />
            {errors.stop ? <p className="text-xs text-destructive">{errors.stop}</p> : null}
          </div>
        )}
      </div>
      {horizon === "hours" ? (
        <div className="space-y-1">
          <Label htmlFor="stop2">{tx("Stop price (optional)", "止损价（可选）")}</Label>
          <Input id="stop2" type="number" inputMode="decimal" min={0} step="any" value={stop} onChange={(e) => setStop(e.target.value)} autoComplete="off" />
        </div>
      ) : null}
      <div className="space-y-1">
        <Label htmlFor="leverage">{tx("Leverage (optional)", "杠杆（可选）")}</Label>
        <Input id="leverage" type="number" inputMode="decimal" min={1} max={125} step="any" value={leverage} onChange={(e) => setLeverage(e.target.value)} aria-invalid={!!errors.leverage} autoComplete="off" placeholder={tx("e.g. 5 - held on the Bitget perpetual", "例如 5 - 在 Bitget 永续合约上持有")} />
        {errors.leverage ? <p className="text-xs text-destructive">{errors.leverage}</p> : null}
      </div>
      <div className="space-y-1">
        <div className="flex items-baseline justify-between gap-2">
          <Label htmlFor="thesis">{tx("Why this trade", "为什么做这笔交易")}</Label>
          {/* The gate refuses a ticket with no written plan, which is the right rule and a
              poor first click. This fills a plausible one so the rule can be seen working
              rather than merely blocking. The stop stays empty on purpose. */}
          {!thesis && !invalidation ? (
            <button
              type="button"
              className="rounded text-[13px] text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              onClick={() => {
                setThesis(side === "long" ? tx("Strength into the US open carries through the overnight session.", "美股开盘前的强势会延续到夜盘。") : tx("Weakness into the US open carries through the overnight session.", "美股开盘前的弱势会延续到夜盘。"));
                setInvalidation(side === "long" ? tx("A close back below the 30-day average.", "收盘重新跌回 30 日均线下方。") : tx("A close back above the 30-day average.", "收盘重新涨回 30 日均线上方。"));
              }}
            >
              {tx("Fill an example", "填入示例")}
            </button>
          ) : null}
        </div>
        <Textarea id="thesis" rows={2} value={thesis} onChange={(e) => setThesis(e.target.value)} placeholder={tx("One line. The gate needs a written reason.", "一句话即可。风控关卡需要一个书面理由。")} />
      </div>
      <LensPicker ticker={ticker} chosen={lenses} onChange={setLenses} />
      <div className="space-y-1">
        <Label htmlFor="invalidation">{tx("What proves it wrong", "什么情况说明判断错了")}</Label>
        <Textarea id="invalidation" rows={2} value={invalidation} onChange={(e) => setInvalidation(e.target.value)} placeholder={tx("e.g. a close below 350", "例如 收盘跌破 350")} />
      </div>
      <Button type="submit" disabled={busy || available.length === 0} className="w-full">
        {busy ? tx("Stress-testing…", "压力测试中…") : tx("Stress-test this trade", "对这笔交易做压力测试")}
      </Button>
      {available.length === 0 ? <p className="text-[13px] text-muted-foreground">{tx("No tokens have stored data yet. Run the sync first.", "还没有任何代币有存储的数据，请先运行同步。")}</p> : null}
    </form>
  );
}
