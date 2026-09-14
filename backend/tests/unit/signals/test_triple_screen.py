"""Tests for app.signals.triple_screen.evaluate_tide (docs/Analyse.md §2, Screen 1 -- the Tide).

Two layers of coverage, matching docs/architecture/Backend.md's "Signal engine
tests cover each Screen 1/2/3 + Impulse combination explicitly" guidance:

1. ``TestMacdHistogramSlope`` / ``TestEvaluateTideCombinationLogic`` isolate
   the *combination logic* itself (the flat-threshold cutoff, and the
   BULLISH/BEARISH/NEUTRAL decision table) from the real indicator math --
   which is already covered by hand-computed reference tests in
   test_ema.py/test_macd.py -- by mocking ``macd_components``/``ema``/the
   slope helper with controlled outputs.
2. ``TestEvaluateTideEndToEnd`` exercises the real, unmocked composition
   (``evaluate_tide`` -> ``macd_components`` -> ``ema``) over small synthetic
   weekly OHLCV series, confirming the wiring itself (not just the decision
   table in isolation) produces each of the three outputs. Series/rates were
   chosen empirically (see comments) to clear or stay under the 0.1% flat
   threshold defined in app.signals.triple_screen; each test asserts the
   qualifying facts it relies on (slope sign, EMA relationship), not just
   the final classification, so a future threshold change that breaks the
   scenario fails loudly here rather than silently.

See the `decisions` entry on docs/tasks/screen1-tide.json for the rationale
behind the two-point slope + 0.1%-of-price flat threshold, the TideResult
shape, and reusing app.indicators.macd.macd_components to avoid computing
EMA(26) twice.
"""

import pandas as pd
import pytest

from app.indicators.macd import MacdComponents
from app.signals.triple_screen import TideResult, evaluate_tide, macd_histogram_slope


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
    """Isolates the flat-threshold cutoff (0.1% of latest close) by feeding
    a controlled histogram Series directly (no need to mock macd_components
    for this -- macd_histogram_slope takes the histogram as a plain argument).
    """

    def test_step_above_threshold_is_rising(self) -> None:
        histogram = pd.Series([1.0, 1.1001])  # step/close = 0.1001/100 = 0.001001 > 0.001

        assert macd_histogram_slope(histogram, latest_close=100.0) == "rising"

    def test_step_at_threshold_boundary_is_flat_not_rising(self) -> None:
        """The comparison is strict (>), so a step of exactly 0.1% of price does not count
        as decisively rising -- only a step that clears the threshold does. Values are chosen
        to be exactly representable in binary floating point (1.0, 2.0, 1000.0), so the
        step/close ratio lands on the 0.001 boundary exactly rather than drifting a few ULPs
        above it the way e.g. 1.10 - 1.0 would (0.10/100 == 0.001 but (1.10-1.0)/100 !=
        0.001 exactly, due to decimal-to-binary rounding of 1.10).
        """
        histogram = pd.Series([1.0, 2.0])  # step/close = 1.0/1000.0 == 0.001 exactly

        assert macd_histogram_slope(histogram, latest_close=1000.0) == "flat"

    def test_step_just_below_threshold_is_flat(self) -> None:
        histogram = pd.Series([1.0, 1.0999])  # step/close = 0.0999/100 = 0.000999 < 0.001

        assert macd_histogram_slope(histogram, latest_close=100.0) == "flat"

    def test_step_below_negative_threshold_is_falling(self) -> None:
        histogram = pd.Series([1.0, 0.8999])  # step/close = -0.1001/100 = -0.001001

        assert macd_histogram_slope(histogram, latest_close=100.0) == "falling"

    def test_step_at_negative_threshold_boundary_is_flat_not_falling(self) -> None:
        """Mirrors test_step_at_threshold_boundary_is_flat_not_rising's binary-exact values,
        on the negative side.
        """
        histogram = pd.Series([2.0, 1.0])  # step/close = -1.0/1000.0 == -0.001 exactly

        assert macd_histogram_slope(histogram, latest_close=1000.0) == "flat"

    def test_zero_close_falls_back_to_absolute_comparison(self) -> None:
        """A zero close price never happens with real market data, but must not raise
        ZeroDivisionError -- falls back to comparing the raw (unnormalized) step.
        """
        histogram = pd.Series([1.0, 1.5])

        assert macd_histogram_slope(histogram, latest_close=0.0) == "rising"

    def test_zero_close_zero_step_is_flat(self) -> None:
        histogram = pd.Series([1.0, 1.0])

        assert macd_histogram_slope(histogram, latest_close=0.0) == "flat"


def _mock_macd_components(mocker, *, histogram: pd.Series, ema_slow: float) -> None:
    """Patch app.signals.triple_screen.macd_components to return a controlled
    histogram + ema_slow, leaving the rest of MacdComponents unused (evaluate_tide
    only reads .histogram and .ema_slow).
    """
    fake = MacdComponents(
        ema_fast=pd.Series([float("nan")]),
        ema_slow=pd.Series([ema_slow]),
        macd_line=pd.Series([float("nan")]),
        signal_line=pd.Series([float("nan")]),
        histogram=histogram,
    )
    mocker.patch("app.signals.triple_screen.macd_components", return_value=fake)


