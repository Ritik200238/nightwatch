"""Narrowing the search, and refusing to when there is not enough left.

A lens changes which past moments count as comparable, which changes the answer a
trader is sized against. That makes two things worth pinning: the predicates mean what
their own descriptions say, and a lens that thins the history too far is refused rather
than answered from a handful of hours.
"""

import pandas as pd
import pytest

from nightwatch.analog import lens


def frame(**cols) -> pd.DataFrame:  # noqa: ANN003
    n = len(next(iter(cols.values())))
    base = {
        "hours_to_earnings": [999.0] * n, "hours_since_earnings": [999.0] * n,
        "hours_to_fomc": [999.0] * n, "hours_since_filing": [999.0] * n,
        "bucket": ["weeknight"] * n, "basis_index_z": [0.0] * n,
        "vol_pctl_90d": [50.0] * n, "liq_ratio": [1.0] * n,
        "trend_sma_pct": [0.0] * n, "vix_pctl_1y": [50.0] * n,
    }
    base.update(cols)
    return pd.DataFrame(base)


# ------------------------------------------------------------------ the predicates


def test_every_lens_has_a_definition_a_reader_can_check():
    """The definition is printed next to the result, so it has to say the threshold."""
    for x in lens.LENSES:
        assert x.label and x.definition, x.name
        assert x.name == x.name.lower() and " " not in x.name
        assert x.says, f"{x.name} has no phrasings, so the model cannot find it"


def test_earnings_lenses_split_before_from_after():
    f = frame(hours_to_earnings=[6.0, 48.0, 999.0], hours_since_earnings=[999.0, 999.0, 6.0])
    assert lens.BY_NAME["earnings_soon"].mask(f).tolist() == [True, False, False]
    assert lens.BY_NAME["earnings_this_week"].mask(f).tolist() == [True, True, False]
    assert lens.BY_NAME["just_after_earnings"].mask(f).tolist() == [False, False, True]


def test_weekend_covers_the_windows_a_trader_means_by_it():
    f = frame(bucket=["weekend", "friday_night", "sunday_night", "weeknight", "us_regular"])
    assert lens.BY_NAME["weekend"].mask(f).tolist() == [True, True, True, False, False]
    assert lens.BY_NAME["weeknight"].mask(f).tolist() == [False, False, False, True, False]
    assert lens.BY_NAME["market_open"].mask(f).tolist() == [False, False, False, False, True]
    # "Market shut" is every window the stock cannot trade in, which is the product's subject.
    assert lens.BY_NAME["market_shut"].mask(f).tolist() == [True, True, True, True, False]


def test_basis_lenses_are_two_sided():
    """A token trading far above fair value is as dislocated as one far below."""
    f = frame(basis_index_z=[3.0, -3.0, 0.2, -0.2, 1.0])
    assert lens.BY_NAME["basis_stretched"].mask(f).tolist() == [True, True, False, False, False]
    assert lens.BY_NAME["basis_calm"].mask(f).tolist() == [False, False, True, True, False]


def test_a_missing_column_matches_nothing_rather_than_everything():
    """A history without the column cannot satisfy the condition. Matching everything
    would quietly answer the unfiltered question under the filtered question's name."""
    f = pd.DataFrame({"bucket": ["weeknight"] * 3})
    assert lens.BY_NAME["earnings_soon"].mask(f).tolist() == [False, False, False]


def test_a_null_is_not_a_match():
    f = frame(vol_pctl_90d=[95.0, float("nan"), 10.0])
    assert lens.BY_NAME["high_volatility"].mask(f).tolist() == [True, False, False]


# -------------------------------------------------------------------- the resolving


def test_names_the_model_invented_are_dropped_not_obeyed():
    resolved = lens.resolve(["earnings_soon", "when_it_felt_scary", "WEEKEND", " weeknight "])
    assert [x.name for x in resolved] == ["earnings_soon", "weekend", "weeknight"]
    assert lens.resolve(None) == [] and lens.resolve([]) == []


def test_a_repeated_name_is_applied_once():
    assert len(lens.resolve(["weekend", "weekend"])) == 1


def test_conditions_combine_with_and():
    """"earnings nights over a weekend" means both, not either."""
    f = frame(hours_to_earnings=[6.0, 6.0, 999.0], bucket=["weekend", "weeknight", "weekend"])
    m = lens.mask(f, lens.resolve(["earnings_soon", "weekend"]))
    assert m.tolist() == [True, False, False]


# ------------------------------------------------------------------- the refusal


def test_a_lens_that_leaves_too_little_is_refused_and_says_so():
    """Narrowing thins the history fast. A distribution built from nine hours is worse
    than admitting there is not enough evidence for the question."""
    f = frame(hours_to_earnings=[6.0] * 5 + [999.0] * 995)
    out, result = lens.apply(f, ["earnings_soon"], min_rows=100)
    assert result.applied is False
    assert len(out) == 1000, "the unfiltered history is searched instead"
    assert "5 past hours" in result.refused and "earnings ahead" in result.refused
    assert result.n_before == 1000 and result.n_after == 5


