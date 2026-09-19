"""Tests for app.signals.engine.analyse (docs/Analyse.md §5, Signal Logic).

Four layers of coverage, matching docs/architecture/Backend.md's "Signal engine tests cover
each Screen 1/2/3 + Impulse combination explicitly" guidance:

1. ``TestDetermineSignal`` isolates the pure BUY/SELL/HOLD combination table
   (``_determine_signal``) from the Screen/gate functions themselves -- covers every
   Tide x Impulse x Wave x Trigger combination named in docs/Analyse.md §5, not just the two
   "everything lines up" happy paths.
2. ``TestWaveLookback`` isolates the "Wave shows/showed" single-pass lookback
   (``_wave_lookback``) by mocking ``evaluate_wave`` with a per-slice-length ``side_effect``
   -- covers today's bar matching, an earlier bar within the lookback window matching, a
   match older than the window not counting, and that only the direction the current tide
   can actually produce is ever scanned (see this task's `decisions` entry).
3. ``TestAnalyseCombinations`` exercises ``analyse()`` itself with ``evaluate_tide`` /
   ``evaluate_impulse`` / ``evaluate_wave`` / ``evaluate_trigger`` all mocked, covering each
   Screen 1/2/3 + Impulse combination end to end (signal + confidence/breakdown shape), plus
   the ``screens``/``indicators`` passthrough shape.
4. ``TestAnalyseEndToEnd`` exercises the real, unmocked composition (every Screen/gate
   function plus every indicator) over small synthetic daily+weekly OHLCV series, confirming
   the actual wiring -- not just the decision table in isolation -- produces a real BUY and a
   real SELL, including the "Wave showed" (not "shows") lookback case in both directions.
"""

import dataclasses
import math
from unittest.mock import patch

import pandas as pd

from app.signals.confidence import ConfidenceComponent
from app.signals.engine import (
    _determine_signal,
    _wave_lookback,
    _weekly_through_bar_date,
    analyse,
    analyse_history,
    drop_malformed_daily_bars,
)
from app.signals.triple_screen import TideResult, evaluate_tide


def _nan_tolerant_equal(a: object, b: object) -> bool:
    """Like ``a == b``, except two ``float('nan')`` leaves anywhere inside a (possibly nested)
    dict/list/tuple/``SignalResult``/``(date, SignalResult)`` structure compare equal -- plain
    ``==``/dict-equality treats NaN as unequal to itself (IEEE 754), which would make an
    otherwise-identical ``screens``/``indicators`` (or a whole ``analyse_history`` result list,
    since ``channel_upper``/``channel_lower`` are NaN for a long leading span of any fixture
    shorter than the Autoenvelope channel's ~100-bar warm-up) spuriously fail a cross-check
    assertion whenever an indicator is still in its NaN warm-up window."""
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_nan_tolerant_equal(a[k], b[k]) for k in a)
    if dataclasses.is_dataclass(a) and dataclasses.is_dataclass(b) and type(a) is type(b):
        a_fields = {f.name: getattr(a, f.name) for f in dataclasses.fields(a)}
        b_fields = {f.name: getattr(b, f.name) for f in dataclasses.fields(b)}
        return _nan_tolerant_equal(a_fields, b_fields)
    if (
        isinstance(a, (list, tuple))
        and isinstance(b, (list, tuple))
        and len(a) == len(b)
    ):
        return all(_nan_tolerant_equal(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _daily_ohlcv(n: int) -> pd.DataFrame:
    """Minimal n-row daily OHLCV frame -- content is a placeholder wherever the
    Screen/gate functions that read it are mocked; real (unmocked) EMA/Elder-Ray/volume
    computation at the bottom of ``analyse()`` still runs against it, so values are chosen
    to be realistic-looking (not all-identical, which would make EMA/Elder-Ray degenerate).
    """
    closes = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i * 1_000 for i in range(n)],
        }
    )


def _weekly_ohlcv(n: int) -> pd.DataFrame:
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": 1_000_000,
        }
    )


class TestDropMalformedDailyBars:
    """Direct unit coverage of drop_malformed_daily_bars, independent of analyse()'s own
    end-to-end regression test below."""

    def test_drops_only_rows_with_nan_ohlc(self) -> None:
        daily_ohlcv = _daily_ohlcv(5)
        daily_ohlcv.loc[daily_ohlcv.index[-1], ["open", "high", "low", "close"]] = float("nan")

        result = drop_malformed_daily_bars(daily_ohlcv)

        assert len(result) == 4
        assert not result.isna().any().any()

    def test_volume_only_nan_does_not_drop_the_row(self) -> None:
        """A NaN volume alone (with real OHLC) isn't the malformed condition this guards
        against -- only open/high/low/close are checked."""
        daily_ohlcv = _daily_ohlcv(5)
        daily_ohlcv.loc[daily_ohlcv.index[-1], "volume"] = float("nan")

        result = drop_malformed_daily_bars(daily_ohlcv)

        assert len(result) == 5

    def test_clean_frame_passes_through_unchanged(self) -> None:
        daily_ohlcv = _daily_ohlcv(5)

        result = drop_malformed_daily_bars(daily_ohlcv)

        pd.testing.assert_frame_equal(result, daily_ohlcv)

    def test_empty_frame_passes_through_unchanged(self) -> None:
        daily_ohlcv = _daily_ohlcv(0)

        result = drop_malformed_daily_bars(daily_ohlcv)

        assert len(result) == 0

    def test_missing_column_does_not_raise_and_still_drops_nan_rows_on_remaining_columns(
        self,
    ) -> None:
        """A frame missing one of open/high/low/close entirely (e.g. a stub test double, or
        any other caller's malformed-frame fixture) is a distinct, pre-existing failure mode
        from the NaN-*value* one this function targets -- it must not raise a bare KeyError
        from dropna(subset=...) naming a column that was never there, leaving that case for
        the caller's own column-presence check (e.g.
        app.portfolio.risk.validate_daily_ohlcv_columns) to raise its documented ValueError
        for instead. See the api-stocks-analysis-nullable-indicators-followups task's
        `decisions` entry."""
        daily_ohlcv = _daily_ohlcv(5).drop(columns=["low"])
        daily_ohlcv.loc[daily_ohlcv.index[-1], ["open", "high", "close"]] = float("nan")

        result = drop_malformed_daily_bars(daily_ohlcv)

        assert len(result) == 4
        assert "low" not in result.columns


