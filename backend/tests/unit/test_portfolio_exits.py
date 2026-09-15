"""Tests for app.portfolio.exits.evaluate_exit_flags (docs/Analyse.md §7, Existing-position
exit signals).

Two layers, mirroring tests/unit/signals/test_engine.py's own split between an isolated
decision-table pass and a real end-to-end pass:

1. ``TestEvaluateExitFlags*`` isolates each flag by mocking ``protective_stop``,
   ``position_risk_pct``, ``autoenvelope``, ``evaluate_impulse`` and ``evaluate_tide`` (all
   imported into and called from ``app.portfolio.exits``) -- covers each flag firing and not
   firing independently, plus a combination case, without needing hand-crafted OHLCV series
   for every scenario.
2. ``TestEvaluateExitFlagsEndToEnd`` uses real (unmocked) data to confirm the actual wiring,
   including the `stop_hit` "stop computed from data *before* today, tested against today's
   close" contract recorded in this task's `decisions` array -- a today-inclusive stop can
   never be breached by construction (swing_low <= today's low <= today's close always), so
   this is the one thing worth verifying end to end rather than only via a mocked return value.
"""

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from app.portfolio.exits import evaluate_exit_flags
from app.portfolio.models import Account, Equity, Position
from app.signals.triple_screen import TideResult


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


def _account(total_equity: float = 1000.0, positions: list[Position] | None = None) -> Account:
    return Account(
        equity=Equity(cash=total_equity, positions_value=0.0, total=total_equity),
        positions=positions or [],
    )


def _daily_ohlcv(closes: list[float], lows: list[float] | None = None) -> pd.DataFrame:
    lows = lows if lows is not None else [c - 1.0 for c in closes]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": lows,
            "close": closes,
            "volume": [1_000_000] * len(closes),
        }
    )


def _weekly_ohlcv(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        }
    )


def _patched(
    *,
    stop: float = 0.0,
    risk_pct: float = 0.0,
    upper: float = float("nan"),
    impulse: str = "BLUE",
    tide_by_len: dict[int, str],
):
    """Patches every collaborator evaluate_exit_flags calls, isolating its own flag logic.

    ``tide_by_len`` maps a weekly_ohlcv slice length to the TideResult.trend
    ``evaluate_tide`` should return for that slice -- evaluate_exit_flags calls it twice (the
    full weekly_ohlcv, then weekly_ohlcv[:-1]), exactly like
    tests/unit/signals/test_engine.py's TestWaveShowedState mocks distinguish slices by len().
    """

    def tide_side_effect(weekly_ohlcv: pd.DataFrame, **_shared_series_kwargs) -> TideResult:
        # evaluate_exit_flags now passes the shared histogram/ema_13/ema_26 series it
        # precomputed once (see the portfolio-exit-rules-followups task's `decisions`
        # entry) -- irrelevant to this isolated-flag test, which only cares about which
        # weekly_ohlcv slice was passed, so they're accepted and ignored here.
        trend = tide_by_len[len(weekly_ohlcv)]
        return TideResult(trend=trend, weekly_macd_histogram_slope="flat")

    return (
        patch("app.portfolio.exits.protective_stop", return_value=stop),
        patch("app.portfolio.exits.position_risk_pct", return_value=risk_pct),
        patch("app.portfolio.exits.autoenvelope", return_value=pd.DataFrame({"upper": [upper]})),
        patch("app.portfolio.exits.evaluate_impulse", return_value=impulse),
        patch("app.portfolio.exits.evaluate_tide", side_effect=tide_side_effect),
    )


