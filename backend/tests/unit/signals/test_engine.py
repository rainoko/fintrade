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

from unittest.mock import patch

import pandas as pd
import pytest

from app.signals.confidence import ConfidenceComponent
from app.signals.engine import _determine_signal, _wave_lookback, analyse, drop_malformed_daily_bars
from app.signals.triple_screen import TideResult


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

        def side_effect(df: pd.DataFrame, tide: str) -> dict:
            state = "OVERSOLD_PULLBACK" if len(df) == 10 else "NO_WAVE"
            return {"stochastic_k": 0.0, "force_index_2ema": 0.0, "state": state}

        with patch("app.signals.engine.evaluate_wave", side_effect=side_effect) as mock_wave:
            wave, showed_pullback, showed_rally = _wave_lookback(daily_ohlcv, "BULLISH")

        assert wave["state"] == "OVERSOLD_PULLBACK"
        assert showed_pullback is True
        assert showed_rally is False
        # Matched on the first (today's) call -- no further evaluate_wave calls needed.
        mock_wave.assert_called_once_with(daily_ohlcv, "BULLISH")

    def test_matches_within_lookback_window_but_not_on_todays_bar(self) -> None:
        daily_ohlcv = _daily_ohlcv(10)

        def side_effect(df: pd.DataFrame, tide: str) -> dict:
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

        def side_effect(df: pd.DataFrame, tide: str) -> dict:
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
        mock_wave.assert_called_once_with(daily_ohlcv, "BULLISH")

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
        mock_wave.assert_called_once_with(daily_ohlcv, "NEUTRAL")

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
            "wave": wave,
            "trigger": trigger,
        }
        assert set(result.indicators) == {"ema_13", "ema_26", "macd_histogram", "bull_power", "bear_power"}
        assert all(isinstance(v, float) for v in result.indicators.values())


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
        # Confirms this really is the "showed" (not "shows") case, not a fixture mistake.
        assert result.screens["wave"]["state"] != "OVERSOLD_PULLBACK"

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
        assert result.indicators == expected.indicators
        assert not any(pd.isna(v) for v in result.indicators.values())
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
        assert result.screens["wave"]["state"] != "OVERBOUGHT_RALLY"

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
