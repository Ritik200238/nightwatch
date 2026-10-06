"use client";

import { useEffect, useState } from "react";
import { api, type AgentRun } from "@/lib/api";

/** One stress-test agent run per forecast and language, kept at module level so a
 *  re-render, a tab switch or the chat chip never restarts it. */
export interface AgentState {
  run: AgentRun | null;
  started: boolean;
  error: boolean;
  elapsed: number;
}

const states = new Map<string, AgentState>();
const listeners = new Map<string, Set<() => void>>();
const key = (id: number, lang: string) => `${id}:${lang}`;
const EMPTY: AgentState = { run: null, started: false, error: false, elapsed: 0 };

function set(k: string, patch: Partial<AgentState>) {
  states.set(k, { ...(states.get(k) ?? EMPTY), ...patch });
  listeners.get(k)?.forEach((f) => f());
}

export function startAgent(id: number, lang: "en" | "zh"): void {
  const k = key(id, lang);
  if (states.get(k)?.started) return;
  const t0 = Date.now();
  set(k, { started: true, error: false, run: { status: "running", steps: [] }, elapsed: 0 });
  void (async () => {
    let misses = 0;
    try {
      const first = await api.agentStart(id, lang);
      set(k, { run: first, elapsed: (Date.now() - t0) / 1000 });
      let cur = first;
      for (let i = 0; i < 120 && cur.status !== "done" && cur.status !== "failed"; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        try {
          cur = await api.agentGet(id, lang);
          misses = 0;
          set(k, { run: cur, elapsed: (Date.now() - t0) / 1000 });
        } catch {
          if (++misses >= 5) throw new Error("poll");
        }
      }
      if (cur.status === "running" || cur.status === "none") set(k, { error: true, run: { ...cur, status: "failed" } });
    } catch {
      const prev = states.get(k)?.run;
      set(k, { error: true, run: { status: "failed", steps: prev?.steps ?? [] } });
    }
  })();
}

/** Allow a failed run to be tried again. */
export function resetAgent(id: number, lang: "en" | "zh"): void {
  const k = key(id, lang);
  if (states.get(k)?.run?.status === "failed") {
    states.delete(k);
    listeners.get(k)?.forEach((f) => f());
  }
}

export function useAgent(id: number | null | undefined, lang: "en" | "zh"): AgentState {
  const [, tick] = useState(0);
  const k = id != null && id > 0 ? key(id, lang) : "";
  useEffect(() => {
    if (!k) return;
    const f = () => tick((n) => n + 1);
    if (!listeners.has(k)) listeners.set(k, new Set());
    listeners.get(k)!.add(f);
    return () => {
      listeners.get(k)?.delete(f);
    };
  }, [k]);
  return (k && states.get(k)) || EMPTY;
}

/** The readable verb for a tool call. */
export function toolVerb(tool: string | undefined, args: Record<string, unknown> | undefined, zh: boolean): string {
  const a = args ?? {};
  const val = (k: string) => (typeof a[k] === "string" ? (a[k] as string) : Array.isArray(a[k]) ? (a[k] as unknown[]).join(",") : "");
  const t = (tool ?? "").toLowerCase();
  const lens = val("lenses");
  const side = val("side");
  const horizon = val("horizon");
  if (/explain|why/.test(t)) return zh ? "询问原因" : "Asked why";
  if (/base_?rate|baseline/.test(t)) return zh ? "查了基础概率" : "Checked the base rate";
  if (/safe|compare|hold/.test(t)) return zh ? "比较了最稳妥的持有方式" : "Compared the safest ways";
  if (/rerun|re_run|run/.test(t)) {
    // Say what was changed in the re-run, in the order a trader would: size, leverage, side, hold, lens.
    const num = (k: string) => (typeof a[k] === "number" ? (a[k] as number) : typeof a[k] === "string" && a[k] !== "" && Number.isFinite(Number(a[k])) ? Number(a[k]) : null);
    const size = num("notional_quote");
    const lev = num("leverage");
    const hours = num("horizon_hours");
    const parts: string[] = [];
    if (size != null) parts.push(zh ? `仓位 ${Math.round(size).toLocaleString("en-US")} USDT` : `at ${Math.round(size).toLocaleString("en-US")} USDT`);
    if (lev != null) parts.push(zh ? `${lev}倍杠杆` : lev <= 1 ? "with no leverage" : `at ${lev}x leverage`);
    if (side) parts.push(zh ? (side === "short" ? "做空" : "做多") : `as a ${side}`);
    if (horizon || hours != null) {
      const h = horizon ? horizon.replace(/_/g, " ") : `${hours}h`;
      parts.push(zh ? `持有期“${h}”` : `holding ${h}`);
    }
    if (lens.includes("earnings")) parts.push(zh ? "只看财报夜" : "on earnings nights only");
    else if (lens) parts.push(zh ? `按条件“${lens}”` : `with the ${lens.replace(/_/g, " ")} lens`);
    if (parts.length) return zh ? `重新运行：${parts.join("，")}` : `Re-ran ${parts.join(", ")}`;
    return zh ? "重新运行" : "Re-ran it";
  }
  return (tool ?? "").replace(/_/g, " ") || (zh ? "检查" : "A check");
}
