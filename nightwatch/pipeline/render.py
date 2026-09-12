"""Plain-text rendering of an AnalysisReport for the CLI (and for logs)."""

from __future__ import annotations

from nightwatch.pipeline.analyze import AnalysisReport


def _f(v, fmt: str = "{:+.2f}", none: str = "n/a") -> str:  # noqa: ANN001
    return none if v is None else fmt.format(v)


def render_text(r: AnalysisReport) -> str:
    t = r.ticket
    lines: list[str] = []
    lines.append(f"NIGHTWATCH — {t.ticker} {t.side.value.upper()} {t.notional_quote:,.0f} USDT  |  as of {r.as_of:%Y-%m-%d %H:%M} UTC")
    lines.append(f"Horizon: {r.primary_horizon} = {r.horizon_h:.1f}h  |  session now: {r.snapshot.labels.get('session')} / regime {r.snapshot.labels.get('regime_label')}")
    lines.append("")
    lines.append(f"VERDICT: {r.verdict.verdict.value}" + (f"  → size {r.verdict.recommended_notional:,.0f}" if r.verdict.recommended_notional is not None else "") + (f"  → hedge {r.verdict.hedge_ratio:.0%}" if r.verdict.hedge_ratio else ""))
    for reason in r.verdict.reasons:
        lines.append(f"  - {reason}")
    lines.append("")
    lines.append("GATE: " + r.gate.decision.value)
    for rule in r.gate.rules:
        mark = "ok " if rule.decision.value == "GO" else ("?? " if rule.decision.value == "REVIEW_REQUIRED" else "XX ")
        lines.append(f"  {mark}{rule.rule}: {rule.reason}")
    lines.append("")
    s = r.snapshot
    f = s.features
    lines.append("NOW")
    lines.append(f"  spot {_f(s.prices['spot_close'], '{:.2f}')}  index {_f(s.prices['index_close'], '{:.2f}')}  native last close {_f(s.prices['native_close'], '{:.2f}')} ({_f(f.get('native_close_age_h'), '{:.0f}')}h old)")
    lines.append(f"  basis vs index {_f(f.get('basis_index_bps'), '{:+.1f}')} bps (z {_f(f.get('basis_index_z'))})  |  rv24 {_f(f.get('rv_24h'), '{:.0%}')} (pctl {_f(f.get('vol_pctl_90d'), '{:.0f}')})  |  trend {_f(f.get('trend_sma_pct'), '{:+.1f}')}% vs 30d avg  |  liq ratio {_f(f.get('liq_ratio'))}")
    hte = f.get("hours_to_earnings")
    earn = "n/a" if hte is None else (">30d" if hte >= 720 else f"{hte:.0f}h")
    lines.append(f"  earnings in {earn}  |  FOMC in {_f(f.get('hours_to_fomc'), '{:.0f}')}h  |  macro events next 72h {_f(f.get('macro_events_72h'), '{:.0f}')}  |  headlines 24h {_f(f.get('news_count_24h'), '{:.0f}')}")
    if s.quality_flags:
        lines.append("  flags: " + ", ".join(s.quality_flags))
    lines.append("")
    a = r.analog
    if a is None or not a.result.ok:
        lines.append(f"ANALOGS: none — {a.result.reason if a else 'not run'}")
    else:
        lines.append(f"ANALOGS: {a.result.n} distinct past moments ({a.scope}; {a.result.n_candidates} candidates, {a.result.n_distinct_available} distinct available)")
        for name, h in a.horizons.items():
            c = h.cohort
            if c.insufficient:
                lines.append(f"  {name:>10}: n={c.n} (insufficient; pending {c.n_pending})")
                continue
            base = ""
            if h.baseline and h.baseline.mean_diff_pct is not None:
                base = f" | vs random {h.baseline.baseline.n} hrs: {h.baseline.mean_diff_pct:+.2f}% (p={h.baseline.permutation_p_value:.2f})"
            adj = f" | calibrated p5 {h.p5_adjusted:+.2f}% p95 {h.p95_adjusted:+.2f}% (k {h.adjustment['k_lo']:.2f}/{h.adjustment['k_hi']:.2f}, n_fit {h.adjustment['n_fit']})" if h.p5_adjusted is not None and h.adjustment else ""
            lines.append(f"  {name:>10} ({h.hours:.0f}h): n={c.n} mean {c.mean_pct:+.2f}% [{c.ci_mean.low:+.2f},{c.ci_mean.high:+.2f}] med {c.median_pct:+.2f}% win {c.win_rate:.0%} | p5 {c.p5:+.2f}% p95 {c.p95:+.2f}%{adj} | worst-in-window p5 {c.mae_p5_pct:+.2f}% | tags {c.tag_counts}{base}")
    lines.append("")
    st = r.stress
    lines.append(f"STRESS ({st.inputs_summary['closed_windows_n']} closed windows, {st.inputs_summary['earnings_gaps_n']} earnings gaps, {st.inputs_summary['closed_basis_obs_n']} closed-hour basis obs)")
    for sc, imp in zip(st.presets, st.impacts, strict=True):
        breach = ",".join(k for k, v in imp.breaches.items() if v)
        lines.append(f"  {sc.severity.value:>8} {sc.name:<48} {_f(imp.total_pct_of_notional, '{:+.2f}')}% ({_f(imp.total_pnl_quote, '{:+,.0f}')})" + (f"  [{breach}]" if breach else ""))
    if st.monte_carlo:
        mc = st.monte_carlo
        lines.append(f"  Monte Carlo {mc.horizon_h}h ({mc.n_paths} paths, {mc.source_hours} source hours): p5 {mc.p5:+.2f}% p50 {mc.p50:+.2f}% p95 {mc.p95:+.2f}% | ES5 {mc.expected_shortfall_5_pct:+.2f}% | P(loss>5%) {mc.prob_loss_gt[5.0]:.1%} | worst-point p5 {mc.drawdown_p5:+.2f}%")
    if st.reverse_move_pct_for_5pct_loss is not None:
        lines.append(f"  Reverse: a {st.reverse_move_pct_for_5pct_loss:+.2f}% move loses 5% after exit costs")
    lines.append("")
    e = r.execution
    lines.append(f"EXIT ({e.book_source}" + (f", book {e.book_ts:%H:%M} UTC" if e.book_ts else "") + ")")
    if e.exit_quote:
        q = e.exit_quote
        lines.append(f"  {q.side} {q.notional_quote:,.0f}: {_f(q.total_cost_bps, '{:.1f}')} bps total ({_f(q.walk_cost_bps, '{:.1f}')} walk + {q.fee_bps:.0f} fee), {q.levels_consumed} levels, {'fills' if q.fully_filled else 'DOES NOT FILL'}")
        lines.append(f"  largest size that exits within the cost budget: {_f(e.max_notional_within_budget, '{:,.0f}')}")
    if e.hedge_quote:
        h = e.hedge_quote
        lines.append(f"  hedge 100% via {h.perp_symbol}: fees {h.entry_fee_quote + h.exit_fee_quote:,.1f} + funding {h.funding_quote:,.1f} (p95 {h.funding_quote_p95:,.1f}) = {h.total_cost_bps_of_position:.1f} bps; residual basis p95 {_f(h.residual_basis_p95_bps, '{:.0f}')} bps")
    lines.append("")
    lines.append("SIZING CAPS")
    for c in r.sizing.caps:
        mark = "*" if c.name == r.sizing.binding_cap else " "
        lines.append(f"  {mark} {c.name:<16} {_f(c.notional, '{:,.0f}')}  {c.detail}")
    if r.warnings:
        lines.append("")
        lines.append("WARNINGS")
        for w in r.warnings:
            lines.append(f"  ! {w}")
    lines.append("")
    lines.append("timings ms: " + ", ".join(f"{k}={v}" for k, v in r.timings_ms.items()))
    return "\n".join(lines)
