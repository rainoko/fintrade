"""Reference-value tests for app.indicators.elder_ray (docs/Analyse.md §4:
Bull Power = High - EMA(13), Bear Power = Low - EMA(13)).

Elder-Ray reuses the caller-supplied EMA(13) of the close price (see
app.indicators.ema.ema) rather than computing its own EMA -- the same trend
EMA used elsewhere for the tide/impulse gate (docs/tasks/indicator-ema.json).
"""

import pandas as pd
import pytest

from app.indicators.elder_ray import bear_power, bull_power
from app.indicators.ema import ema


class TestBullPower:
    def test_reference_values(self) -> None:
        """Simple hand-computed subtraction against a fixed, arbitrary
        EMA(13) input series (Elder-Ray does no smoothing of its own, so the
        formula is exactly elementwise high - ema_13):

        high   = [105, 107, 103, 110, 108]
        ema_13 = [100, 100.5, 101, 102, 103]
        bull   = [5, 6.5, 2, 8, 5]
        """
        high = pd.Series([105, 107, 103, 110, 108], dtype=float)
        ema_13 = pd.Series([100, 100.5, 101, 102, 103], dtype=float)

        result = bull_power(high, ema_13)

        assert result.iloc[0] == pytest.approx(5.0)
        assert result.iloc[1] == pytest.approx(6.5)
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[3] == pytest.approx(8.0)
        assert result.iloc[4] == pytest.approx(5.0)

    def test_reference_values_against_real_ema_13(self) -> None:
        """Integration with the real EMA(13) (period=3 here for a hand-
        verifiable warm-up window, k = 2/(3+1) = 0.5):

        closes = [10, 12, 15, 14, 13]
        ema_3  = [10, 11.0, 13.0, 13.5, 13.25]   (see test_ema.py for the
                                                   identical hand-computation)
        high   = [10.5, 12.5, 15.5, 14.5, 13.5]
        bull   = high - ema_3
               = [0.5, 1.5, 2.5, 1.0, 0.25]
        """
        closes = pd.Series([10, 12, 15, 14, 13], dtype=float)
        high = closes + 0.5
        ema_3 = ema(closes, period=3)

        result = bull_power(high, ema_3)

        assert result.iloc[0] == pytest.approx(0.5)
        assert result.iloc[1] == pytest.approx(1.5)
        assert result.iloc[2] == pytest.approx(2.5)
        assert result.iloc[3] == pytest.approx(1.0)
        assert result.iloc[4] == pytest.approx(0.25)

    def test_rejects_index_misalignment_even_with_equal_length(self) -> None:
        """high and ema_13 with the same length but offset index labels must
        raise rather than silently combine via pandas' label-based alignment
        (high - ema_13 would otherwise shift one series relative to the
        other and produce a wrong result with no error)."""
        high = pd.Series([105, 107, 103], dtype=float)
        offset_ema = pd.Series([100, 100.5, 101], dtype=float)
        offset_ema.index = offset_ema.index + 1

        with pytest.raises(ValueError):
            bull_power(high, offset_ema)


class TestBearPower:
    def test_reference_values(self) -> None:
        """Simple hand-computed subtraction against a fixed, arbitrary
        EMA(13) input series:

        low    = [95, 96, 91, 100, 99]
        ema_13 = [100, 100.5, 101, 102, 103]
        bear   = [-5, -4.5, -10, -2, -4]
        """
        low = pd.Series([95, 96, 91, 100, 99], dtype=float)
        ema_13 = pd.Series([100, 100.5, 101, 102, 103], dtype=float)

        result = bear_power(low, ema_13)

        assert result.iloc[0] == pytest.approx(-5.0)
        assert result.iloc[1] == pytest.approx(-4.5)
        assert result.iloc[2] == pytest.approx(-10.0)
        assert result.iloc[3] == pytest.approx(-2.0)
        assert result.iloc[4] == pytest.approx(-4.0)

    def test_reference_values_against_real_ema_13(self) -> None:
        """Integration with the real EMA(13) (period=3, same fixture as the
        bull_power integration test):

        closes = [10, 12, 15, 14, 13]
        ema_3  = [10, 11.0, 13.0, 13.5, 13.25]
        low    = [9.5, 11.5, 14.5, 13.5, 12.5]
        bear   = low - ema_3
               = [-0.5, 0.5, 1.5, 0.0, -0.75]
        """
        closes = pd.Series([10, 12, 15, 14, 13], dtype=float)
        low = closes - 0.5
        ema_3 = ema(closes, period=3)

        result = bear_power(low, ema_3)

        assert result.iloc[0] == pytest.approx(-0.5)
        assert result.iloc[1] == pytest.approx(0.5)
        assert result.iloc[2] == pytest.approx(1.5)
        assert result.iloc[3] == pytest.approx(0.0)
        assert result.iloc[4] == pytest.approx(-0.75)

    def test_rejects_index_misalignment_even_with_equal_length(self) -> None:
        """low and ema_13 with the same length but offset index labels must
        raise rather than silently combine via pandas' label-based
        alignment."""
        low = pd.Series([95, 96, 91], dtype=float)
        offset_ema = pd.Series([100, 100.5, 101], dtype=float)
        offset_ema.index = offset_ema.index + 1

        with pytest.raises(ValueError):
            bear_power(low, offset_ema)
