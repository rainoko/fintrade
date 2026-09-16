"""Tests for app.signals.triple_screen (docs/Analyse.md §2, Triple Screen).

Covers ``evaluate_tide`` (Screen 1 / Tide) and ``evaluate_wave`` (Screen 2 / Wave):

Screen 1 (Tide):

1. ``TestMacdHistogramSlope`` / ``TestEvaluateTideCombinationLogic`` isolate
   the *combination logic* itself (the flat-threshold cutoff, and the
   BULLISH/BEARISH/NEUTRAL decision table) from the real indicator math --
   which is already covered by hand-computed reference tests in
   test_ema.py/test_macd.py -- by mocking ``macd_components``/``ema``/the
   slope helper with controlled outputs.
2. ``TestEvaluateTideEndToEnd`` exercises the real, unmocked composition
   (``evaluate_tide`` -> ``macd_components`` -> ``ema``) over small synthetic
   weekly OHLCV series, confirming the wiring itself (not just the decision
   table in isolation) produces each of the three outputs.

See the `decisions` entry on docs/tasks/screen1-tide.json for the rationale
behind the two-point slope + 0.1%-of-price flat threshold, the TideResult
shape, and reusing app.indicators.macd.macd_components to avoid computing
EMA(26) twice.

Screen 2 (Wave), matching the precedent set by test_impulse.py:

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

``evaluate_trigger`` is an unimplemented stub owned by a separate, not-yet-merged
task (screen3-trigger) and is intentionally not touched or tested here.
"""

import pandas as pd
import pytest

from app.indicators.macd import MacdComponents
from app.signals.triple_screen import (
    STOCHASTIC_OVERBOUGHT,
    STOCHASTIC_OVERSOLD,
    TideResult,
    _is_force_index_spike,
    evaluate_tide,
    evaluate_wave,
    macd_histogram_slope,
    validate_weekly_ohlcv_columns,
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

    def test_malformed_weekly_ohlcv_missing_close_raises_value_error_not_key_error(self) -> None:
        # Regression test for the PR #29 re-review finding: evaluate_tide() raised a bare
        # KeyError('close') for a >=2-row weekly_ohlcv missing the 'close' column, instead of
        # the documented ValueError, because weekly_ohlcv['close'] was accessed with no
        # column validation -- see the portfolio-exit-rules-followups task's `decisions`
        # entry. Reproduced against pre-fix code first (confirmed it raised
        # KeyError('close')) before adding the validate_weekly_ohlcv_columns() call this
        # asserts on.
        weekly_ohlcv = pd.DataFrame(
            {"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "volume": [1_000_000] * 2}
        )

        with pytest.raises(ValueError, match="missing required column"):
            evaluate_tide(weekly_ohlcv)

    def test_short_weekly_ohlcv_missing_close_does_not_raise(self) -> None:
        # A <2-row weekly_ohlcv degrades gracefully to NEUTRAL without ever touching
        # 'close' -- validate_weekly_ohlcv_columns must not turn that pre-existing,
        # documented graceful-degradation path into a new error.
        weekly_ohlcv = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "volume": [1_000_000]})

        assert evaluate_tide(weekly_ohlcv) == TideResult(
            trend="NEUTRAL", weekly_macd_histogram_slope="flat"
        )


class TestValidateWeeklyOhlcvColumns:
    def test_raises_on_missing_close_column(self) -> None:
        weekly_ohlcv = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0]})

        with pytest.raises(ValueError, match="missing required column"):
            validate_weekly_ohlcv_columns(weekly_ohlcv)

    def test_does_not_raise_when_close_present(self) -> None:
        weekly_ohlcv = pd.DataFrame({"close": [1.0]})

        validate_weekly_ohlcv_columns(weekly_ohlcv)  # no raise

    def test_does_not_raise_on_empty_frame_with_close_column(self) -> None:
        # Row-count emptiness is not this validator's concern -- only column presence.
        weekly_ohlcv = pd.DataFrame({"close": pd.Series([], dtype=float)})

        validate_weekly_ohlcv_columns(weekly_ohlcv)  # no raise


