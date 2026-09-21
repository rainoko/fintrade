"""Tests for app.portfolio.homework (Elder ch. 57's "Am I ready to trade?" 5-question daily
psychological readiness self-test, docs/ideas.md's ch. 57 entry).

``TestBandForTotalScore`` covers every boundary the book's own color-banding scheme defines:
<=4 red, 5-6 yellow, 7-8 green, 9-10 yellow again -- specifically the 4/5, 6/7, and 8/9
transitions the task's own checklist calls out, plus the 0 and 10 extremes.
``TestSuggestedYesterdayTradingScore`` covers the net-realized-P&L-to-suggested-score mapping
(the "decide whether this auto-populates" checklist item's resulting behavior).
"""

import pytest

from app.portfolio.homework import band_for_total_score, suggested_yesterday_trading_score


class TestBandForTotalScore:
    @pytest.mark.parametrize(
        "total_score,expected_band",
        [
            (0, "red"),
            (4, "red"),
            (5, "yellow"),
            (6, "yellow"),
            (7, "green"),
            (8, "green"),
            (9, "yellow"),
            (10, "yellow"),
        ],
    )
    def test_matches_book_thresholds(self, total_score: int, expected_band: str) -> None:
        assert band_for_total_score(total_score) == expected_band

    def test_4_5_boundary(self) -> None:
        assert band_for_total_score(4) == "red"
        assert band_for_total_score(5) == "yellow"

    def test_6_7_boundary(self) -> None:
        assert band_for_total_score(6) == "yellow"
        assert band_for_total_score(7) == "green"

    def test_8_9_boundary(self) -> None:
        assert band_for_total_score(8) == "green"
        assert band_for_total_score(9) == "yellow"


class TestSuggestedYesterdayTradingScore:
    def test_null_pnl_suggests_nothing(self) -> None:
        assert suggested_yesterday_trading_score(None) is None

    def test_net_gain_suggests_2(self) -> None:
        assert suggested_yesterday_trading_score(150.0) == 2

    def test_net_loss_suggests_0(self) -> None:
        assert suggested_yesterday_trading_score(-42.0) == 0

    def test_exact_breakeven_suggests_1(self) -> None:
        assert suggested_yesterday_trading_score(0.0) == 1

    def test_tiny_net_gain_still_suggests_2(self) -> None:
        assert suggested_yesterday_trading_score(0.01) == 2

    def test_tiny_net_loss_still_suggests_0(self) -> None:
        assert suggested_yesterday_trading_score(-0.01) == 0

    def test_multi_trade_breakeven_sum_still_suggests_1(self) -> None:
        """Regression test: a multi-trade day whose individual currency amounts sum to exactly
        zero can still land on a non-zero float like -1.15e-14 due to binary floating point,
        because sum() accumulates each ClosedTradeORM.realized_pnl in order rather than
        rounding to cents first. A naive `net_realized_pnl == 0` check misses this and falls
        through to "traded poorly" (0) instead of "neutral" (1)."""
        net_realized_pnl = sum([100.10, 5.05, -105.15])
        assert net_realized_pnl != 0  # sanity check that this really doesn't hit exact 0.0
        assert suggested_yesterday_trading_score(net_realized_pnl) == 1