def test_a_lens_with_enough_behind_it_is_applied():
    f = frame(hours_to_earnings=[6.0] * 400 + [999.0] * 600)
    out, result = lens.apply(f, ["earnings_soon"], min_rows=100)
    assert result.applied is True and len(out) == 400
    assert result.refused == "" and result.names == ["earnings_soon"]


def test_no_lens_means_no_filtering_and_no_claim_of_it():
    f = frame(vol_pctl_90d=[50.0] * 10)
    out, result = lens.apply(f, [], min_rows=1)
    assert len(out) == 10 and result.applied is False and result.lenses == []
    assert result.to_dict()["description"] == ""


def test_the_result_serialises_with_its_definitions():
    f = frame(bucket=["weekend"] * 500)
    _, result = lens.apply(f, ["weekend"], min_rows=100)
    d = result.to_dict()
    assert d["names"] == ["weekend"] and d["applied"] is True
    assert d["lenses"][0]["definition"], "the page shows what the filter actually was"


# ------------------------------------------------------------------- the offering


def _history(n: int = 400, **now) -> pd.DataFrame:  # noqa: ANN003
    """A plain history with one distinctive hour appended at the end, which is "now"."""
    past = frame(bucket=["weeknight"] * n)
    return pd.concat([past, frame(**{k: [v] for k, v in now.items()})], ignore_index=True)


def test_suggestions_describe_the_moment_in_front_of_the_trader():
    out = lens.suggest_now(_history(hours_to_earnings=5.0, vol_pctl_90d=90.0))
    assert "earnings_soon" in out and "high_volatility" in out


def test_suggestions_read_the_present_hour_not_an_older_one():
    """The frame the interface asks about runs to now, so the offer has to come off its
    last row. Reading any other row offers conditions that were true last week."""
    f = _history(hours_to_earnings=5.0)
    assert "earnings_soon" in lens.suggest_now(f)
    assert "earnings_soon" not in lens.suggest_now(f.iloc[:-1])


def test_a_condition_true_most_of_the_time_is_not_offered():
    """Offering "the market is shut" on a weeknight says nothing: it is true for nearly
    every hour in the history, so narrowing to it leaves the same answer under a name
    that implies a different one."""
    f = _history(bucket="weeknight")
    assert "market_shut" not in lens.suggest_now(f) and "weeknight" not in lens.suggest_now(f)


def test_the_rarest_condition_is_offered_first():
    """The unusual thing about tonight is the one worth asking about."""
    past = pd.concat(
        [frame(hours_to_earnings=[6.0] * 100), frame(vol_pctl_90d=[95.0] * 10), frame(bucket=["weeknight"] * 290)],
        ignore_index=True,
    )
    now = frame(hours_to_earnings=[6.0], vol_pctl_90d=[95.0])
    out = lens.suggest_now(pd.concat([past, now], ignore_index=True))
    assert out[0] == "high_volatility", "11 of 401 hours, against 101 for earnings ahead"
    assert "earnings_soon" in out


def test_no_more_than_a_handful_are_offered():
    assert len(lens.suggest_now(_history(hours_to_earnings=5.0, vol_pctl_90d=90.0, basis_index_z=3.0, liq_ratio=0.2, vix_pctl_1y=95.0))) <= lens.MAX_SUGGESTIONS


def test_suggesting_from_an_empty_history_offers_nothing():
    assert lens.suggest_now(pd.DataFrame()) == []


def test_the_menu_the_model_sees_names_every_lens_and_how_it_is_said():
    text = lens.prompt_menu()
    for x in lens.LENSES:
        assert f'"{x.name}"' in text and x.definition in text
    assert "earnings night" in text  # a phrasing, so the model can match on words


@pytest.mark.parametrize("name", [x.name for x in lens.LENSES])
def test_no_lens_is_dead_on_a_history_that_should_trigger_it(name):
    """A lens that can never match is a promise the desk cannot keep. Each one is given
    a row built to satisfy it; if it still does not fire, the predicate is wrong."""
    satisfying = {
        "earnings_soon": {"hours_to_earnings": [1.0]},
        "earnings_this_week": {"hours_to_earnings": [40.0]},
        "just_after_earnings": {"hours_since_earnings": [2.0]},
        "fomc_soon": {"hours_to_fomc": [10.0]},
        "weekend": {"bucket": ["weekend"]},
        "weeknight": {"bucket": ["weeknight"]},
        "market_shut": {"bucket": ["weeknight"]},
        "market_open": {"bucket": ["us_regular"]},
        "basis_stretched": {"basis_index_z": [2.5]},
        "basis_calm": {"basis_index_z": [0.1]},
        "high_volatility": {"vol_pctl_90d": [90.0]},
        "low_volatility": {"vol_pctl_90d": [10.0]},
        "thin_liquidity": {"liq_ratio": [0.3]},
        "uptrend": {"trend_sma_pct": [1.0]},
        "downtrend": {"trend_sma_pct": [-1.0]},
        "fresh_filing": {"hours_since_filing": [3.0]},
        "risk_off": {"vix_pctl_1y": [90.0]},
    }[name]
    assert lens.BY_NAME[name].mask(frame(**satisfying)).tolist() == [True]
