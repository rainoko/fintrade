"""Tests for app.portfolio.grading (Elder ch. 55 "Is This an A-Trade?", docs/Analyse.md §7 /
docs/ideas.md's ch. 55 cross-check).

``TestGradeTradeReferenceValues`` reproduces the book's own worked ADSK example exactly (its
three formulas hand-computed independently below, not just re-derived from the
implementation under test):

    Buy grade  = (day's high - buy price) / (day's high - day's low)
               = (52.49 - 51.77) / (52.49 - 51.75) = 0.72 / 0.74 = 0.972972972973 -> 97%
    Sell grade = (sell price - day's low) / (day's high - day's low)
               = (53.78 - 53.39) / (54.49 - 53.39) = 0.39 / 1.10 = 0.354545454545 -> 35%
    Trade grade = (sell price - buy price) / (channel high - channel low, entry day)
               = (53.78 - 51.77) / (53.87 - 47.61) = 2.01 / 6.26 = 0.321086261981 -> 32%

``TestRatioPctEdgeCases``/``TestGradeTrade*`` cover the undefined-ratio (None-returning)
cases each formula shares. ``TestGradeClosedTrade*`` covers the data-fetching wrapper that
derives the eight `grade_trade` arguments from a ticker's daily OHLCV history.
"""

import math

import pandas as pd
import pytest

from app.indicators.autoenvelope import autoenvelope
from app.portfolio.grading import (
    TradeGrade,
    buy_grade_pct,
    grade_closed_trade,
    grade_trade,
    grade_trade_from_filtered_history,
    sell_grade_pct,
    trade_grade_pct,
    trade_letter_grade,
)


class TestGradeTradeReferenceValues:
    """The book's own worked ADSK example (Elder ch. 55) -- see this module's own docstring
    for the by-hand arithmetic."""

    def test_buy_grade_matches_book_exactly(self) -> None:
        grade = buy_grade_pct(buy_price=51.77, entry_day_high=52.49, entry_day_low=51.75)
        assert grade == pytest.approx(97.2972972972973)
        assert round(grade) == 97

    def test_sell_grade_matches_book_exactly(self) -> None:
        grade = sell_grade_pct(sell_price=53.78, exit_day_high=54.49, exit_day_low=53.39)
        assert grade == pytest.approx(35.45454545454545)
        assert round(grade) == 35

    def test_trade_grade_matches_book_exactly(self) -> None:
        grade = trade_grade_pct(
            buy_price=51.77,
            sell_price=53.78,
            channel_upper_entry_day=53.87,
            channel_lower_entry_day=47.61,
        )
        assert grade == pytest.approx(32.10862619808307)
        assert round(grade) == 32

    def test_grade_trade_combines_all_three(self) -> None:
        grade = grade_trade(
            buy_price=51.77,
            entry_day_high=52.49,
            entry_day_low=51.75,
            sell_price=53.78,
            exit_day_high=54.49,
            exit_day_low=53.39,
            channel_upper_entry_day=53.87,
            channel_lower_entry_day=47.61,
        )
        assert grade == TradeGrade(
            buy_grade_pct=pytest.approx(97.2972972972973),
            sell_grade_pct=pytest.approx(35.45454545454545),
            trade_grade_pct=pytest.approx(32.10862619808307),
        )


class TestUndefinedRatiosReturnNone:
    def test_buy_grade_none_for_zero_day_range(self) -> None:
        assert buy_grade_pct(buy_price=100.0, entry_day_high=100.0, entry_day_low=100.0) is None

    def test_sell_grade_none_for_zero_day_range(self) -> None:
        assert sell_grade_pct(sell_price=100.0, exit_day_high=100.0, exit_day_low=100.0) is None

    def test_trade_grade_none_for_zero_channel_height(self) -> None:
        assert (
            trade_grade_pct(
                buy_price=50.0,
                sell_price=55.0,
                channel_upper_entry_day=60.0,
                channel_lower_entry_day=60.0,
            )
            is None
        )

    def test_trade_grade_none_for_inverted_channel(self) -> None:
        """channel_upper < channel_lower is degenerate (shouldn't happen from a real
        autoenvelope() call) but must still degrade to None, not a nonsensical negative-
        denominator ratio."""
        assert (
            trade_grade_pct(
                buy_price=50.0,
                sell_price=55.0,
                channel_upper_entry_day=40.0,
                channel_lower_entry_day=60.0,
            )
            is None
        )

    def test_buy_grade_none_for_nan_input(self) -> None:
        assert buy_grade_pct(buy_price=float("nan"), entry_day_high=100.0, entry_day_low=90.0) is None

    def test_trade_grade_none_for_infinite_channel_bound(self) -> None:
        assert (
            trade_grade_pct(
                buy_price=50.0,
                sell_price=55.0,
                channel_upper_entry_day=float("inf"),
                channel_lower_entry_day=40.0,
            )
            is None
        )


