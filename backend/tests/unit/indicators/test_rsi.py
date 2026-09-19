"""Reference-value tests for app.indicators.rsi (docs/Analyse.md §4, Elder ch. 27:
Relative Strength Index -- closing-price-only, simple/arithmetic rolling averages).

Formula under test:
    delta_t   = close_t - close_(t-1)
    gain_t    = max(delta_t, 0)
    loss_t    = max(-delta_t, 0)
    avg_gain  = SMA(gain, period)
    avg_loss  = SMA(loss, period)
    RS        = avg_gain / avg_loss
    RSI       = 100 - 100 / (1 + RS)

Fixture (12 bars, 0-indexed to match pandas' default RangeIndex):

    idx    0   1   2   3   4   5   6   7   8   9  10  11
    close 10  11  12  11  10   9  10  11  12  11  12  14

Reference values hand-computed independently of the implementation, using the
default period=9 (needs 9 daily changes -- indices 1-9 -- before the first
real value, at index 9):

    delta (idx 1-11):  +1  +1  -1  -1  -1  +1  +1  +1  -1  +1  +2
    gain  (idx 1-11):   1   1   0   0   0   1   1   1   0   1   2
    loss  (idx 1-11):   0   0   1   1   1   0   0   0   1   0   0

    idx 9  (window idx1-9):  avg_gain = (1+1+0+0+0+1+1+1+0)/9 = 5/9
                              avg_loss = (0+0+1+1+1+0+0+0+1)/9 = 4/9
                              RS = 1.25 -> RSI = 100 - 100/2.25 = 55.55555555555556

    idx 10 (window idx2-10): avg_gain = (1+0+0+0+1+1+1+0+1)/9 = 5/9
                              avg_loss = (0+1+1+1+0+0+0+1+0)/9 = 4/9
                              RS = 1.25 -> RSI = 55.55555555555556

    idx 11 (window idx3-11): avg_gain = (0+0+0+1+1+1+0+1+2)/9 = 6/9
                              avg_loss = (1+1+1+0+0+0+1+0+0)/9 = 4/9
                              RS = 1.5 -> RSI = 100 - 100/2.5 = 60.0
"""

import pandas as pd
import pytest

from app.indicators.rsi import rsi


CLOSE = pd.Series([10, 11, 12, 11, 10, 9, 10, 11, 12, 11, 12, 14], dtype=float)


class TestRsi:
    def test_returns_series_same_length(self) -> None:
        result = rsi(CLOSE)

        assert isinstance(result, pd.Series)
        assert len(result) == len(CLOSE)

    def test_warmup_period_is_nan(self) -> None:
        """Needs `period` daily changes (period + 1 closes) -- the first 9 bars
        (indices 0-8) are NaN with the default period=9."""
        result = rsi(CLOSE)

        assert result.iloc[:9].isna().all()

    def test_reference_values(self) -> None:
        result = rsi(CLOSE)

        assert result.iloc[9] == pytest.approx(55.55555555555556)
        assert result.iloc[10] == pytest.approx(55.55555555555556)
        assert result.iloc[11] == pytest.approx(60.0)

    def test_no_down_closes_yields_rsi_100(self) -> None:
        """A window with zero net down-closes makes RS undefined (avg_loss=0);
        conventionally read as maximal strength, RSI = 100."""
        all_up = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])

        result = rsi(all_up, period=3)

        assert result.iloc[3] == pytest.approx(100.0)

    def test_no_up_closes_yields_rsi_0(self) -> None:
        all_down = pd.Series([14.0, 13.0, 12.0, 11.0, 10.0])

        result = rsi(all_down, period=3)

        assert result.iloc[3] == pytest.approx(0.0)

    def test_flat_window_yields_rsi_50_not_nan(self) -> None:
        """Zero gains AND zero losses (a perfectly flat trailing run) is a 0/0
        division for RS -- mapped explicitly to the neutral midpoint (50), not
        left as NaN and not misread as either extreme (0 or 100)."""
        flat = pd.Series([10.0, 10.0, 10.0, 10.0])

        result = rsi(flat, period=3)

        assert result.iloc[3] == pytest.approx(50.0)

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            rsi(CLOSE, period=0)

    def test_rejects_non_integer_period(self) -> None:
        with pytest.raises(TypeError):
            rsi(CLOSE, period=9.5)

    def test_rejects_bool_period(self) -> None:
        """bool is a subclass of int in Python; period=True must not be
        silently accepted as period=1."""
        with pytest.raises(TypeError):
            rsi(CLOSE, period=True)