class TestDropMalformedDailyBarsRequireFullOhlcOnLatestBarFalse:
    """`require_full_ohlc_on_latest_bar=False` -- app.api.routers.portfolio.get_risk's own
    argument, reconciling this function's default with app.portfolio.pricing.latest_close's
    close-only validity rule for the latest bar. See the
    api-stocks-analysis-nullable-indicators-followups task's `decisions` entry (and
    tests/integration/test_portfolio_risk.py's
    test_malformed_open_high_low_on_latest_bar_does_not_suppress_stop_hit for the end-to-end
    regression this exists to fix)."""

    def test_latest_bar_with_real_close_but_nan_ohl_is_kept(self) -> None:
        daily_ohlcv = _daily_ohlcv(5)
        daily_ohlcv.loc[daily_ohlcv.index[-1], ["open", "high", "low"]] = float("nan")

        result = drop_malformed_daily_bars(daily_ohlcv, require_full_ohlc_on_latest_bar=False)

        assert len(result) == 5
        assert result.iloc[-1]["close"] == daily_ohlcv.iloc[-1]["close"]
        assert pd.isna(result.iloc[-1]["open"])

    def test_latest_bar_with_nan_close_is_still_dropped(self) -> None:
        daily_ohlcv = _daily_ohlcv(5)
        daily_ohlcv.loc[daily_ohlcv.index[-1], ["open", "high", "low", "close"]] = float("nan")

        result = drop_malformed_daily_bars(daily_ohlcv, require_full_ohlc_on_latest_bar=False)

        assert len(result) == 4
        assert not result.isna().any().any()

    def test_earlier_malformed_bar_still_dropped(self) -> None:
        """A malformed bar earlier in history still needs full OHLC validity even with
        `require_full_ohlc_on_latest_bar=False` -- only the *latest* bar's rule relaxes."""
        daily_ohlcv = _daily_ohlcv(5)
        daily_ohlcv.loc[daily_ohlcv.index[1], ["open", "high"]] = float("nan")

        result = drop_malformed_daily_bars(daily_ohlcv, require_full_ohlc_on_latest_bar=False)

        assert len(result) == 4
        assert not result.isna().any().any()

    def test_clean_frame_passes_through_unchanged(self) -> None:
        daily_ohlcv = _daily_ohlcv(5)

        result = drop_malformed_daily_bars(daily_ohlcv, require_full_ohlc_on_latest_bar=False)

        pd.testing.assert_frame_equal(result, daily_ohlcv)

    def test_empty_frame_passes_through_unchanged(self) -> None:
        daily_ohlcv = _daily_ohlcv(0)

        result = drop_malformed_daily_bars(daily_ohlcv, require_full_ohlc_on_latest_bar=False)

        assert len(result) == 0

    def test_missing_close_column_does_not_raise_and_keeps_latest_bar(self) -> None:
        """A frame missing `close` entirely is left for the caller's own column-presence
        check to raise for, same as the require_full_ohlc_on_latest_bar=True case -- the
        latest bar's `pd.isna(latest["close"])` guard here must not raise a bare KeyError."""
        daily_ohlcv = _daily_ohlcv(5).drop(columns=["close"])

        result = drop_malformed_daily_bars(daily_ohlcv, require_full_ohlc_on_latest_bar=False)

        assert len(result) == 5
        assert "close" not in result.columns


class TestDetermineSignal:
    """Isolates the pure BUY/SELL/HOLD combination table from every Screen/gate function."""

    def test_buy_when_bullish_impulse_not_red_wave_showed_pullback_and_trigger_fired(self) -> None:
        assert _determine_signal("BULLISH", "GREEN", True, False, True) == "BUY"

    def test_buy_allowed_under_blue_impulse(self) -> None:
        assert _determine_signal("BULLISH", "BLUE", True, False, True) == "BUY"

    def test_buy_blocked_by_red_impulse(self) -> None:
        assert _determine_signal("BULLISH", "RED", True, False, True) == "HOLD"

    def test_buy_blocked_by_no_wave_pullback(self) -> None:
        assert _determine_signal("BULLISH", "GREEN", False, False, True) == "HOLD"

    def test_buy_blocked_by_trigger_not_fired(self) -> None:
        assert _determine_signal("BULLISH", "GREEN", True, False, False) == "HOLD"

    def test_sell_when_bearish_impulse_not_green_wave_showed_rally_and_trigger_fired(self) -> None:
        assert _determine_signal("BEARISH", "RED", False, True, True) == "SELL"

    def test_sell_allowed_under_blue_impulse(self) -> None:
        assert _determine_signal("BEARISH", "BLUE", False, True, True) == "SELL"

    def test_sell_blocked_by_green_impulse(self) -> None:
        assert _determine_signal("BEARISH", "GREEN", False, True, True) == "HOLD"

    def test_sell_blocked_by_no_wave_rally(self) -> None:
        assert _determine_signal("BEARISH", "RED", False, False, True) == "HOLD"

    def test_sell_blocked_by_trigger_not_fired(self) -> None:
        assert _determine_signal("BEARISH", "RED", False, True, False) == "HOLD"

    def test_neutral_tide_is_always_hold_even_if_everything_else_lines_up(self) -> None:
        assert _determine_signal("NEUTRAL", "GREEN", True, True, True) == "HOLD"

    def test_bearish_tide_never_produces_buy_even_with_pullback_flag_set(self) -> None:
        # wave_showed_pullback True is meaningless for a BEARISH tide -- BUY requires BULLISH.
        assert _determine_signal("BEARISH", "GREEN", True, False, True) == "HOLD"

    def test_bullish_tide_never_produces_sell_even_with_rally_flag_set(self) -> None:
        assert _determine_signal("BULLISH", "RED", False, True, True) == "HOLD"