def _frame(n: int, *, start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n)
    closes = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000.0 for _ in closes],
        },
        index=idx,
    )


class TestGradeClosedTrade:
    """`grade_closed_trade` is the data-fetching wrapper around `grade_trade` -- these tests
    confirm the wiring (correct rows/columns pulled for the right dates), not the underlying
    formula math (covered by TestGradeTradeReferenceValues) or autoenvelope()'s own math
    (covered by tests/unit/indicators/test_autoenvelope.py)."""

    def test_matches_grade_trade_called_directly_with_the_same_extracted_values(self) -> None:
        frame = _frame(150)
        entry_ts, exit_ts = frame.index[120], frame.index[130]
        entry_date, exit_date = entry_ts.date(), exit_ts.date()
        entry_price, exit_price = 101.0, 103.0

        result = grade_closed_trade(
            entry_price=entry_price,
            entry_date=entry_date,
            exit_price=exit_price,
            exit_date=exit_date,
            daily_ohlcv=frame,
        )

        channel = autoenvelope(frame["close"])
        expected = grade_trade(
            buy_price=entry_price,
            entry_day_high=float(frame.loc[entry_ts, "high"]),
            entry_day_low=float(frame.loc[entry_ts, "low"]),
            sell_price=exit_price,
            exit_day_high=float(frame.loc[exit_ts, "high"]),
            exit_day_low=float(frame.loc[exit_ts, "low"]),
            channel_upper_entry_day=float(channel.loc[entry_ts, "upper"]),
            channel_lower_entry_day=float(channel.loc[entry_ts, "lower"]),
        )
        assert result == expected
        # Channel bounds are well past the ~100-bar warm-up window by bar 120, so this is a
        # genuine non-trivial (non-None) trade_grade_pct, not a NaN==NaN coincidence.
        assert result.trade_grade_pct is not None

    def test_none_when_entry_date_not_in_history(self) -> None:
        frame = _frame(150)
        result = grade_closed_trade(
            entry_price=100.0,
            entry_date=frame.index[0].date().replace(year=1999),
            exit_price=105.0,
            exit_date=frame.index[130].date(),
            daily_ohlcv=frame,
        )
        assert result == TradeGrade(buy_grade_pct=None, sell_grade_pct=None, trade_grade_pct=None)

    def test_none_when_exit_date_not_in_history(self) -> None:
        frame = _frame(150)
        result = grade_closed_trade(
            entry_price=100.0,
            entry_date=frame.index[120].date(),
            exit_price=105.0,
            exit_date=frame.index[-1].date().replace(year=2099),
            daily_ohlcv=frame,
        )
        assert result == TradeGrade(buy_grade_pct=None, sell_grade_pct=None, trade_grade_pct=None)

    def test_none_trade_grade_but_real_buy_sell_grades_inside_channel_warmup_window(self) -> None:
        """The Autoenvelope's rolling deviation average needs ~100 bars; entry_date at bar 10
        is well inside that warm-up window, so channel_upper/lower are NaN there --
        trade_grade_pct must be None, but buy_grade_pct/sell_grade_pct (which don't depend on
        the channel at all) must still be real numbers."""
        frame = _frame(150)
        result = grade_closed_trade(
            entry_price=100.5,
            entry_date=frame.index[10].date(),
            exit_price=103.0,
            exit_date=frame.index[130].date(),
            daily_ohlcv=frame,
        )
        assert result.trade_grade_pct is None
        assert result.buy_grade_pct is not None
        assert result.sell_grade_pct is not None

    def test_none_when_entry_day_bar_is_malformed(self) -> None:
        """A NaN open/high/low/close on entry_date's own bar means it doesn't survive
        drop_malformed_daily_bars, so it's treated the same as "not in history at all"."""
        frame = _frame(150)
        entry_ts = frame.index[120]
        frame.loc[entry_ts, "high"] = math.nan

        result = grade_closed_trade(
            entry_price=100.5,
            entry_date=entry_ts.date(),
            exit_price=103.0,
            exit_date=frame.index[130].date(),
            daily_ohlcv=frame,
        )
        assert result == TradeGrade(buy_grade_pct=None, sell_grade_pct=None, trade_grade_pct=None)


