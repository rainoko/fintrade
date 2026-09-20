"""Reference-value tests for app.indicators.atr (docs/Analyse.md §4, Elder ch. 24: True
Range / Average True Range).

Fixture (8 bars, 0-indexed to match pandas' default RangeIndex) -- constructed so
``high - low`` is a constant 2 and ``close`` is the exact midpoint of ``high``/``low`` on
every bar, so True Range collapses to a small, easy-to-verify-by-hand set of values:

    idx    0   1   2   3   4   5   6   7
    high  10  12  11  13  15  14  16  15
    low    8  10   9  11  13  12  14  13
    close  9  11  10  12  14  13  15  14

True Range, hand-computed (``max(high-low, |high-prev_close|, |low-prev_close|)``):

    idx 0: NaN (no prior close)
    idx 1: max(2, |12-9|=3,  |10-9|=1)  = 3
    idx 2: max(2, |11-11|=0, |9-11|=2)  = 2
    idx 3: max(2, |13-10|=3, |11-10|=1) = 3
    idx 4: max(2, |15-12|=3, |13-12|=1) = 3
    idx 5: max(2, |14-14|=0, |12-14|=2) = 2
    idx 6: max(2, |16-13|=3, |14-13|=1) = 3
    idx 7: max(2, |15-15|=0, |13-15|=2) = 2

ATR (period=3, simple rolling mean of True Range):

    idx 3 (window idx1-3): (3+2+3)/3 = 8/3 = 2.666666...
    idx 4 (window idx2-4): (2+3+3)/3 = 8/3 = 2.666666...
    idx 5 (window idx3-5): (3+3+2)/3 = 8/3 = 2.666666...
    idx 6 (window idx4-6): (3+2+3)/3 = 8/3 = 2.666666...
    idx 7 (window idx5-7): (2+3+2)/3 = 7/3 = 2.333333...
"""

import pandas as pd
import pytest

from app.indicators.atr import atr, true_range

HIGH = pd.Series([10, 12, 11, 13, 15, 14, 16, 15], dtype=float)
LOW = pd.Series([8, 10, 9, 11, 13, 12, 14, 13], dtype=float)
CLOSE = pd.Series([9, 11, 10, 12, 14, 13, 15, 14], dtype=float)


class TestTrueRange:
    def test_returns_series_same_length(self) -> None:
        result = true_range(HIGH, LOW, CLOSE)

        assert isinstance(result, pd.Series)
        assert len(result) == len(HIGH)

    def test_first_bar_is_nan(self) -> None:
        result = true_range(HIGH, LOW, CLOSE)

        assert pd.isna(result.iloc[0])

    def test_reference_values(self) -> None:
        result = true_range(HIGH, LOW, CLOSE)

        expected = [None, 3, 2, 3, 3, 2, 3, 2]
        for idx, value in enumerate(expected):
            if value is None:
                assert pd.isna(result.iloc[idx])
            else:
                assert result.iloc[idx] == pytest.approx(value)

    def test_rejects_misaligned_index(self) -> None:
        misaligned = CLOSE.copy()
        misaligned.index = misaligned.index + 1

        with pytest.raises(ValueError):
            true_range(HIGH, LOW, misaligned)


class TestAtr:
    def test_returns_series_same_length(self) -> None:
        result = atr(HIGH, LOW, CLOSE, period=3)

        assert isinstance(result, pd.Series)
        assert len(result) == len(HIGH)

    def test_warmup_period_is_nan(self) -> None:
        """True Range's own first bar is NaN, so a full 3-bar window isn't available
        until index 3 (0-indexed) -- indices 0-2 are NaN."""
        result = atr(HIGH, LOW, CLOSE, period=3)

        assert result.iloc[:3].isna().all()

    def test_reference_values(self) -> None:
        result = atr(HIGH, LOW, CLOSE, period=3)

        assert result.iloc[3] == pytest.approx(8 / 3)
        assert result.iloc[4] == pytest.approx(8 / 3)
        assert result.iloc[5] == pytest.approx(8 / 3)
        assert result.iloc[6] == pytest.approx(8 / 3)
        assert result.iloc[7] == pytest.approx(7 / 3)

    def test_default_period_is_13(self) -> None:
        """13 days is the book's own default (docs/ideas.md)."""
        long_high = pd.Series(range(10, 40), dtype=float)
        long_low = long_high - 2
        long_close = (long_high + long_low) / 2

        result = atr(long_high, long_low, long_close)

        assert result.iloc[:13].isna().all()
        assert not pd.isna(result.iloc[13])

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            atr(HIGH, LOW, CLOSE, period=0)

    def test_rejects_non_integer_period(self) -> None:
        with pytest.raises(TypeError):
            atr(HIGH, LOW, CLOSE, period=13.5)

    def test_rejects_bool_period(self) -> None:
        """bool is a subclass of int in Python; period=True must not be silently
        accepted as period=1."""
        with pytest.raises(TypeError):
            atr(HIGH, LOW, CLOSE, period=True)

    def test_precomputed_true_range_is_used_as_is(self) -> None:
        """A caller-supplied ``true_range`` (e.g. shared with
        ``app.indicators.directional_system.plus_minus_di`` -- docs/tasks/backend-indicator-atr-
        adx-followups.json) is used verbatim instead of being recomputed, and yields the exact
        same result as the default (no-``true_range``) call for the same inputs."""
        precomputed = true_range(HIGH, LOW, CLOSE)

        result = atr(HIGH, LOW, CLOSE, period=3, true_range=precomputed)
        expected = atr(HIGH, LOW, CLOSE, period=3)

        pd.testing.assert_series_equal(result, expected)

    def test_precomputed_true_range_overrides_recomputation(self) -> None:
        """A deliberately wrong ``true_range`` (not actually derived from ``HIGH``/``LOW``/
        ``CLOSE``) is trusted as-is, proving it isn't silently ignored/recomputed."""
        wrong_true_range = pd.Series([100.0] * len(HIGH))

        result = atr(HIGH, LOW, CLOSE, period=3, true_range=wrong_true_range)

        assert result.iloc[3] == pytest.approx(100.0)
