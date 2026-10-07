"use client";

import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLang } from "@/lib/lang";
import type { Side, UniverseEntry } from "@/lib/api";

export interface OpenPosition {
  ticker: string;
  side: Side;
  notional_quote: number;
}

const STORAGE_KEY = "nightwatch.positions";
/** The same limits the server holds: a size from 1 to 10,000,000 USDT, and the first twelve
 *  positions are the ones judged, so a thirteenth would be accepted and then ignored. */
export const MIN_SIZE = 1;
export const MAX_SIZE = 10_000_000;
export const MAX_POSITIONS = 12;

/**
 * What the trader already holds.
 *
 * Kept in this browser only. The desk has no accounts, and a list of someone's positions
 * is not something to store on a server that does not need it; it is sent with an
 * analysis so the report can judge the book, and never written down anywhere else.
 */
export function useOpenPositions() {
  const [positions, setPositions] = useState<OpenPosition[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        // A stored list is whatever an older version, or a person, left there: keep only rows the server would accept.
        const parsed: unknown = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setPositions(
            (parsed as OpenPosition[])
              .filter((p) => p && typeof p.ticker === "string" && p.ticker && (p.side === "long" || p.side === "short") && Number.isFinite(p.notional_quote) && p.notional_quote >= MIN_SIZE && p.notional_quote <= MAX_SIZE)
              .slice(0, MAX_POSITIONS),
          );
        }
      }
    } catch {
      /* a blocked or corrupt store just means an empty book */
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(positions));
    } catch {
      /* private mode: the list simply does not persist */
    }
  }, [positions, loaded]);

  return { positions, setPositions };
}

interface Props {
  universe: UniverseEntry[];
  positions: OpenPosition[];
  onChange: (next: OpenPosition[]) => void;
}

export function OpenPositions({ universe, positions, onChange }: Props) {
  const { tx } = useLang();
  const available = universe.filter((u) => u.has_data);
  const [ticker, setTicker] = useState(available[0]?.ticker ?? "NVDA");
  const [side, setSide] = useState<Side>("long");
  const [size, setSize] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  function add() {
    const n = Number(size);
    if (!ticker) return;
    if (!Number.isFinite(n) || n < MIN_SIZE || n > MAX_SIZE) {
      setProblem(tx(`Size must be between ${MIN_SIZE} and ${MAX_SIZE.toLocaleString()} USDT.`, `仓位须在 ${MIN_SIZE} 到 ${MAX_SIZE.toLocaleString()} USDT 之间。`));
      return;
    }
    // The same token and side again is the same position, made bigger, not a second row.
    const at = positions.findIndex((p) => p.ticker === ticker && p.side === side);
    if (at < 0 && positions.length >= MAX_POSITIONS) {
      setProblem(tx(`Up to ${MAX_POSITIONS} positions are judged. Remove one first.`, `最多评估 ${MAX_POSITIONS} 个持仓，请先移除一个。`));
      return;
    }
    if (at >= 0 && positions[at].notional_quote + n > MAX_SIZE) {
      setProblem(tx(`That would take ${ticker} past ${MAX_SIZE.toLocaleString()} USDT.`, `加上后 ${ticker} 将超过 ${MAX_SIZE.toLocaleString()} USDT。`));
      return;
    }
    setProblem(null);
    onChange(at >= 0 ? positions.map((p, i) => (i === at ? { ...p, notional_quote: p.notional_quote + n } : p)) : [...positions, { ticker, side, notional_quote: n }]);
    setSize("");
  }

  const gross = positions.reduce((a, p) => a + p.notional_quote, 0);

  return (
    <section className="space-y-3" aria-labelledby="book-heading">
      <div>
        <h2 id="book-heading" className="text-sm font-medium">
          {tx("What you already hold", "你已有的持仓")}
        </h2>
        <p className="text-[13px] text-muted-foreground">{tx("Optional. Stays in this browser; sent with an analysis so the report can judge the whole book.", "可选。只保存在本浏览器里；分析时一并发送，报告才能评估整个持仓组合。")}</p>
      </div>

      {positions.length ? (
        <ul className="space-y-1">
          {positions.map((p, i) => (
            <li key={`${p.ticker}-${i}`} className="flex min-h-10 items-center gap-2 border-t border-border py-1 text-sm">
              <span className="font-medium">{p.ticker}</span>
              <span className="text-muted-foreground">{p.side === "long" ? tx("long", "做多") : tx("short", "做空")}</span>
              <span className="tabular ml-auto">{p.notional_quote.toLocaleString()} USDT</span>
              <Button variant="ghost" size="icon" className="h-10 w-10 min-h-10 min-w-10" aria-label={tx(`Remove ${p.ticker}`, `移除 ${p.ticker}`)} onClick={() => onChange(positions.filter((_, j) => j !== i))}>
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </li>
          ))}
          <li className="px-2 pt-1 text-[13px] text-muted-foreground">{tx(`Gross ${gross.toLocaleString()} USDT across ${positions.length} position${positions.length === 1 ? "" : "s"}`, `合计 ${gross.toLocaleString()} USDT，共 ${positions.length} 个持仓`)}</li>
        </ul>
      ) : null}

      <div className="grid grid-cols-[1fr_auto_1fr_auto] items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="pos-ticker" className="text-xs">
            {tx("Token", "代币")}
          </Label>
          <Select value={ticker} onValueChange={(v) => setTicker(v ?? "")}>
            <SelectTrigger id="pos-ticker" className="h-10 min-h-10 w-full">
              <SelectValue placeholder={tx("Token", "代币")} />
            </SelectTrigger>
            <SelectContent>
              {available.map((u) => (
                <SelectItem key={u.ticker} value={u.ticker}>
                  {u.ticker}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="pos-side" className="text-xs">
            {tx("Side", "方向")}
          </Label>
          <Select value={side} onValueChange={(v) => setSide((v as Side) ?? "long")}>
            <SelectTrigger id="pos-side" className="h-10 min-h-10">
              <SelectValue>{side === "short" ? tx("short", "做空") : tx("long", "做多")}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="long">{tx("long", "做多")}</SelectItem>
              <SelectItem value="short">{tx("short", "做空")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="pos-size" className="text-xs">
            {tx("Size (USDT)", "仓位 (USDT)")}
          </Label>
          <Input
            id="pos-size"
            type="number"
            inputMode="decimal"
            min={MIN_SIZE}
            max={MAX_SIZE}
            step="any"
            className="h-10 min-h-10"
            value={size}
            onChange={(e) => {
              setSize(e.target.value);
              setProblem(null);
            }}
            aria-invalid={problem ? true : undefined}
            aria-describedby={problem ? "pos-problem" : undefined}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            autoComplete="off"
          />
        </div>
        <Button type="button" variant="default" className="h-10 min-h-10 px-3" onClick={add} disabled={!size.trim()}>
          {tx("Add", "添加")}
        </Button>
      </div>
      {problem ? (
        <p id="pos-problem" role="alert" className="text-[13px] text-destructive">
          {problem}
        </p>
      ) : null}
    </section>
  );
}
