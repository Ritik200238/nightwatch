"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type DataSource, type Health, type MissesResponse, type VerifyResponse } from "@/lib/api";
import { useLang } from "@/lib/lang";

const REPO = "https://github.com/Ritik200238/nightwatch/tree/main/skills/nightwatch-stress-test";

function ageH(iso: string | null | undefined): number | null {
  return iso ? (Date.now() - new Date(iso).getTime()) / 3_600_000 : null;
}

interface Piece {
  key: string;
  en: string;
  zh: string;
  ok: boolean | null;
  href?: string;
}

/** What the desk has earned in public, and which Bitget pieces are live right now. Both
 *  read the same endpoints the /status page does, so the two cannot disagree. */
export function ProofStrip({ stocks }: { stocks: number | null }) {
  const { tx } = useLang();
  const [verify, setVerify] = useState<VerifyResponse | null>(null);
  const [misses, setMisses] = useState<MissesResponse | null>(null);
  const [rows, setRows] = useState<DataSource[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let live = true;
    void api.verify().then((v) => live && setVerify(v)).catch(() => {});
    void api.misses().then((m) => live && setMisses(m)).catch(() => {});
    void api.sources().then((r) => live && setRows(r)).catch(() => {});
    void api.health().then((h) => live && setHealth(h)).catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const scored = misses?.totals?.ticket;
  const fresh = (key: string, maxH: number, useLatest = false): boolean | null => {
    if (!rows) return null;
    const r = rows.find((x) => x.key === key);
    if (!r) return false;
    const h = ageH(useLatest ? (r.latest ?? r.last_update) : r.last_update);
    return h != null && h <= maxH;
  };
  const books = fresh("bitget_bars", 1, true);
  const pieces: Piece[] = [
    { key: "bars", en: "Bitget candles and order books", zh: "Bitget K 线和盘口", ok: books },
    { key: "tiers", en: "Bitget perp margin tiers (liquidation)", zh: "Bitget 永续保证金档位（强平）", ok: books },
    { key: "mcp", en: "Bitget US-stock MCP", zh: "Bitget 美股 MCP", ok: fresh("bitget_mcp", 3) },
    { key: "signal", en: "bitget-signal skill", zh: "bitget-signal 技能", ok: fresh("bitget_signal", 3) },
    { key: "qwen", en: "Qwen through the Bitget hackathon gateway", zh: "通过 Bitget 黑客松网关调用 Qwen", ok: health ? Boolean(health.llm?.ready) : null },
    { key: "skill", en: "Agent Hub skill file (in the repo)", zh: "Agent Hub 技能文件（在仓库中）", ok: true, href: REPO },
  ];

  return (
    <section className="space-y-2 rounded-lg border border-border bg-card px-4 py-3" aria-label={tx("Track record and Bitget pieces", "战绩与 Bitget 组件")}>
      <p className="text-sm">
        {verify ? (
          <>
            <span className="font-semibold tabular-nums">{verify.checked}</span> {tx("live verdicts given and scored in public", "个实盘结论已公开给出并评分")}
            {scored ? (
              <>
                {"; "}
                <Link href="/wrong" className="underline underline-offset-2 hover:text-foreground">
                  <span className="font-semibold tabular-nums">{scored.missed}</span> {tx("went past their line", "超出了自己划的线")}
                </Link>
                <span className="text-muted-foreground"> {tx(`(of ${scored.scored} already matured)`, `（已到期的 ${scored.scored} 个中）`)}</span>
              </>
            ) : null}
            {stocks ? <span className="text-muted-foreground"> · {tx(`${stocks} tokenized US stocks`, `${stocks} 只代币化美股`)}</span> : null}
          </>
        ) : (
          <span className="text-muted-foreground">{tx("Loading the public record…", "正在加载公开记录…")}</span>
        )}
      </p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
        {pieces.map((p) => (
          <li key={p.key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className={`h-2 w-2 rounded-full ${p.ok === true ? "bg-emerald-500" : p.ok === false ? "bg-amber-500" : "bg-muted-foreground/40"}`} />
            {p.href ? (
              <a href={p.href} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-foreground">
                {tx(p.en, p.zh)}
              </a>
            ) : (
              tx(p.en, p.zh)
            )}
            <span className="sr-only">{p.ok === true ? tx("live", "正常") : p.ok === false ? tx("stale", "过期") : tx("checking", "检查中")}</span>
          </li>
        ))}
      </ul>
      <p className="text-[13px] text-muted-foreground">
        <Link href="/status" className="underline underline-offset-2 hover:text-foreground">
          {tx("Live status and receipts", "实时状态与凭证")}
        </Link>
        {" · "}
        <Link href="/sources" className="underline underline-offset-2 hover:text-foreground">
          {tx("Data sources", "数据来源")}
        </Link>
      </p>
    </section>
  );
}
