"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { tr, type Lang } from "./i18n";

const KEY = "nightwatch.lang";

interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  /** `tx(english, chinese)` for the current language. */
  tx: (en: string, zh: string) => string;
}

const Ctx = createContext<LangCtx>({ lang: "en", setLang: () => {}, tx: tr("en") });

/** Global UI language. Server render and first client render are both "en" so hydration
 *  matches; the stored or browser language is applied right after mount. */
export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    let next: Lang | null = null;
    try {
      const s = localStorage.getItem(KEY);
      if (s === "en" || s === "zh") next = s;
    } catch {
      /* storage blocked: fall through to the browser language */
    }
    if (!next) next = typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en";
    setLangState(next);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(KEY, l);
    } catch {
      /* not persisted */
    }
  }, []);

  const value = useMemo(() => ({ lang, setLang, tx: tr(lang) }), [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLang(): LangCtx {
  return useContext(Ctx);
}

/** Compact EN / 中文 switch for the header. */
export function LangToggle() {
  const { lang, setLang } = useLang();
  const base = "min-h-10 min-w-10 px-2 py-1 text-xs sm:min-h-0 sm:min-w-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";
  return (
    <div role="group" aria-label="Language / 语言" className="inline-flex shrink-0 overflow-hidden rounded-md border border-border">
      {(["en", "zh"] as const).map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={`${base} ${lang === l ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60"}`}
        >
          {l === "en" ? "EN" : "中文"}
        </button>
      ))}
    </div>
  );
}
