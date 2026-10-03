"use client";

import { useCallback, useEffect, useState } from "react";
import { Section } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { engagement, EngagementError, type PlanAction, type PlanScenario, type PlanView } from "@/lib/engagement";
import { fmtPct, fmtPrice, fmtUsd } from "@/lib/format";
import { type Lang, fmtTimeL, tr } from "@/lib/i18n";

const ORDER: PlanAction[] = ["hold", "cut_half", "exit", "hedge"];

export function actionName(lang: Lang, a: string): string {
  const L = tr(lang);
  switch (a) {
    case "hold":
      return L("Hold", "持有");
    case "cut_half":
      return L("Cut half", "减半");
    case "exit":
      return L("Exit", "离场");
    case "hedge":
      return L("Hedge with the perp", "永续对冲");
    default:
      return a;
  }
}

/** Decide now, not at 3 a.m.: for each way the trade can fail at a price, pick the action in
 *  advance. The prices and frequencies are the report's own measured numbers; saving arms a
 *  tripwire on each line so the alert repeats the choice. */
export function PlanCard({ forecastId, lang, openAll }: { forecastId: number; lang: Lang; openAll?: boolean }) {
  const L = tr(lang);
  const [view, setView] = useState<PlanView | null>(null);
  const [picks, setPicks] = useState<Record<string, PlanAction>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let off = false;
    engagement
      .planGet(forecastId)
      .then((v) => {
        if (off) return;
        setView(v);
        const saved: Record<string, PlanAction> = {};
        for (const s of v.scenarios) if (s.chosen) saved[s.key] = s.chosen.action;
        setPicks(saved);
      })
      .catch(() => undefined);
    return () => {
      off = true;
    };
  }, [forecastId]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const v = await engagement.planSave({ forecast_id: forecastId, choices: picks, arm: true, lang });
      setView(v);
      setMsg(
        v.arm_error
          ? L("Plan saved. Some alerts could not be armed (too many armed at once).", "计划已保存。部分价格警报未能设置（同时设置的数量已达上限）。")
          : L("Plan saved and the price alerts are armed.", "计划已保存，价格警报已设置。"),
      );
    } catch (e) {
      setError(e instanceof EngagementError ? e.message : L("Could not save the plan.", "无法保存计划。"));
    } finally {
      setBusy(false);
    }
  }, [forecastId, picks, lang, L]);

  if (!view || !view.scenarios.length) return null;
  const chosen = Object.keys(picks).length;
  return (
    <Section
      openAll={openAll}
      collapsible
      title={L("Your plan for each way it can go wrong", "每一种出错方式，你的应对计划")}
      subtitle={L(
        "Decide now, not at 3 a.m. Each line is a price from this report; pick what you will do when it trades through. Saving sets an alert that reminds you of the choice.",
        "现在决定，别等凌晨三点。每条线都是本报告算出的价格；预先选好触及时要做什么。保存后会设置警报，到时提醒你当初的选择。",
      )}
      summary={chosen ? L(`${chosen} of ${view.scenarios.length} decided`, `已决定 ${chosen}/${view.scenarios.length}`) : L(`${view.scenarios.length} price lines`, `${view.scenarios.length} 条价格线`)}
    >
      <ul className="space-y-3">
        {view.scenarios.map((s) => (
          <ScenarioRow key={s.key} s={s} lang={lang} pick={picks[s.key]} onPick={(a) => setPicks((p) => ({ ...p, [s.key]: a }))} />
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button size="sm" disabled={busy || !chosen} onClick={() => void save()}>
          {L("Save plan and arm alerts", "保存计划并设置警报")}
        </Button>
        {view.saved_at ? <span className="text-[13px] text-muted-foreground">{L(`Last saved ${fmtTimeL(view.saved_at, lang)}`, `上次保存 ${fmtTimeL(view.saved_at, lang)}`)}</span> : null}
      </div>
      <p className="mt-2 text-[13px] text-muted-foreground">
        {L(
          "Kept outside the signed receipt, with its own timestamp, so it never changes the anchored record. It lives on this server.",
          "保存在签名回执之外，带有自己的时间戳，因此不会改动已锚定的记录。数据存放在本服务器上。",
        )}
      </p>
      {msg ? <p className="mt-1 text-sm">{msg}</p> : null}
      {error ? <p className="mt-1 text-xs text-status-critical">{error}</p> : null}
    </Section>
  );
}

function ScenarioRow({ s, lang, pick, onPick }: { s: PlanScenario; lang: Lang; pick?: PlanAction; onPick: (a: PlanAction) => void }) {
  const L = tr(lang);
  const title = lang === "zh" && s.title_zh ? s.title_zh : s.title;
  const dir = s.direction === "below" ? L("below", "跌破") : L("above", "涨破");
  const fired = s.chosen?.tripwire_status === "fired";
  return (
    <li className="rounded-lg border border-border px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="font-medium">{title}</span>
        <span className="tabular text-sm">
          {dir} <span className="font-medium">{fmtPrice(s.price)}</span>
          <span className="text-muted-foreground"> · {fmtPct(s.move_pct, 1)}</span>
          {s.loss_quote != null ? <span className="text-status-critical"> · {fmtUsd(s.loss_quote)} USDT</span> : null}
        </span>
      </div>
      <p className="mt-1 text-[13px] text-muted-foreground">{L(`History: ${s.history}`, `历史：${s.history}`)}</p>
      <div role="group" aria-label={title} className="mt-2 flex flex-wrap gap-1.5">
        {ORDER.filter((a) => a in s.actions).map((a) => (
          <Button key={a} variant={pick === a ? "default" : "outline"} size="sm" aria-pressed={pick === a} onClick={() => onPick(a)}>
            {actionName(lang, a)}
            {a === "cut_half" || a === "exit" || a === "hedge" ? <span className="tabular text-xs opacity-70"> {fmtUsd(s.actions[a]?.size_quote ?? 0)}</span> : null}
          </Button>
        ))}
      </div>
      {s.chosen ? (
        <p className="mt-1.5 text-[13px] text-muted-foreground">
          {fired
            ? L(`Alert fired at ${fmtPrice(s.chosen.fired_price)}. You decided: ${actionName(lang, s.chosen.action).toLowerCase()}.`, `警报已于 ${fmtPrice(s.chosen.fired_price)} 触发。你当初决定：${actionName(lang, s.chosen.action)}。`)
            : s.chosen.tripwire_status === "armed"
              ? L("Alert armed.", "警报已设置。")
              : L("Saved, no alert armed.", "已保存，未设置警报。")}
        </p>
      ) : null}
    </li>
  );
}