class TestEvaluateTideCombinationLogic:
    """Isolates the BULLISH/BEARISH/NEUTRAL decision table from real indicator math by
    mocking the slope helper, macd_components, and ema() directly -- covers every slope x
    EMA-relationship combination, not just the two "everything agrees" happy paths.
    """

    def _mock_ema_13(self, mocker, *, ema_13: float) -> None:
        mocker.patch(
            "app.signals.triple_screen.ema",
            return_value=pd.Series([ema_13]),
        )

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
        _mock_macd_components(mocker, histogram=pd.Series([0.0, 0.0]), ema_slow=ema_26)
        mocker.patch("app.signals.triple_screen.macd_histogram_slope", return_value=slope)
        self._mock_ema_13(mocker, ema_13=ema_13)
        weekly_ohlcv = _weekly_ohlcv(pd.Series([100.0, 101.0]))

        result = evaluate_tide(weekly_ohlcv)

        assert result == TideResult(trend=expected, weekly_macd_histogram_slope=slope)

    def test_empty_frame_is_neutral_flat_without_calling_indicators(self, mocker) -> None:
        components_mock = mocker.patch("app.signals.triple_screen.macd_components")
        ema_mock = mocker.patch("app.signals.triple_screen.ema")
        weekly_ohlcv = _weekly_ohlcv(pd.Series([], dtype=float))

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="NEUTRAL", weekly_macd_histogram_slope="flat"
        )
        components_mock.assert_not_called()
        ema_mock.assert_not_called()

    def test_single_row_frame_is_neutral_flat_without_calling_indicators(self, mocker) -> None:
        components_mock = mocker.patch("app.signals.triple_screen.macd_components")
        ema_mock = mocker.patch("app.signals.triple_screen.ema")
        weekly_ohlcv = _weekly_ohlcv(pd.Series([100.0]))

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="NEUTRAL", weekly_macd_histogram_slope="flat"
        )
        components_mock.assert_not_called()
        ema_mock.assert_not_called()


class TestEvaluateTideEndToEnd:
    """Real (unmocked) composition of evaluate_tide -> macd_components -> ema, over small
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

        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_components as real_macd_components

        histogram = real_macd_components(closes).histogram
        assert macd_histogram_slope(histogram, closes.iloc[-1]) == "rising"
        assert real_ema(closes, 13).iloc[-1] > real_ema(closes, 26).iloc[-1]

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="BULLISH", weekly_macd_histogram_slope="rising"
        )

    def test_bearish_on_accelerating_downtrend(self) -> None:
        """40 weeks of 10%/week compounding decline (1000 * 0.9**i): mirrors the bullish
        case -- histogram's last step clears the flat threshold on the falling side, and
        EMA(13) stays below EMA(26) throughout the decline.
        """
        closes = pd.Series([1000 * (0.9**i) for i in range(40)], dtype=float)
        weekly_ohlcv = _weekly_ohlcv(closes)

        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_components as real_macd_components

        histogram = real_macd_components(closes).histogram
        assert macd_histogram_slope(histogram, closes.iloc[-1]) == "falling"
        assert real_ema(closes, 13).iloc[-1] < real_ema(closes, 26).iloc[-1]

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="BEARISH", weekly_macd_histogram_slope="falling"
        )

    def test_neutral_on_flat_price(self) -> None:
        """A perfectly constant weekly close is already at MACD-Histogram steady state
        (identically 0 at every point per app.indicators.macd's first-value-seed
        convention), so the slope is exactly flat regardless of the EMA relationship.
        """
        closes = pd.Series([50.0] * 10)
        weekly_ohlcv = _weekly_ohlcv(closes)

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="NEUTRAL", weekly_macd_histogram_slope="flat"
        )

    def test_neutral_on_empty_history(self) -> None:
        weekly_ohlcv = _weekly_ohlcv(pd.Series([], dtype=float))

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="NEUTRAL", weekly_macd_histogram_slope="flat"
        )

    def test_neutral_on_single_week_history(self) -> None:
        weekly_ohlcv = _weekly_ohlcv(pd.Series([100.0]))

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="NEUTRAL", weekly_macd_histogram_slope="flat"
        )

    def test_neutral_slope_rising_but_ema_disagrees(self) -> None:
        """Exercises the "mixed" case from real (unmocked) indicator math: a genuine
        rising histogram slope, but the 13/26-week EMA relationship hasn't caught up
        yet (or disagrees), so evaluate_tide must still return NEUTRAL overall while
        weekly_macd_histogram_slope still reports the real 'rising' classification --
        the piece of information a downstream confidence scorer needs to tell this
        "mixed" NEUTRAL apart from a flat/genuinely-ambiguous one (see this task's
        `decisions` entry).
        """
        # A sharp rally in just the last two weeks after a long decline: the
        # histogram's last step is clearly rising, but 26 weeks of prior decline
        # means EMA(13) is still below EMA(26).
        declining = [200 * (0.95**i) for i in range(30)]
        closes = pd.Series(declining + [declining[-1] * 1.5, declining[-1] * 2.5])
        weekly_ohlcv = _weekly_ohlcv(closes)

        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_components as real_macd_components

        histogram = real_macd_components(closes).histogram
        slope = macd_histogram_slope(histogram, closes.iloc[-1])
        assert slope == "rising"
        assert real_ema(closes, 13).iloc[-1] < real_ema(closes, 26).iloc[-1]

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="NEUTRAL", weekly_macd_histogram_slope="rising"
        )
