"""Tests for app.signals.triple_screen.evaluate_trigger (docs/Analyse.md §2, Screen 3).

Covers both tide directions (bullish: close > prior day's high; bearish: close < prior
day's low), the fired=True/False outcome for each, and the NEUTRAL-tide /
insufficient-data fallback that returns {"fired": False, "reference": "not_applicable"}
rather than forcing a guess -- matching docs/architecture/API.md's exact
``screens.trigger`` shape (``fired``/``reference``).
"""

import pandas as pd

from app.signals.triple_screen import evaluate_trigger


def _daily_ohlcv(highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
    """Minimal daily OHLCV frame -- evaluate_trigger only reads high/low/close."""
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": 1_000_000,
        }
    )


class TestBullishTrigger:
    def test_fires_when_close_crosses_above_prior_high(self) -> None:
        # Prior day: high=101. Today: close=101.5 > prior high.
        daily_ohlcv = _daily_ohlcv(highs=[101.0, 102.0], lows=[99.0, 100.5], closes=[100.5, 101.5])

        result = evaluate_trigger(daily_ohlcv, "BULLISH")

        assert result == {"fired": True, "reference": "close_above_prior_high"}

    def test_does_not_fire_when_close_at_or_below_prior_high(self) -> None:
        # Prior day: high=101. Today: close=101.0, exactly at the prior high (not "above").
        daily_ohlcv = _daily_ohlcv(highs=[101.0, 101.2], lows=[99.0, 100.0], closes=[100.5, 101.0])

        result = evaluate_trigger(daily_ohlcv, "BULLISH")

        assert result == {"fired": False, "reference": "close_above_prior_high"}


class TestBearishTrigger:
    def test_fires_when_close_crosses_below_prior_low(self) -> None:
        # Prior day: low=99. Today: close=98.5 < prior low.
        daily_ohlcv = _daily_ohlcv(highs=[101.0, 99.5], lows=[99.0, 98.0], closes=[100.5, 98.5])

        result = evaluate_trigger(daily_ohlcv, "BEARISH")

        assert result == {"fired": True, "reference": "close_below_prior_low"}

    def test_does_not_fire_when_close_at_or_above_prior_low(self) -> None:
        # Prior day: low=99. Today: close=99.0, exactly at the prior low (not "below").
        daily_ohlcv = _daily_ohlcv(highs=[101.0, 100.0], lows=[99.0, 98.5], closes=[100.5, 99.0])

        result = evaluate_trigger(daily_ohlcv, "BEARISH")

        assert result == {"fired": False, "reference": "close_below_prior_low"}


class TestNeutralTideAndInsufficientData:
    def test_neutral_tide_never_fires_regardless_of_price_action(self) -> None:
        # Price action that would fire a bullish trigger, but the tide is NEUTRAL.
        daily_ohlcv = _daily_ohlcv(highs=[101.0, 102.0], lows=[99.0, 100.5], closes=[100.5, 101.5])

        result = evaluate_trigger(daily_ohlcv, "NEUTRAL")

        assert result == {"fired": False, "reference": "not_applicable"}

    def test_empty_frame_is_not_applicable_without_indexing_error(self) -> None:
        daily_ohlcv = _daily_ohlcv(highs=[], lows=[], closes=[])

        result = evaluate_trigger(daily_ohlcv, "BULLISH")

        assert result == {"fired": False, "reference": "not_applicable"}

    def test_single_row_frame_is_not_applicable_no_prior_bar(self) -> None:
        daily_ohlcv = _daily_ohlcv(highs=[101.0], lows=[99.0], closes=[100.5])

        result = evaluate_trigger(daily_ohlcv, "BEARISH")

        assert result == {"fired": False, "reference": "not_applicable"}
