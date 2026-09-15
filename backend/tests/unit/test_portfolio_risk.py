"""Tests for app.portfolio.risk (docs/Analyse.md §7: SafeZone-style protective
stop, the 2% per-trade rule, and the 6% total-open-risk rule).

See docs/tasks/portfolio-risk-rules.json's `decisions` array for the
parameter choices (10-trading-day lookback, EMA(13) as the "short EMA",
`stops` keyed by position.id, current_price required rather than falling
back to avg_cost_basis) hand-computed/justified below.
"""

from datetime import date

import pandas as pd
import pytest

from app.portfolio.models import Account, Equity, Position
from app.portfolio.risk import (
    position_risk_pct,
    protective_stop,
    total_open_risk_pct,
)


def _position(
    id: str = "pos_1",
    ticker: str = "AAPL",
    quantity: float = 10.0,
    avg_cost_basis: float = 100.0,
    current_price: float | None = 100.0,
) -> Position:
    return Position(
        id=id,
        ticker=ticker,
        quantity=quantity,
        avg_cost_basis=avg_cost_basis,
        entry_date=date(2026, 1, 1),
        current_price=current_price,
    )


def _account(total_equity: float, positions: list[Position] | None = None) -> Account:
    return Account(
        equity=Equity(cash=total_equity, positions_value=0.0, total=total_equity),
        positions=positions or [],
    )


