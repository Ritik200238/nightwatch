"""The closed-hours study, on worlds whose answer is known.

Each test builds token bars from a process with a chosen volatility by session (or a
chosen weekend-to-Monday relationship) and checks that the measurement recovers it, and
that it says "no" when the truth is no."""

from datetime import date

import numpy as np
import pandas as pd

from nightwatch.journal import closed_hours as ch

FIRST, LAST = date(2025, 2, 3), date(2026, 1, 30)
TICKERS = [f"T{i}" for i in range(8)]


def hourly_kinds():
    wins = ch.session_windows(FIRST, LAST)
    idx = pd.date_range(pd.Timestamp(FIRST, tz="UTC"), pd.Timestamp(LAST, tz="UTC"), freq="1h")
    kind = ch.classify_times(ch._ns(idx) // 1_000_000, wins)
    return wins, idx, kind


def token_close(rng, idx, kind, sd_open, sd_closed, start=100.0):
    sd = np.where(kind == "open", sd_open, sd_closed)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(0, sd))), index=idx)


def inputs_from(closes, daily=None, earnings=None, books=None):
    return ch.Inputs(spot_close=closes, daily=daily or {}, earnings=earnings or {}, books=books or {})


# ------------------------------------------------------------------ the calendar


def test_windows_cover_the_week_without_gaps_and_name_the_weekend():
    w = ch.session_windows(date(2025, 3, 17), date(2025, 3, 28))
    w = w[w["start"] >= pd.Timestamp("2025-03-17", tz="UTC")].reset_index(drop=True)
    # each window starts where the previous one ended
    assert (w["start"].iloc[1:].to_numpy() == w["end"].iloc[:-1].to_numpy()).all()
    wk = w[w["kind"] == "weekend"].iloc[0]
    assert abs(wk["hours"] - 65.0) < 1e-9  # Fri 16:00 -> Mon 09:00 ET
    assert wk["d0"] == date(2025, 3, 21) and wk["d1"] == date(2025, 3, 24)
    assert set(w["kind"]) == {"open", "overnight", "weekend"}
    assert (w.loc[w["kind"] == "open", "hours"] == 7.0).all()


def test_a_weekday_holiday_is_its_own_kind_and_an_early_close_is_shorter():
    w = ch.session_windows(date(2025, 11, 20), date(2025, 12, 5))
    # Thanksgiving Thu 27 Nov 2025: the closed window across it is a holiday, and Fri 28 closes at 13:00
    hol = w[(w["kind"] == "holiday")]
    assert len(hol) == 1 and hol.iloc[0]["d0"] == date(2025, 11, 26) and hol.iloc[0]["d1"] == date(2025, 11, 28)
    fri = w[(w["kind"] == "open") & (w["d0"] == date(2025, 11, 28))].iloc[0]
    assert fri["hours"] == 4.0  # 09:00 -> 13:00


def test_price_at_uses_only_bars_that_had_closed_and_reports_their_age():
    idx = pd.DatetimeIndex(["2025-03-03 10:00", "2025-03-03 11:00", "2025-03-03 15:00"], tz="UTC")
    s = pd.Series([1.0, 2.0, 3.0], index=idx)
    t = pd.DatetimeIndex(["2025-03-03 10:30", "2025-03-03 12:00", "2025-03-03 15:30", "2025-03-03 16:00"], tz="UTC")
    px, age = ch.price_at(s, t)
    assert np.isnan(px[0])  # the 10:00 bar has not closed at 10:30
    assert px[1] == 2.0 and age[1] == 0.0
    assert px[2] == 2.0 and abs(age[2] - 3.5) < 1e-9  # the 11:00 bar closed at 12:00
    assert px[3] == 3.0 and age[3] == 0.0


def test_block_resamples_always_draw_every_week_slot():
    c = ch.block_counts(37, 50, 4, np.random.default_rng(1))
    assert c.shape == (50, 37) and (c.sum(axis=1) == 37).all()


# ------------------------------------------------------------------ Q1


def q1(sd_open, sd_closed, seed=0):
    rng = np.random.default_rng(seed)
    wins, idx, kind = hourly_kinds()
    closes = {t: token_close(rng, idx, kind, sd_open, sd_closed) for t in TICKERS}
    per = {t: ch.flag_earnings(ch.window_returns(c, wins), set()) for t, c in closes.items()}
    return ch.movement(ch.movement_rows(per)), wins


