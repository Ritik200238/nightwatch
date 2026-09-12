"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { HorizonKind, Side, TicketInput, UniverseEntry } from "@/lib/api";

interface Props {
  universe: UniverseEntry[];
  busy: boolean;
  onSubmit: (ticket: TicketInput) => void;
  initial?: Partial<TicketInput>;
}

type Errors = Partial<Record<"ticker" | "notional" | "equity" | "stop" | "hours", string>>;

export function TicketForm({ universe, busy, onSubmit, initial }: Props) {
  const [ticker, setTicker] = useState(initial?.ticker ?? "TSLA");
  const [side, setSide] = useState<Side>(initial?.side ?? "long");
  const [notional, setNotional] = useState(String(initial?.notional_quote ?? 20000));
  const [equity, setEquity] = useState(initial?.account_equity_quote ? String(initial.account_equity_quote) : "200000");
  const [horizon, setHorizon] = useState<HorizonKind>(initial?.horizon_kind ?? "next_open");
  const [hours, setHours] = useState("");
  const [stop, setStop] = useState(initial?.stop_price ? String(initial.stop_price) : "");
  const [thesis, setThesis] = useState(initial?.thesis ?? "");
  const [invalidation, setInvalidation] = useState(initial?.invalidation ?? "");
  const [errors, setErrors] = useState<Errors>({});

  const available = universe.filter((u) => u.has_data);

  function validate(): TicketInput | null {
    const e: Errors = {};
    const n = Number(notional);
    const eq = equity.trim() ? Number(equity) : null;
    const st = stop.trim() ? Number(stop) : null;
    const hrs = hours.trim() ? Number(hours) : null;
    if (!ticker) e.ticker = "Pick a token.";
    if (!(n > 0)) e.notional = "Enter a size in USDT.";
    if (eq != null && !(eq > 0)) e.equity = "Equity must be positive.";
    if (st != null && !(st > 0)) e.stop = "Stop must be a price.";
    if (horizon === "hours" && !(hrs && hrs > 0)) e.hours = "Enter how many hours.";
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
      thesis,
      invalidation,
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
          <Label htmlFor="ticker">Token</Label>
          <Select value={ticker} onValueChange={(v) => setTicker(v ?? "")}>
            <SelectTrigger id="ticker" className="w-full" aria-invalid={!!errors.ticker}>
              <SelectValue placeholder="Pick a token" />
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
          <Label htmlFor="side">Direction</Label>
          <Select value={side} onValueChange={(v) => setSide(v as Side)}>
            <SelectTrigger id="side" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="long">Long</SelectItem>
              <SelectItem value="short">Short</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="notional">Size (USDT)</Label>
          <Input id="notional" type="number" inputMode="decimal" min={1} step="any" value={notional} onChange={(e) => setNotional(e.target.value)} aria-invalid={!!errors.notional} autoComplete="off" />
          {errors.notional ? <p className="text-xs text-destructive">{errors.notional}</p> : null}
        </div>
        <div className="space-y-1">
          <Label htmlFor="equity">Account equity (USDT)</Label>
          <Input id="equity" type="number" inputMode="decimal" min={1} step="any" value={equity} onChange={(e) => setEquity(e.target.value)} aria-invalid={!!errors.equity} autoComplete="off" />
          {errors.equity ? <p className="text-xs text-destructive">{errors.equity}</p> : null}
        </div>
        <div className="space-y-1">
          <Label htmlFor="horizon">Hold until</Label>
          <Select value={horizon} onValueChange={(v) => setHorizon(v as HorizonKind)}>
            <SelectTrigger id="horizon" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="next_open">Next US market open</SelectItem>
              <SelectItem value="window_end">End of this closed window / session</SelectItem>
              <SelectItem value="hours">A number of hours</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {horizon === "hours" ? (
          <div className="space-y-1">
            <Label htmlFor="hours">Hours</Label>
            <Input id="hours" type="number" inputMode="numeric" min={1} value={hours} onChange={(e) => setHours(e.target.value)} aria-invalid={!!errors.hours} autoComplete="off" />
            {errors.hours ? <p className="text-xs text-destructive">{errors.hours}</p> : null}
          </div>
        ) : (
          <div className="space-y-1">
            <Label htmlFor="stop">Stop price (optional)</Label>
            <Input id="stop" type="number" inputMode="decimal" min={0} step="any" value={stop} onChange={(e) => setStop(e.target.value)} aria-invalid={!!errors.stop} autoComplete="off" placeholder="e.g. 350" />
            {errors.stop ? <p className="text-xs text-destructive">{errors.stop}</p> : null}
          </div>
        )}
      </div>
      {horizon === "hours" ? (
        <div className="space-y-1">
          <Label htmlFor="stop2">Stop price (optional)</Label>
          <Input id="stop2" type="number" inputMode="decimal" min={0} step="any" value={stop} onChange={(e) => setStop(e.target.value)} autoComplete="off" />
        </div>
      ) : null}
      <div className="space-y-1">
        <Label htmlFor="thesis">Why this trade</Label>
        <Textarea id="thesis" rows={2} value={thesis} onChange={(e) => setThesis(e.target.value)} placeholder="One line. The gate needs a written reason." />
      </div>
      <div className="space-y-1">
        <Label htmlFor="invalidation">What proves it wrong</Label>
        <Textarea id="invalidation" rows={2} value={invalidation} onChange={(e) => setInvalidation(e.target.value)} placeholder="e.g. a close below 350" />
      </div>
      <Button type="submit" disabled={busy || available.length === 0} className="w-full">
        {busy ? "Stress-testing…" : "Stress-test this trade"}
      </Button>
      {available.length === 0 ? <p className="text-xs text-muted-foreground">No tokens have stored data yet. Run the sync first.</p> : null}
    </form>
  );
}
