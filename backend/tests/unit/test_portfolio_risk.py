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
    ratchet_trailing_profit_stop,
    realized_losses_pct,
    total_open_risk_pct,
    trailing_profit_stop,
    trailing_stop_floor_before_merge,
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
        protective_stop = 99 - (_SAFEZONE_COEFFICIENT=2.0 * 0.534694) = 99 - 1.069388 = 97.930612
        """
        daily_ohlcv = pd.DataFrame(
            {
                "close": [100.0, 102.0, 101.0, 103.0, 104.0],
                "low": [99.0, 100.0, 99.0, 101.0, 102.0],
            }
        )

        stop = protective_stop(_position(), daily_ohlcv)

        assert stop == pytest.approx(97.930612, abs=1e-5)

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
          - protective_stop = 95 - (_SAFEZONE_COEFFICIENT=2.0 * 5) = 85

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

        assert stop_recent_only == pytest.approx(85.0)
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

    def test_columns_validated_true_skips_column_check(self) -> None:
        """Isolates `columns_validated`'s own contract directly (not just as exercised
        indirectly by evaluate_exit_flags's end-to-end tests, which always hand it an
        already-column-valid frame -- see the portfolio-exit-rules-followups-followups
        task's `decisions` entry): with `columns_validated=True`, a non-empty frame
        missing the 'low' column is *not* caught by protective_stop's own
        `{'low', 'close'} - set(columns)` check -- it's trusted instead, and fails later
        with a bare KeyError from the first `daily_ohlcv["low"]` access, not the
        'missing required column(s)' ValueError that `columns_validated=False` (the
        default) raises for the identical frame."""
        daily_ohlcv = pd.DataFrame({"close": [100.0, 102.0, 101.0, 103.0, 104.0]})

        with pytest.raises(KeyError):
            protective_stop(_position(), daily_ohlcv, columns_validated=True)

        # Confirms the KeyError is specifically due to the skipped column check --
        # the same frame with columns_validated=False (default) raises the
        # column-membership ValueError instead, never reaching the KeyError.
        with pytest.raises(ValueError, match="missing required column"):
            protective_stop(_position(), daily_ohlcv)

    def test_columns_validated_true_still_checks_empty(self) -> None:
        """`columns_validated=True` skips only the column-membership check, not the
        `.empty` check -- an empty frame still raises the same ValueError as the
        default path, since slicing (protective_stop's real-world callers pass a
        row-sliced view) can turn a validated frame empty even though it can't change
        which columns exist."""
        with pytest.raises(ValueError, match="at least one row"):
            protective_stop(
                _position(), pd.DataFrame(columns=["close", "low"]), columns_validated=True
            )

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

    def test_safezone_coefficient_is_applied_not_raw_buffer(self) -> None:
        """Regression test for the SafeZone coefficient fix (backend-safezone-stop-
        coefficient-fix task): the book's own formula (Elder ch. 54) multiplies the raw
        average downside penetration by a coefficient (>= 2) before subtracting it from
        the swing low -- `swing_low - raw_buffer` (no multiplier) was the pre-fix bug.
        Confirms the actual distance from swing_low is exactly
        `_SAFEZONE_COEFFICIENT * raw_buffer`, not the raw, unmultiplied buffer itself."""
        daily_ohlcv = pd.DataFrame(
            {
                "close": [100.0, 102.0, 101.0, 103.0, 104.0],
                "low": [99.0, 100.0, 99.0, 101.0, 102.0],
            }
        )
        # Hand-computed raw (unmultiplied) buffer from test_reference_values_short_series
        # above: mean(1.0, 0.285714, 1.387755, 0.0, 0.0) = 0.534694.
        raw_buffer = 0.534694

        stop = protective_stop(_position(), daily_ohlcv)
        swing_low = float(daily_ohlcv["low"].min())
        distance_from_swing_low = swing_low - stop

        assert distance_from_swing_low == pytest.approx(2.0 * raw_buffer, abs=1e-5)
        assert distance_from_swing_low != pytest.approx(raw_buffer, abs=1e-5)


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


class TestRealizedLossesPct:
    """The other half of the book's actual 6% Rule formula (docs/Analyse.md §7, per
    docs/ideas.md's ch. 51 cross-check) -- see the backend-trade-history-table task's
    `decisions` entry for why this is a sibling function to total_open_risk_pct rather than a
    single combined function."""

    def test_expresses_dollar_loss_as_percentage_of_equity(self) -> None:
        account = _account(total_equity=10_000.0, positions=[])

        assert realized_losses_pct(account, 600.0) == pytest.approx(6.0)

    def test_zero_realized_losses_is_zero_percent(self) -> None:
        account = _account(total_equity=10_000.0, positions=[])

        assert realized_losses_pct(account, 0.0) == pytest.approx(0.0)

    def test_zero_equity_raises(self) -> None:
        account = _account(total_equity=0.0, positions=[])

        with pytest.raises(ValueError, match="equity"):
            realized_losses_pct(account, 100.0)

    def test_negative_equity_raises(self) -> None:
        account = _account(total_equity=-500.0, positions=[])

        with pytest.raises(ValueError, match="equity"):
            realized_losses_pct(account, 100.0)


def _daily_frame_since(entry: date, closes: list[float]) -> pd.DataFrame:
    """A minimal `close`-only daily frame, indexed by a real `pd.DatetimeIndex` starting at
    `entry` (matching every genuine `DataProvider` frame's index shape -- see
    `ratchet_trailing_profit_stop`'s own docstring for why this matters)."""
    return pd.DataFrame(
        {"close": closes},
        index=pd.date_range(entry, periods=len(closes), freq="D", name="date"),
    )


class TestTrailingProfitStop:
    """Elder ch. 54 "Don't Let a Winning Trade Turn into a Loss" -- single point-in-time
    building block (see TestRatchetTrailingProfitStop below for the actual hard-ratchet
    wrapper wired into GET /api/portfolio/risk). entry_price=100, breakeven trigger=10% (so
    threshold_profit=10), profit-protection fraction=1/3 of profit BEYOND that threshold --
    see this task's (backend-trailing-profit-stop) `decisions` entry for both numbers."""

    def test_profit_below_threshold_returns_safezone_stop_unchanged(self) -> None:
        # profit=5 (5%), below the 10% trigger -- must pass safezone_stop straight through,
        # even though it's *below* entry_price (a real stop-loss, matching a plain SafeZone
        # stop's usual position under an unprofitable-so-far trade).
        assert trailing_profit_stop(
            entry_price=100.0, current_price=105.0, safezone_stop=90.0
        ) == pytest.approx(90.0)

    def test_profit_exactly_at_threshold_moves_to_breakeven(self) -> None:
        # profit=10 (exactly 10%) -> profit_beyond_threshold=0 -> entry_price + 0 == entry_price
        # exactly ("cuffing the trade" to breakeven, per the book's own language).
        assert trailing_profit_stop(
            entry_price=100.0, current_price=110.0, safezone_stop=90.0
        ) == pytest.approx(100.0)

    def test_profit_growing_further_ratchets_up(self) -> None:
        # profit=30 (30%) -> threshold_profit=10 -> profit_beyond_threshold=20 ->
        # 100 + (1/3 * 20) = 106.666...
        result = trailing_profit_stop(entry_price=100.0, current_price=130.0, safezone_stop=90.0)

        assert result == pytest.approx(106.666667, abs=1e-5)
        assert result > 100.0  # strictly past breakeven now, not just at it

    def test_safezone_stop_not_reconsidered_once_triggered(self) -> None:
        """A `safezone_stop` far ABOVE the profit-protection candidate must not leak into the
        post-trigger result -- see `trailing_profit_stop`'s own docstring for why (a live,
        non-monotonic safezone_stop could otherwise reopen the "could decrease later" gap
        `ratchet_trailing_profit_stop` exists to close)."""
        result = trailing_profit_stop(
            entry_price=100.0, current_price=130.0, safezone_stop=999.0
        )

        assert result == pytest.approx(106.666667, abs=1e-5)

    def test_non_positive_entry_price_raises(self) -> None:
        with pytest.raises(ValueError, match="entry_price"):
            trailing_profit_stop(entry_price=0.0, current_price=10.0, safezone_stop=5.0)


class TestRatchetTrailingProfitStop:
    """The actual hard-ratchet wrapper wired into GET /api/portfolio/risk
    (`RiskPosition.trailing_stop`) -- a stateless recomputation over a position's full price
    history since entry, floored by an optional caller-supplied `persisted_high_water_mark`
    (see the function's own docstring for why the floor is needed: a same-ticker merge
    raising `avg_cost_basis` can otherwise make the stateless recompute alone regress)."""

    def test_never_triggered_matches_safezone_stop(self) -> None:
        position = _position(avg_cost_basis=100.0)
        # Every close stays under the 10% trigger (max close 108 -> 8% profit).
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, 102.0, 105.0, 108.0])

        assert ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0) == pytest.approx(
            90.0
        )

    def test_crossing_threshold_moves_to_breakeven(self) -> None:
        position = _position(avg_cost_basis=100.0)
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, 105.0, 110.0])

        assert ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0) == pytest.approx(
            100.0
        )

    def test_ratchets_up_as_profit_grows_further(self) -> None:
        position = _position(avg_cost_basis=100.0)
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, 110.0, 130.0])

        # Same reference value as TestTrailingProfitStop.test_profit_growing_further_ratchets_up
        # (the 130.0 day's own candidate) -- the running max across the whole history.
        assert ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0) == pytest.approx(
            106.666667, abs=1e-5
        )

    def test_never_decreases_across_a_sequence_of_calls(self) -> None:
        """The book's companion rule, "Move Your Stop Only in the Direction of Your Trade":
        a rally to +30% profit (candidate 106.666...) followed by a pullback to +12% profit
        (a lower candidate, 100 + 1/3*2 = 100.6667, if computed fresh from that day alone)
        must still report the HIGHER value reached during the rally, not the lower
        pulled-back one."""
        position = _position(avg_cost_basis=100.0)
        rally_then_pullback = _daily_frame_since(
            date(2026, 1, 1), [100.0, 110.0, 130.0, 118.0, 112.0]
        )

        result = ratchet_trailing_profit_stop(position, rally_then_pullback, safezone_stop=90.0)

        # 130.0's own candidate (106.666...) must still be the answer, not 112.0's own lower
        # fresh candidate (100 + 1/3*(12-10) = 100.6667) -- confirming this isn't just "last
        # row wins".
        fresh_candidate_for_pulled_back_day = trailing_profit_stop(
            entry_price=100.0, current_price=112.0, safezone_stop=90.0
        )
        assert fresh_candidate_for_pulled_back_day == pytest.approx(100.666667, abs=1e-5)
        assert result == pytest.approx(106.666667, abs=1e-5)
        assert result > fresh_candidate_for_pulled_back_day

    def test_extending_history_with_more_calls_never_lowers_the_result(self) -> None:
        """Simulates successive real GET /api/portfolio/risk calls as time passes -- each
        later call's `daily_ohlcv` is a strict superset (one more day appended) of the
        previous call's. The result across that growing sequence must never decrease, even
        though the newly-appended days themselves pull back from the rally's peak and even
        though `safezone_stop` (recomputed fresh "each call" here) genuinely drops too."""
        position = _position(avg_cost_basis=100.0)
        closes = [100.0, 110.0, 130.0, 118.0, 112.0, 105.0]
        safezone_stops_per_call = [90.0, 91.0, 95.0, 88.0, 80.0, 75.0]  # deliberately non-monotonic

        results = [
            ratchet_trailing_profit_stop(
                position,
                _daily_frame_since(date(2026, 1, 1), closes[: i + 1]),
                safezone_stops_per_call[i],
            )
            for i in range(len(closes))
        ]

        assert results == sorted(results)  # monotonically non-decreasing
        assert results[-1] == pytest.approx(106.666667, abs=1e-5)  # still the rally's peak

    def test_uses_position_entry_date_to_scope_history_not_the_whole_frame(self) -> None:
        """A pre-entry rally (this position wasn't held for) must not count towards the
        ratchet -- only rows on/after `position.entry_date` are considered."""
        position = _position(avg_cost_basis=100.0)
        # Rows before 2026-01-10 simulate a pre-entry rally to +50% (which this position never
        # actually captured); the position's own held history (from 2026-01-10) never crosses
        # the 10% trigger at all.
        pre_entry_rally = _daily_frame_since(date(2026, 1, 1), [100.0] * 8 + [150.0])
        held_history = _daily_frame_since(date(2026, 1, 10), [103.0, 104.0, 105.0])
        combined = pd.concat([pre_entry_rally, held_history])
        position_entered_later = Position(
            id=position.id,
            ticker=position.ticker,
            quantity=position.quantity,
            avg_cost_basis=position.avg_cost_basis,
            entry_date=date(2026, 1, 10),
            current_price=position.current_price,
        )

        result = ratchet_trailing_profit_stop(position_entered_later, combined, safezone_stop=90.0)

        assert result == pytest.approx(90.0)  # never triggered -- pre-entry rally excluded

    def test_entry_date_predating_frame_includes_the_whole_frame_via_the_filter(self) -> None:
        """`position.entry_date` earlier than every row in `daily_ohlcv` (e.g. a merged
        position whose `entry_date` moved earlier than this ticker's fetched history) leaves
        every row `>=` entry_date -- the normal filter path, not the "no row matched at all"
        fallback below."""
        position = Position(
            id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0,
            entry_date=date(2020, 1, 1), current_price=130.0,
        )
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, 110.0, 130.0])

        result = ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

        assert result == pytest.approx(106.666667, abs=1e-5)

    def test_no_row_on_or_after_entry_date_falls_back_to_whole_frame(self) -> None:
        """`position.entry_date` *later* than every row in `daily_ohlcv` (a data completeness
        gap -- history hasn't caught up to entry yet) leaves the `>=` filter matching nothing
        at all, degrading to the whole frame instead of an empty one (which would otherwise
        silently make this function report `safezone_stop` unconditionally, mimicking "never
        triggered" for a position that, per its own `current_price`, clearly has)."""
        position = Position(
            id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0,
            entry_date=date(2030, 1, 1), current_price=130.0,
        )
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, 110.0, 130.0])

        result = ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

        assert result == pytest.approx(106.666667, abs=1e-5)

    def test_non_datetime_index_falls_back_to_whole_frame_rather_than_raising(self) -> None:
        """A caller-constructed frame with a plain `RangeIndex` (not every fixture uses a real
        `pd.DatetimeIndex` -- see e.g. the `ignore_index=True` frames in
        tests/integration/test_portfolio_risk.py) must not raise a `TypeError` from comparing
        a non-datetime index against `pd.Timestamp(position.entry_date)`."""
        position = _position(avg_cost_basis=100.0)
        daily = pd.DataFrame({"close": [100.0, 110.0, 130.0]})

        result = ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

        assert result == pytest.approx(106.666667, abs=1e-5)

    def test_nan_close_is_skipped(self) -> None:
        position = _position(avg_cost_basis=100.0)
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, float("nan"), 130.0])

        result = ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

        assert result == pytest.approx(106.666667, abs=1e-5)

    def test_empty_dataframe_raises(self) -> None:
        position = _position(avg_cost_basis=100.0)

        with pytest.raises(ValueError, match="at least one row"):
            ratchet_trailing_profit_stop(position, pd.DataFrame(columns=["close"]), safezone_stop=90.0)

    def test_missing_close_column_raises(self) -> None:
        position = _position(avg_cost_basis=100.0)
        daily = pd.DataFrame({"low": [99.0]})

        with pytest.raises(ValueError, match="missing required column"):
            ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

    def test_non_positive_avg_cost_basis_raises(self) -> None:
        position = _position(avg_cost_basis=0.0)
        daily = _daily_frame_since(date(2026, 1, 1), [100.0])

        with pytest.raises(ValueError, match="entry_price"):
            ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

    def test_persisted_high_water_mark_floors_a_lower_fresh_recompute(self) -> None:
        """PR #240 review repro (backend-trailing-profit-stop): a same-ticker merge raising
        `avg_cost_basis` with no further price movement makes the FRESH stateless recompute
        alone come out lower than it used to (see `ratchet_trailing_profit_stop`'s own
        docstring) -- `persisted_high_water_mark` must floor the result at the previously
        -reported value regardless."""
        # Entered at $100, rallied to $115 (profit=15, threshold=10, profit_beyond=5) ->
        # candidate = 100 + 1/3*5 = 101.666...
        rallied_position = _position(avg_cost_basis=100.0)
        rally_daily = _daily_frame_since(date(2026, 1, 1), [100.0, 108.0, 115.0])
        previously_reported = ratchet_trailing_profit_stop(
            rallied_position, rally_daily, safezone_stop=95.0
        )
        assert previously_reported == pytest.approx(101.666667, abs=1e-5)

        # Merge in more shares at $200/share with NO further price change -> avg_cost_basis
        # rises to $150 (reviewer's exact repro numbers). Recomputed fresh (no floor), this now
        # never crosses the (higher) 10% trigger at all (current price 115 < entry 150), so the
        # stateless-alone candidate collapses back to safezone_stop.
        merged_position = _position(avg_cost_basis=150.0)
        stale_candidate = ratchet_trailing_profit_stop(
            merged_position, rally_daily, safezone_stop=95.0
        )
        assert stale_candidate == pytest.approx(95.0)  # the bug, if there were no floor

        # With the floor supplied (as app.portfolio.risk.trailing_stop_floor_before_merge's own
        # persisted floor, read back by GET /api/portfolio/risk, now supplies -- see this
        # task's round-2 `decisions` entry for why the write moved to the merge path), the
        # result must not drop below what was already reported.
        floored_result = ratchet_trailing_profit_stop(
            merged_position,
            rally_daily,
            safezone_stop=95.0,
            persisted_high_water_mark=previously_reported,
        )
        assert floored_result == pytest.approx(previously_reported)
        assert floored_result >= previously_reported

    def test_persisted_high_water_mark_does_not_suppress_a_higher_fresh_candidate(self) -> None:
        """The floor is a `max`, not an override -- a fresh candidate that's genuinely higher
        than the persisted value (e.g. the position rallied further) must still win."""
        position = _position(avg_cost_basis=100.0)
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, 110.0, 130.0])

        result = ratchet_trailing_profit_stop(
            position, daily, safezone_stop=90.0, persisted_high_water_mark=95.0
        )

        assert result == pytest.approx(106.666667, abs=1e-5)

    def test_no_persisted_high_water_mark_behaves_exactly_as_the_original_stateless_call(
        self,
    ) -> None:
        position = _position(avg_cost_basis=100.0)
        daily = _daily_frame_since(date(2026, 1, 1), [100.0, 110.0, 130.0])

        with_none = ratchet_trailing_profit_stop(
            position, daily, safezone_stop=90.0, persisted_high_water_mark=None
        )
        without_kwarg = ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

        assert with_none == pytest.approx(without_kwarg)

    def test_filters_a_malformed_interior_bar_internally_even_when_caller_did_not(self) -> None:
        """backend-trailing-profit-stop-followups: this function no longer trusts the caller to
        have already run `daily_ohlcv` through `drop_malformed_daily_bars` (the PR #240 round-3
        bug class -- a single malformed bar permanently locking in an arbitrarily wrong
        high-water-mark floor) -- it filters internally now, so even a caller that skipped that
        convention entirely gets the same safe result a filtering caller would have."""
        position = _position(avg_cost_basis=100.0)
        # A flat $100 series (never crosses the 10% trigger on its own) with one interior bar
        # corrupted to a garbage $5000 close -- if that bar reached the fold unfiltered, it
        # alone would cross the trigger and permanently lock in an absurd floor.
        daily = pd.DataFrame(
            {
                "open": [100.0] * 10,
                "high": [101.0] * 10,
                "low": [99.0] * 10,
                "close": [100.0] * 10,
            },
            index=pd.date_range(date(2026, 1, 1), periods=10, freq="D", name="date"),
        )
        daily.iloc[5, daily.columns.get_loc("open")] = float("nan")
        daily.iloc[5, daily.columns.get_loc("high")] = float("nan")
        daily.iloc[5, daily.columns.get_loc("close")] = 5000.0

        result = ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

        # Never actually crosses the trigger once the garbage bar is filtered out -- the flat
        # $100 series alone is only breakeven, never +10% profit.
        assert result == pytest.approx(90.0)

    def test_entirely_malformed_frame_falls_back_to_safezone_stop(self) -> None:
        """Every row unusable (even the latest bar's own `close` is NaN) after internal
        filtering leaves no day to inform the ratchet at all -- degrades to `safezone_stop`
        verbatim rather than raising, matching the "nothing ever qualified" fallback."""
        position = _position(avg_cost_basis=100.0)
        daily = pd.DataFrame(
            {
                "open": [float("nan")] * 3,
                "high": [float("nan")] * 3,
                "low": [float("nan")] * 3,
                "close": [float("nan")] * 3,
            },
            index=pd.date_range(date(2026, 1, 1), periods=3, freq="D", name="date"),
        )

        result = ratchet_trailing_profit_stop(position, daily, safezone_stop=90.0)

        assert result == pytest.approx(90.0)

    def test_entirely_malformed_frame_still_respects_the_persisted_floor(self) -> None:
        position = _position(avg_cost_basis=100.0)
        daily = pd.DataFrame(
            {
                "open": [float("nan")] * 3,
                "high": [float("nan")] * 3,
                "low": [float("nan")] * 3,
                "close": [float("nan")] * 3,
            },
            index=pd.date_range(date(2026, 1, 1), periods=3, freq="D", name="date"),
        )

        result = ratchet_trailing_profit_stop(
            position, daily, safezone_stop=90.0, persisted_high_water_mark=101.666667
        )

        assert result == pytest.approx(101.666667)


