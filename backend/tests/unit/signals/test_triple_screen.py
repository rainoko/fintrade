"""Tests for app.signals.triple_screen.evaluate_tide (docs/Analyse.md §2, Screen 1 -- the Tide)
and app.signals.triple_screen.evaluate_wave (docs/Analyse.md §2, Screen 2 / Wave).

Tide coverage (matching docs/architecture/Backend.md's "Signal engine tests cover each Screen
1/2/3 + Impulse combination explicitly" guidance):

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

Wave coverage (matching the precedent set by test_impulse.py):

1. ``TestIsForceIndexSpike`` isolates the Force Index "spike" threshold (this task's own
   `decisions` entry on docs/tasks/screen2-wave.json) with hand-constructed series where the
   trailing rolling standard deviation is either clearly exceeded or clearly not.
2. ``TestEvaluateWave`` isolates the OVERSOLD_PULLBACK / OVERBOUGHT_RALLY / NO_WAVE decision
   table from real Stochastic/Force Index math by mocking ``stochastic_oscillator`` and
   ``force_index`` (letting the real, unmocked ``_is_force_index_spike`` run against the
   mocked Force Index series) -- covers every tide x oscillator-state combination, not just
   the two "everything lines up" happy paths.
3. ``TestEvaluateWaveEndToEnd`` exercises the real, unmocked composition
   (``evaluate_wave`` -> ``stochastic_oscillator``/``force_index``) over small synthetic
   daily OHLCV series, confirming the wiring itself produces both OVERSOLD_PULLBACK and
   OVERBOUGHT_RALLY.

``evaluate_trigger`` is an unimplemented stub owned by a different, not-yet-merged task
(screen3-trigger) and is intentionally not touched or tested here.
"""

import pandas as pd
import pytest

from app.signals.triple_screen import (
    STOCHASTIC_OVERBOUGHT,
    STOCHASTIC_OVERSOLD,
    _is_force_index_spike,
    _macd_histogram_slope,
    evaluate_tide,
    evaluate_wave,
)


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


def _daily_ohlcv(n: int) -> pd.DataFrame:
    """Minimal daily OHLCV frame with n rows.

    ``evaluate_wave``'s underlying stochastic_oscillator()/force_index() calls are mocked in
    ``TestEvaluateWave``, so these placeholder values only need to satisfy column access
    (["high"], ["low"], ["close"], ["volume"]) and length -- their content is irrelevant there.
    """
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1_000_000] * n,
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


class TestIsForceIndexSpike:
    def test_negative_spike_when_magnitude_exceeds_rolling_stdev(self) -> None:
        # 12 flat values then a -50 outlier -- rolling std over the trailing 13-bar window
        # is ~13.87 (pandas rolling().std(), sample/ddof=1); |-50| clears it comfortably.
        series = pd.Series([0.0] * 12 + [-50.0])
        assert _is_force_index_spike(series, negative=True) is True

    def test_negative_not_a_spike_when_within_normal_variance(self) -> None:
        # High-variance alternating series (rolling std ~20.19) followed by a -10.0 latest
        # value -- negative and directionally right, but its magnitude doesn't clear this
        # series' own recent volatility, so it isn't classified as an outsized "spike".
        series = pd.Series([-20.0, 20.0] * 6 + [-10.0])
        assert _is_force_index_spike(series, negative=True) is False

    def test_positive_spike_when_magnitude_exceeds_rolling_stdev(self) -> None:
        series = pd.Series([0.0] * 12 + [50.0])
        assert _is_force_index_spike(series, negative=False) is True

    def test_positive_not_a_spike_when_within_normal_variance(self) -> None:
        series = pd.Series([-20.0, 20.0] * 6 + [10.0])
        assert _is_force_index_spike(series, negative=False) is False

    def test_wrong_sign_is_never_a_spike(self) -> None:
        # A comfortably outsized *positive* value doesn't count when asking for a negative spike.
        series = pd.Series([0.0] * 12 + [50.0])
        assert _is_force_index_spike(series, negative=True) is False
        # And vice versa.
        series = pd.Series([0.0] * 12 + [-50.0])
        assert _is_force_index_spike(series, negative=False) is False

    def test_nan_latest_value_is_not_a_spike(self) -> None:
        series = pd.Series([0.0] * 12 + [float("nan")])
        assert _is_force_index_spike(series, negative=True) is False
        assert _is_force_index_spike(series, negative=False) is False

    def test_insufficient_history_for_rolling_stdev_is_not_a_spike(self) -> None:
        # Fewer than _FORCE_INDEX_SPIKE_WINDOW (13) bars -> rolling std is NaN.
        series = pd.Series([-999.0] * 5)
        assert _is_force_index_spike(series, negative=True) is False

    def test_zero_stdev_is_not_a_spike(self) -> None:
        # A perfectly flat recent Force Index (std == 0) -- any nonzero value would trivially
        # "exceed" a zero threshold, so this is explicitly guarded against.
        series = pd.Series([3.0] * 13)
        assert _is_force_index_spike(series, negative=False) is False


