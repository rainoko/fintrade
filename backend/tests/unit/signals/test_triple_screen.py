"""Tests for app.signals.triple_screen.evaluate_wave (docs/Analyse.md §2, Screen 2 / Wave).

Three layers of coverage, matching the precedent set by test_impulse.py:

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

``evaluate_tide``/``evaluate_trigger`` are unimplemented stubs owned by other, not-yet-merged
tasks (screen1-tide, screen3-trigger) and are intentionally not touched or tested here.
"""

import pandas as pd
import pytest

from app.signals.triple_screen import (
    STOCHASTIC_OVERBOUGHT,
    STOCHASTIC_OVERSOLD,
    _is_force_index_spike,
    evaluate_wave,
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
