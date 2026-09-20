"""Reference-value tests for app.indicators.directional_system (docs/Analyse.md §4,
Elder ch. 24: the Directional System / ADX).

Reuses the exact same fixture as tests/unit/indicators/test_atr.py (see that module's own
docstring for the True Range derivation this module's +DI/-DI/DX/ADX build on top of):

    idx    0   1   2   3   4   5   6   7
    high  10  12  11  13  15  14  16  15
    low    8  10   9  11  13  12  14  13
    close  9  11  10  12  14  13  15  14

+DM/-DM, hand-computed (``up_move = high - prior high``, ``down_move = prior low - low``;
``+DM = up_move`` if it strictly exceeds ``down_move`` and is positive, else 0; ``-DM``
mirrored):

    idx 0: NaN, NaN (no prior bar)
    idx 1: up=12-10=2,  down=8-10=-2  -> +DM=2, -DM=0
    idx 2: up=11-12=-1, down=10-9=1   -> +DM=0, -DM=1
    idx 3: up=13-11=2,  down=9-11=-2  -> +DM=2, -DM=0
    idx 4: up=15-13=2,  down=11-13=-2 -> +DM=2, -DM=0
    idx 5: up=14-15=-1, down=13-12=1  -> +DM=0, -DM=1
    idx 6: up=16-14=2,  down=12-14=-2 -> +DM=2, -DM=0
    idx 7: up=15-16=-1, down=14-13=1  -> +DM=0, -DM=1

+DI/-DI (period=3): smoothed(+DM)/smoothed(TR)*100 and smoothed(-DM)/smoothed(TR)*100,
each a plain 3-bar rolling mean (True Range values from test_atr.py: idx1-7 = 3,2,3,3,2,3,2):

    idx 3: smoothed(+DM) over idx1-3 = (2+0+2)/3 = 4/3; smoothed(TR) = 8/3
           +DI = 100*(4/3)/(8/3) = 50.0
           smoothed(-DM) over idx1-3 = (0+1+0)/3 = 1/3
           -DI = 100*(1/3)/(8/3) = 12.5
    idx 4: smoothed(+DM) idx2-4 = (0+2+2)/3 = 4/3, smoothed(TR) = 8/3 -> +DI = 50.0
           smoothed(-DM) idx2-4 = (1+0+0)/3 = 1/3 -> -DI = 12.5
    idx 5: smoothed(+DM) idx3-5 = (2+2+0)/3 = 4/3, smoothed(TR) = 8/3 -> +DI = 50.0
           smoothed(-DM) idx3-5 = (0+0+1)/3 = 1/3 -> -DI = 12.5
    idx 6: smoothed(+DM) idx4-6 = (2+0+2)/3 = 4/3, smoothed(TR) = 8/3 -> +DI = 50.0
           smoothed(-DM) idx4-6 = (0+1+0)/3 = 1/3 -> -DI = 12.5
    idx 7: smoothed(+DM) idx5-7 = (0+2+0)/3 = 2/3, smoothed(TR) = 7/3
           +DI = 100*(2/3)/(7/3) = 28.571428...
           smoothed(-DM) idx5-7 = (1+0+1)/3 = 2/3 -> -DI = 100*(2/3)/(7/3) = 28.571428...
           (+DI == -DI here -- a perfectly balanced bar, DX = 0)

DX (``100 * |+DI - -DI| / (+DI + -DI)``):

    idx 3-6: 100*|50-12.5|/(50+12.5) = 100*37.5/62.5 = 60.0
    idx 7:   100*|28.5714-28.5714|/(28.5714+28.5714) = 0.0

ADX (period=3, plain rolling mean of DX -- DX itself is NaN for idx 0-2):

    idx 5 (window idx3-5, first fully valid): (60+60+60)/3 = 60.0
    idx 6 (window idx4-6): (60+60+60)/3 = 60.0
    idx 7 (window idx5-7): (60+60+0)/3 = 40.0
"""

import pandas as pd
import pytest

from app.indicators.atr import true_range
from app.indicators.directional_system import adx, dx, plus_minus_di, plus_minus_dm

HIGH = pd.Series([10, 12, 11, 13, 15, 14, 16, 15], dtype=float)
LOW = pd.Series([8, 10, 9, 11, 13, 12, 14, 13], dtype=float)
CLOSE = pd.Series([9, 11, 10, 12, 14, 13, 15, 14], dtype=float)


