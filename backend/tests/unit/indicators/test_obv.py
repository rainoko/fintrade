"""Reference-value tests for app.indicators.obv (docs/Analyse.md §4, Elder ch. 29:
On-Balance Volume -- a running total keyed only on the *sign* of the close-to-close change).

Formula under test:
    direction_t = sign(close_t - close_(t-1)), with the undefined first bar (no prior close)
                  mapped to 0 rather than NaN
    OBV_t       = cumsum(direction_t * volume_t)

Fixture (5 bars, 0-indexed):

    idx     0    1    2    3    4
    close  10   11   11    9   10
    volume 100  200  150  300  250

Reference values hand-computed independently of the implementation:

    diff      (idx 0-4):  NaN  +1   0   -2   +1
    direction (idx 0-4):    0  +1   0   -1   +1   (first bar's NaN direction mapped to 0)
    signed_volume:          0 +200   0 -300 +250
    OBV (cumsum):           0  200 200  -100  150
"""

import pandas as pd
import pytest

from app.indicators.obv import obv

CLOSE = pd.Series([10, 11, 11, 9, 10], dtype=float)
VOLUME = pd.Series([100, 200, 150, 300, 250], dtype=float)


class TestObv:
    def test_returns_series_same_length(self) -> None:
        result = obv(CLOSE, VOLUME)

        assert isinstance(result, pd.Series)
        assert len(result) == len(CLOSE)

    def test_reference_values(self) -> None:
        result = obv(CLOSE, VOLUME)

        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(200.0)
        assert result.iloc[2] == pytest.approx(200.0)
        assert result.iloc[3] == pytest.approx(-100.0)
        assert result.iloc[4] == pytest.approx(150.0)

    def test_first_bar_is_not_nan(self) -> None:
        """The first bar has no prior close (its own direction is undefined), but this must
        not leave the whole cumulative series NaN from that point on (NaN is "sticky" under
        cumsum) -- it's mapped to a 0 contribution instead."""
        result = obv(CLOSE, VOLUME)

        assert not result.isna().any()

    def test_flat_close_leaves_obv_unchanged(self) -> None:
        """idx 1->2: close stays 11 -> 11 (no change) -- OBV must not move."""
        result = obv(CLOSE, VOLUME)

        assert result.iloc[2] == result.iloc[1]

    def test_rejects_misaligned_index(self) -> None:
        misaligned_volume = VOLUME.copy()
        misaligned_volume.index = misaligned_volume.index + 1

        with pytest.raises(ValueError):
            obv(CLOSE, misaligned_volume)