class TestWaveLookback:
    """Isolates the "Wave shows/showed" single-pass lookback by mocking evaluate_wave with a
    per-slice-length side_effect, so the loop's actual windowing/early-exit behavior (not
    evaluate_wave's own oversold/overbought math, already covered in test_triple_screen.py)
    is what's tested -- including that only the direction the current tide can actually
    produce is ever scanned, and that today's bar is never re-evaluated a second time (see
    this task's `decisions` entry).
    """

    def test_matches_on_todays_bar_without_further_calls(self) -> None:
        daily_ohlcv = _daily_ohlcv(10)

        def side_effect(
            df: pd.DataFrame, tide: str, *, stochastic_k=None, force_index_2ema=None
        ) -> dict:
            state = "OVERSOLD_PULLBACK" if len(df) == 10 else "NO_WAVE"
            return {"stochastic_k": 0.0, "force_index_2ema": 0.0, "state": state}

        with patch("app.signals.engine.evaluate_wave", side_effect=side_effect) as mock_wave:
            wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "BULLISH")

        assert wave["state"] == "OVERSOLD_PULLBACK"
        assert showed_pullback is True
        assert showed_rally is False
        # Matched on the first (today's) call -- no further evaluate_wave calls needed.
        mock_wave.assert_called_once_with(
            daily_ohlcv, "BULLISH", stochastic_k=None, force_index_2ema=None
        )

    def test_matches_within_lookback_window_but_not_on_todays_bar(self) -> None:
        daily_ohlcv = _daily_ohlcv(10)

        def side_effect(
            df: pd.DataFrame, tide: str, *, stochastic_k=None, force_index_2ema=None
        ) -> dict:
            # Qualifies 3 bars ago (len == 7 of 10), within the 5-day lookback window.
            state = "OVERSOLD_PULLBACK" if len(df) == 7 else "NO_WAVE"
            return {"stochastic_k": 0.0, "force_index_2ema": 0.0, "state": state}

        with patch("app.signals.engine.evaluate_wave", side_effect=side_effect):
            wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "BULLISH")

        assert wave["state"] == "NO_WAVE"
        assert showed_pullback is True
        assert showed_rally is False

    def test_does_not_match_outside_lookback_window(self) -> None:
        daily_ohlcv = _daily_ohlcv(10)

        def side_effect(
            df: pd.DataFrame, tide: str, *, stochastic_k=None, force_index_2ema=None
        ) -> dict:
            # Qualifies 6 bars ago (len == 4 of 10) -- one bar older than the 5-day window
            # (which covers bars with len in [6, 10] for a 10-row frame).
            state = "OVERSOLD_PULLBACK" if len(df) == 4 else "NO_WAVE"
            return {"stochastic_k": 0.0, "force_index_2ema": 0.0, "state": state}

        with patch("app.signals.engine.evaluate_wave", side_effect=side_effect):
            _wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "BULLISH")

        assert showed_pullback is False
        assert showed_rally is False

    def test_no_match_anywhere_in_window_is_false(self) -> None:
        daily_ohlcv = _daily_ohlcv(10)

        with patch(
            "app.signals.engine.evaluate_wave",
            return_value={"stochastic_k": 0.0, "force_index_2ema": 0.0, "state": "NO_WAVE"},
        ):
            _wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "BULLISH")

        assert showed_pullback is False
        assert showed_rally is False

    def test_empty_daily_ohlcv_is_false_without_indexing_error(self) -> None:
        daily_ohlcv = _daily_ohlcv(0)

        with patch(
            "app.signals.engine.evaluate_wave",
            return_value={
                "stochastic_k": float("nan"),
                "force_index_2ema": float("nan"),
                "state": "NO_WAVE",
            },
        ) as mock_wave:
            _wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "BULLISH")

        assert showed_pullback is False
        assert showed_rally is False
        # Only today's (the sole, empty) bar is ever evaluated -- no window to loop over.
        mock_wave.assert_called_once_with(
            daily_ohlcv, "BULLISH", stochastic_k=None, force_index_2ema=None
        )

    def test_neutral_tide_never_matches_and_evaluates_wave_only_once(self) -> None:
        """NEUTRAL tide can never produce OVERSOLD_PULLBACK or OVERBOUGHT_RALLY (see
        evaluate_wave's own contract), so the lookback loop is skipped entirely -- confirms
        this task's headline fix: a tide whose target state can never match doesn't spend
        any evaluate_wave calls scanning for it.
        """
        daily_ohlcv = _daily_ohlcv(10)

        with patch(
            "app.signals.engine.evaluate_wave",
            return_value={"stochastic_k": 50.0, "force_index_2ema": 0.0, "state": "NO_WAVE"},
        ) as mock_wave:
            _wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "NEUTRAL")

        assert showed_pullback is False
        assert showed_rally is False
        mock_wave.assert_called_once_with(
            daily_ohlcv, "NEUTRAL", stochastic_k=None, force_index_2ema=None
        )

    def test_bearish_tide_only_ever_reports_rally_never_pullback(self) -> None:
        """A BEARISH tide can only ever show a rally, never a pullback (and vice versa for
        BULLISH) -- the unreachable boolean is always False without evaluate_wave needing to
        report anything about it, since the lookback loop for it is never even entered.
        """
        daily_ohlcv = _daily_ohlcv(10)

        with patch(
            "app.signals.engine.evaluate_wave",
            return_value={
                "stochastic_k": 80.0,
                "force_index_2ema": 100.0,
                "state": "OVERBOUGHT_RALLY",
            },
        ):
            _wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "BEARISH")

        assert showed_pullback is False
        assert showed_rally is True


def _patched_screens(tide: TideResult, impulse: str, wave: dict, trigger: dict):
    """Context manager patching all four Screen/gate functions used by analyse() at once."""
    return (
        patch("app.signals.engine.evaluate_tide", return_value=tide),
        patch("app.signals.engine.evaluate_impulse", return_value=impulse),
        patch("app.signals.engine.evaluate_wave", return_value=wave),
        patch("app.signals.engine.evaluate_trigger", return_value=trigger),
    )