def test_equal_volatility_means_the_closed_share_is_just_the_clock():
    res, _ = q1(0.004, 0.004)
    st = res["stats"]
    assert abs(st["var_share"]["est"] - st["time_share"]["est"]) < 0.03
    assert abs(st["per_hour_var_ratio"]["est"] - 1.0) < 0.15  # no hour is busier than another
    assert st["per_hour_var_ratio"]["lo"] < 1.1 and st["per_hour_var_ratio"]["hi"] > 0.9
    assert 0.78 < st["time_share"]["est"] < 0.84  # about 80% of the week is closed


def test_quiet_closed_hours_are_reported_as_quiet_even_when_they_hold_most_of_the_movement():
    # closed hours half as volatile per hour: variance per hour a quarter of an open hour's,
    # yet still more than half of all variance because they are 80% of the clock
    res, _ = q1(0.006, 0.003)
    st = res["stats"]
    assert st["per_hour_var_ratio"]["hi"] < 0.4 and abs(st["per_hour_var_ratio"]["est"] - 0.25) < 0.04
    assert 0.45 < st["var_share"]["est"] < 0.60
    assert st["var_share"]["lo"] < st["var_share"]["est"] < st["var_share"]["hi"]


def test_busy_closed_hours_show_up_as_a_ratio_above_one():
    res, _ = q1(0.003, 0.006)
    assert res["stats"]["per_hour_var_ratio"]["lo"] > 3.0
    assert res["stats"]["var_share"]["lo"] > 0.9


def test_dropping_stale_and_earnings_windows_only_removes_windows():
    rng = np.random.default_rng(3)
    wins, idx, kind = hourly_kinds()
    c = token_close(rng, idx, kind, 0.004, 0.004)
    c = c[(c.index.hour % 5) != 0]  # a token that skips hours, so some boundaries are stale
    e = {date(2025, 4, 23), date(2025, 7, 23)}
    per = {"T0": ch.flag_earnings(ch.window_returns(c, wins), e)}
    rows = ch.movement_rows(per)
    assert rows["earn"].sum() > 0 and (~rows["fresh"]).sum() > 0
    full = ch.movement(rows)["n_windows"]
    assert ch.movement(rows, drop_earnings=True)["n_windows"] < full
    assert ch.movement(rows, only_fresh=True)["n_windows"] <= full


# ------------------------------------------------------------------ Q2


def q2(beta, seed=0, noise=0.004, sd_token=0.0003, weekend_sd=0.02):
    """Token weekend move W; the stock's Monday gap is beta * W + noise."""
    rng = np.random.default_rng(seed)
    wins, idx, kind = hourly_kinds()
    wk = wins[wins["kind"] == "weekend"].reset_index(drop=True)
    market = rng.normal(0, weekend_sd, len(wk))  # the weekend's common move
    closes, daily = {}, {}
    for t in TICKERS:
        c = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0, sd_token, len(idx)))), index=idx)
        stock_open, stock_close = {}, {}
        price = 100.0
        W = market + rng.normal(0, weekend_sd / 2, len(wk))
        # splice the weekend move into the token path as one hourly step 20 hours into the weekend
        adj = np.zeros(len(idx))
        for i, r in wk.iterrows():
            j = idx.searchsorted(r["start"]) + 20
            if j < len(idx):
                adj[j] += W[i]
        c = c * np.exp(np.cumsum(adj))
        closes[t] = c
        # stock: close each trading day = the token's own price at 16:00 (close-of-day), open gap from the weekend
        wins_open = wins[wins["kind"] == "open"]
        wk_by_d1 = {r["d1"]: i for i, r in wk.iterrows()}
        level = 100.0
        for r in wins_open.itertuples():
            prev = level
            open_px = prev
            if r.d0 in wk_by_d1:
                # realised W from the token's own series so the truth is exactly what is stored
                i = wk_by_d1[r.d0]
                open_px = prev * np.exp(beta * W[i] + rng.normal(0, noise))
            close_px = open_px * np.exp(rng.normal(0, 0.004))
            ts = pd.Timestamp(r.start) + pd.Timedelta(minutes=30)
            stock_open[ts], stock_close[ts] = open_px, close_px
            level = close_px
        daily[t] = pd.DataFrame({"open": pd.Series(stock_open), "close": pd.Series(stock_close)})
    return ch.run(inputs_from(closes, daily), first=FIRST, last=LAST)


