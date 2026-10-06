"""The `analyze` command: the README's form works, and a bad ticket is a message."""

from datetime import UTC, datetime

import pytest

from nightwatch.cli import build_parser, cmd_analyze, parse_as_of


def test_the_ticker_can_be_positional_as_the_readme_shows_or_a_flag():
    p = build_parser()
    a = p.parse_args(["analyze", "TSLA", "--side", "long", "--notional", "20000", "--equity", "100000", "--stop", "350"])
    assert a.ticker_pos == "TSLA" and a.ticker is None and a.stop == 350.0
    b = p.parse_args(["analyze", "--ticker", "TSLA", "--notional", "1000", "--leverage", "5", "--no-record"])
    assert b.ticker == "TSLA" and b.leverage == 5.0 and b.no_record is True


def test_no_ticker_or_two_different_ones_is_refused_with_a_sentence(capsys):
    p = build_parser()
    for argv in (["analyze", "--notional", "1000"], ["analyze", "TSLA", "--ticker", "NVDA", "--notional", "1000"]):
        assert cmd_analyze(p.parse_args(argv), None) == 2
        assert "give the stock once" in capsys.readouterr().err


def test_as_of_with_an_offset_is_converted_not_relabelled():
    assert parse_as_of("2026-10-01T12:00:00") == datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert parse_as_of("2026-10-01T12:00:00+08:00") == datetime(2026, 10, 1, 4, tzinfo=UTC)
    assert parse_as_of("2026-10-01T12:00:00Z") == datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize("argv", [["analyze", "TSLA", "--notional", "-5"], ["analyze", "TSLA", "--notional", "100", "--horizon", "hours", "--hours", "1e9"]])
def test_a_bad_ticket_prints_an_error_not_a_traceback(argv, capsys, tmp_path, monkeypatch):
    from nightwatch.config import Settings

    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    code = cmd_analyze(build_parser().parse_args([*argv, "--offline"]), Settings(data_dir=tmp_path, db_filename="x.sqlite", core_tickers=("TSLA",)))
    assert code == 2 and capsys.readouterr().err.startswith("error:")


def test_proof_sync_check_fails_when_a_figure_is_stale(monkeypatch):
    """`--check` that always exits 0 cannot gate anything: stale figures must be a non-zero exit."""
    from nightwatch import proof_sync
    from nightwatch.cli import cmd_proof_sync

    args = build_parser().parse_args(["proof-sync", "--check"])
    monkeypatch.setattr(proof_sync, "run", lambda **kw: ["README.md: README receipts"])
    assert cmd_proof_sync(args, None) == 1
    monkeypatch.setattr(proof_sync, "run", lambda **kw: [])
    assert cmd_proof_sync(args, None) == 0
    # Without --check it writes and succeeds.
    monkeypatch.setattr(proof_sync, "run", lambda **kw: ["README.md: README receipts"])
    assert cmd_proof_sync(build_parser().parse_args(["proof-sync"]), None) == 0