class TestAnalyseCombinations:
    """analyse() end to end with the four Screen/gate functions mocked -- covers each
    Screen 1/2/3 + Impulse combination from docs/Analyse.md §5, not just the happy paths.
    """

    daily_ohlcv = _daily_ohlcv(10)
    weekly_ohlcv = _weekly_ohlcv(10)

    def _analyse(self, tide: TideResult, impulse: str, wave: dict, trigger: dict):
        p_tide, p_impulse, p_wave, p_trigger = _patched_screens(tide, impulse, wave, trigger)
        with p_tide, p_impulse, p_wave, p_trigger:
            return analyse("TEST", self.daily_ohlcv, self.weekly_ohlcv)

    def test_bullish_green_oversold_fired_is_buy(self) -> None:
        result = self._analyse(
            TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising"),
            "GREEN",
            {"stochastic_k": 20.0, "force_index_2ema": -100.0, "state": "OVERSOLD_PULLBACK"},
            {"fired": True, "reference": "close_above_prior_high"},
        )
        assert result.signal == "BUY"
        assert 0 <= result.confidence <= 100
        assert result.confidence_band in ("Low", "Medium", "High")
        assert [c.component for c in result.breakdown] == [
            "tide_alignment",
            "impulse_gate",
            "oscillator_extremity",
            "elder_ray_confirmation",
            "volume_confirmation",
        ]

    def test_bullish_blue_oversold_fired_is_buy(self) -> None:
        result = self._analyse(
            TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising"),
            "BLUE",
            {"stochastic_k": 20.0, "force_index_2ema": -100.0, "state": "OVERSOLD_PULLBACK"},
            {"fired": True, "reference": "close_above_prior_high"},
        )
        assert result.signal == "BUY"

    def test_bullish_red_oversold_fired_is_hold_not_buy(self) -> None:
        """The Impulse gate: RED blocks a fresh BUY even with Tide/Wave/Trigger all aligned
        (docs/Analyse.md §3).
        """
        result = self._analyse(
            TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising"),
            "RED",
            {"stochastic_k": 20.0, "force_index_2ema": -100.0, "state": "OVERSOLD_PULLBACK"},
            {"fired": True, "reference": "close_above_prior_high"},
        )
        assert result.signal == "HOLD"
        assert result.confidence == 0
        assert result.confidence_band == "Low"
        assert result.breakdown == []

    def test_bullish_green_no_wave_fired_is_hold(self) -> None:
        result = self._analyse(
            TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising"),
            "GREEN",
            {"stochastic_k": 50.0, "force_index_2ema": 100.0, "state": "NO_WAVE"},
            {"fired": True, "reference": "close_above_prior_high"},
        )
        assert result.signal == "HOLD"

    def test_bullish_green_oversold_not_fired_is_hold(self) -> None:
        result = self._analyse(
            TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising"),
            "GREEN",
            {"stochastic_k": 20.0, "force_index_2ema": -100.0, "state": "OVERSOLD_PULLBACK"},
            {"fired": False, "reference": "close_above_prior_high"},
        )
        assert result.signal == "HOLD"

    def test_bearish_red_overbought_fired_is_sell(self) -> None:
        result = self._analyse(
            TideResult(trend="BEARISH", weekly_macd_histogram_slope="falling"),
            "RED",
            {"stochastic_k": 80.0, "force_index_2ema": 100.0, "state": "OVERBOUGHT_RALLY"},
            {"fired": True, "reference": "close_below_prior_low"},
        )
        assert result.signal == "SELL"
        assert [c.component for c in result.breakdown] == [
            "tide_alignment",
            "impulse_gate",
            "oscillator_extremity",
            "elder_ray_confirmation",
            "volume_confirmation",
        ]

    def test_bearish_blue_overbought_fired_is_sell(self) -> None:
        result = self._analyse(
            TideResult(trend="BEARISH", weekly_macd_histogram_slope="falling"),
            "BLUE",
            {"stochastic_k": 80.0, "force_index_2ema": 100.0, "state": "OVERBOUGHT_RALLY"},
            {"fired": True, "reference": "close_below_prior_low"},
        )
        assert result.signal == "SELL"

    def test_bearish_green_overbought_fired_is_hold_not_sell(self) -> None:
        """The Impulse gate: GREEN blocks a fresh SELL even with Tide/Wave/Trigger all
        aligned (docs/Analyse.md §3).
        """
        result = self._analyse(
            TideResult(trend="BEARISH", weekly_macd_histogram_slope="falling"),
            "GREEN",
            {"stochastic_k": 80.0, "force_index_2ema": 100.0, "state": "OVERBOUGHT_RALLY"},
            {"fired": True, "reference": "close_below_prior_low"},
        )
        assert result.signal == "HOLD"
        assert result.confidence == 0
        assert result.breakdown == []

    def test_bearish_red_no_wave_fired_is_hold(self) -> None:
        result = self._analyse(
            TideResult(trend="BEARISH", weekly_macd_histogram_slope="falling"),
            "RED",
            {"stochastic_k": 50.0, "force_index_2ema": -100.0, "state": "NO_WAVE"},
            {"fired": True, "reference": "close_below_prior_low"},
        )
        assert result.signal == "HOLD"

    def test_bearish_red_overbought_not_fired_is_hold(self) -> None:
        result = self._analyse(
            TideResult(trend="BEARISH", weekly_macd_histogram_slope="falling"),
            "RED",
            {"stochastic_k": 80.0, "force_index_2ema": 100.0, "state": "OVERBOUGHT_RALLY"},
            {"fired": False, "reference": "not_applicable"},
        )
        assert result.signal == "HOLD"

    def test_neutral_tide_is_hold_regardless_of_everything_else(self) -> None:
        result = self._analyse(
            TideResult(trend="NEUTRAL", weekly_macd_histogram_slope="flat"),
            "GREEN",
            {"stochastic_k": 20.0, "force_index_2ema": -100.0, "state": "OVERSOLD_PULLBACK"},
            {"fired": True, "reference": "not_applicable"},
        )
        assert result.signal == "HOLD"
        assert result.confidence == 0
        assert result.confidence_band == "Low"

    def test_screens_and_indicators_are_always_populated(self) -> None:
        """screens/indicators are informational passthroughs for the API response, populated
        regardless of signal -- see this task's `decisions` entry.
        """
        tide = TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising")
        wave = {"stochastic_k": 50.0, "force_index_2ema": 0.0, "state": "NO_WAVE"}
        trigger = {"fired": False, "reference": "not_applicable"}
        result = self._analyse(tide, "BLUE", wave, trigger)

        assert result.signal == "HOLD"
        assert result.screens == {
            "tide": {"trend": "BULLISH", "weekly_macd_histogram_slope": "rising"},
            "impulse": "BLUE",
            "wave": {
                **wave,
                "showed_pullback_in_lookback": False,
                "showed_rally_in_lookback": False,
            },
            "trigger": trigger,
        }
        assert set(result.indicators) == {
            "ema_13",
            "ema_26",
            "macd_histogram",
            "bull_power",
            "bear_power",
            "channel_upper",
            "channel_lower",
            "rsi",
        }
        assert all(isinstance(v, float) for v in result.indicators.values())

    def test_channel_upper_and_lower_passthrough_are_independent(self) -> None:
        """channel_upper/channel_lower, like every other precomputed-series parameter
        analyse() accepts, are independent -- a caller may supply just one of the pair (only
        `analyse_history` ever supplies both together in practice, but the contract doesn't
        require that)."""
        tide = TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising")
        wave = {"stochastic_k": 50.0, "force_index_2ema": 0.0, "state": "NO_WAVE"}
        trigger = {"fired": False, "reference": "not_applicable"}
        daily_ohlcv = _daily_ohlcv(5)
        weekly_ohlcv = _weekly_ohlcv(5)
        given_upper = pd.Series([111.0] * len(daily_ohlcv))

        p_tide, p_impulse, p_wave, p_trigger = _patched_screens(tide, "BLUE", wave, trigger)
        with p_tide, p_impulse, p_wave, p_trigger:
            result = analyse(
                "TEST", daily_ohlcv, weekly_ohlcv, channel_upper=given_upper
            )

        # The caller-supplied upper band is used verbatim...
        assert result.indicators["channel_upper"] == 111.0
        # ...while the omitted lower band is still computed internally (real autoenvelope()
        # math on this short fixture NaNs out, since it's far shorter than the ~100-bar
        # warm-up -- this only asserts it wasn't silently left at the caller's upper value).
        assert math.isnan(result.indicators["channel_lower"])

        # Mirror case: only the lower band supplied.
        given_lower = pd.Series([99.0] * len(daily_ohlcv))
        with p_tide, p_impulse, p_wave, p_trigger:
            result = analyse(
                "TEST", daily_ohlcv, weekly_ohlcv, channel_lower=given_lower
            )
        assert math.isnan(result.indicators["channel_upper"])
        assert result.indicators["channel_lower"] == 99.0

    def test_rsi_passthrough_is_used_verbatim(self) -> None:
        """rsi, like channel_upper/channel_lower above, is a precomputed-series passthrough
        parameter -- a caller-supplied series is used as-is (only its latest value read),
        never recomputed internally."""
        tide = TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising")
        wave = {"stochastic_k": 50.0, "force_index_2ema": 0.0, "state": "NO_WAVE"}
        trigger = {"fired": False, "reference": "not_applicable"}
        daily_ohlcv = _daily_ohlcv(5)
        weekly_ohlcv = _weekly_ohlcv(5)
        given_rsi = pd.Series([42.0] * len(daily_ohlcv))

        p_tide, p_impulse, p_wave, p_trigger = _patched_screens(tide, "BLUE", wave, trigger)
        with p_tide, p_impulse, p_wave, p_trigger:
            result = analyse("TEST", daily_ohlcv, weekly_ohlcv, rsi=given_rsi)

        assert result.indicators["rsi"] == 42.0

    def test_divergence_passthrough_is_used_verbatim(self) -> None:
        """``divergence``, like ``rsi``/``channel_upper``/etc, is a precomputed-value
        passthrough parameter -- but unlike those (always a real ``pd.Series``), ``None`` is
        itself a legitimate supplied value here (no divergence), distinct from the sentinel
        default meaning "compute it yourself" (``app.signals.divergence.current_divergence``
        would otherwise run against this fixture's own real MACD-Histogram/Stochastic/RSI,
        which -- being flat/too-short -- has no genuine divergence anyway, but this test
        confirms the *given* value is used regardless of what internal computation would have
        produced, the same contract every other passthrough parameter has)."""
        from app.signals.divergence import Divergence, DivergenceExtreme

        tide = TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising")
        wave = {"stochastic_k": 50.0, "force_index_2ema": 0.0, "state": "NO_WAVE"}
        trigger = {"fired": False, "reference": "not_applicable"}
        daily_ohlcv = _daily_ohlcv(5)
        weekly_ohlcv = _weekly_ohlcv(5)
        given_divergence = Divergence(
            indicator="rsi",
            kind="bullish",
            first=DivergenceExtreme(date=pd.Timestamp("2024-01-01"), price=10.0, indicator_value=15.0),
            second=DivergenceExtreme(date=pd.Timestamp("2024-01-31"), price=8.0, indicator_value=25.0),
            bars_apart=21,
            centerline_crossed=None,
            beyond_reference_line=True,
            aborted=False,
        )

        p_tide, p_impulse, p_wave, p_trigger = _patched_screens(tide, "BLUE", wave, trigger)
        with p_tide, p_impulse, p_wave, p_trigger:
            result = analyse(
                "TEST", daily_ohlcv, weekly_ohlcv, divergence=given_divergence
            )
        assert result.divergence == given_divergence

        # Explicit `None` (a real "no divergence" answer) must also be used verbatim, not
        # trigger the "not supplied, compute it" sentinel path.
        with p_tide, p_impulse, p_wave, p_trigger:
            result = analyse("TEST", daily_ohlcv, weekly_ohlcv, divergence=None)
        assert result.divergence is None

    def test_divergence_is_computed_internally_when_not_supplied(self) -> None:
        """Omitting `divergence` entirely computes it from this same call's own
        histogram/stochastic_k/rsi -- this fixture is far too short/flat for a genuine
        divergence (needs 20+ bars of real swing structure), so the only thing under test here
        is that *some* value (not a crash) comes back, and that it's None for this fixture --
        the real detection math itself is covered by tests/unit/signals/test_divergence.py."""
        tide = TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising")
        wave = {"stochastic_k": 50.0, "force_index_2ema": 0.0, "state": "NO_WAVE"}
        trigger = {"fired": False, "reference": "not_applicable"}
        daily_ohlcv = _daily_ohlcv(5)
        weekly_ohlcv = _weekly_ohlcv(5)

        p_tide, p_impulse, p_wave, p_trigger = _patched_screens(tide, "BLUE", wave, trigger)
        with p_tide, p_impulse, p_wave, p_trigger:
            result = analyse("TEST", daily_ohlcv, weekly_ohlcv)

        assert result.divergence is None