class TestGradeTradeFromFilteredHistory:
    """`grade_trade_from_filtered_history` is the shared per-row step `grade_closed_trade`
    itself delegates to after deriving the filtered frame/channel once -- and the one a
    multi-row-per-ticker caller (e.g. `app.api.routers.portfolio._grade_closed_trades`) is
    meant to call directly with an already-derived filtered frame/channel, instead of paying
    for `drop_malformed_daily_bars`/`autoenvelope` again per row (`backend-trade-grading-
    followups`)."""

    def test_grade_closed_trade_delegates_to_it_with_identical_results(self) -> None:
        """`grade_closed_trade` (single-trade convenience wrapper) must produce byte-identical
        results to calling `grade_trade_from_filtered_history` directly against the same
        already-filtered frame/channel -- proving the split didn't change any behavior, just
        where the filtering/channel derivation happens."""
        frame = _frame(150)
        entry_ts, exit_ts = frame.index[120], frame.index[130]
        entry_date, exit_date = entry_ts.date(), exit_ts.date()
        entry_price, exit_price = 101.0, 103.0

        via_wrapper = grade_closed_trade(
            entry_price=entry_price,
            entry_date=entry_date,
            exit_price=exit_price,
            exit_date=exit_date,
            daily_ohlcv=frame,
        )

        channel = autoenvelope(frame["close"])
        via_shared_step = grade_trade_from_filtered_history(
            entry_price=entry_price,
            entry_date=entry_date,
            exit_price=exit_price,
            exit_date=exit_date,
            filtered_daily_ohlcv=frame,
            channel=channel,
        )

        assert via_wrapper == via_shared_step
        assert via_shared_step.trade_grade_pct is not None

    def test_none_when_entry_date_not_in_filtered_frame(self) -> None:
        frame = _frame(150)
        channel = autoenvelope(frame["close"])
        result = grade_trade_from_filtered_history(
            entry_price=100.0,
            entry_date=frame.index[0].date().replace(year=1999),
            exit_price=105.0,
            exit_date=frame.index[130].date(),
            filtered_daily_ohlcv=frame,
            channel=channel,
        )
        assert result == TradeGrade(buy_grade_pct=None, sell_grade_pct=None, trade_grade_pct=None)

    def test_a_shared_channel_grades_multiple_rows_of_the_same_ticker_correctly(self) -> None:
        """The core scenario the followups task fixes: two closed trades on the same ticker,
        graded off one shared filtered-frame/channel pair, each still getting their own
        correct entry/exit-day values."""
        frame = _frame(150)
        channel = autoenvelope(frame["close"])

        first = grade_trade_from_filtered_history(
            entry_price=101.0,
            entry_date=frame.index[120].date(),
            exit_price=103.0,
            exit_date=frame.index[130].date(),
            filtered_daily_ohlcv=frame,
            channel=channel,
        )
        second = grade_trade_from_filtered_history(
            entry_price=100.5,
            entry_date=frame.index[105].date(),
            exit_price=102.0,
            exit_date=frame.index[115].date(),
            filtered_daily_ohlcv=frame,
            channel=channel,
        )

        assert first == grade_closed_trade(
            entry_price=101.0,
            entry_date=frame.index[120].date(),
            exit_price=103.0,
            exit_date=frame.index[130].date(),
            daily_ohlcv=frame,
        )
        assert second == grade_closed_trade(
            entry_price=100.5,
            entry_date=frame.index[105].date(),
            exit_price=102.0,
            exit_date=frame.index[115].date(),
            daily_ohlcv=frame,
        )


class TestTradeLetterGrade:
    """`trade_letter_grade` -- the `backend-trade-grade-letter` task's A/B/C/D mapping of
    `trade_grade_pct` (see that function's own docstring/module comment for the full
    decision record). A >= 30%, B in [20%, 30%), C in [10%, 20%), D < 10% (no floor)."""

    def test_none_when_trade_grade_pct_is_none(self) -> None:
        assert trade_letter_grade(None) is None

    def test_book_given_a_anchor_is_graded_a(self) -> None:
        """The book's own explicit anchor: >=30% capture is an 'A' trade."""
        assert trade_letter_grade(30.0) == "A"

    def test_book_given_c_anchor_is_graded_c(self) -> None:
        """The book's own explicit anchor: ~10% capture is a 'C' trade."""
        assert trade_letter_grade(10.0) == "C"

    def test_well_above_a_threshold_is_a(self) -> None:
        assert trade_letter_grade(97.3) == "A"

    def test_just_above_a_threshold_is_a(self) -> None:
        assert trade_letter_grade(30.01) == "A"

    def test_just_below_a_threshold_is_b(self) -> None:
        assert trade_letter_grade(29.99) == "B"

    def test_midpoint_between_anchors_is_b(self) -> None:
        assert trade_letter_grade(25.0) == "B"

    def test_at_b_threshold_is_b(self) -> None:
        assert trade_letter_grade(20.0) == "B"

    def test_just_below_b_threshold_is_c(self) -> None:
        assert trade_letter_grade(19.99) == "C"

    def test_just_above_c_threshold_is_c(self) -> None:
        assert trade_letter_grade(10.01) == "C"

    def test_just_below_c_threshold_is_d(self) -> None:
        assert trade_letter_grade(9.99) == "D"

    def test_zero_is_d(self) -> None:
        assert trade_letter_grade(0.0) == "D"

    def test_negative_losing_trade_is_d_with_no_floor(self) -> None:
        """A losing trade (sell price below buy price) yields a negative trade_grade_pct --
        still "poor", i.e. D, not a separate undefined case."""
        assert trade_letter_grade(-42.0) == "D"