def _daily_ohlcv_frame_since(entry: date, closes: list[float]) -> pd.DataFrame:
    """Like `_daily_frame_since` above, but with a `low` column too (`close - 1.0` throughout)
    -- `trailing_stop_floor_before_merge` needs both (it calls `protective_stop` internally,
    unlike `ratchet_trailing_profit_stop`'s own tests above, which are handed a manual
    `safezone_stop` and so never touch `daily_ohlcv["low"]` at all)."""
    return pd.DataFrame(
        {"close": closes, "low": [c - 1.0 for c in closes]},
        index=pd.date_range(entry, periods=len(closes), freq="D", name="date"),
    )


class TestTrailingStopFloorBeforeMerge:
    """`app.portfolio.risk.trailing_stop_floor_before_merge` -- the value `POST
    /api/portfolio/positions`'s same-ticker-merge branch persists as
    `PositionORM.trailing_stop_high_water_mark`'s floor, captured against the position's OLD,
    pre-merge `avg_cost_basis`/`entry_date` before the merge overwrites them (backend-
    trailing-profit-stop round 2 -- see `ratchet_trailing_profit_stop`'s own docstring for why
    `GET /api/portfolio/risk` no longer writes this column itself)."""

    def test_none_daily_ohlcv_returns_none(self) -> None:
        """A `provider.get_daily_ohlcv` fetch failure at merge time (already caught by the
        caller and turned into `daily_ohlcv=None`) must degrade to leaving the floor
        untouched, never raise or fabricate a value from no data."""
        position = _position(avg_cost_basis=100.0)

        assert trailing_stop_floor_before_merge(position, None, persisted_high_water_mark=50.0) is None

    def test_too_short_daily_ohlcv_returns_none(self) -> None:
        """Fewer than 2 rows leaves nothing for `protective_stop`'s own `.iloc[:-1]` slice to
        compute a stop from -- degrades to `None` rather than raising."""
        position = _position(avg_cost_basis=100.0)
        daily = _daily_ohlcv_frame_since(date(2026, 1, 1), [100.0])

        assert (
            trailing_stop_floor_before_merge(position, daily, persisted_high_water_mark=None)
            is None
        )

    def test_malformed_frame_degrades_to_none_rather_than_raising(self) -> None:
        """A frame missing the `low` column `protective_stop` requires raises `ValueError`
        internally -- caught here and degraded to `None`, matching every other
        can't-be-computed case in this module (a data hiccup at merge time must never block
        the merge)."""
        position = _position(avg_cost_basis=100.0)
        daily = pd.DataFrame(
            {"close": [100.0, 110.0]},
            index=pd.date_range(date(2026, 1, 1), periods=2, freq="D", name="date"),
        )

        assert (
            trailing_stop_floor_before_merge(position, daily, persisted_high_water_mark=None)
            is None
        )

    def test_matches_directly_calling_protective_stop_then_ratchet_trailing_profit_stop(
        self,
    ) -> None:
        """The result must be identical to what a real `GET /api/portfolio/risk` call would
        have reported for this exact position/`daily_ohlcv`/persisted floor at this exact
        moment -- i.e. `protective_stop(position, daily.iloc[:-1])` feeding
        `ratchet_trailing_profit_stop(position, daily, that_stop, persisted_high_water_mark=...)`,
        with no divergence in the intermediate `safezone_stop`."""
        position = _position(avg_cost_basis=100.0)
        # Ends at close=115 -- +15% profit, comfortably past the 10% breakeven trigger.
        daily = _daily_ohlcv_frame_since(
            date(2026, 1, 1), [100.0 + 15.0 * i / 14.0 for i in range(15)]
        )

        result = trailing_stop_floor_before_merge(position, daily, persisted_high_water_mark=None)

        expected_stop = protective_stop(position, daily.iloc[:-1])
        expected = ratchet_trailing_profit_stop(position, daily, expected_stop)
        assert result == pytest.approx(expected)
        # 100 + 1/3 * (15 - 10) == 101.666...
        assert result == pytest.approx(101.666667, abs=1e-4)

    def test_never_returns_lower_than_the_persisted_high_water_mark(self) -> None:
        """A position whose OLD cost basis no longer crosses the trigger against unchanged
        price history (e.g. a second merge that raises `avg_cost_basis` further) must still
        floor at whatever was already locked in -- this is `ratchet_trailing_profit_stop`'s
        own floor contract, just exercised through this wrapper."""
        # avg_cost_basis=150 vs. a flat $90 close history never crosses the 10% trigger at
        # all -- the fresh candidate alone collapses to protective_stop (87.0: swing_low=89,
        # a constant downside penetration of 1.0 against the converged EMA(13)=90 -- 89 -
        # 2*1.0), well below the already-locked-in 101.667 floor.
        position = _position(avg_cost_basis=150.0)
        daily = _daily_ohlcv_frame_since(date(2026, 1, 1), [90.0] * 15)

        result = trailing_stop_floor_before_merge(
            position, daily, persisted_high_water_mark=101.666667
        )

        assert result == pytest.approx(101.666667, abs=1e-4)
        assert result >= 101.666667 - 1e-9

    def test_filters_a_malformed_interior_bar_internally_even_when_caller_did_not(self) -> None:
        """backend-trailing-profit-stop-followups: this function no longer trusts the caller
        to have already run `daily_ohlcv` through `drop_malformed_daily_bars` -- it filters
        internally now (see its own docstring), so a raw, unfiltered frame with one malformed
        interior bar produces the exact same result a pre-filtered one would."""
        position = _position(avg_cost_basis=100.0)
        closes = [100.0 + 15.0 * i / 14.0 for i in range(15)]
        daily = pd.DataFrame(
            {"close": closes, "low": [c - 1.0 for c in closes]},
            index=pd.date_range(date(2026, 1, 1), periods=15, freq="D", name="date"),
        )
        # Corrupt one interior bar's `low` (NaN) -- `drop_malformed_daily_bars` requires every
        # present column to be a real number on a non-latest bar, so this alone makes the row
        # unusable, exactly like a real settling-data glitch.
        daily.iloc[7, daily.columns.get_loc("low")] = float("nan")

        result = trailing_stop_floor_before_merge(position, daily, persisted_high_water_mark=None)

        filtered = daily.dropna(subset=["low", "close"])
        expected_stop = protective_stop(position, filtered.iloc[:-1])
        expected = ratchet_trailing_profit_stop(position, filtered, expected_stop)
        assert result == pytest.approx(expected)

    def test_too_short_after_internal_filtering_returns_none(self) -> None:
        """A frame with >= 2 raw rows that internal filtering then collapses to < 2 usable rows
        is exactly as uncomputable as one that never had 2 rows at all -- degrades to `None`,
        not a stale/short-lived `ValueError`. The 2 raw rows here are: an interior (non-latest)
        bar with a NaN `low` -- dropped, since only the LATEST bar's own open/high/low are
        exempt from `drop_malformed_daily_bars`'s check -- and the latest bar itself (valid
        `close`, so it alone survives), leaving exactly 1 usable row."""
        position = _position(avg_cost_basis=100.0)
        daily = pd.DataFrame(
            {"close": [100.0, 110.0], "low": [float("nan"), 109.0]},
            index=pd.date_range(date(2026, 1, 1), periods=2, freq="D", name="date"),
        )

        assert (
            trailing_stop_floor_before_merge(position, daily, persisted_high_water_mark=None)
            is None
        )