class TestAnalyseEndToEnd:
    """Real (unmocked) composition of analyse() -> every Screen/gate/indicator function, over
    small synthetic daily+weekly OHLCV series -- confirms the actual wiring (not just the
    decision table in isolation) produces a real BUY and a real SELL, exercising the "Wave
    showed" (not "shows") lookback case: by the day the Trigger fires, the pullback/rally has
    already ended (price has moved on), which is exactly when docs/Analyse.md §5's "shows/
    showed" language matters.
    """

    def test_end_to_end_buy_after_pullback_and_trigger(self) -> None:
        # Daily: 20 days of a gentle uptrend, then a 5-day steep selloff on elevated volume
        # (an oversold pullback -- see test_triple_screen.py's matching Screen 2 fixture),
        # then one more day rallying sharply back above the prior day's high (the Trigger).
        # By the final (trigger) day, the oscillator has already moved off its oversold
        # extreme -- this only fires BUY because of the "Wave showed" lookback, not "shows".
        closes = [100 + i * 0.5 for i in range(20)]
        closes += [closes[-1] - 3 * i for i in range(1, 6)]
        closes.append(closes[-1] + 8.0)
        volumes = [1_000_000] * 24 + [9_000_000, 3_000_000]
        daily_ohlcv = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 0.3 for c in closes],
                "low": [c - 0.3 for c in closes],
                "close": closes,
                "volume": volumes,
            }
        )
        # Weekly: 40 weeks of accelerating 5%/week growth -- BULLISH tide (matches
        # test_triple_screen.py's TestEvaluateTideEndToEnd fixture).
        weekly_closes = pd.Series([100 * (1.05**i) for i in range(40)], dtype=float)
        weekly_ohlcv = pd.DataFrame(
            {
                "open": weekly_closes,
                "high": weekly_closes * 1.01,
                "low": weekly_closes * 0.99,
                "close": weekly_closes,
                "volume": 1_000_000,
            }
        )

        result = analyse("TEST", daily_ohlcv, weekly_ohlcv)

        assert result.screens["tide"]["trend"] == "BULLISH"
        assert result.screens["impulse"] != "RED"
        assert bool(result.screens["trigger"]["fired"]) is True
        # Confirms this really is the "showed" (not "shows") case, not a fixture mistake:
        # today's own Wave state doesn't show the pullback, but showed_pullback_in_lookback
        # (what _determine_signal actually gated the BUY on) is True regardless -- this is
        # exactly the case api-stocks-analysis-wave-lookback's showed_pullback_in_lookback
        # field exists to expose, since `state` alone can't distinguish it from the
        # condition never having been met.
        assert result.screens["wave"]["state"] != "OVERSOLD_PULLBACK"
        assert result.screens["wave"]["showed_pullback_in_lookback"] is True
        assert result.screens["wave"]["showed_rally_in_lookback"] is False

        assert result.signal == "BUY"
        assert 0 <= result.confidence <= 100
        assert len(result.breakdown) == 5

    def test_malformed_latest_bar_is_excluded_and_does_not_change_signal(self) -> None:
        """Regression test for the real, observed yfinance condition (see
        drop_malformed_daily_bars's docstring and this task's `decisions` entry): the most
        recent daily bar can come back with NaN open/high/low/close and only volume populated.
        Appending such a bar on top of the BUY fixture above must not change the signal,
        must not leak NaN into `indicators`/`screens.wave`, and -- the sharper regression --
        must not silently flip `screens.trigger.fired` to False (which a NaN `today_close`
        would otherwise do via `today_close > prior_high` quietly evaluating False, not
        raising).
        """
        closes = [100 + i * 0.5 for i in range(20)]
        closes += [closes[-1] - 3 * i for i in range(1, 6)]
        closes.append(closes[-1] + 8.0)
        volumes = [1_000_000] * 24 + [9_000_000, 3_000_000]
        daily_ohlcv = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 0.3 for c in closes],
                "low": [c - 0.3 for c in closes],
                "close": closes,
                "volume": volumes,
            }
        )
        weekly_closes = pd.Series([100 * (1.05**i) for i in range(40)], dtype=float)
        weekly_ohlcv = pd.DataFrame(
            {
                "open": weekly_closes,
                "high": weekly_closes * 1.01,
                "low": weekly_closes * 0.99,
                "close": weekly_closes,
                "volume": 1_000_000,
            }
        )
        expected = analyse("TEST", daily_ohlcv, weekly_ohlcv)

        malformed_row = pd.DataFrame(
            {
                "open": [float("nan")],
                "high": [float("nan")],
                "low": [float("nan")],
                "close": [float("nan")],
                "volume": [500_000],
            }
        )
        daily_with_malformed_latest_bar = pd.concat(
            [daily_ohlcv, malformed_row], ignore_index=True
        )

        result = analyse("TEST", daily_with_malformed_latest_bar, weekly_ohlcv)

        assert result.signal == expected.signal == "BUY"
        assert result.screens["trigger"] == expected.screens["trigger"]
        assert bool(result.screens["trigger"]["fired"]) is True
        assert result.screens == expected.screens
        # NaN-tolerant: this fixture is far shorter than the Autoenvelope channel's ~100-bar
        # deviation-average warm-up window, so channel_upper/channel_lower are NaN in both
        # `result` and `expected` -- still equal to each other (the malformed bar changes
        # neither), just not via plain `==` (NaN != NaN).
        assert _nan_tolerant_equal(result.indicators, expected.indicators)
        assert not any(
            pd.isna(v)
            for key, v in result.indicators.items()
            if key not in ("channel_upper", "channel_lower")
        )
        assert result.confidence == expected.confidence

    def test_end_to_end_sell_after_rally_and_trigger(self) -> None:
        # Mirror image: gentle downtrend, then a 5-day steep rebound rally on elevated
        # volume, then one more day selling off sharply back below the prior day's low.
        closes = [100 - i * 0.5 for i in range(20)]
        closes += [closes[-1] + 3 * i for i in range(1, 6)]
        closes.append(closes[-1] - 8.0)
        volumes = [1_000_000] * 24 + [9_000_000, 3_000_000]
        daily_ohlcv = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 0.3 for c in closes],
                "low": [c - 0.3 for c in closes],
                "close": closes,
                "volume": volumes,
            }
        )
        weekly_closes = pd.Series([1000 * (0.9**i) for i in range(40)], dtype=float)
        weekly_ohlcv = pd.DataFrame(
            {
                "open": weekly_closes,
                "high": weekly_closes * 1.01,
                "low": weekly_closes * 0.99,
                "close": weekly_closes,
                "volume": 1_000_000,
            }
        )

        result = analyse("TEST", daily_ohlcv, weekly_ohlcv)

        assert result.screens["tide"]["trend"] == "BEARISH"
        assert result.screens["impulse"] != "GREEN"
        assert bool(result.screens["trigger"]["fired"]) is True
        # Mirror image of the BUY case above: today's Wave state doesn't show the rally,
        # but showed_rally_in_lookback (what gated the SELL) is True regardless.
        assert result.screens["wave"]["state"] != "OVERBOUGHT_RALLY"
        assert result.screens["wave"]["showed_rally_in_lookback"] is True
        assert result.screens["wave"]["showed_pullback_in_lookback"] is False

        assert result.signal == "SELL"
        assert 0 <= result.confidence <= 100
        assert len(result.breakdown) == 5

    def test_end_to_end_hold_on_flat_history(self) -> None:
        daily_ohlcv = pd.DataFrame(
            {
                "open": [100.0] * 30,
                "high": [101.0] * 30,
                "low": [99.0] * 30,
                "close": [100.0] * 30,
                "volume": [1_000_000] * 30,
            }
        )
        weekly_ohlcv = pd.DataFrame(
            {
                "open": [100.0] * 10,
                "high": [101.0] * 10,
                "low": [99.0] * 10,
                "close": [100.0] * 10,
                "volume": [1_000_000] * 10,
            }
        )

        result = analyse("TEST", daily_ohlcv, weekly_ohlcv)

        assert result.signal == "HOLD"
        assert result.screens["tide"]["trend"] == "NEUTRAL"
        # Neutral tide: Wave is never evaluated against a direction, so both lookback
        # fields are null (not False) -- see WaveScreen.showed_pullback_in_lookback's
        # docstring in backend/app/api/schemas.py for why null rather than False here.
        assert result.screens["wave"]["showed_pullback_in_lookback"] is None
        assert result.screens["wave"]["showed_rally_in_lookback"] is None
        assert result.confidence == 0
        assert result.confidence_band == "Low"
        assert result.breakdown == []

    def test_end_to_end_empty_history_degrades_to_hold_without_raising(self) -> None:
        daily_ohlcv = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        weekly_ohlcv = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        result = analyse("TEST", daily_ohlcv, weekly_ohlcv)

        assert result.signal == "HOLD"
        assert result.confidence == 0
        assert result.breakdown == []
        assert result.screens["tide"] == {"trend": "NEUTRAL", "weekly_macd_histogram_slope": "flat"}
        assert result.screens["impulse"] == "BLUE"
        assert result.screens["trigger"] == {"fired": False, "reference": "not_applicable"}
        assert all(pd.isna(v) for v in result.indicators.values())


