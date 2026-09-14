"""Reference-value tests for app.indicators.stochastic (docs/Analyse.md §4:
Stochastic Oscillator %K 5, %D 3, smoothing 3 -- SMA-based, not EMA-based
like the rest of this app's indicators).

Formula under test (the "slow" Stochastic construction):
    fast_k_t = 100 * (close_t - LL_k) / (HH_k - LL_k)   (LL/HH = rolling
                                                            min/max of low/high
                                                            over k_period bars)
    k_t      = SMA(fast_k, smooth)
    d_t      = SMA(k, d_period)

Fixture (10 bars, 1-indexed day numbers in the comments below):

    day  1   2   3   4   5   6   7   8   9  10
    H   10  11  12  11  10   9  10  11  12  13
    L    8   9  10   9   8   7   8   9  10  11
    C    9  10  11  10   9   8   9  10  11  12

Reference values were hand-computed independently of the implementation
(rolling 5-bar HH/LL, then two more layers of plain 3-bar SMA), using
0-indexed positions to match pandas' default RangeIndex:

    fast_k (index 4, day5): window = days1-5, HH=12, LL=8
        100*(9-8)/(12-8)  = 25.0
    fast_k (index 5, day6): window = days2-6, HH=12, LL=7
        100*(8-7)/(12-7)  = 20.0
    fast_k (index 6, day7): window = days3-7, HH=12, LL=7
        100*(9-7)/(12-7)  = 40.0
    fast_k (index 7, day8): window = days4-8, HH=11, LL=7
        100*(10-7)/(11-7) = 75.0
    fast_k (index 8, day9): window = days5-9, HH=12, LL=7
        100*(11-7)/(12-7) = 80.0
    fast_k (index 9, day10): window = days6-10, HH=13, LL=7
        100*(12-7)/(13-7) = 83.33333333333333

    k (index 6, day7)  = mean(fast_k[4:7])  = (25+20+40)/3        = 28.333333333333332
    k (index 7, day8)  = mean(fast_k[5:8])  = (20+40+75)/3        = 45.0
    k (index 8, day9)  = mean(fast_k[6:9])  = (40+75+80)/3        = 65.0
    k (index 9, day10) = mean(fast_k[7:10]) = (75+80+83.3333)/3   = 79.44444444444444

    d (index 8, day9)  = mean(k[6:9]) = (28.333333+45.0+65.0)/3   = 46.111111111111114
    d (index 9, day10) = mean(k[7:10]) = (45.0+65.0+79.44444)/3   = 63.148148148148145
"""

import pandas as pd
import pytest

from app.indicators.stochastic import stochastic_oscillator


HIGH = pd.Series([10, 11, 12, 11, 10, 9, 10, 11, 12, 13], dtype=float)
LOW = pd.Series([8, 9, 10, 9, 8, 7, 8, 9, 10, 11], dtype=float)
CLOSE = pd.Series([9, 10, 11, 10, 9, 8, 9, 10, 11, 12], dtype=float)


class TestStochasticOscillator:
    def test_returns_dataframe_with_k_and_d_columns(self) -> None:
        result = stochastic_oscillator(HIGH, LOW, CLOSE)

        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["k", "d"]
        assert len(result) == len(CLOSE)

    def test_warmup_period_is_nan(self) -> None:
        """%K needs k_period + smooth - 1 = 7 bars, %D needs a further
        d_period - 1 = 2 bars on top of that (9 bars total) before either
        column has its first real value."""
        result = stochastic_oscillator(HIGH, LOW, CLOSE)

        assert result["k"].iloc[:6].isna().all()
        assert result["d"].iloc[:8].isna().all()

    def test_reference_values_k(self) -> None:
        result = stochastic_oscillator(HIGH, LOW, CLOSE)

        assert result["k"].iloc[6] == pytest.approx(28.333333333333332)
        assert result["k"].iloc[7] == pytest.approx(45.0)
        assert result["k"].iloc[8] == pytest.approx(65.0)
        assert result["k"].iloc[9] == pytest.approx(79.44444444444444)

    def test_reference_values_d(self) -> None:
        result = stochastic_oscillator(HIGH, LOW, CLOSE)

        assert result["d"].iloc[8] == pytest.approx(46.111111111111114)
        assert result["d"].iloc[9] == pytest.approx(63.148148148148145)

    def test_flat_range_yields_nan_not_zero_division_error(self) -> None:
        """HH == LL over the window (a perfectly flat market) makes fast %K
        a 0/0 division; it must come out as NaN, not raise or silently
        produce 0/inf."""
        flat_high = pd.Series([10.0] * 6)
        flat_low = pd.Series([10.0] * 6)
        flat_close = pd.Series([10.0] * 6)

        result = stochastic_oscillator(
            flat_high, flat_low, flat_close, k_period=5, d_period=3, smooth=1
        )

        assert pd.isna(result["k"].iloc[4])

    def test_rejects_mismatched_index(self) -> None:
        offset_low = LOW.copy()
        offset_low.index = offset_low.index + 1

        with pytest.raises(ValueError):
            stochastic_oscillator(HIGH, offset_low, CLOSE)

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            stochastic_oscillator(HIGH, LOW, CLOSE, k_period=0)

    def test_rejects_non_integer_period(self) -> None:
        with pytest.raises(TypeError):
            stochastic_oscillator(HIGH, LOW, CLOSE, smooth=3.5)

    def test_rejects_bool_period(self) -> None:
        """bool is a subclass of int in Python; d_period=True must not be
        silently accepted as d_period=1."""
        with pytest.raises(TypeError):
            stochastic_oscillator(HIGH, LOW, CLOSE, d_period=True)