class TestPlusMinusDm:
    def test_returns_two_series_same_length(self) -> None:
        plus_dm, minus_dm = plus_minus_dm(HIGH, LOW)

        assert isinstance(plus_dm, pd.Series)
        assert isinstance(minus_dm, pd.Series)
        assert len(plus_dm) == len(HIGH)
        assert len(minus_dm) == len(HIGH)

    def test_first_bar_is_nan(self) -> None:
        plus_dm, minus_dm = plus_minus_dm(HIGH, LOW)

        assert pd.isna(plus_dm.iloc[0])
        assert pd.isna(minus_dm.iloc[0])

    def test_reference_values(self) -> None:
        plus_dm, minus_dm = plus_minus_dm(HIGH, LOW)

        expected_plus = [None, 2, 0, 2, 2, 0, 2, 0]
        expected_minus = [None, 0, 1, 0, 0, 1, 0, 1]
        for idx, (plus_expected, minus_expected) in enumerate(
            zip(expected_plus, expected_minus, strict=True)
        ):
            if plus_expected is None:
                assert pd.isna(plus_dm.iloc[idx])
                assert pd.isna(minus_dm.iloc[idx])
            else:
                assert plus_dm.iloc[idx] == pytest.approx(plus_expected)
                assert minus_dm.iloc[idx] == pytest.approx(minus_expected)

    def test_tie_yields_zero_for_both(self) -> None:
        """up_move == down_move (both positive) satisfies neither strict '>' condition --
        Wilder's rule counts neither direction, rather than crediting either or both."""
        # up_move = 11-10 = 1, down_move = 8-7 = 1 -- an explicit tie.
        high = pd.Series([10.0, 11.0])
        low = pd.Series([8.0, 7.0])

        plus_dm, minus_dm = plus_minus_dm(high, low)

        assert plus_dm.iloc[1] == pytest.approx(0.0)
        assert minus_dm.iloc[1] == pytest.approx(0.0)

    def test_rejects_misaligned_index(self) -> None:
        misaligned = LOW.copy()
        misaligned.index = misaligned.index + 1

        with pytest.raises(ValueError):
            plus_minus_dm(HIGH, misaligned)