class TestConfidenceComponentPassthrough:
    """A focused check that compute_confidence()'s ConfidenceComponent objects (not just
    plain dicts/floats) are what analyse() returns in `breakdown`, matching
    docs/architecture/API.md's confidence_breakdown shape (component/weight/score).
    """

    def test_breakdown_entries_are_confidence_components_with_expected_weights(self) -> None:
        p_tide, p_impulse, p_wave, p_trigger = _patched_screens(
            TideResult(trend="BULLISH", weekly_macd_histogram_slope="rising"),
            "GREEN",
            {"stochastic_k": 20.0, "force_index_2ema": -100.0, "state": "OVERSOLD_PULLBACK"},
            {"fired": True, "reference": "close_above_prior_high"},
        )
        with p_tide, p_impulse, p_wave, p_trigger:
            result = analyse("TEST", _daily_ohlcv(10), _weekly_ohlcv(10))

        assert all(isinstance(c, ConfidenceComponent) for c in result.breakdown)
        weights = {c.component: c.weight for c in result.breakdown}
        assert weights == {
            "tide_alignment": 0.30,
            "impulse_gate": 0.20,
            "oscillator_extremity": 0.25,
            "elder_ray_confirmation": 0.15,
            "volume_confirmation": 0.10,
        }
        # tide_alignment and impulse_gate are both fully agreeing with the BUY signal here.
        scores = {c.component: c.score for c in result.breakdown}
        assert scores["tide_alignment"] == 1.0
        assert scores["impulse_gate"] == 1.0


def _dated_buy_daily_ohlcv() -> pd.DataFrame:
    # Same series as TestAnalyseEndToEnd.test_end_to_end_buy_after_pullback_and_trigger, but
    # with a real DatetimeIndex -- analyse_history() reads dates off the index positionally.
    closes = [100 + i * 0.5 for i in range(20)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
    volumes = [1_000_000] * 24 + [9_000_000, 3_000_000]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


def _dated_buy_weekly_ohlcv() -> pd.DataFrame:
    # A plain list, not a pd.Series -- a Series column carries its own (default RangeIndex)
    # index, which pandas would otherwise reindex against the DataFrame's explicit
    # DatetimeIndex below, silently turning every value NaN (same pitfall documented in
    # tests/integration/test_stocks_analysis.py's _buy_weekly_ohlcv).
    weekly_closes = [100 * (1.05**i) for i in range(40)]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=40, freq="W", name="date"),
    )