class TestProtectiveStop:
    def test_reference_values_short_series(self) -> None:
        """5 rows (fewer than the 10-day window), so tail(10) covers the
        whole series and the EMA(13)/penetration-average can be hand-computed
        end to end.

        close = [100, 102, 101, 103, 104], low = [99, 100, 99, 101, 102]

        EMA(13), k = 2/14 = 1/7, seeded with the first close value:
          e0 = 100
          e1 = 100 + (102-100)/7        = 100.285714
          e2 = e1 + (101-e1)/7          = 100.387755
          e3 = e2 + (103-e2)/7          = 100.760933
          e4 = e3 + (104-e3)/7          = 101.223657

        Downside penetration_t = max(e_t - low_t, 0):
          p0 = 100 - 99          = 1.0
          p1 = 100.285714 - 100  = 0.285714
          p2 = 100.387755 - 99   = 1.387755
          p3 = 100.760933 - 101  -> negative -> 0.0
          p4 = 101.223657 - 102  -> negative -> 0.0

        volatility_buffer = mean(p0..p4) = (1 + 0.285714 + 1.387755) / 5 = 0.534694
        swing_low = min(low) = 99
        protective_stop = 99 - 0.534694 = 98.465306
        """
        daily_ohlcv = pd.DataFrame(
            {
                "close": [100.0, 102.0, 101.0, 103.0, 104.0],
                "low": [99.0, 100.0, 99.0, 101.0, 102.0],
            }
        )

        stop = protective_stop(_position(), daily_ohlcv)

        assert stop == pytest.approx(98.465306, abs=1e-5)

    def test_stop_is_below_swing_low(self) -> None:
        """The buffer must be subtracted (never added), so the stop is
        always at or below the plain swing low whenever any penetration
        occurred in the window."""
        daily_ohlcv = pd.DataFrame(
            {
                "close": [50.0, 48.0, 47.0, 49.0, 46.0, 45.0],
                "low": [49.0, 46.0, 45.0, 47.0, 44.0, 43.0],
            }
        )

        stop = protective_stop(_position(), daily_ohlcv)

        assert stop < daily_ohlcv["low"].min()

    def test_only_last_10_days_considered(self) -> None:
        """A swing low/penetration far outside the 10-day window must not
        affect the result. `close` is held constant throughout (padding and
        recent alike) so EMA(13) is path-independent (seeded at 100, stays
        100 with no input change) -- isolating the swing-low/penetration
        *windowing* behavior from EMA's own path dependency on history.

        Padding: 15 rows, close=100, low=100 -- except one row with an
        extreme low=1 (a fake older "swing low" that must be excluded).
        Recent: exactly 10 rows (the window size), close=100, low=95.

        Since close is constant everywhere, EMA(13) == 100 for every row
        (padded or not), so penetration_t = max(100 - low_t, 0):
          - recent rows: 100 - 95 = 5, for all 10 rows -> buffer = 5
          - swing_low over the recent window = 95
          - protective_stop = 95 - 5 = 90

        This must come out identical whether or not the padding (and its
        low=1 outlier) precedes it, since only the last 10 rows are
        in-window.
        """
        recent = pd.DataFrame({"close": [100.0] * 10, "low": [95.0] * 10})
        padding_low = [100.0] * 14 + [1.0]
        padded = pd.concat(
            [
                pd.DataFrame({"close": [100.0] * 15, "low": padding_low}),
                recent,
            ],
            ignore_index=True,
        )

        stop_recent_only = protective_stop(_position(), recent)
        stop_padded = protective_stop(_position(), padded)

        assert stop_recent_only == pytest.approx(90.0)
        assert stop_padded == pytest.approx(stop_recent_only)

    def test_empty_dataframe_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one row"):
            protective_stop(_position(), pd.DataFrame(columns=["close", "low"]))

    def test_missing_column_raises(self) -> None:
        with pytest.raises(ValueError, match="missing required column"):
            protective_stop(_position(), pd.DataFrame({"close": [100.0]}))

    def test_precomputed_short_ema_matches_internal_computation(self) -> None:
        """Passing `short_ema` (e.g. a caller-shared EMA(13) series -- see the
        portfolio-exit-rules-followups task's `decisions` entry) must produce the exact same
        stop as letting protective_stop compute it internally, given the true EMA(13) of the
        same close series."""
        from app.indicators.ema import ema

        daily_ohlcv = pd.DataFrame(
            {
                "close": [100.0, 102.0, 101.0, 103.0, 104.0],
                "low": [99.0, 100.0, 99.0, 101.0, 102.0],
            }
        )
        precomputed = ema(daily_ohlcv["close"], 13)

        stop_default = protective_stop(_position(), daily_ohlcv)
        stop_shared = protective_stop(_position(), daily_ohlcv, short_ema=precomputed)

        assert stop_shared == pytest.approx(stop_default)

    def test_precomputed_short_ema_is_actually_used_not_ignored(self) -> None:
        """A deliberately wrong `short_ema` must change the result -- confirms the parameter
        is actually wired in, not silently ignored in favor of always recomputing."""
        daily_ohlcv = pd.DataFrame(
            {
                "close": [100.0, 102.0, 101.0, 103.0, 104.0],
                "low": [99.0, 100.0, 99.0, 101.0, 102.0],
            }
        )
        wrong_ema = pd.Series([1000.0] * len(daily_ohlcv))

        stop_default = protective_stop(_position(), daily_ohlcv)
        stop_with_wrong_ema = protective_stop(_position(), daily_ohlcv, short_ema=wrong_ema)

        assert stop_with_wrong_ema != pytest.approx(stop_default)


class TestPositionRiskPct:
    def test_reference_value(self) -> None:
        """quantity=10, current_price=100, stop=98 -> distance=2, risk
        amount=20, equity=1000 -> 20/1000 = 2%."""
        position = _position(quantity=10.0, current_price=100.0)
        account = _account(total_equity=1000.0, positions=[position])

        assert position_risk_pct(position, stop=98.0, account=account) == pytest.approx(2.0)

    def test_oversized_position_exceeds_two_percent(self) -> None:
        """A deliberately oversized position: a wide stop distance relative
        to equity pushes risk well past the 2% rule threshold."""
        position = _position(quantity=100.0, current_price=100.0)
        account = _account(total_equity=1000.0, positions=[position])

        risk = position_risk_pct(position, stop=80.0, account=account)

        assert risk == pytest.approx(200.0)
        assert risk > 2.0

    def test_uses_current_price_not_entry_cost_basis(self) -> None:
        """Risk must react to a price move even though avg_cost_basis (the
        entry-time value) hasn't changed -- confirms 'current', not
        'frozen at entry'."""
        position = _position(quantity=10.0, avg_cost_basis=50.0, current_price=100.0)
        account = _account(total_equity=1000.0, positions=[position])

        risk_at_current_price = position_risk_pct(position, stop=98.0, account=account)

        assert risk_at_current_price == pytest.approx(2.0)
        # If this had used avg_cost_basis (50) instead of current_price (100),
        # distance-to-stop would be negative and clamped to 0 -> risk 0%.
        assert risk_at_current_price != 0.0

    def test_distance_floored_at_zero_when_already_below_stop(self) -> None:
        position = _position(quantity=10.0, current_price=90.0)
        account = _account(total_equity=1000.0, positions=[position])

        assert position_risk_pct(position, stop=98.0, account=account) == pytest.approx(0.0)

    def test_missing_current_price_raises(self) -> None:
        position = _position(current_price=None)
        account = _account(total_equity=1000.0, positions=[position])

        with pytest.raises(ValueError, match="current_price"):
            position_risk_pct(position, stop=98.0, account=account)

    def test_zero_equity_raises(self) -> None:
        position = _position()
        account = _account(total_equity=0.0, positions=[position])

        with pytest.raises(ValueError, match="equity"):
            position_risk_pct(position, stop=98.0, account=account)