class TestStopHitFlag:
    def test_flags_when_close_below_stop(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])  # latest close = 100.0
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=105.0, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == ["stop_hit"]

    def test_no_flag_when_close_at_or_above_stop(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=100.0, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert "stop_hit" not in flags

    def test_stop_computed_excluding_todays_bar(self) -> None:
        """protective_stop must be called with daily_ohlcv[:-1] (today excluded), not the
        full frame -- see this task's `decisions` entry.
        """
        daily = _daily_ohlcv([100.0, 100.0, 90.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=95.0, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0] as mock_stop, patches[1], patches[2], patches[3], patches[4]:
            evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        called_with = mock_stop.call_args.args[1]
        assert len(called_with) == 2
        assert list(called_with["close"]) == [100.0, 100.0]


class TestTwoPercentRuleFlag:
    def test_flags_when_risk_exceeds_threshold(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=50.0, risk_pct=2.5, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == ["two_percent_rule_breached"]

    def test_no_flag_at_exactly_two_percent(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=50.0, risk_pct=2.0, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == []


class TestSixPercentRuleContributorFlag:
    def test_flags_when_portfolio_breached_and_position_has_risk(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=50.0, risk_pct=1.0, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 7.0)
        assert flags == ["six_percent_rule_contributor"]

    def test_no_flag_when_portfolio_not_breached(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=50.0, risk_pct=1.0, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 6.0)
        assert flags == []

    def test_no_flag_when_position_has_zero_own_risk_even_if_portfolio_breached(self) -> None:
        """A position whose own risk is already 0 (e.g. it already hit its stop) doesn't
        count as a contributor to the 6% breach -- see this task's `decisions` entry.
        """
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(stop=50.0, risk_pct=0.0, tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 9.0)
        assert flags == []


class TestProfitZoneImpulseRedFlag:
    def test_flags_when_at_upper_band_and_impulse_red(self) -> None:
        daily = _daily_ohlcv([125.0, 125.0])  # latest close = 125.0
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(
            stop=50.0, upper=120.0, impulse="RED", tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"}
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == ["profit_zone_impulse_red"]

    def test_flags_when_exactly_at_upper_band(self) -> None:
        daily = _daily_ohlcv([120.0, 120.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(
            stop=50.0, upper=120.0, impulse="RED", tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"}
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == ["profit_zone_impulse_red"]

    def test_no_flag_when_below_upper_band(self) -> None:
        daily = _daily_ohlcv([119.0, 119.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(
            stop=50.0, upper=120.0, impulse="RED", tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"}
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == []

    def test_no_flag_when_impulse_not_red(self) -> None:
        daily = _daily_ohlcv([125.0, 125.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(
            stop=50.0, upper=120.0, impulse="GREEN", tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"}
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == []

    def test_no_flag_when_upper_band_is_nan(self) -> None:
        """Insufficient history for autoenvelope's rolling deviation window (NaN upper) must
        not raise and must not flag."""
        daily = _daily_ohlcv([125.0, 125.0])
        weekly = _weekly_ohlcv([100.0, 100.0])
        patches = _patched(
            stop=50.0, upper=float("nan"), impulse="RED", tide_by_len={2: "NEUTRAL", 1: "NEUTRAL"}
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == []


class TestTideFlippedBearishFlag:
    def test_flags_when_tide_flips_bullish_to_bearish(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0, 100.0])  # len 3, sliced len 2
        patches = _patched(stop=50.0, tide_by_len={3: "BEARISH", 2: "BULLISH"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == ["tide_flipped_bearish"]

    def test_no_flag_when_tide_stays_bearish(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0, 100.0])
        patches = _patched(stop=50.0, tide_by_len={3: "BEARISH", 2: "BEARISH"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == []

    def test_no_flag_when_tide_flips_bullish_to_neutral(self) -> None:
        """Only a flip specifically *to BEARISH* counts -- a lapse to NEUTRAL isn't the same
        condition docs/Analyse.md §7 names."""
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0, 100.0])
        patches = _patched(stop=50.0, tide_by_len={3: "NEUTRAL", 2: "BULLISH"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == []

    def test_no_flag_on_short_weekly_history(self) -> None:
        """Fewer than 2 weekly bars degrades to NEUTRAL both times (evaluate_tide's own
        <2-row guard), never raising and never flagging."""
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0])
        patches = _patched(stop=50.0, tide_by_len={1: "NEUTRAL", 0: "NEUTRAL"})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 0.0)
        assert flags == []


class TestCombinationOfFlags:
    def test_multiple_flags_fire_together(self) -> None:
        daily = _daily_ohlcv([125.0, 125.0])  # latest close = 125.0
        weekly = _weekly_ohlcv([100.0, 100.0, 100.0])
        patches = _patched(
            stop=130.0,  # close (125) < stop -> stop_hit
            risk_pct=3.0,  # > 2% -> two_percent_rule_breached; also > 0 -> six_percent contributor
            upper=120.0,
            impulse="RED",  # close (125) >= upper and RED -> profit_zone_impulse_red
            tide_by_len={3: "BEARISH", 2: "BULLISH"},  # flips -> tide_flipped_bearish
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 8.0)
        assert flags == [
            "stop_hit",
            "two_percent_rule_breached",
            "six_percent_rule_contributor",
            "profit_zone_impulse_red",
            "tide_flipped_bearish",
        ]

    def test_no_flags_at_all_in_a_quiet_state(self) -> None:
        daily = _daily_ohlcv([100.0, 100.0])
        weekly = _weekly_ohlcv([100.0, 100.0, 100.0])
        patches = _patched(
            stop=50.0, risk_pct=0.5, upper=200.0, impulse="GREEN",
            tide_by_len={3: "BULLISH", 2: "BULLISH"},
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            flags = evaluate_exit_flags(_position(), _account(), daily, weekly, 1.0)
        assert flags == []

    def test_hold_signal_is_irrelevant_the_function_takes_no_signal_input(self) -> None:
        """Confirms the verify-elder-signal checklist item: exit flags are computed with no
        knowledge of the fresh-entry signal at all, so nothing from signal-engine-orchestration
        can suppress them -- evaluate_exit_flags's signature doesn't even accept a signal."""
        import inspect

        params = inspect.signature(evaluate_exit_flags).parameters
        assert "signal" not in params


class TestEvaluateExitFlagsEndToEnd:
    """Real (unmocked) computation, confirming the actual wiring -- in particular that
    'stop_hit' really is reachable in practice now that the stop excludes today's own bar (see
    this task's `decisions` entry -- a today-inclusive stop is mathematically unreachable).
    """

    def test_real_stop_hit(self) -> None:
        # 10 quiet days (close/low steady around 100), then a sharp gap-down close today
        # that closes below yesterday's (already-established) protective stop. Once
        # current_price has fallen below the stop, position_risk_pct floors distance-to-stop
        # at 0 (risk.py's own documented behavior), so this scenario deliberately doesn't
        # also assert two_percent_rule_breached -- that's covered by its own real scenario
        # below, where current_price stays above the stop.
        closes = [100.0] * 10
        lows = [99.0] * 10
        daily = _daily_ohlcv(closes, lows)
        gap_down_row = pd.DataFrame(
            {"open": [80.0], "high": [81.0], "low": [78.0], "close": [80.0], "volume": [1_000_000]}
        )
        daily = pd.concat([daily, gap_down_row], ignore_index=True)

        weekly = _weekly_ohlcv([100.0] * 5)  # flat -> NEUTRAL tide, no flip

        position = _position(quantity=1.0, current_price=80.0)
        account = _account(total_equity=1000.0, positions=[position])

        flags = evaluate_exit_flags(position, account, daily, weekly, portfolio_open_risk_pct=0.0)

        assert "stop_hit" in flags

    def test_real_two_percent_rule_breach_without_stop_hit(self) -> None:
        # Same quiet 10-day history establishing a stop close to 90 (swing_low=99 minus a
        # small volatility buffer), but today's close stays comfortably above that stop --
        # no stop_hit -- while the position itself is grossly oversized relative to equity,
        # breaching the 2% rule on its own.
        closes = [100.0] * 10
        lows = [99.0] * 10
        daily = _daily_ohlcv(closes, lows)
        steady_row = pd.DataFrame(
            {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.0], "volume": [1_000_000]}
        )
        daily = pd.concat([daily, steady_row], ignore_index=True)

        weekly = _weekly_ohlcv([100.0] * 5)

        position = _position(quantity=50.0, current_price=100.0)
        account = _account(total_equity=1000.0, positions=[position])

        flags = evaluate_exit_flags(position, account, daily, weekly, portfolio_open_risk_pct=0.0)

        assert "stop_hit" not in flags
        assert "two_percent_rule_breached" in flags

    def test_real_quiet_uptrend_has_no_stop_hit(self) -> None:
        closes = [100.0 + i * 0.2 for i in range(15)]
        lows = [c - 0.5 for c in closes]
        daily = _daily_ohlcv(closes, lows)
        weekly = _weekly_ohlcv([100.0] * 5)
        position = _position(quantity=1.0, current_price=closes[-1])
        account = _account(total_equity=100_000.0, positions=[position])

        flags = evaluate_exit_flags(position, account, daily, weekly, portfolio_open_risk_pct=0.0)

        assert "stop_hit" not in flags

    def test_real_missing_current_price_raises(self) -> None:
        closes = [100.0] * 10
        daily = _daily_ohlcv(closes)
        weekly = _weekly_ohlcv([100.0] * 5)
        position = _position(current_price=None)
        account = _account(positions=[position])

        with pytest.raises(ValueError, match="current_price"):
            evaluate_exit_flags(position, account, daily, weekly, portfolio_open_risk_pct=0.0)

    def test_real_too_short_daily_history_raises(self) -> None:
        daily = _daily_ohlcv([100.0])  # 1 row -> [:-1] slice is empty
        weekly = _weekly_ohlcv([100.0] * 5)
        position = _position()
        account = _account(positions=[position])

        with pytest.raises(ValueError, match="at least one row"):
            evaluate_exit_flags(position, account, daily, weekly, portfolio_open_risk_pct=0.0)


class TestSharedIndicatorComputation:
    """Regression coverage for the portfolio-exit-rules-followups task: evaluate_exit_flags
    must compute the daily EMA(13) and the weekly MACD-Histogram/EMA(13)/EMA(26) each exactly
    once and share them (via protective_stop/autoenvelope/evaluate_impulse/evaluate_tide's
    optional precomputed-series parameters) instead of each collaborator independently
    recomputing an identical pass -- see this task's `decisions` entry. Uses real (unmocked)
    collaborators wrapped in call-counting spies, not mocked return values, so a regression
    back to each function computing its own series would actually be caught here."""

    def test_daily_and_weekly_series_computed_once_and_shared(self, mocker) -> None:
        # 30+ daily/weekly bars of mild, non-degenerate growth -- enough history for every
        # collaborator (protective_stop's 10-day window, autoenvelope's rolling deviation,
        # evaluate_tide's slope) to run its real math without hitting an insufficient-data
        # short-circuit that would skip calling ema()/macd_components() at all.
        daily_closes = [100.0 + i * 0.3 for i in range(40)]
        daily_lows = [c - 1.0 for c in daily_closes]
        daily = _daily_ohlcv(daily_closes, daily_lows)
        weekly = _weekly_ohlcv([100.0 + i * 0.5 for i in range(30)])
        position = _position(current_price=daily_closes[-1])
        account = _account(total_equity=1_000_000.0, positions=[position])

        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_components as real_macd_components

        exits_ema_spy = mocker.patch("app.portfolio.exits.ema", wraps=real_ema)
        exits_macd_spy = mocker.patch("app.portfolio.exits.macd_components", wraps=real_macd_components)
        risk_ema_spy = mocker.patch("app.portfolio.risk.ema", wraps=real_ema)
        autoenvelope_ema_spy = mocker.patch("app.indicators.autoenvelope.ema", wraps=real_ema)
        impulse_ema_spy = mocker.patch("app.signals.impulse.ema", wraps=real_ema)
        tide_ema_spy = mocker.patch("app.signals.triple_screen.ema", wraps=real_ema)
        tide_macd_spy = mocker.patch(
            "app.signals.triple_screen.macd_components", wraps=real_macd_components
        )

        evaluate_exit_flags(position, account, daily, weekly, portfolio_open_risk_pct=0.0)

        # exits.py itself calls the shared `ema` function exactly twice total -- once for
        # the daily EMA(13) (shared, via the sliced/unsliced series passed to
        # short_ema=/mid=/ema_13=, with protective_stop/autoenvelope/evaluate_impulse) and
        # once for the weekly EMA(13) (shared, via ema_13=, with both evaluate_tide calls)
        # -- rather than each collaborator calling ema() itself.
        assert exits_ema_spy.call_count == 2
        assert risk_ema_spy.call_count == 0
        assert autoenvelope_ema_spy.call_count == 0
        assert impulse_ema_spy.call_count == 0

        # The weekly MACD-Histogram/EMA(26) and EMA(13) are likewise each computed exactly
        # once in exits.py and shared across both evaluate_tide calls (current bar, then
        # the prior-bar slice).
        assert exits_macd_spy.call_count == 1
        assert tide_macd_spy.call_count == 0
        assert tide_ema_spy.call_count == 0
