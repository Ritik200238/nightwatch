"use client";

import { useEffect, useState } from "react";
import { OpenSection as Section } from "@/components/proof-page";
import { api, type ChatCheck } from "@/lib/api";
import { useLang } from "@/lib/lang";

/** The blind check of the chat reader. The sentences were written the way a trader types
 *  (typos, slang, English and Chinese mixed, "15 000", "2万U") with the answers fixed before
 *  the reader ran; every miss is listed below, including the ones that are not fixed. The
 *  figures are the committed result of research/intake_blind_eval.py. */
export function ChatCheckSection() {
  const { tx } = useLang();
  const [c, setC] = useState<ChatCheck | null>(null);
  useEffect(() => {
    let live = true;
    api.chatCheck().then((r) => live && setC(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  if (!c?.available) return null;
  const wrong = c.fields - c.fields_ok;
  return (
    <Section title={tx("Does the chat read a messy sentence right?", "聊天能读对一句乱七八糟的话吗？")}>
      <p className="max-w-prose text-sm">
        {tx(
          `${c.cases_ok} of ${c.cases} sentences were read fully right, and ${c.fields_ok} of ${c.fields} fields (ticker, side, size, leverage, weekend). Wrong fields: ${wrong}.`,
          `${c.cases} 句里有 ${c.cases_ok} 句完全读对；${c.fields} 个字段（代币、方向、仓位、杠杆、是否过周末）里读对 ${c.fields_ok} 个，读错 ${wrong} 个。`,
        )}
      </p>
      <p className="mt-2 max-w-prose text-[13px] text-muted-foreground">
        {tx(
          "The first run of this check found a size of 15 000 USDT read as zero; that and four other misses are fixed and pinned by tests. What is left is listed, not hidden. A miss here makes the desk ask again; it never makes it invent a number.",
          "这项检查第一次运行时，发现“15 000 USDT”被读成 0；它和另外四处错误已经修复并有测试固定。剩下的都列在下面，没有隐藏。这里的错误只会让系统再问一次，不会让它编造数字。",
        )}
      </p>
      <ul className="mt-3 space-y-1 text-[13px]">
        {c.misses.map((m) => (
          <li key={m.text} className="flex flex-wrap gap-x-2">
            <code className="rounded bg-muted px-1">{m.text}</code>
            <span className="text-muted-foreground">
              {Object.entries(m.wrong)
                .map(([k, [want, got]]) => `${k}: ${tx("expected", "应为")} ${String(want)}, ${tx("read", "读成")} ${String(got)}`)
                .join("; ")}
            </span>
          </li>
        ))}
      </ul>
      {c.ran_at ? <p className="mt-2 text-[13px] text-muted-foreground">{tx("Run", "运行于")} {c.ran_at.slice(0, 10)}.</p> : null}
    </Section>
  );
}