class TestAnalyseHistory:
    """Tests for analyse_history() (docs/tasks/api-stocks-indicator-history.json)."""

    def test_last_point_matches_a_full_history_analyse_call(self) -> None:
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()
        expected = analyse("TEST", daily_ohlcv, weekly_ohlcv)

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        assert len(history) == len(daily_ohlcv)
        last_date, last_result = history[-1]
        assert last_date == daily_ohlcv.index[-1]
        assert last_result.signal == expected.signal == "BUY"
        assert last_result.confidence == expected.confidence
        # NaN-tolerant -- see test_malformed_latest_bar_is_excluded_and_does_not_change_signal's
        # comment: this fixture is shorter than the Autoenvelope channel's ~100-bar warm-up.
        assert _nan_tolerant_equal(last_result.indicators, expected.indicators)
        assert last_result.screens == expected.screens
        assert last_result.divergence == expected.divergence

    def test_dates_are_oldest_first_and_one_per_bar(self) -> None:
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        dates = [bar_date for bar_date, _ in history]
        assert dates == list(daily_ohlcv.index)

    def test_malformed_bar_mid_history_is_dropped_from_history_entirely(self) -> None:
        """Regression test for a currently-dormant behavior change from PR #121's
        precompute-and-slice refactor (docs/tasks/api-stocks-indicator-history-followups-
        followups.json, `analyse_history`'s own docstring): a malformed bar *mid*-history
        (not just the trailing bar -- see ``TestAnalyseEndToEnd
        .test_malformed_latest_bar_is_excluded_and_does_not_change_signal`` for that case) is
        now omitted from the returned history entirely, since `analyse_history` cleans
        `daily_ohlcv` once up front via `drop_malformed_daily_bars` before ever slicing it.

        Confirmed against git history (the pre-PR-#121 implementation, which never cleaned
        `daily_ohlcv` at the top of this function at all -- only `analyse()`'s own per-slice
        clean ran): that version still emitted an entry for the malformed bar's own date, with
        a `SignalResult` identical to the prior clean bar's (the malformed row fell out of
        that bar's own truncated slice inside `analyse()`, leaving a slice identical to the
        prior bar's own call) -- one entry per original row, `len(daily_ohlcv)` total. This
        test only asserts the current (post-PR-#121) behavior -- one fewer entry, with the
        malformed date entirely absent -- not the historical duplicate-entry behavior, which
        no longer exists to test against directly.
        """
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()
        malformed_date = daily_ohlcv.index[10]
        daily_with_malformed_middle_bar = daily_ohlcv.copy()
        daily_with_malformed_middle_bar.loc[
            malformed_date, ["open", "high", "low", "close"]
        ] = float("nan")

        history = analyse_history("TEST", daily_with_malformed_middle_bar, weekly_ohlcv)

        assert len(history) == len(daily_ohlcv) - 1
        dates = [bar_date for bar_date, _ in history]
        assert malformed_date not in dates
        assert dates == [d for d in daily_ohlcv.index if d != malformed_date]

    def test_from_index_skips_bars_but_keeps_full_warm_up_context(self) -> None:
        """A later bar's indicators must be identical whether computed via a full-history loop
        or via a `from_index`-trimmed one starting at that same bar -- `from_index` only
        controls which entries are *emitted*, not how much history feeds the computation of
        each one (unlike naively pre-trimming daily_ohlcv itself, which would degrade the
        indicators of early emitted bars)."""
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()
        full_history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        trimmed_history = analyse_history(
            "TEST", daily_ohlcv, weekly_ohlcv, from_index=len(daily_ohlcv) - 3
        )

        assert len(trimmed_history) == 3
        # NaN-tolerant -- see _nan_tolerant_equal's docstring: this fixture is shorter than the
        # Autoenvelope channel's ~100-bar warm-up, so channel_upper/channel_lower are NaN here.
        assert _nan_tolerant_equal(trimmed_history, full_history[-3:])

    def test_negative_from_index_behaves_like_zero(self) -> None:
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv, from_index=-5)

        assert len(history) == len(daily_ohlcv)

    def test_from_index_past_the_end_returns_empty_list(self) -> None:
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        history = analyse_history(
            "TEST", daily_ohlcv, weekly_ohlcv, from_index=len(daily_ohlcv)
        )

        assert history == []

    def test_empty_daily_ohlcv_returns_empty_list_without_raising(self) -> None:
        daily_ohlcv = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        assert history == []

    def test_tide_constant_when_all_weekly_data_precedes_daily_range(self) -> None:
        """Screen 1 (Tide) IS point-in-time recomputed per bar (see
        ``TestAnalyseHistoryTideLookAhead`` below) -- but in this particular fixture every
        weekly bar in ``_dated_buy_weekly_ohlcv()`` (2025 dates) already precedes every daily
        bar in ``_dated_buy_daily_ohlcv()`` (2026 dates), so each bar's as-of-that-week weekly
        truncation includes the *entire* weekly series regardless of which daily bar it's
        computed for -- the constant BULLISH tide here is a property of this fixture's dates,
        not evidence Tide is held fixed in general."""
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        tides = {result.screens["tide"]["trend"] for _, result in history if len(result.screens) > 0}
        assert tides == {"BULLISH"}

    def test_daily_cadence_fields_vary_across_the_series(self) -> None:
        """Contrast with the tide-is-constant test above: indicators that only depend on the
        (growing) daily window must actually change bar to bar, confirming this isn't
        accidentally replaying one fixed result for every date."""
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        ema_13_values = {result.indicators["ema_13"] for _, result in history}
        assert len(ema_13_values) > 1


class TestAnalyseHistoryPerformance:
    """Regression coverage for the O(range_size x history_length) -> O(history_length) fix
    (docs/tasks/api-stocks-indicator-history-followups.json's `decisions` entry): every daily
    EMA(13)/EMA(26)/MACD-Histogram/Stochastic/Force-Index computation, plus every weekly
    EMA(13)/EMA(26)/MACD-Histogram computation feeding Screen 1 (Tide), must happen exactly once
    per ``analyse_history()`` call -- not once per emitted bar -- regardless of how many bars
    are in range. Uses ``wraps=`` (not a stub ``return_value``) so the real indicator math
    still runs and every other test's correctness assertions (e.g. ``TestAnalyseHistory``'s
    "last point matches /analysis") keep meaning something -- this class only adds a call-count
    assertion on top.
    """

    def test_daily_and_weekly_ema_and_macd_computed_once_regardless_of_bar_count(self) -> None:
        import app.signals.engine as engine_module

        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        with (
            patch("app.signals.engine.ema", wraps=engine_module.ema) as mock_ema,
            patch(
                "app.signals.engine.macd_components", wraps=engine_module.macd_components
            ) as mock_macd,
        ):
            history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        assert len(history) == len(daily_ohlcv)
        # Daily ema_13 + ema_26 + weekly ema_13, precomputed once each over their respective
        # full series -- not once per bar.
        assert mock_ema.call_count == 3
        # Daily MACD-Histogram + weekly MACD-Histogram, precomputed once each -- not once per
        # bar.
        assert mock_macd.call_count == 2

    def test_stochastic_and_force_index_computed_once_regardless_of_bar_or_lookback_count(
        self,
    ) -> None:
        import app.signals.triple_screen as triple_screen_module

        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        with (
            patch(
                "app.signals.engine.stochastic_oscillator",
                wraps=triple_screen_module.stochastic_oscillator,
            ) as mock_stochastic,
            patch(
                "app.signals.engine.force_index", wraps=triple_screen_module.force_index
            ) as mock_force_index,
            patch(
                "app.signals.triple_screen.stochastic_oscillator"
            ) as mock_stochastic_inside_wave,
            patch("app.signals.triple_screen.force_index") as mock_force_index_inside_wave,
        ):
            history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        assert len(history) == len(daily_ohlcv)
        # Precomputed exactly once each in analyse_history() itself...
        assert mock_stochastic.call_count == 1
        assert mock_force_index.call_count == 1
        # ...and, since every evaluate_wave call (the "shows" call plus every "showed"
        # lookback call, across every bar) is always given the precomputed slice, neither
        # evaluate_wave nor _wave_lookback ever falls back to recomputing internally.
        mock_stochastic_inside_wave.assert_not_called()
        mock_force_index_inside_wave.assert_not_called()

    def test_evaluate_tide_never_recomputes_weekly_ema_macd_internally(self) -> None:
        """Mirrors the Stochastic/Force-Index test above, for Screen 1's weekly side: since
        every ``analyse()`` call is given a precomputed, per-bar-sliced ``weekly_ema_13``/
        ``weekly_ema_26``/``weekly_histogram``, ``evaluate_tide`` itself should never fall back
        to its own internal ``ema``/``macd_components`` calls."""
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        with (
            patch("app.signals.triple_screen.ema") as mock_ema_inside_tide,
            patch("app.signals.triple_screen.macd_components") as mock_macd_inside_tide,
        ):
            history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        assert len(history) == len(daily_ohlcv)
        mock_ema_inside_tide.assert_not_called()
        mock_macd_inside_tide.assert_not_called()

    def test_skips_weekly_precompute_entirely_when_weekly_ohlcv_too_short(self) -> None:
        """A <2-row weekly_ohlcv can never produce anything for evaluate_tide to use (its own
        guard clause returns NEUTRAL before touching any precomputed series) -- there is
        nothing to precompute, and this function must not spend the (small but real) cost of
        computing a weekly EMA/MACD nobody will ever read, nor raise on the resulting
        insufficient-history frame."""
        import app.signals.engine as engine_module

        daily_ohlcv = _dated_buy_daily_ohlcv()
        # 1 row -- below evaluate_tide's own 2-row minimum -- while still keeping a real
        # DatetimeIndex (_weekly_through_bar_date requires one to compare against bar dates).
        weekly_ohlcv = _dated_buy_weekly_ohlcv().iloc[:1]

        with patch("app.signals.engine.ema", wraps=engine_module.ema) as mock_ema:
            history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        assert len(history) == len(daily_ohlcv)
        # ema() is still called twice for the daily side (ema_13/ema_26) -- but never for the
        # weekly side, since there was nothing worth precomputing.
        assert mock_ema.call_count == 2
        tides = {result.screens["tide"]["trend"] for _, result in history}
        assert tides == {"NEUTRAL"}

    def test_matches_independently_computed_analyse_for_every_bar(self) -> None:
        """The precompute-and-slice optimization must not change a single emitted value --
        cross-checks every bar (not just the last one, already covered by
        ``test_last_point_matches_a_full_history_analyse_call``) against an independent
        ``analyse()`` call on that exact same (per-bar) truncated daily/weekly window."""
        daily_ohlcv = _dated_buy_daily_ohlcv()
        weekly_ohlcv = _dated_buy_weekly_ohlcv()

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        for i, (bar_date, result) in enumerate(history):
            expected = analyse(
                "TEST",
                daily_ohlcv.iloc[: i + 1],
                _weekly_through_bar_date(weekly_ohlcv, daily_ohlcv.index[i]),
            )
            assert bar_date == daily_ohlcv.index[i]
            assert result.signal == expected.signal
            assert result.confidence == expected.confidence
            assert _nan_tolerant_equal(result.indicators, expected.indicators)
            assert _nan_tolerant_equal(result.screens, expected.screens)