class TestPlusMinusDi:
    def test_returns_two_series_same_length(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        assert len(plus_di) == len(HIGH)
        assert len(minus_di) == len(HIGH)

    def test_warmup_period_is_nan(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        assert plus_di.iloc[:3].isna().all()
        assert minus_di.iloc[:3].isna().all()

    def test_reference_values(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        assert plus_di.iloc[3] == pytest.approx(50.0)
        assert minus_di.iloc[3] == pytest.approx(12.5)
        assert plus_di.iloc[4] == pytest.approx(50.0)
        assert minus_di.iloc[4] == pytest.approx(12.5)
        assert plus_di.iloc[5] == pytest.approx(50.0)
        assert minus_di.iloc[5] == pytest.approx(12.5)
        assert plus_di.iloc[6] == pytest.approx(50.0)
        assert minus_di.iloc[6] == pytest.approx(12.5)
        assert plus_di.iloc[7] == pytest.approx(100 * (2 / 3) / (7 / 3))
        assert minus_di.iloc[7] == pytest.approx(100 * (2 / 3) / (7 / 3))

    def test_default_period_is_13(self) -> None:
        long_high = pd.Series(range(10, 40), dtype=float)
        long_low = long_high - 2
        long_close = (long_high + long_low) / 2

        plus_di, minus_di = plus_minus_di(long_high, long_low, long_close)

        assert plus_di.iloc[:13].isna().all()
        assert not pd.isna(plus_di.iloc[13])
        assert minus_di.iloc[:13].isna().all()
        assert not pd.isna(minus_di.iloc[13])

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            plus_minus_di(HIGH, LOW, CLOSE, period=0)

    def test_rejects_non_integer_period(self) -> None:
        with pytest.raises(TypeError):
            plus_minus_di(HIGH, LOW, CLOSE, period=13.5)

    def test_rejects_bool_period(self) -> None:
        with pytest.raises(TypeError):
            plus_minus_di(HIGH, LOW, CLOSE, period=True)

    def test_precomputed_true_range_is_used_as_is(self) -> None:
        """A caller-supplied ``true_range`` (e.g. shared with ``app.indicators.atr.atr`` --
        docs/tasks/backend-indicator-atr-adx-followups.json) is used verbatim instead of being
        recomputed, and yields the exact same result as the default (no-``true_range``) call
        for the same inputs."""
        precomputed = true_range(HIGH, LOW, CLOSE)

        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3, true_range=precomputed)
        expected_plus_di, expected_minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        pd.testing.assert_series_equal(plus_di, expected_plus_di)
        pd.testing.assert_series_equal(minus_di, expected_minus_di)

    def test_precomputed_true_range_overrides_recomputation(self) -> None:
        """A deliberately wrong ``true_range`` (not actually derived from ``HIGH``/``LOW``/
        ``CLOSE``) is trusted as-is, proving it isn't silently ignored/recomputed."""
        wrong_true_range = pd.Series([1.0] * len(HIGH))

        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3, true_range=wrong_true_range)

        # smoothed(TR) collapses to 1.0 for every bar, so +DI/-DI == 100 * smoothed(+DM/-DM).
        assert plus_di.iloc[3] == pytest.approx(100 * (4 / 3))
        assert minus_di.iloc[3] == pytest.approx(100 * (1 / 3))


class TestDx:
    def test_reference_values(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        result = dx(plus_di, minus_di)

        assert result.iloc[3] == pytest.approx(60.0)
        assert result.iloc[4] == pytest.approx(60.0)
        assert result.iloc[5] == pytest.approx(60.0)
        assert result.iloc[6] == pytest.approx(60.0)
        assert result.iloc[7] == pytest.approx(0.0)

    def test_flat_balance_is_zero_not_nan(self) -> None:
        """+DI == -DI (perfectly balanced) is a well-defined 0, not a 0/0 division --
        distinct from the actual 0/0 case (both +DI and -DI are exactly 0), which stays NaN
        (test_zero_di_is_nan)."""
        plus_di = pd.Series([10.0])
        minus_di = pd.Series([10.0])

        result = dx(plus_di, minus_di)

        assert result.iloc[0] == pytest.approx(0.0)

    def test_zero_di_is_nan(self) -> None:
        plus_di = pd.Series([0.0])
        minus_di = pd.Series([0.0])

        result = dx(plus_di, minus_di)

        assert pd.isna(result.iloc[0])

    def test_rejects_misaligned_index(self) -> None:
        plus_di = pd.Series([10.0, 20.0])
        minus_di = pd.Series([10.0, 20.0])
        minus_di.index = minus_di.index + 1

        with pytest.raises(ValueError):
            dx(plus_di, minus_di)


class TestAdx:
    def test_reference_values(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        result = adx(plus_di, minus_di, period=3)

        assert pd.isna(result.iloc[4])
        assert result.iloc[5] == pytest.approx(60.0)
        assert result.iloc[6] == pytest.approx(60.0)
        assert result.iloc[7] == pytest.approx(40.0)

    def test_default_period_is_13(self) -> None:
        long_high = pd.Series(range(10, 60), dtype=float)
        long_low = long_high - 2
        long_close = (long_high + long_low) / 2

        plus_di, minus_di = plus_minus_di(long_high, long_low, long_close)
        result = adx(plus_di, minus_di)

        # +DI/-DI themselves warm up over the first 13 bars (indices 0-12); ADX needs a
        # further 13-bar rolling window of DX on top of that, so ADX isn't defined until
        # index 25 (0-indexed) -- one index earlier than 13+13 since DX is first valid at
        # index 13, the start of the following 13-bar window.
        assert result.iloc[:25].isna().all()
        assert not pd.isna(result.iloc[25])

    def test_rejects_non_positive_period(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        with pytest.raises(ValueError):
            adx(plus_di, minus_di, period=0)

    def test_rejects_non_integer_period(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        with pytest.raises(TypeError):
            adx(plus_di, minus_di, period=13.5)

    def test_rejects_bool_period(self) -> None:
        plus_di, minus_di = plus_minus_di(HIGH, LOW, CLOSE, period=3)

        with pytest.raises(TypeError):
            adx(plus_di, minus_di, period=True)
