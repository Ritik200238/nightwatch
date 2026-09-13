"use client";

import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Side, UniverseEntry } from "@/lib/api";

export interface OpenPosition {
  ticker: string;
  side: Side;
  notional_quote: number;
}

const STORAGE_KEY = "nightwatch.positions";

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
      if (raw) setPositions(JSON.parse(raw) as OpenPosition[]);
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
  const available = universe.filter((u) => u.has_data);
  const [ticker, setTicker] = useState(available[0]?.ticker ?? "NVDA");
  const [side, setSide] = useState<Side>("long");
  const [size, setSize] = useState("");

  function add() {
    const n = Number(size);
    if (!(n > 0) || !ticker) return;
    onChange([...positions, { ticker, side, notional_quote: n }]);
    setSize("");
  }

  const gross = positions.reduce((a, p) => a + p.notional_quote, 0);

  return (
    <section className="space-y-3" aria-labelledby="book-heading">
      <div>
        <h2 id="book-heading" className="text-sm font-medium">
          What you already hold
        </h2>
        <p className="text-xs text-muted-foreground">Optional. Stays in this browser; sent with an analysis so the report can judge the whole book.</p>
      </div>

      {positions.length ? (
        <ul className="space-y-1">
          {positions.map((p, i) => (
            <li key={`${p.ticker}-${i}`} className="flex items-center gap-2 rounded-md border border-border px-2 py-1 text-sm">
              <span className="font-medium">{p.ticker}</span>
              <span className="text-muted-foreground">{p.side}</span>
              <span className="tabular ml-auto">{p.notional_quote.toLocaleString()} USDT</span>
              <Button variant="ghost" size="icon" aria-label={`Remove ${p.ticker}`} onClick={() => onChange(positions.filter((_, j) => j !== i))}>
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </li>
          ))}
          <li className="px-2 pt-1 text-xs text-muted-foreground">Gross {gross.toLocaleString()} USDT across {positions.length} position{positions.length === 1 ? "" : "s"}</li>
        </ul>
      ) : null}

      <div className="grid grid-cols-[1fr_auto_1fr_auto] items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="pos-ticker" className="text-xs">
            Token
          </Label>
          <Select value={ticker} onValueChange={(v) => setTicker(v ?? "")}>
            <SelectTrigger id="pos-ticker" className="w-full">
              <SelectValue placeholder="Token" />
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
            Side
          </Label>
          <Select value={side} onValueChange={(v) => setSide((v as Side) ?? "long")}>
            <SelectTrigger id="pos-side">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="long">long</SelectItem>
              <SelectItem value="short">short</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="pos-size" className="text-xs">
            Size (USDT)
          </Label>
          <Input
            id="pos-size"
            type="number"
            inputMode="decimal"
            min={0}
            step="any"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            autoComplete="off"
          />
        </div>
        <Button type="button" variant="secondary" onClick={add} disabled={!size.trim()}>
          Add
        </Button>
      </div>
    </section>
  );
}
