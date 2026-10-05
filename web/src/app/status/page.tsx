"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { api, probeHealth, type Liveness, type Anchor, type CalibrationReport, type DataSource, type Health, type VerifyResponse } from "@/lib/api";
import { fmtAge, isFresh, sourceAgeIso } from "@/lib/freshness";
import { PageHead, PROOF_WIDTH } from "@/components/proof-page";
import { useLang } from "@/lib/lang";
import { AsOf } from "@/components/as-of";
import { localSource } from "@/lib/source-zh";
import { fmtDateTimeL } from "@/lib/i18n";

type Load<T> = { data: T | null; error: boolean };

function useLoad<T>(fn: () => Promise<T>): Load<T> {
  const [state, setState] = useState<Load<T>>({ data: null, error: false });
  useEffect(() => {
    let live = true;
    void fn()
      .then((data) => live && setState({ data, error: false }))
      .catch(() => live && setState({ data: null, error: true }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return state;
}

function Dot({ ok }: { ok: boolean | null }) {
  return <span aria-hidden className={`inline-block h-2 w-2 shrink-0 rounded-full ${ok === true ? "bg-emerald-500" : ok === false ? "bg-red-500" : "bg-muted-foreground/40"}`} />;
}

function Card({ title, ok, children }: { title: string; ok: boolean | null; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Dot ok={ok} />
        {title}
      </h2>
      <div className="mt-2 space-y-1 text-sm text-muted-foreground">{children}</div>
    </section>
  );
}

const short = (h: string) => `${h.slice(0, 10)}…${h.slice(-6)}`;

/** Is the thing running, are the feeds fresh, can the receipts be checked, and has the
 *  calibration held. Everything here is read live; nothing is cached on this page. */
export default function StatusPage() {
  const { tx, lang } = useLang();
  const zh = lang === "zh";
  // One bounded check (about 16 s at most) that always ends as up, slow or down.
  const health = useLoad<Liveness>(() => probeHealth());
  const sources = useLoad<DataSource[]>(() => api.sources());
  const verify = useLoad<VerifyResponse>(() => api.verify());
  const anchors = useLoad<{ anchors: Anchor[] }>(() => api.anchors());
  const calib = useLoad<CalibrationReport>(() => api.calibration());

  const stale = sources.data?.filter((r) => !isFresh(r)).length;
  const list = anchors.data?.anchors ?? [];
  const latestAnchor = list.length ? list[list.length - 1] : null;
  const band = calib.data?.adjusted?.adj_tail_band;
  const NA = tx("unavailable", "不可用");

  return (
    <div className={`${PROOF_WIDTH} space-y-4`}>
      <PageHead title={tx("Status", "状态")} intro={health.data?.state === "down" ? tx("The API is down, so the cards below may be saved copies, not live readings.", "API 离线，下面的卡片可能是已保存的副本，而非实时读数。") : tx("Read live from the API each time you open this page.", "每次打开页面都从 API 实时读取。")} />

      <AsOf path="/sources" />
      <Card title="API" ok={health.data ? health.data.state === "up" : null}>
        {health.data && health.data.state !== "down" ? (
          <p>
            {health.data.state === "slow" ? tx("Up but slow", "运行中，但响应较慢") : tx("Up", "运行中")} · v{health.data.health.version} · {health.data.health.bars.toLocaleString()} {tx("candles", "根 K 线")} · {health.data.health.orderbook_snapshots.toLocaleString()} {tx("order-book snapshots", "个盘口快照")} · {health.data.health.tickers_with_data} {tx("tokens with data", "个有数据的代币")}
            {health.data.health.llm ? ` · ${tx("analyst model", "分析师模型")} ${health.data.health.llm.ready ? tx("ready", "就绪") : tx("not ready", "未就绪")}` : ""}
          </p>
        ) : health.data ? (
          <p>
            {tx("Down: the API is not answering right now.", "离线：API 暂时没有响应。")}{" "}
            {health.data.savedAt
              ? tx(`Showing saved data from ${fmtDateTimeL(health.data.savedAt, lang)}.`, `正在显示 ${fmtDateTimeL(health.data.savedAt, lang)} 的已保存数据。`)
              : tx("Saved copies of the public pages are still shown.", "公开页面仍显示已保存的副本。")}
          </p>
        ) : (
          <p>{tx("Checking (up to 15 seconds)…", "检查中（最多 15 秒）…")}</p>
        )}
      </Card>

      <Card title={tx("Feed freshness", "数据源新鲜度")} ok={sources.error ? false : sources.data ? stale === 0 : null}>
        {sources.data ? (
          <ul className="space-y-1">
            {sources.data.map((r) => (
              <li key={r.key} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  <Dot ok={isFresh(r)} />
                  {localSource(r, zh).label}
                </span>
                <span className="text-[13px]">
                  {fmtAge(sourceAgeIso(r), zh)} · {isFresh(r) ? tx("ok", "正常") : tx("stale", "过期")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p>{sources.error ? NA : tx("Checking…", "检查中…")}</p>
        )}
        <p className="pt-1 text-[13px]">
          <Link href="/sources" className="underline underline-offset-2 hover:text-foreground">
            {tx("What each feed is", "每个数据源是什么")}
          </Link>
        </p>
      </Card>

      <Card title={tx("Receipt chain", "凭证链")} ok={verify.error ? false : verify.data ? verify.data.ok && !verify.data.first_break : null}>
        {verify.data ? (
          <>
            <p>
              {verify.data.ok ? tx("Intact", "完整") : tx("BROKEN", "已断裂")} · {verify.data.checked} {tx("verdicts re-checked just now", "个结论刚刚重新校验")} · {verify.data.unchained} {tx("unchained", "个未入链")}
            </p>
            {verify.data.first_break ? (
              <p className="text-destructive">
                {tx("First break at seq", "首个断点序号")} {verify.data.first_break.seq}: {verify.data.first_break.reason}
              </p>
            ) : null}
            <p className="font-mono text-[13px] break-all">
              {tx("head", "链头")} {short(verify.data.head)}
            </p>
          </>
        ) : (
          <p>{verify.error ? NA : tx("Re-checking every receipt…", "正在重新校验每张凭证…")}</p>
        )}
      </Card>

      <Card title={tx("Latest Bitcoin anchor", "最新比特币锚定")} ok={anchors.error ? false : anchors.data ? latestAnchor?.state === "bitcoin" : null}>
        {latestAnchor ? (
          <>
            <p>
              {latestAnchor.state === "bitcoin" ? tx("Confirmed in Bitcoin", "已写入比特币") : tx("Waiting for a Bitcoin block", "等待比特币区块")}
              {latestAnchor.block ? ` · ${tx("block", "区块")} ${latestAnchor.block.toLocaleString()}` : ""} · {tx("covers receipts up to", "覆盖到序号")} {latestAnchor.seq}
            </p>
            <p className="font-mono text-[13px] break-all">
              {tx("head", "链头")} {short(latestAnchor.head)}
            </p>
            {latestAnchor.verified ? (
              <p className="text-[13px]">
                {tx("Stamped", "盖章于")} {fmtAge(latestAnchor.verified, zh)}
              </p>
            ) : null}
          </>
        ) : (
          <p>{anchors.error ? NA : anchors.data ? tx("No anchor yet.", "还没有锚定记录。") : tx("Checking…", "检查中…")}</p>
        )}
      </Card>

      <Card title={tx("Calibration", "校准")} ok={calib.error ? false : band ? band === "green" : null}>
        {calib.data?.adjusted ? (
          <p>
            {tx("Tail band after adjustment", "调整后的尾部区间")}: <span className="font-semibold text-foreground">{band}</span> · {calib.data.adjusted.n_evaluated.toLocaleString()} {tx("matured forecasts evaluated", "个已到期预测已评估")} ·{" "}
            <Link href="/calibration" className="underline underline-offset-2 hover:text-foreground">
              {tx("details", "详情")}
            </Link>
          </p>
        ) : (
          <p>{calib.error ? NA : tx("Checking…", "检查中…")}</p>
        )}
      </Card>
    </div>
  );
}