def test_a_weekend_move_the_stock_follows_is_informative():
    res = q2(beta=1.0)
    blk = res["weekend"]["primary"]
    st = blk["stats"]
    assert blk["n"] > 300
    assert abs(st["slope_open"]["est"] - 1.0) < 0.2 and st["slope_open"]["lo"] > 0.6
    assert st["gap_after_up_minus_down"]["lo"] > 0
    assert st["oos_skill"]["lo"] > 0.3
    assert res["weekend"]["verdict"] == "yes"


def test_a_weekend_move_the_stock_ignores_is_not_called_informative():
    res = q2(beta=0.0, seed=4)
    st = res["weekend"]["primary"]["stats"]
    assert st["slope_open"]["lo"] < 0 < st["slope_open"]["hi"]
    assert st["oos_skill"]["est"] < 0.05
    assert res["weekend"]["verdict"] in ("no", "unclear")
    assert res["weekend"]["verdict"] != "yes"


def test_a_noisy_weekend_price_pulls_the_slope_toward_zero_which_is_why_it_is_not_read_as_a_ratio_of_one():
    # Same truth (the stock follows the token one for one), but the token's weekend price
    # carries 5x the noise: the measured slope must fall, and the report says "kept".
    clean = q2(beta=1.0, seed=3)["weekend"]["primary"]["stats"]["slope_open"]["est"]
    noisy = q2(beta=1.0, seed=3, sd_token=0.0015)["weekend"]["primary"]["stats"]["slope_open"]["est"]
    assert noisy < clean - 0.1


def test_half_kept_is_measured_as_half():
    res = q2(beta=0.5, seed=7)
    s = res["weekend"]["primary"]["stats"]["slope_open"]
    assert s["lo"] < 0.5 < s["hi"]


def test_stale_tokens_are_dropped_from_the_primary_weekend_population():
    res = q2(beta=1.0, seed=2)
    assert res["weekend"]["primary"]["n"] <= res["weekend"]["all_weekends"]["n"]


def test_stock_days_ignores_a_live_partial_bar():
    idx = pd.DatetimeIndex(["2025-03-03 14:30:00", "2025-03-04 14:30:07"], tz="UTC")
    d = pd.DataFrame({"open": [10.0, 11.0], "close": [10.5, 11.5]}, index=idx)
    out = ch.stock_days(d)
    assert list(out.index) == [date(2025, 3, 3)]


def test_report_line_quotes_only_what_was_measured():
    res = q2(beta=1.0, seed=5)
    line = ch.report_line(res, "T0")
    assert line and "while the US market was shut" in line and "weekends" in line and "n=" in line
    assert ch.report_line(res, "NOPE") is None


# ------------------------------------------------------------------ Q3


def book_frame(rng, wins, spread_closed, depth_closed, per_class=400):
    rows = []
    for kind, sp, dp in (("open", 2.0, 100_000.0), ("overnight", spread_closed, depth_closed), ("weekend", spread_closed, depth_closed)):
        w = wins[wins["kind"] == kind]
        for r in w.sample(min(len(w), 30), random_state=1).itertuples():
            ts = (pd.Timestamp(r.start).value // 1_000_000) + (rng.uniform(0, 1, per_class // 30) * r.hours * 3_600_000).astype("int64")
            for x in ts:
                rows.append((int(x), sp * np.exp(rng.normal(0, 0.1)), dp * np.exp(rng.normal(0, 0.1))))
    df = pd.DataFrame(rows, columns=["ts", "spread_bps", "depth"]).sort_values("ts")
    return df


def test_a_thinner_closed_book_is_measured_as_thinner():
    rng = np.random.default_rng(0)
    wins = ch.session_windows(date(2025, 3, 3), date(2025, 9, 1))
    books = {t: book_frame(rng, wins, 6.0, 25_000.0) for t in TICKERS[:4]}
    out = ch.liquidity(books, wins)
    st = out["stats"]
    assert abs(st["spread_ratio_weekend"]["est"] - 3.0) < 0.3
    assert abs(st["depth_ratio_weekend"]["est"] - 0.25) < 0.05
    assert st["spread_ratio_weekend"]["lo"] > 2.0
    assert out["n_weekend_days"] >= 3


def test_no_book_means_no_claim():
    out = ch.liquidity({}, ch.session_windows(date(2025, 3, 3), date(2025, 3, 14)))
    assert out["n_snapshots"] == 0 and out["stats"] == {}