class TestEvaluateWave:
    def _mock_wave_inputs(
        self, mocker, *, stochastic_k: float, force_index_2ema: pd.Series
    ) -> None:
        mocker.patch(
            "app.signals.triple_screen.stochastic_oscillator",
            return_value=pd.DataFrame({"k": [stochastic_k], "d": [stochastic_k]}),
        )
        mocker.patch("app.signals.triple_screen.force_index", return_value=force_index_2ema)

    def test_bullish_tide_oversold_stochastic_with_negative_spike_is_pullback(self, mocker) -> None:
        force_index_2ema = pd.Series([0.0] * 12 + [-50.0])
        self._mock_wave_inputs(mocker, stochastic_k=20.0, force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(14), "BULLISH")

        assert result == {
            "stochastic_k": 20.0,
            "force_index_2ema": -50.0,
            "state": "OVERSOLD_PULLBACK",
        }

    def test_bearish_tide_overbought_stochastic_with_positive_spike_is_rally(self, mocker) -> None:
        force_index_2ema = pd.Series([0.0] * 12 + [50.0])
        self._mock_wave_inputs(mocker, stochastic_k=80.0, force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(14), "BEARISH")

        assert result == {
            "stochastic_k": 80.0,
            "force_index_2ema": 50.0,
            "state": "OVERBOUGHT_RALLY",
        }

    def test_neutral_tide_never_produces_a_wave_state(self, mocker) -> None:
        # Oscillators are at their most extreme possible readings; only the tide is neutral.
        force_index_2ema = pd.Series([0.0] * 12 + [-50.0])
        self._mock_wave_inputs(mocker, stochastic_k=5.0, force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(14), "NEUTRAL")

        assert result["state"] == "NO_WAVE"

    def test_bullish_tide_oversold_without_force_index_spike_is_no_wave(self, mocker) -> None:
        # Stochastic is oversold, but Force Index hasn't spiked (§2 requires both together).
        force_index_2ema = pd.Series([-20.0, 20.0] * 6 + [-10.0])
        self._mock_wave_inputs(mocker, stochastic_k=20.0, force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(14), "BULLISH")

        assert result["state"] == "NO_WAVE"

    def test_bullish_tide_force_index_spike_without_oversold_stochastic_is_no_wave(self, mocker) -> None:
        # Force Index has spiked negative, but %K is exactly at (not below) the oversold
        # threshold -- docs/Analyse.md §2 says "below 30", a strict boundary.
        force_index_2ema = pd.Series([0.0] * 12 + [-50.0])
        self._mock_wave_inputs(
            mocker, stochastic_k=STOCHASTIC_OVERSOLD, force_index_2ema=force_index_2ema
        )

        result = evaluate_wave(_daily_ohlcv(14), "BULLISH")

        assert result["state"] == "NO_WAVE"

    def test_bearish_tide_overbought_without_force_index_spike_is_no_wave(self, mocker) -> None:
        force_index_2ema = pd.Series([-20.0, 20.0] * 6 + [10.0])
        self._mock_wave_inputs(mocker, stochastic_k=80.0, force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(14), "BEARISH")

        assert result["state"] == "NO_WAVE"

    def test_bearish_tide_force_index_spike_without_overbought_stochastic_is_no_wave(self, mocker) -> None:
        # %K is exactly at (not above) the overbought threshold.
        force_index_2ema = pd.Series([0.0] * 12 + [50.0])
        self._mock_wave_inputs(
            mocker, stochastic_k=STOCHASTIC_OVERBOUGHT, force_index_2ema=force_index_2ema
        )

        result = evaluate_wave(_daily_ohlcv(14), "BEARISH")

        assert result["state"] == "NO_WAVE"

    def test_bullish_tide_with_bearish_style_oscillator_reading_is_no_wave(self, mocker) -> None:
        # Tide is bullish but the oscillators show the bearish-tide pattern (overbought +
        # positive spike) -- must not be misread as a pullback.
        force_index_2ema = pd.Series([0.0] * 12 + [50.0])
        self._mock_wave_inputs(mocker, stochastic_k=80.0, force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(14), "BULLISH")

        assert result["state"] == "NO_WAVE"

    def test_nan_stochastic_k_from_insufficient_history_is_no_wave(self, mocker) -> None:
        force_index_2ema = pd.Series([0.0] * 12 + [-50.0])
        self._mock_wave_inputs(mocker, stochastic_k=float("nan"), force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(14), "BULLISH")

        assert result["state"] == "NO_WAVE"
        assert pd.isna(result["stochastic_k"])

    def test_empty_daily_ohlcv_degrades_to_no_wave_instead_of_raising(self, mocker) -> None:
        # 0-row frame: there's no bar for stochastic_oscillator()/force_index() to compute
        # from, let alone for .iloc[-1] to read -- must degrade to NaN/NO_WAVE like any other
        # insufficient-history case, not raise IndexError. Real (unmocked) indicators here,
        # since the guard must fire before stochastic_oscillator/force_index are even called.
        result = evaluate_wave(_daily_ohlcv(0), "BULLISH")

        assert result["state"] == "NO_WAVE"
        assert pd.isna(result["stochastic_k"])
        assert pd.isna(result["force_index_2ema"])

    def test_returns_latest_bar_values_matching_api_shape(self, mocker) -> None:
        force_index_2ema = pd.Series([1.0, 2.0, -18234.5])
        self._mock_wave_inputs(mocker, stochastic_k=24.3, force_index_2ema=force_index_2ema)

        result = evaluate_wave(_daily_ohlcv(3), "BULLISH")

        assert set(result.keys()) == {"stochastic_k", "force_index_2ema", "state"}
        assert result["stochastic_k"] == pytest.approx(24.3)
        assert result["force_index_2ema"] == pytest.approx(-18234.5)


