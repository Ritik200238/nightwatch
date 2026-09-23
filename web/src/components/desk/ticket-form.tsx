"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, type HorizonKind, type Lens, type Side, type TicketInput, type UniverseEntry } from "@/lib/api";

interface Props {
  universe: UniverseEntry[];
  busy: boolean;
  onSubmit: (ticket: TicketInput) => void;
  initial?: Partial<TicketInput>;
}

type Errors = Partial<Record<"ticker" | "notional" | "equity" | "stop" | "hours", string>>;

interface Menu {
  lenses: Lens[];
  counts: Record<string, number>;
  floor: number;
  suggested: string[];
}

/** Which past moments the search is allowed to compare against.
 *
 *  The same seventeen conditions the model picks from when a trader asks for one in
 *  words, offered as a list so the feature is not hidden behind knowing to ask. Each
 *  one carries how many hours of this token's own history it leaves, because that is
 *  the cost: narrow far enough and there is no evidence left to answer from.
 */
function LensPicker({ ticker, chosen, onChange }: { ticker: string; chosen: string[]; onChange: (names: string[]) => void }) {
  const [menu, setMenu] = useState<Menu | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    let live = true;
    void api
      .lenses(ticker)
      .then((r) => {
        if (live) setMenu({ lenses: r.lenses, counts: r.counts ?? {}, floor: r.floor_hours, suggested: r.suggested ?? [] });
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
        <Label>Compare against</Label>
        <button
          type="button"
          className="rounded text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "Fewer" : `All ${menu.lenses.length}`}
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {shown.map((x) => {
          const on = chosen.includes(x.name);
          const n = menu.counts[x.name];
          return (
            <button
              key={x.name}
              type="button"
              aria-pressed={on}
              title={`${x.definition}${n != null ? ` — ${n.toLocaleString()} past hours in ${ticker}` : ""}`}
              onClick={() => toggle(x.name)}
              className={`rounded-full border px-2 py-0.5 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none ${
                on ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {x.label}
              {n != null ? <span className="ml-1 opacity-60 tabular-nums">{n.toLocaleString()}h</span> : null}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        {chosen.length === 0 ? (
          <>All past hours ranked by how much they resemble now. Pick a condition to rank inside it instead.</>
        ) : thin.length > 0 ? (
          <>
            Under {menu.floor.toLocaleString()} hours left in {ticker}&apos;s own past, so the search widens across tokens — or says it cannot answer.
          </>
        ) : (
          <>Ranked inside that history only, and the report says what it cost.</>
        )}
      </p>
    </div>
  );
}

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
  const [lenses, setLenses] = useState<string[]>(initial?.lenses ?? []);
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
        <div className="flex items-baseline justify-between gap-2">
          <Label htmlFor="thesis">Why this trade</Label>
          {/* The gate refuses a ticket with no written plan, which is the right rule and a
              poor first click. This fills a plausible one so the rule can be seen working
              rather than merely blocking. The stop stays empty on purpose. */}
          {!thesis && !invalidation ? (
            <button
              type="button"
              className="rounded text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              onClick={() => {
                setThesis(`${side === "long" ? "Strength" : "Weakness"} into the US open carries through the overnight session.`);
                setInvalidation(side === "long" ? "A close back below the 30-day average." : "A close back above the 30-day average.");
              }}
            >
              Fill an example
            </button>
          ) : null}
        </div>
        <Textarea id="thesis" rows={2} value={thesis} onChange={(e) => setThesis(e.target.value)} placeholder="One line. The gate needs a written reason." />
      </div>
      <LensPicker ticker={ticker} chosen={lenses} onChange={setLenses} />
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
