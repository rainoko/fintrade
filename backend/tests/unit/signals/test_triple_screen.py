"""Tests for app.signals.triple_screen.evaluate_tide (docs/Analyse.md §2, Screen 1 -- the Tide).

Two layers of coverage, matching docs/architecture/Backend.md's "Signal engine
tests cover each Screen 1/2/3 + Impulse combination explicitly" guidance:

1. ``TestMacdHistogramSlope`` / ``TestEvaluateTideCombinationLogic`` isolate
   the *combination logic* itself (the flat-threshold cutoff, and the
   BULLISH/BEARISH/NEUTRAL decision table) from the real indicator math --
   which is already covered by hand-computed reference tests in
   test_ema.py/test_macd.py -- by mocking ``macd_histogram``/``ema``/the
   slope helper with controlled outputs.
2. ``TestEvaluateTideEndToEnd`` exercises the real, unmocked composition
   (``evaluate_tide`` -> ``macd_histogram`` -> ``ema``) over small synthetic
   weekly OHLCV series, confirming the wiring itself (not just the decision
   table in isolation) produces each of the three outputs. Series/rates were
   chosen empirically (see comments) to clear or stay under the 0.1% flat
   threshold defined in app.signals.triple_screen; each test asserts the
   qualifying facts it relies on (slope sign, EMA relationship), not just
   the final classification, so a future threshold change that breaks the
   scenario fails loudly here rather than silently.

See the `decisions` entry on docs/tasks/screen1-tide.json for the rationale
behind the two-point slope + 0.1%-of-price flat threshold.
"""

import pandas as pd
import pytest

from app.signals.triple_screen import _macd_histogram_slope, evaluate_tide


def _weekly_ohlcv(closes: pd.Series) -> pd.DataFrame:
    """Wrap a close-price Series into a minimal weekly OHLCV frame (open/high/low/volume
    filled with plausible placeholder values -- evaluate_tide only reads the close column).
    """
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": 1_000_000,
        }
    )


class TestMacdHistogramSlope:
    """Isolates the flat-threshold cutoff (0.1% of latest close) from real MACD math
    by mocking macd_histogram's output directly.
    """

    def test_step_above_threshold_is_rising(self, mocker) -> None:
        mocker.patch(
            "app.signals.triple_screen.macd_histogram",
            return_value=pd.Series([1.0, 1.1001]),  # step/close = 0.1001/100 = 0.001001 > 0.001
        )
        weekly_close = pd.Series([90.0, 100.0])

        assert _macd_histogram_slope(weekly_close) == "rising"

    def test_step_at_threshold_boundary_is_flat_not_rising(self, mocker) -> None:
        """The comparison is strict (>), so a step of exactly 0.1% of price does not count
        as decisively rising -- only a step that clears the threshold does. Values are chosen
        to be exactly representable in binary floating point (1.0, 2.0, 1000.0), so the
        step/close ratio lands on the 0.001 boundary exactly rather than drifting a few ULPs
        above it the way e.g. 1.10 - 1.0 would (0.10/100 == 0.001 but (1.10-1.0)/100 !=
        0.001 exactly, due to decimal-to-binary rounding of 1.10).
        """
        mocker.patch(
            "app.signals.triple_screen.macd_histogram",
            return_value=pd.Series([1.0, 2.0]),  # step/close = 1.0/1000.0 == 0.001 exactly
        )
        weekly_close = pd.Series([900.0, 1000.0])

        assert _macd_histogram_slope(weekly_close) == "flat"

    def test_step_just_below_threshold_is_flat(self, mocker) -> None:
        mocker.patch(
            "app.signals.triple_screen.macd_histogram",
            return_value=pd.Series([1.0, 1.0999]),  # step/close = 0.0999/100 = 0.000999 < 0.001
        )
        weekly_close = pd.Series([90.0, 100.0])

        assert _macd_histogram_slope(weekly_close) == "flat"

    def test_step_below_negative_threshold_is_falling(self, mocker) -> None:
        mocker.patch(
            "app.signals.triple_screen.macd_histogram",
            return_value=pd.Series([1.0, 0.8999]),  # step/close = -0.1001/100 = -0.001001
        )
        weekly_close = pd.Series([110.0, 100.0])

        assert _macd_histogram_slope(weekly_close) == "falling"

    def test_step_at_negative_threshold_boundary_is_flat_not_falling(self, mocker) -> None:
        """Mirrors test_step_at_threshold_boundary_is_flat_not_rising's binary-exact values,
        on the negative side.
        """
        mocker.patch(
            "app.signals.triple_screen.macd_histogram",
            return_value=pd.Series([2.0, 1.0]),  # step/close = -1.0/1000.0 == -0.001 exactly
        )
        weekly_close = pd.Series([1100.0, 1000.0])

        assert _macd_histogram_slope(weekly_close) == "flat"

    def test_zero_close_falls_back_to_absolute_comparison(self, mocker) -> None:
        """A zero close price never happens with real market data, but must not raise
        ZeroDivisionError -- falls back to comparing the raw (unnormalized) step.
        """
        mocker.patch(
            "app.signals.triple_screen.macd_histogram",
            return_value=pd.Series([1.0, 1.5]),
        )
        weekly_close = pd.Series([5.0, 0.0])

        assert _macd_histogram_slope(weekly_close) == "rising"

    def test_zero_close_zero_step_is_flat(self, mocker) -> None:
        mocker.patch(
            "app.signals.triple_screen.macd_histogram",
            return_value=pd.Series([1.0, 1.0]),
        )
        weekly_close = pd.Series([5.0, 0.0])

        assert _macd_histogram_slope(weekly_close) == "flat"


