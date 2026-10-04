/** Says how many sentences the number guard dropped from a model's take, and why. */
export function guardText(n: number, lang: "en" | "zh"): string {
  // Calm wording: this is the check doing its job, not the analyst failing.
  return lang === "zh" ? `已与报告核对：略去了 ${n} 句数字无依据的话` : `Checked against the report: ${n} sentence${n === 1 ? "" : "s"} with unsupported numbers left out`;
}

export function GuardNote({ n, lang, className = "mt-2 text-[13px] text-muted-foreground" }: { n: number; lang: "en" | "zh"; className?: string }) {
  const why =
    lang === "zh"
      ? "分析师写完后，护栏逐句检查：引用了报告里没有的数字的句子会被删掉，只保留有依据的部分。"
      : "After the analyst writes, a guard checks every sentence: any that cites a number not in the report is deleted, so only supported sentences remain.";
  return (
    <p className={className}>
      <span title={why} tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-2">
        {guardText(n, lang)}
      </span>
    </p>
  );
}
