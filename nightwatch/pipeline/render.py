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
    if r.breaker.state.value != "NORMAL" or r.breaker.n_taken:
        lines.append(f"CIRCUIT BREAKER: {r.breaker.state.value} ({r.breaker.n_taken} taken trades) — " + "; ".join(r.breaker.reasons[:2]))
        lines.append("")
    if r.second_opinion and r.second_opinion.against:
        so = r.second_opinion
        lines.append("SECOND OPINION — " + so.summary)
        for c in so.against:
            lines.append(f"  - {c.text} [{c.source}]")
        for c in so.supporting:
            lines.append(f"  + {c.text} [{c.source}]")
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
    lines.append(f"  basis vs index {_f(f.get('basis_index_bps'), '{:+.1f}')} bps (z {_f(f.get('basis_index_z'))})  |  rv24 {_f(f.get('rv_24h'), '{:.0%}')} (pctl {_f(f.get('vol_pctl_90d'), '{:.0f}')})  |  trend {_f(f.get('trend_sma_pct'), '{:+.1f}')}% vs 30d avg")
    hte = f.get("hours_to_earnings")
    earn = "n/a" if hte is None else (">30d" if hte >= 720 else f"{hte:.0f}h")
    hsf = f.get("hours_since_filing")
    filing = "n/a" if hsf is None else (">30d ago" if hsf >= 720 else f"{hsf:.0f}h ago")
    lines.append(f"  earnings in {earn}  |  FOMC in {_f(f.get('hours_to_fomc'), '{:.0f}')}h  |  macro events next 72h {_f(f.get('macro_events_72h'), '{:.0f}')}  |  headlines 24h {_f(f.get('news_count_24h'), '{:.0f}')}")
    lines.append(f"  last SEC filing {filing}  |  filings in last 72h {_f(f.get('filings_72h'), '{:.0f}')}  |  liq vs same hour of week {_f(f.get('liq_ratio'), '{:.2f}x')}  |  no-trade share 24h {_f(f.get('no_trade_share_24h'), '{:.0%}')} ({_f(f.get('no_trade_excess_24h'), '{:+.0%}')} vs its norm)")
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
            lines.append(f"  {name:>10} ({h.hours:.0f}h): n={c.n} mean {c.mean_pct:+.2f}% [{c.ci_mean.low:+.2f},{c.ci_mean.high:+.2f}] med {c.median_pct:+.2f}% win {c.win_rate:.0%} | p5 {c.p5:+.2f}% p95 {c.p95:+.2f}%{adj} | ES5 {c.es5_pct:+.2f}% (n={c.es5_n}) | worst-in-window p5 {c.mae_p5_pct:+.2f}% | tags {c.tag_counts}{base}")
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
    lh = e.liquidity_history
    if lh and lh.buckets:
        usable = [b for b in lh.buckets if not b.thin]
        if usable:
            lines.append(f"  recorded book, {lh.n_snapshots:,} snapshots since {lh.since:%d %b}:")
            for b in usable[:4]:
                lines.append(f"    {b.bucket:<14} spread {b.spread_median_bps:>5.1f} bps | sellable in 25bps {b.depth_25bps_median:>10,.0f} | too thin for this size {(b.share_below_reference or 0):.0%} of the time")
        else:
            lines.append(f"  recorded book: {lh.note}")
    lines.append("")
    if r.sensitivity is not None:
        sen = r.sensitivity
        lines.append("WHAT WOULD CHANGE IT")
        for note in sen.notes:
            lines.append(f"  - {note}")
        flips = []
        prev = None
        for p in sen.sizes:
            if prev is not None and p.verdict != prev.verdict:
                flips.append(f"{prev.verdict} up to {prev.notional:,.0f} then {p.verdict} ({p.binding_cap})")
            prev = p
        if flips:
            lines.append("  size: " + "; ".join(flips))
        if sen.widest_stop_pct_for_requested_size is not None:
            lines.append(f"  stop: up to {sen.widest_stop_pct_for_requested_size:.2f}% away keeps the requested size inside the risk budget")
        lines.append("")
    if r.regimes and r.regimes.regimes:
        rm = r.regimes
        cur = rm.regime(rm.current)
        lines.append(f"REGIME MAP ({rm.n_fitted} past hours, {len(rm.regimes)} states; {rm.note})")
        for g in rm.regimes:
            mark = "*" if g.id == rm.current else " "
            band = f"next {rm.horizon_h}h med {g.next_ret_median_pct:+.2f}% p5 {g.next_ret_p5_pct:+.2f}%" if g.next_ret_median_pct is not None else f"only {g.n_outcomes} outcomes"
            lines.append(f"  {mark} {g.id}: {g.description:<52} {g.share:>4.0%} of hours, stays {g.persistence:.0%} | {band}")
        if cur is not None:
            nxt = sorted(((j, p) for j, p in enumerate(rm.transitions[rm.current]) if j != rm.current), key=lambda kv: -kv[1])[:2]
            lines.append("  most likely next: " + ", ".join(f"regime {j} {p:.0%}" for j, p in nxt))
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