class TestEvaluateTideCombinationLogic:
    """Isolates the BULLISH/BEARISH/NEUTRAL decision table from real indicator math by
    mocking the slope helper and ema() directly -- covers every slope x EMA-relationship
    combination, not just the two "everything agrees" happy paths.
    """

    def _mock_ema(self, mocker, *, ema_13: float, ema_26: float) -> None:
        def fake_ema(series: pd.Series, period: int) -> pd.Series:
            value = ema_13 if period == 13 else ema_26
            return pd.Series([value])

        mocker.patch("app.signals.triple_screen.ema", side_effect=fake_ema)

    @pytest.mark.parametrize(
        ("slope", "ema_13", "ema_26", "expected"),
        [
            ("rising", 110.0, 100.0, "BULLISH"),
            ("rising", 100.0, 110.0, "NEUTRAL"),  # slope/EMA disagree
            ("rising", 100.0, 100.0, "NEUTRAL"),  # EMA relationship not strictly up
            ("falling", 100.0, 110.0, "BEARISH"),
            ("falling", 110.0, 100.0, "NEUTRAL"),  # slope/EMA disagree
            ("falling", 100.0, 100.0, "NEUTRAL"),  # EMA relationship not strictly down
            ("flat", 110.0, 100.0, "NEUTRAL"),
            ("flat", 100.0, 110.0, "NEUTRAL"),
            ("flat", 100.0, 100.0, "NEUTRAL"),
        ],
    )
    def test_decision_table(self, mocker, slope, ema_13, ema_26, expected) -> None:
        mocker.patch("app.signals.triple_screen._macd_histogram_slope", return_value=slope)
        self._mock_ema(mocker, ema_13=ema_13, ema_26=ema_26)
        weekly_ohlcv = _weekly_ohlcv(pd.Series([100.0, 101.0]))

        assert evaluate_tide(weekly_ohlcv) == expected

    def test_empty_frame_is_neutral_without_calling_indicators(self, mocker) -> None:
        slope_mock = mocker.patch("app.signals.triple_screen._macd_histogram_slope")
        ema_mock = mocker.patch("app.signals.triple_screen.ema")
        weekly_ohlcv = _weekly_ohlcv(pd.Series([], dtype=float))

        assert evaluate_tide(weekly_ohlcv) == "NEUTRAL"
        slope_mock.assert_not_called()
        ema_mock.assert_not_called()

    def test_single_row_frame_is_neutral_without_calling_indicators(self, mocker) -> None:
        slope_mock = mocker.patch("app.signals.triple_screen._macd_histogram_slope")
        ema_mock = mocker.patch("app.signals.triple_screen.ema")
        weekly_ohlcv = _weekly_ohlcv(pd.Series([100.0]))

        assert evaluate_tide(weekly_ohlcv) == "NEUTRAL"
        slope_mock.assert_not_called()
        ema_mock.assert_not_called()


class TestEvaluateTideEndToEnd:
    """Real (unmocked) composition of evaluate_tide -> macd_histogram -> ema, over small
    synthetic weekly series -- confirms the actual wiring, not just the decision table.
    """

    def test_bullish_on_accelerating_uptrend(self) -> None:
        """40 weeks of 5%/week compounding growth (100 * 1.05**i): fast EMA pulls away
        from slow EMA fast enough that the histogram's last step clears the 0.1%-of-price
        flat threshold on the rising side, while the compounding growth keeps EMA(13)
        above EMA(26) throughout.
        """
        closes = pd.Series([100 * (1.05**i) for i in range(40)], dtype=float)
        weekly_ohlcv = _weekly_ohlcv(closes)

        assert _macd_histogram_slope(closes) == "rising"
        from app.indicators.ema import ema as real_ema

        assert real_ema(closes, 13).iloc[-1] > real_ema(closes, 26).iloc[-1]
        assert evaluate_tide(weekly_ohlcv) == "BULLISH"

    def test_bearish_on_accelerating_downtrend(self) -> None:
        """40 weeks of 10%/week compounding decline (1000 * 0.9**i): mirrors the bullish
        case -- histogram's last step clears the flat threshold on the falling side, and
        EMA(13) stays below EMA(26) throughout the decline.
        """
        closes = pd.Series([1000 * (0.9**i) for i in range(40)], dtype=float)
        weekly_ohlcv = _weekly_ohlcv(closes)

        assert _macd_histogram_slope(closes) == "falling"
        from app.indicators.ema import ema as real_ema

        assert real_ema(closes, 13).iloc[-1] < real_ema(closes, 26).iloc[-1]
        assert evaluate_tide(weekly_ohlcv) == "BEARISH"

    def test_neutral_on_flat_price(self) -> None:
        """A perfectly constant weekly close is already at MACD-Histogram steady state
        (identically 0 at every point per app.indicators.macd's first-value-seed
        convention), so the slope is exactly flat regardless of the EMA relationship.
        """
        closes = pd.Series([50.0] * 10)
        weekly_ohlcv = _weekly_ohlcv(closes)

        assert evaluate_tide(weekly_ohlcv) == "NEUTRAL"

    def test_neutral_on_empty_history(self) -> None:
        weekly_ohlcv = _weekly_ohlcv(pd.Series([], dtype=float))

        assert evaluate_tide(weekly_ohlcv) == "NEUTRAL"

    def test_neutral_on_single_week_history(self) -> None:
        weekly_ohlcv = _weekly_ohlcv(pd.Series([100.0]))

        assert evaluate_tide(weekly_ohlcv) == "NEUTRAL"