def _flipping_tide_weekly_ohlcv(n_weeks: int = 31) -> pd.DataFrame:
    """Weekly closes that rise 5%/week for the first 20 weeks (a real BULLISH tide, per
    ``evaluate_tide``) then fall 10%/week for the rest -- by week ``n_weeks=31`` this produces
    a BEARISH tide when evaluated against the *full* series (confirmed via
    ``test_tide_recomputed_as_of_each_bar_date_not_held_at_todays_value`` below), while the
    first ~20 weeks were genuinely BULLISH at the time. Used to catch Screen 1 look-ahead
    bias: a historical bar within the first 20 weeks must reflect the BULLISH tide that
    actually held then, not the BEARISH tide the full (today's) series later reaches."""
    closes = []
    close = 100.0
    for week in range(n_weeks):
        close *= 1.05 if week < 20 else 0.90
        closes.append(close)
    index = pd.date_range("2025-01-03", periods=n_weeks, freq="W-FRI", name="date")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": 1_000_000,
        },
        index=index,
    )


def _flat_daily_ohlcv_spanning(weekly_ohlcv: pd.DataFrame) -> pd.DataFrame:
    """One daily bar per calendar day spanning ``weekly_ohlcv``'s full date range (inclusive),
    with a flat/placeholder price -- only the dates matter for the look-ahead tests below,
    which read Screen 1 (Tide) off each bar and don't otherwise depend on daily price action."""
    index = pd.date_range(weekly_ohlcv.index[0], weekly_ohlcv.index[-1], freq="D", name="date")
    close = [100.0] * len(index)
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 0.3 for c in close],
            "low": [c - 0.3 for c in close],
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )


class TestAnalyseHistoryTideLookAhead:
    """Regression coverage for the Screen 1 (Tide) look-ahead bias fix (this task's `review`
    finding on docs/tasks/api-stocks-indicator-history.json): ``analyse_history`` must gate
    each historical point against the Tide *as of that bar's own date*, not against whatever
    Tide the full (today's) weekly series currently shows -- see
    ``app.signals.engine._weekly_through_bar_date``.
    """

    def test_tide_recomputed_as_of_each_bar_date_not_held_at_todays_value(self) -> None:
        weekly_ohlcv = _flipping_tide_weekly_ohlcv()
        daily_ohlcv = _flat_daily_ohlcv_spanning(weekly_ohlcv)

        todays_tide = evaluate_tide(weekly_ohlcv).trend
        assert todays_tide == "BEARISH"  # sanity check on the fixture itself

        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)
        tides_by_date = {bar_date: result.screens["tide"]["trend"] for bar_date, result in history}

        # An early bar, well within the 20-week bullish run, must reflect the tide that
        # actually held then -- not today's (since-flipped) BEARISH tide.
        early_bar_date = weekly_ohlcv.index[4]  # the Friday of week 5, still in the rising run
        assert tides_by_date[early_bar_date] == "BULLISH"
        assert tides_by_date[early_bar_date] != todays_tide

    def test_last_point_still_matches_todays_full_series_tide(self) -> None:
        """The fix must not break the pre-existing "last point matches /analysis" invariant --
        see this task's `decisions` entry for why truncating by the calendar week containing
        each bar's date (rather than by the date directly) is what makes this hold."""
        weekly_ohlcv = _flipping_tide_weekly_ohlcv()
        daily_ohlcv = _flat_daily_ohlcv_spanning(weekly_ohlcv)

        expected = analyse("TEST", daily_ohlcv, weekly_ohlcv)
        history = analyse_history("TEST", daily_ohlcv, weekly_ohlcv)

        last_date, last_result = history[-1]
        assert last_date == daily_ohlcv.index[-1]
        assert last_result.screens["tide"] == expected.screens["tide"]

    def test_earlier_bar_sees_fewer_weekly_bars_than_a_later_bar(self) -> None:
        """Direct check on the truncation helper itself: an earlier daily bar's as-of weekly
        window has fewer rows than a later one's, and the latest bar's window is the full
        weekly series -- confirming the truncation is actually happening (not a no-op) while
        still preserving the last-point invariant."""
        weekly_ohlcv = _flipping_tide_weekly_ohlcv()
        daily_ohlcv = _flat_daily_ohlcv_spanning(weekly_ohlcv)

        early_window = _weekly_through_bar_date(weekly_ohlcv, daily_ohlcv.index[10])
        late_window = _weekly_through_bar_date(weekly_ohlcv, daily_ohlcv.index[-1])

        assert len(early_window) < len(late_window)
        assert len(late_window) == len(weekly_ohlcv)
        pd.testing.assert_frame_equal(late_window, weekly_ohlcv)