class TestTotalOpenRiskPct:
    def test_sums_across_positions(self) -> None:
        pos_a = _position(id="pos_a", ticker="AAPL", quantity=10.0, current_price=100.0)
        pos_b = _position(id="pos_b", ticker="MSFT", quantity=5.0, current_price=200.0)
        account = _account(total_equity=1000.0, positions=[pos_a, pos_b])
        stops = {"pos_a": 98.0, "pos_b": 190.0}

        # pos_a: 10 * (100-98) = 20 -> 2.0%
        # pos_b: 5 * (200-190) = 50 -> 5.0%
        assert total_open_risk_pct(account, stops) == pytest.approx(7.0)

    def test_breaches_six_percent_rule(self) -> None:
        """A portfolio whose combined open risk clears the 6% threshold."""
        pos_a = _position(id="pos_a", ticker="AAPL", quantity=20.0, current_price=100.0)
        pos_b = _position(id="pos_b", ticker="MSFT", quantity=10.0, current_price=200.0)
        pos_c = _position(id="pos_c", ticker="GOOG", quantity=15.0, current_price=150.0)
        account = _account(total_equity=1000.0, positions=[pos_a, pos_b, pos_c])
        stops = {"pos_a": 95.0, "pos_b": 195.0, "pos_c": 145.0}

        # pos_a: 20*5=100 -> 10%; pos_b: 10*5=50 -> 5%; pos_c: 15*5=75 -> 7.5%
        total = total_open_risk_pct(account, stops)

        assert total == pytest.approx(22.5)
        assert total > 6.0

    def test_position_missing_from_stops_is_skipped(self) -> None:
        pos_a = _position(id="pos_a", current_price=100.0)
        pos_b = _position(id="pos_b", current_price=200.0)
        account = _account(total_equity=1000.0, positions=[pos_a, pos_b])

        # Only pos_a has a known stop; pos_b (e.g. protective_stop() couldn't
        # be computed for it yet) must not raise and must not be counted.
        total = total_open_risk_pct(account, {"pos_a": 98.0})

        assert total == pytest.approx(2.0)

    def test_no_positions_is_zero(self) -> None:
        account = _account(total_equity=1000.0, positions=[])

        assert total_open_risk_pct(account, {}) == pytest.approx(0.0)

    def test_keyed_by_id_not_ticker(self) -> None:
        """Two lots of the same ticker must be risk-assessed independently
        via their distinct ids, not collapsed/overwritten by ticker."""
        lot_1 = _position(id="lot_1", ticker="AAPL", quantity=10.0, current_price=100.0)
        lot_2 = _position(id="lot_2", ticker="AAPL", quantity=5.0, current_price=100.0)
        account = _account(total_equity=1000.0, positions=[lot_1, lot_2])
        stops = {"lot_1": 98.0, "lot_2": 90.0}

        # lot_1: 10*2=20 -> 2.0%; lot_2: 5*10=50 -> 5.0%
        assert total_open_risk_pct(account, stops) == pytest.approx(7.0)