class TestEvaluateTidePrecomputedSeries:
    """Covers the `histogram`/`ema_13`/`ema_26` parameters (see the
    portfolio-exit-rules-followups task's `decisions` entry) that let a caller share an
    already-computed MACD-Histogram/EMA(13)/EMA(26) of the same weekly close series
    instead of evaluate_tide recomputing them internally -- used by
    app.portfolio.exits.evaluate_exit_flags to avoid two independent MACD/EMA passes when
    it calls evaluate_tide twice (full series, then the prior-bar slice)."""

    def test_precomputed_series_matches_default_computation(self) -> None:
        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_components as real_macd_components

        closes = pd.Series([100 * (1.05**i) for i in range(40)], dtype=float)
        weekly_ohlcv = _weekly_ohlcv(closes)
        components = real_macd_components(closes)
        precomputed_ema_13 = real_ema(closes, 13)

        result_default = evaluate_tide(weekly_ohlcv)
        result_shared = evaluate_tide(
            weekly_ohlcv,
            histogram=components.histogram,
            ema_13=precomputed_ema_13,
            ema_26=components.ema_slow,
        )

        assert result_shared == result_default

    def test_precomputed_series_causal_slice_matches_recomputing_on_truncated_series(
        self,
    ) -> None:
        """The whole point of sharing: a full-series MACD/EMA computation, sliced to
        exclude the latest bar, must equal recomputing from scratch on that shorter
        series -- since EMA/MACD are causal (a value at index t depends only on data up
        to t). This is exactly what evaluate_exit_flags relies on for its "previous tide"
        call."""
        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_components as real_macd_components

        closes = pd.Series([100 * (1.03**i) for i in range(20)], dtype=float)
        full_ohlcv = _weekly_ohlcv(closes)
        truncated_ohlcv = _weekly_ohlcv(closes.iloc[:-1])

        full_components = real_macd_components(closes)
        full_ema_13 = real_ema(closes, 13)

        result_from_shared_slice = evaluate_tide(
            truncated_ohlcv,
            histogram=full_components.histogram.iloc[:-1],
            ema_13=full_ema_13.iloc[:-1],
            ema_26=full_components.ema_slow.iloc[:-1],
        )
        result_from_fresh_recomputation = evaluate_tide(truncated_ohlcv)

        assert result_from_shared_slice == result_from_fresh_recomputation

    def test_precomputed_series_is_actually_used_not_ignored(self, mocker) -> None:
        """A deliberately wrong precomputed series must change the result -- confirms the
        parameters are wired in, not silently ignored in favor of always recomputing."""
        components_mock = mocker.patch("app.signals.triple_screen.macd_components")
        ema_mock = mocker.patch("app.signals.triple_screen.ema")
        weekly_ohlcv = _weekly_ohlcv(pd.Series([100.0, 101.0]))

        result = evaluate_tide(
            weekly_ohlcv,
            histogram=pd.Series([-5.0, 5.0]),  # rising
            ema_13=pd.Series([110.0]),
            ema_26=pd.Series([100.0]),
        )

        assert result == TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising")
        components_mock.assert_not_called()
        ema_mock.assert_not_called()

    def test_each_precomputed_series_can_be_supplied_independently(self, mocker) -> None:
        """Supplying only `ema_13` (leaving histogram/ema_26 to be computed internally)
        must still work -- the three parameters are independent, not all-or-nothing."""
        from app.indicators.ema import ema as real_ema

        closes = pd.Series([100 * (1.05**i) for i in range(40)], dtype=float)
        weekly_ohlcv = _weekly_ohlcv(closes)
        precomputed_ema_13 = real_ema(closes, 13)

        result_default = evaluate_tide(weekly_ohlcv)
        result_partial = evaluate_tide(weekly_ohlcv, ema_13=precomputed_ema_13)

        assert result_partial == result_default

    def test_only_histogram_supplied_still_derives_ema_26_from_macd_components(self) -> None:
        """Supplying `histogram` alone (leaving `ema_26` unsupplied) must still call
        macd_components internally to get `ema_26` -- the two aren't both skipped just
        because one of them was provided."""
        from app.indicators.macd import macd_components as real_macd_components

        closes = pd.Series([100 * (1.05**i) for i in range(40)], dtype=float)
        weekly_ohlcv = _weekly_ohlcv(closes)
        components = real_macd_components(closes)

        result_default = evaluate_tide(weekly_ohlcv)
        result_partial = evaluate_tide(weekly_ohlcv, histogram=components.histogram)

        assert result_partial == result_default

    def test_only_ema_26_supplied_still_derives_histogram_from_macd_components(self) -> None:
        """Supplying `ema_26` alone (leaving `histogram` unsupplied) must still call
        macd_components internally to get `histogram`."""
        from app.indicators.macd import macd_components as real_macd_components

        closes = pd.Series([100 * (1.05**i) for i in range(40)], dtype=float)
        weekly_ohlcv = _weekly_ohlcv(closes)
        components = real_macd_components(closes)

        result_default = evaluate_tide(weekly_ohlcv)
        result_partial = evaluate_tide(weekly_ohlcv, ema_26=components.ema_slow)

        assert result_partial == result_default


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

    def test_single_row_daily_ohlcv_degrades_to_no_wave_instead_of_raising(self) -> None:
        # 1-row frame: the len == 0 guard doesn't fire here (unlike the 0-row case above), so
        # this exercises the real stochastic_oscillator()/force_index() calls with a single
        # bar. Neither indicator has enough history to produce a defined value yet (%K needs
        # k_period=5 bars; Force Index's raw series needs a prior close to diff against), so
        # both come back NaN and .iloc[-1] on a 1-element Series is still valid -- degrading to
        # NO_WAVE via the ordinary NaN path rather than the len-guard. Real (unmocked)
        # indicators, to prove this boundary case doesn't need its own guard the way the 0-row
        # case does.
        result = evaluate_wave(_daily_ohlcv(1), "BULLISH")

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