class TestEvaluateWaveEndToEnd:
    """Real (unmocked) composition of evaluate_wave -> stochastic_oscillator/force_index,
    over small synthetic daily series -- confirms the actual wiring (not just the decision
    table in isolation) produces both directional wave states.
    """

    def test_end_to_end_pullback_on_multi_day_selloff_in_an_uptrend(self) -> None:
        # 20 days of a gentle uptrend (0.5/day) followed by 5 days of a steep decline
        # (-3/day, accelerating) on the last day's elevated volume -- both %K and the 2-EMA
        # Force Index should read oversold/spike on the same final bar.
        closes = [100 + i * 0.5 for i in range(20)]
        closes += [closes[-1] - 3 * i for i in range(1, 6)]
        volumes = [1_000_000] * 24 + [9_000_000]
        daily_ohlcv = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 0.3 for c in closes],
                "low": [c - 0.3 for c in closes],
                "close": closes,
                "volume": volumes,
            }
        )

        from app.indicators.force_index import force_index as real_force_index
        from app.indicators.stochastic import stochastic_oscillator as real_stochastic

        real_k = real_stochastic(daily_ohlcv["high"], daily_ohlcv["low"], daily_ohlcv["close"])["k"].iloc[-1]
        assert real_k < STOCHASTIC_OVERSOLD

        real_force_index_2ema = real_force_index(daily_ohlcv["close"], daily_ohlcv["volume"], ema_period=2)
        assert _is_force_index_spike(real_force_index_2ema, negative=True) is True

        result = evaluate_wave(daily_ohlcv, "BULLISH")

        assert result["state"] == "OVERSOLD_PULLBACK"
        assert result["stochastic_k"] == pytest.approx(real_k)
        assert result["force_index_2ema"] == pytest.approx(real_force_index_2ema.iloc[-1])

    def test_end_to_end_rally_on_multi_day_rebound_in_a_downtrend(self) -> None:
        # Mirror image: 20 days of a gentle downtrend followed by 5 days of a steep rally on
        # elevated volume -- both %K and the 2-EMA Force Index should read overbought/spike.
        closes = [100 - i * 0.5 for i in range(20)]
        closes += [closes[-1] + 3 * i for i in range(1, 6)]
        volumes = [1_000_000] * 24 + [9_000_000]
        daily_ohlcv = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 0.3 for c in closes],
                "low": [c - 0.3 for c in closes],
                "close": closes,
                "volume": volumes,
            }
        )

        from app.indicators.force_index import force_index as real_force_index
        from app.indicators.stochastic import stochastic_oscillator as real_stochastic

        real_k = real_stochastic(daily_ohlcv["high"], daily_ohlcv["low"], daily_ohlcv["close"])["k"].iloc[-1]
        assert real_k > STOCHASTIC_OVERBOUGHT

        real_force_index_2ema = real_force_index(daily_ohlcv["close"], daily_ohlcv["volume"], ema_period=2)
        assert _is_force_index_spike(real_force_index_2ema, negative=False) is True

        result = evaluate_wave(daily_ohlcv, "BEARISH")

        assert result["state"] == "OVERBOUGHT_RALLY"
        assert result["stochastic_k"] == pytest.approx(real_k)
        assert result["force_index_2ema"] == pytest.approx(real_force_index_2ema.iloc[-1])
