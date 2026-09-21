"""Tests for app.portfolio.trade_apgar (Elder ch. 58's "Trade Apgar" pre-trade go/no-go
score, docs/ideas.md's ch. 58 entry).

``TestScoreImpulse``/``TestPriceVsValueZone``/``TestScoreFalseBreakout``/``TestScorePerfection``
cover each individual question's scoring table. ``TestScoreTradeApgar`` covers the combined
go/no-go rule -- specifically the "no single zero" carve-out the task's own checklist calls
out by name: a trade whose summed score is >= 7 but has one question scored 0 must still
fail (``go=False``)."""

import pytest

from app.portfolio.trade_apgar import (
    price_vs_value_zone,
    score_false_breakout,
    score_impulse,
    score_perfection,
    score_price_vs_value,
    score_trade_apgar,
)


class TestScoreImpulse:
    @pytest.mark.parametrize(
        "color,expected_score",
        [("RED", 0), ("GREEN", 1), ("BLUE", 2)],
    )
    def test_matches_book_scale(self, color: str, expected_score: int) -> None:
        assert score_impulse(color) == expected_score  # type: ignore[arg-type]


class TestPriceVsValueZone:
    def test_close_above_both_emas_is_above_value(self) -> None:
        assert price_vs_value_zone(close=120.0, ema_13=110.0, ema_26=100.0) == "above_value"

    def test_close_below_both_emas_is_below_value(self) -> None:
        assert price_vs_value_zone(close=90.0, ema_13=110.0, ema_26=100.0) == "below_value"

    def test_close_between_emas_is_in_value_zone(self) -> None:
        assert price_vs_value_zone(close=105.0, ema_13=110.0, ema_26=100.0) == "in_value_zone"

    def test_close_exactly_at_upper_bound_is_in_value_zone(self) -> None:
        assert price_vs_value_zone(close=110.0, ema_13=110.0, ema_26=100.0) == "in_value_zone"

    def test_close_exactly_at_lower_bound_is_in_value_zone(self) -> None:
        assert price_vs_value_zone(close=100.0, ema_13=110.0, ema_26=100.0) == "in_value_zone"

    def test_downtrend_ema_ordering_still_classifies_correctly(self) -> None:
        """A downtrend has EMA(13) < EMA(26) -- the zone's bounds are min/max of the two, not
        a fixed ema_13-is-upper assumption."""
        assert price_vs_value_zone(close=95.0, ema_13=90.0, ema_26=100.0) == "in_value_zone"
        assert price_vs_value_zone(close=105.0, ema_13=90.0, ema_26=100.0) == "above_value"
        assert price_vs_value_zone(close=85.0, ema_13=90.0, ema_26=100.0) == "below_value"

    @pytest.mark.parametrize(
        "status,expected_score",
        [("above_value", 0), ("in_value_zone", 1), ("below_value", 2)],
    )
    def test_score_matches_book_scale(self, status: str, expected_score: int) -> None:
        assert score_price_vs_value(status) == expected_score  # type: ignore[arg-type]


class TestScoreFalseBreakout:
    @pytest.mark.parametrize(
        "status,expected_score",
        [("none", 0), ("already_happened", 1), ("on_the_verge", 2)],
    )
    def test_matches_book_scale(self, status: str, expected_score: int) -> None:
        assert score_false_breakout(status) == expected_score  # type: ignore[arg-type]


class TestScorePerfection:
    @pytest.mark.parametrize(
        "status,expected_score",
        [("neither", 0), ("one", 1), ("both", 2)],
    )
    def test_matches_book_scale(self, status: str, expected_score: int) -> None:
        assert score_perfection(status) == expected_score  # type: ignore[arg-type]


class TestScoreTradeApgar:
    def test_all_max_scores_totals_10_and_goes(self) -> None:
        result = score_trade_apgar(
            weekly_impulse="BLUE",
            daily_impulse="BLUE",
            price_vs_value="below_value",
            false_breakout_status="on_the_verge",
            perfection="both",
        )
        assert result.total_score == 10
        assert result.go is True
        assert [q.score for q in result.questions] == [2, 2, 2, 2, 2]

    def test_all_zero_scores_totals_0_and_does_not_go(self) -> None:
        result = score_trade_apgar(
            weekly_impulse="RED",
            daily_impulse="RED",
            price_vs_value="above_value",
            false_breakout_status="none",
            perfection="neither",
        )
        assert result.total_score == 0
        assert result.go is False

    def test_exactly_7_with_no_zero_goes(self) -> None:
        # 1 (GREEN weekly) + 2 (BLUE daily) + 2 (below_value) + 1 (already_happened) + 1 (one)
        # = 7, every question > 0.
        result = score_trade_apgar(
            weekly_impulse="GREEN",
            daily_impulse="BLUE",
            price_vs_value="below_value",
            false_breakout_status="already_happened",
            perfection="one",
        )
        assert result.total_score == 7
        assert result.go is True

    def test_6_total_does_not_go_even_with_no_zero(self) -> None:
        # 1 + 1 + 2 + 1 + 1 = 6 -- below the >=7 threshold, despite no single zero.
        result = score_trade_apgar(
            weekly_impulse="GREEN",
            daily_impulse="GREEN",
            price_vs_value="below_value",
            false_breakout_status="already_happened",
            perfection="one",
        )
        assert result.total_score == 6
        assert result.go is False

    def test_8_total_with_one_zero_still_does_not_go(self) -> None:
        """The task's own explicitly-called-out regression: a trade scoring 8 total but with
        one question scored 0 must still fail -- summing to >=7 is necessary but not
        sufficient."""
        # 0 (RED weekly) + 2 (BLUE daily) + 2 (below_value) + 2 (on_the_verge) + 2 (both) = 8.
        result = score_trade_apgar(
            weekly_impulse="RED",
            daily_impulse="BLUE",
            price_vs_value="below_value",
            false_breakout_status="on_the_verge",
            perfection="both",
        )
        assert result.total_score == 8
        assert result.go is False
        weekly_question = next(q for q in result.questions if q.key == "weekly_impulse")
        assert weekly_question.score == 0

    def test_questions_are_returned_in_book_order_with_correct_sources(self) -> None:
        result = score_trade_apgar(
            weekly_impulse="GREEN",
            daily_impulse="RED",
            price_vs_value="in_value_zone",
            false_breakout_status="none",
            perfection="one",
        )
        assert [q.key for q in result.questions] == [
            "weekly_impulse",
            "daily_impulse",
            "price_vs_value",
            "false_breakout",
            "perfection",
        ]
        assert [q.source for q in result.questions] == ["auto", "auto", "auto", "manual", "manual"]
        assert [q.value for q in result.questions] == [
            "GREEN",
            "RED",
            "in_value_zone",
            "none",
            "one",
        ]
