"""Reference-value tests for app.indicators.accumulation_distribution (docs/Analyse.md §4,
Elder ch. 29: Accumulation/Distribution -- a running total that credits volume proportional
to where the close landed within the day's own range).

Formula under test:
    range_t = high_t - low_t
    clv_t   = (close_t - open_t) / range_t, mapped to 0 when range_t == 0 (rather than 0/0)
    A/D_t   = cumsum(clv_t * volume_t)

Fixture (4 bars, 0-indexed):

    idx    0    1    2    3
    open  10   11   10    9
    high  12   11   15   10
    low    9   11    8    8
    close 11   11    9   10
    vol  100   50  200   80

Reference values hand-computed independently of the implementation:

    idx 0: range = 12-9  =  3, clv = (11-10)/3  =  1/3,  raw = 100 *  1/3  =  33.333333333333336
    idx 1: range = 11-11 =  0 (zero-range bar) -> clv mapped to 0,         raw =   0.0
    idx 2: range = 15-8  =  7, clv = (9-10)/7   = -1/7,  raw = 200 * -1/7  = -28.571428571428573
    idx 3: range = 10-8  =  2, clv = (10-9)/2   =  1/2,  raw = 80  *  1/2  =  40.0

    A/D (cumsum):
    idx 0: 33.333333333333336
    idx 1: 33.333333333333336        (+0, unchanged)
    idx 2: 4.761904761904762         (33.333333333333336 - 28.571428571428573)
    idx 3: 44.76190476190476         (4.761904761904762 + 40.0)
"""

import pandas as pd
import pytest

from app.indicators.accumulation_distribution import accumulation_distribution

OPEN = pd.Series([10, 11, 10, 9], dtype=float)
HIGH = pd.Series([12, 11, 15, 10], dtype=float)
LOW = pd.Series([9, 11, 8, 8], dtype=float)
CLOSE = pd.Series([11, 11, 9, 10], dtype=float)
VOLUME = pd.Series([100, 50, 200, 80], dtype=float)


class TestAccumulationDistribution:
    def test_returns_series_same_length(self) -> None:
        result = accumulation_distribution(OPEN, HIGH, LOW, CLOSE, VOLUME)

        assert isinstance(result, pd.Series)
        assert len(result) == len(CLOSE)

    def test_reference_values(self) -> None:
        result = accumulation_distribution(OPEN, HIGH, LOW, CLOSE, VOLUME)

        assert result.iloc[0] == pytest.approx(33.333333333333336)
        assert result.iloc[1] == pytest.approx(33.333333333333336)
        assert result.iloc[2] == pytest.approx(4.761904761904762)
        assert result.iloc[3] == pytest.approx(44.76190476190476)

    def test_zero_range_bar_contributes_zero_not_nan(self) -> None:
        """idx 1 is a zero-range (high == low) bar -- 0/0 is mapped to a 0 contribution
        rather than left as NaN, since NaN would poison every later cumulative total."""
        result = accumulation_distribution(OPEN, HIGH, LOW, CLOSE, VOLUME)

        assert not result.isna().any()
        assert result.iloc[1] == result.iloc[0]

    def test_rejects_misaligned_index(self) -> None:
        misaligned_volume = VOLUME.copy()
        misaligned_volume.index = misaligned_volume.index + 1

        with pytest.raises(ValueError):
            accumulation_distribution(OPEN, HIGH, LOW, CLOSE, misaligned_volume)
